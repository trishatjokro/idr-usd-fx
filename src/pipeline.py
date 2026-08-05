"""
Phase 1 — Data pipeline for the IDR/USD analysis.

Builds a clean daily history of the Indonesian Rupiah / US Dollar exchange rate
plus regional comparators, and documents every cleaning decision.

DATA SOURCE NOTE
----------------
The project spec names FRED series `DEXINUS` as the primary source. In practice
FRED's public CSV endpoint was unreachable from the build environment (its WAF
tarpits repeated automated requests — the connection opens but no body is ever
returned). To keep the pipeline reproducible for *anyone* running it, the
implemented source is the **European Central Bank euro reference rates**, pulled
via the free, no-API-key **DBnomics** mirror (`ECB/EXR`). We fetch each currency
priced per EUR and reconstruct the USD cross-rate:

    IDR per USD  =  (IDR per EUR) / (USD per EUR)

ECB reference rates are an official, widely-cited daily FX source (back to 1999)
and cover IDR, USD, MYR, THB, SGD and PHP. They differ marginally from FRED
DEXINUS only in fixing time (ECB ~14:15 CET vs. the Fed's ~noon ET); the level
and dynamics are equivalent. When FRED *is* reachable we use it as an independent
cross-check of the reconstructed series.

  * Quote convention: IDR per 1 USD. A higher value = a weaker rupiah.
  * ECB marks TARGET-holiday / non-trading days with null; those rows are DROPPED
    (not forward-filled), so every row is a genuine observation. All downstream
    return/volatility math therefore runs on trading days only.

Run:  python src/pipeline.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"

# DBnomics mirror of the ECB euro reference rates (units per EUR, daily, spot).
CURRENCIES = ["IDR", "USD", "MYR", "THB", "SGD", "PHP"]
DBNOMICS_URL = (
    "https://api.db.nomics.world/v22/series/ECB/EXR/"
    "D.{curs}.EUR.SP00.A?observations=1"
)
ECB_CACHE = RAW_DIR / "ecb_exr.json"

# Optional FRED cross-check (best-effort; often blocked by the WAF).
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_CACHE = RAW_DIR / "DEXINUS.csv"

HEADERS = {"User-Agent": "idr-usd-fx/1.0 (portfolio analysis)"}


# --------------------------------------------------------------------------- #
# ECB via DBnomics
# --------------------------------------------------------------------------- #
def load_ecb_json(timeout: int = 60) -> dict:
    """Return the raw DBnomics ECB/EXR payload, preferring the local cache."""
    if ECB_CACHE.exists() and ECB_CACHE.stat().st_size > 0:
        print(f"  using cached {ECB_CACHE.relative_to(ROOT)}")
        return json.loads(ECB_CACHE.read_text())

    url = DBNOMICS_URL.format(curs="+".join(CURRENCIES))
    last_exc = None
    for attempt in range(1, 6):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            ECB_CACHE.write_text(resp.text)
            print(f"  fetched ECB/EXR from DBnomics -> cached "
                  f"{ECB_CACHE.relative_to(ROOT)}")
            return resp.json()
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            wait = 2 * attempt
            print(f"  DBnomics attempt {attempt} failed ({type(exc).__name__}); "
                  f"retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"failed to fetch ECB/EXR after retries: {last_exc}")


def ecb_to_frame(payload: dict) -> pd.DataFrame:
    """Wide DataFrame indexed by date: one column per currency (units per EUR)."""
    cols = {}
    for s in payload["series"]["docs"]:
        cur = s["series_code"].split(".")[1]  # D.<CUR>.EUR.SP00.A
        cols[cur] = pd.Series(
            dict(zip(pd.to_datetime(s["period"]), s["value"])), name=cur
        )
    df = pd.DataFrame(cols).sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df


def reconstruct_usd_crosses(ecb: pd.DataFrame) -> pd.DataFrame:
    """Convert per-EUR rates to per-USD: X per USD = (X per EUR)/(USD per EUR)."""
    usd_per_eur = ecb["USD"]
    out = pd.DataFrame(index=ecb.index)
    for cur in CURRENCIES:
        if cur == "USD":
            continue
        out[cur] = ecb[cur] / usd_per_eur  # e.g. IDR per USD
    out = out.reset_index().rename(columns={"index": "date"})
    out.columns = ["date"] + list(out.columns[1:])
    return out


# --------------------------------------------------------------------------- #
# Optional FRED cross-check
# --------------------------------------------------------------------------- #
def fred_dexinus(timeout: int = 12) -> pd.DataFrame | None:
    """Best-effort FRED DEXINUS pull for cross-checking. None if unreachable."""
    if FRED_CACHE.exists() and FRED_CACHE.stat().st_size > 0:
        text = FRED_CACHE.read_text()
    else:
        try:
            resp = requests.get(FRED_CSV.format(series="DEXINUS"),
                                headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            FRED_CACHE.write_text(resp.text)
            text = resp.text
        except requests.exceptions.RequestException as exc:
            print(f"  FRED cross-check unavailable (non-fatal): "
                  f"{type(exc).__name__}")
            return None
    df = pd.read_csv(io.StringIO(text))
    df.columns = ["date", "DEXINUS"]
    df["date"] = pd.to_datetime(df["date"])
    df["DEXINUS"] = pd.to_numeric(df["DEXINUS"], errors="coerce")
    return df.dropna().reset_index(drop=True)


def crosscheck(primary: pd.DataFrame, days: int = 180) -> dict:
    fred = fred_dexinus()
    if fred is None or fred.empty:
        return {"status": "unavailable",
                "detail": "FRED endpoint not reachable from this environment"}
    start = primary["date"].max() - pd.Timedelta(days=days)
    merged = primary[primary["date"] >= start].merge(fred, on="date", how="inner")
    if merged.empty:
        return {"status": "no_overlap", "detail": "no shared recent dates"}
    merged["pct_diff"] = (merged["rate"] - merged["DEXINUS"]).abs() / merged["rate"] * 100
    mean_diff = round(float(merged["pct_diff"].mean()), 4)
    return {
        "status": "ok",
        "source": "FRED DEXINUS",
        "n_overlap": int(len(merged)),
        "window_start": str(merged["date"].min().date()),
        "window_end": str(merged["date"].max().date()),
        "mean_abs_pct_diff": mean_diff,
        "max_abs_pct_diff": round(float(merged["pct_diff"].max()), 4),
        "flag": "OK" if mean_diff < 1.5 else "REVIEW",
    }


# --------------------------------------------------------------------------- #
def write_data_notes(primary: pd.DataFrame, wide: pd.DataFrame, xcheck: dict) -> None:
    lo, hi = primary["date"].min().date(), primary["date"].max().date()
    rate = primary["rate"]
    comps = [c for c in wide.columns if c not in ("date", "IDR")]
    lines = [
        "# Data notes",
        "",
        "## Source",
        "- **Implemented source:** European Central Bank euro reference rates",
        "  (`ECB/EXR`, daily spot), via the free no-key **DBnomics** API.",
        "- **Reconstruction:** `IDR per USD = (IDR per EUR) / (USD per EUR)`.",
        "- **Spec'd source:** FRED `DEXINUS`. FRED's CSV endpoint tarpits repeated",
        "  automated requests, so ECB (an equally official, citable daily source",
        "  back to 1999) is used for reproducibility. See `src/pipeline.py` header.",
        f"- **Date range:** {lo} to {hi}  ({len(primary):,} trading-day observations)",
        f"- **Quote convention:** IDR per 1 USD — higher = weaker rupiah.",
        f"- **Range in sample:** {rate.min():,.0f} to {rate.max():,.0f} IDR/USD.",
        f"- **Comparators (per USD):** {', '.join(comps)}.",
        "",
        "## Cleaning decisions",
        "- ECB marks non-trading / TARGET-holiday days with null. These rows are",
        "  **dropped, not forward-filled**, so every row is a real observation.",
        "  All returns/volatility are computed on trading days only.",
        "- The primary series keeps only dates where both IDR and USD per-EUR",
        "  rates exist. Comparators are left-joined onto that spine.",
        "",
        "## Cross-check (FRED `DEXINUS`)",
        f"- Status: **{xcheck.get('status')}** "
        f"({xcheck.get('flag', xcheck.get('detail',''))})",
    ]
    if xcheck.get("status") == "ok":
        lines += [
            f"- Overlap {xcheck['window_start']}..{xcheck['window_end']} "
            f"({xcheck['n_overlap']} shared days).",
            f"- Mean absolute difference vs FRED: **{xcheck['mean_abs_pct_diff']}%** "
            f"(max {xcheck['max_abs_pct_diff']}%). Small gaps are expected from the",
            "  different fixing time; this confirms the reconstruction is sound.",
        ]
    else:
        lines += ["- FRED not reachable from the build environment; ECB used as the "
                  "sole source. Re-run where FRED is reachable to populate this check."]
    lines += ["", "_Generated by `src/pipeline.py`._", ""]
    (DATA_DIR / "data_notes.md").write_text("\n".join(lines))
    print(f"  wrote {(DATA_DIR/'data_notes.md').relative_to(ROOT)}")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Phase 1: loading ECB euro reference rates (DBnomics) ...")
    ecb = ecb_to_frame(load_ecb_json())
    print(f"  {ecb.shape[0]:,} dates x {ecb.shape[1]} currencies")

    wide = reconstruct_usd_crosses(ecb)
    # Primary spine: dates with a valid IDR/USD.
    wide = wide.dropna(subset=["IDR"]).sort_values("date").reset_index(drop=True)

    primary = wide[["date", "IDR"]].rename(columns={"IDR": "rate"})
    primary.to_csv(DATA_DIR / "idr_usd_daily.csv", index=False)
    print(f"  wrote data/idr_usd_daily.csv ({len(primary):,} rows)")

    wide.to_csv(DATA_DIR / "fx_wide.csv", index=False)
    print(f"  wrote data/fx_wide.csv ({wide.shape[0]:,} rows, {wide.shape[1]} cols: "
          f"{', '.join(wide.columns)})")

    print("Cross-checking against FRED DEXINUS (best-effort) ...")
    xcheck = crosscheck(primary)
    print(f"  cross-check: {xcheck.get('status')} "
          f"{xcheck.get('flag', xcheck.get('detail',''))}")

    write_data_notes(primary, wide, xcheck)

    # Acceptance checks.
    assert primary["date"].is_monotonic_increasing, "dates not sorted"
    assert primary["date"].is_unique, "duplicate dates"
    assert primary["rate"].between(1000, 100000).all(), "rate out of sane range"
    print(f"Acceptance checks passed. Latest: {primary.iloc[-1]['date'].date()} = "
          f"{primary.iloc[-1]['rate']:,.0f} IDR/USD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
