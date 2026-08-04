"""
Phase 1 — Data pipeline for the IDR/USD analysis.

Pulls the full daily history of the Indonesian Rupiah / US Dollar exchange rate
from FRED (series DEXINUS), cleans it, cross-checks a recent window against
yfinance, and optionally pulls comparator FX series and Brent crude for the
enrichment analysis.

Design decisions (documented in data/data_notes.md):
  * DEXINUS is quoted as IDR per 1 USD. A *higher* value means a *weaker* rupiah.
  * FRED marks non-trading days (weekends, US holidays) with ".". We DROP these
    rows rather than forward-fill, so every row is a genuine observation. Downstream
    return/volatility math therefore operates on trading days only.
  * Output is written to data/idr_usd_daily.csv with columns: date, rate.

Run:  python src/pipeline.py
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# Primary series + optional enrichment/comparators.
PRIMARY = "DEXINUS"  # Indonesia Rupiah to USD
COMPARATORS = {
    "DEXMAUS": "MYR",  # Malaysian Ringgit to USD
    "DEXTHUS": "THB",  # Thai Baht to USD
    "DEXSIUS": "SGD",  # Singapore Dollar to USD
}
BRENT = "DCOILBRENTEU"  # Brent crude, USD/barrel

HEADERS = {"User-Agent": "idr-usd-fx/1.0 (portfolio analysis)"}


def fetch_fred_series(series: str, timeout: int = 60) -> pd.DataFrame:
    """Download one FRED series as a tidy (date, value) DataFrame.

    FRED marks missing observations with '.'; those rows are dropped here.
    Returns columns: date (datetime64), <series> (float).
    """
    url = FRED_CSV.format(series=series)
    last_exc = None
    for attempt in range(1, 5):  # FRED occasionally drops the connection
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            wait = 2 * attempt
            print(f"  {series}: attempt {attempt} failed ({type(exc).__name__}); "
                  f"retrying in {wait}s")
            time.sleep(wait)
    else:
        raise RuntimeError(f"failed to fetch {series} after retries: {last_exc}")

    df = pd.read_csv(io.StringIO(resp.text))
    # FRED's date column has been named DATE (older) or observation_date (newer).
    date_col = df.columns[0]
    val_col = df.columns[1]
    df = df.rename(columns={date_col: "date", val_col: series})
    df["date"] = pd.to_datetime(df["date"])
    # '.' -> NaN, then drop non-trading days.
    df[series] = pd.to_numeric(df[series], errors="coerce")
    n_raw = len(df)
    df = df.dropna(subset=[series]).reset_index(drop=True)
    print(f"  {series}: {n_raw} rows raw -> {len(df)} valid observations "
          f"({df['date'].min().date()} .. {df['date'].max().date()})")
    return df


def crosscheck_yfinance(fred: pd.DataFrame, days: int = 120) -> dict:
    """Compare the recent FRED window against yfinance ticker IDR=X.

    Returns a dict of summary stats. Never raises — a failed cross-check is
    logged and flagged, not fatal, because yfinance is a best-effort backup.
    """
    result: dict = {"status": "not_run", "detail": ""}
    try:
        import yfinance as yf

        start = (fred["date"].max() - pd.Timedelta(days=days)).date()
        yfd = yf.download(
            "IDR=X", start=str(start), progress=False, auto_adjust=False
        )
        if yfd is None or yfd.empty:
            result.update(status="unavailable", detail="yfinance returned no rows")
            return result

        yclose = yfd["Close"]
        if isinstance(yclose, pd.DataFrame):  # MultiIndex columns in newer yfinance
            yclose = yclose.iloc[:, 0]
        y = yclose.rename("yf").reset_index()
        y.columns = ["date", "yf"]
        y["date"] = pd.to_datetime(y["date"]).dt.tz_localize(None).dt.normalize()

        merged = fred.merge(y, on="date", how="inner")
        if merged.empty:
            result.update(status="no_overlap", detail="no shared dates in window")
            return result

        merged["pct_diff"] = (
            (merged[PRIMARY] - merged["yf"]).abs() / merged[PRIMARY] * 100
        )
        result.update(
            status="ok",
            n_overlap=int(len(merged)),
            mean_abs_pct_diff=round(float(merged["pct_diff"].mean()), 4),
            max_abs_pct_diff=round(float(merged["pct_diff"].max()), 4),
            window_start=str(merged["date"].min().date()),
            window_end=str(merged["date"].max().date()),
        )
        flag = "OK" if result["mean_abs_pct_diff"] < 1.0 else "REVIEW"
        result["flag"] = flag
        print(f"  yfinance cross-check [{flag}]: {result['n_overlap']} shared days, "
              f"mean |diff| {result['mean_abs_pct_diff']}%, "
              f"max |diff| {result['max_abs_pct_diff']}%")
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        result.update(status="error", detail=f"{type(exc).__name__}: {exc}")
        print(f"  yfinance cross-check ERROR (non-fatal): {result['detail']}")
    return result


def write_data_notes(primary: pd.DataFrame, xcheck: dict,
                     comparators: dict, brent_ok: bool) -> None:
    lo, hi = primary["date"].min().date(), primary["date"].max().date()
    rate = primary[PRIMARY]
    lines = [
        "# Data notes",
        "",
        "## Primary series",
        f"- **Source:** FRED series `DEXINUS` (Indonesia Rupiah to US Dollar, daily).",
        f"- **URL:** {FRED_CSV.format(series=PRIMARY)}",
        f"- **Date range:** {lo} to {hi}",
        f"- **Valid trading-day observations:** {len(primary):,}",
        f"- **Quote convention:** IDR per 1 USD. A higher value = a *weaker* rupiah.",
        f"- **Range in sample:** {rate.min():,.0f} to {rate.max():,.0f} IDR/USD.",
        "",
        "## Cleaning decisions",
        "- FRED marks non-trading days (weekends, US bank holidays) with `.`.",
        "  These are **dropped**, not forward-filled, so every row is a real",
        "  observation. All returns/volatility are computed on trading days.",
        "- Values coerced to numeric; the single date column (named `DATE` or",
        "  `observation_date` depending on FRED's export) is parsed to datetime.",
        "",
        "## Cross-check (yfinance `IDR=X`)",
        f"- Status: **{xcheck.get('status')}** ({xcheck.get('flag', xcheck.get('detail',''))})",
    ]
    if xcheck.get("status") == "ok":
        lines += [
            f"- Overlap window: {xcheck['window_start']} .. {xcheck['window_end']} "
            f"({xcheck['n_overlap']} shared days).",
            f"- Mean absolute difference: **{xcheck['mean_abs_pct_diff']}%**; "
            f"max **{xcheck['max_abs_pct_diff']}%**.",
            "- FRED is treated as the source of truth; yfinance is a sanity check only.",
        ]
    else:
        lines += ["- Cross-check not conclusive; FRED used as sole source. "
                  f"Detail: {xcheck.get('detail','')}"]
    lines += ["", "## Comparator & enrichment series"]
    for series, code in COMPARATORS.items():
        ok = comparators.get(series)
        lines.append(f"- `{series}` ({code}/USD): "
                     f"{'loaded' if ok else 'unavailable — skipped'}")
    lines.append(f"- `{BRENT}` (Brent crude, USD/bbl): "
                 f"{'loaded' if brent_ok else 'unavailable — skipped'}")
    lines += ["", "_Generated by `src/pipeline.py`._", ""]
    (DATA_DIR / "data_notes.md").write_text("\n".join(lines))
    print(f"  wrote {DATA_DIR/'data_notes.md'}")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Phase 1: pulling primary series from FRED ...")
    primary = fetch_fred_series(PRIMARY)

    out = primary.rename(columns={PRIMARY: "rate"})[["date", "rate"]]
    out.to_csv(DATA_DIR / "idr_usd_daily.csv", index=False)
    print(f"  wrote {DATA_DIR/'idr_usd_daily.csv'} ({len(out):,} rows)")

    print("Cross-checking against yfinance ...")
    xcheck = crosscheck_yfinance(primary)

    # Comparators + Brent, merged into a single wide file for the dashboard.
    print("Fetching comparators + Brent (best-effort) ...")
    wide = primary.rename(columns={PRIMARY: "IDR"})[["date", "IDR"]]
    loaded = {}
    for series, code in COMPARATORS.items():
        try:
            s = fetch_fred_series(series)
            wide = wide.merge(s.rename(columns={series: code}), on="date", how="left")
            loaded[series] = True
        except Exception as exc:  # noqa: BLE001
            print(f"  {series} unavailable (non-fatal): {exc}")
            loaded[series] = False

    brent_ok = False
    try:
        b = fetch_fred_series(BRENT)
        wide = wide.merge(b.rename(columns={BRENT: "BRENT"}), on="date", how="left")
        brent_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"  {BRENT} unavailable (non-fatal): {exc}")

    wide.to_csv(DATA_DIR / "fx_wide.csv", index=False)
    print(f"  wrote {DATA_DIR/'fx_wide.csv'} ({wide.shape[0]:,} rows, "
          f"{wide.shape[1]} cols)")

    write_data_notes(primary, xcheck, loaded, brent_ok)

    # Acceptance check: sane range, monotone dates, no dup dates.
    assert out["date"].is_monotonic_increasing, "dates not sorted"
    assert out["date"].is_unique, "duplicate dates present"
    assert out["rate"].between(1000, 100000).all(), "rate out of sane IDR/USD range"
    print("Acceptance checks passed (sorted, unique, sane range).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
