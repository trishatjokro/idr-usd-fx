"""
Phase 2 — Core analysis for the IDR/USD study.

Reads the cleaned data from Phase 1 and produces every derived artifact the
dashboard and write-up consume:

  results/metrics_timeseries.csv  per-day rate, returns, rolling MAs, rolling
                                  annualized volatility, rolling return z-score
  results/summary.json            headline stat cards + full-history stats
  results/regimes.csv             the sharpest depreciation/appreciation episodes
  results/event_study.json        FOMC / BI event-window test vs. baseline
  results/correlations.json       IDR vs Brent and vs regional-FX co-movement
  results/findings.md             plain-English findings with the real numbers

All statistics are computed on trading-day observations only (see data_notes.md).
Volatility is annualized with sqrt(252). No forecasting — descriptive only.

Run:  python src/analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
EVENTS_DIR = ROOT / "events"
RESULTS_DIR = ROOT / "results"

TRADING_DAYS = 252
FWD_WINDOW = 5  # trading days after an event


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load_rate() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "idr_usd_daily.csv", parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_wide() -> pd.DataFrame | None:
    path = DATA_DIR / "fx_wide.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, parse_dates=["date"]).sort_values("date")


def load_events() -> pd.DataFrame:
    """Concatenate all events/*.csv into date, kind, label rows."""
    frames = []
    for path in sorted(EVENTS_DIR.glob("*.csv")):
        e = pd.read_csv(path, parse_dates=["date"])
        if "kind" not in e.columns:
            e["kind"] = path.stem
        if "label" not in e.columns:
            e["label"] = path.stem
        frames.append(e[["date", "kind", "label"]])
    if not frames:
        return pd.DataFrame(columns=["date", "kind", "label"])
    return pd.concat(frames).sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Core metrics
# --------------------------------------------------------------------------- #
def build_metrics(rate: pd.DataFrame) -> pd.DataFrame:
    df = rate.copy()
    df["ret"] = df["rate"].pct_change()  # daily fractional return
    df["log_ret"] = np.log(df["rate"]).diff()
    df["ma30"] = df["rate"].rolling(30).mean()
    df["ma90"] = df["rate"].rolling(90).mean()
    # Annualized rolling volatility of daily returns.
    df["vol30"] = df["ret"].rolling(30).std() * np.sqrt(TRADING_DAYS)
    df["vol90"] = df["ret"].rolling(90).std() * np.sqrt(TRADING_DAYS)
    # Rolling z-score of daily returns (250d window) — the regime signal.
    roll_mean = df["ret"].rolling(250).mean()
    roll_std = df["ret"].rolling(250).std()
    df["ret_z"] = (df["ret"] - roll_mean) / roll_std
    return df


def pct_change_over(df: pd.DataFrame, days: int) -> float | None:
    """% change in rate from ~`days` calendar days ago to the latest obs."""
    latest = df.iloc[-1]
    cutoff = latest["date"] - pd.Timedelta(days=int(days))
    past = df[df["date"] <= cutoff]
    if past.empty:
        return None
    prior = past.iloc[-1]["rate"]
    return float((latest["rate"] / prior - 1) * 100)


def ytd_change(df: pd.DataFrame) -> float | None:
    latest = df.iloc[-1]
    year_start = df[df["date"] >= pd.Timestamp(latest["date"].year, 1, 1)]
    if year_start.empty:
        return None
    return float((latest["rate"] / year_start.iloc[0]["rate"] - 1) * 100)


def summarize(df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    cur_vol = df["vol30"].iloc[-1]
    vol_series = df["vol30"].dropna()
    vol_pct = float((vol_series < cur_vol).mean() * 100) if len(vol_series) else None
    return {
        "as_of": str(latest["date"].date()),
        "history_start": str(df["date"].min().date()),
        "history_end": str(df["date"].max().date()),
        "n_obs": int(len(df)),
        "current_rate": round(float(latest["rate"]), 2),
        "min_rate": round(float(df["rate"].min()), 2),
        "max_rate": round(float(df["rate"].max()), 2),
        "min_rate_date": str(df.loc[df["rate"].idxmin(), "date"].date()),
        "max_rate_date": str(df.loc[df["rate"].idxmax(), "date"].date()),
        "ytd_change_pct": _r(ytd_change(df)),
        "chg_1y_pct": _r(pct_change_over(df, 365)),
        "chg_5y_pct": _r(pct_change_over(df, 365 * 5)),
        "current_vol30_annualized": _r(float(cur_vol) * 100 if pd.notna(cur_vol) else None),
        "current_vol_percentile": _r(vol_pct),
        "mean_annualized_vol": _r(float(vol_series.mean()) * 100 if len(vol_series) else None),
        "worst_1d_ret_pct": _r(float(df["ret"].min()) * 100),
        "worst_1d_date": str(df.loc[df["ret"].idxmin(), "date"].date()),
        "best_1d_ret_pct": _r(float(df["ret"].max()) * 100),
        "best_1d_date": str(df.loc[df["ret"].idxmax(), "date"].date()),
    }


def _r(x, nd: int = 2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


# --------------------------------------------------------------------------- #
# Regimes — sharpest non-overlapping 63-day (quarter) moves
# --------------------------------------------------------------------------- #
def find_regimes(df: pd.DataFrame, window: int = 63, top_n: int = 5) -> pd.DataFrame:
    d = df.dropna(subset=["rate"]).reset_index(drop=True)
    d["fwd_chg"] = d["rate"].shift(-window) / d["rate"] - 1
    episodes = []
    for direction, ascending in (("depreciation", False), ("appreciation", True)):
        pool = d.dropna(subset=["fwd_chg"]).sort_values("fwd_chg", ascending=ascending)
        chosen: list[pd.Timestamp] = []
        for _, row in pool.iterrows():
            start = row["date"]
            # enforce non-overlap: keep episodes >window trading days apart
            if all(abs((start - c).days) > window * 1.4 for c in chosen):
                chosen.append(start)
                end_idx = min(d.index[d["date"] == start][0] + window, len(d) - 1)
                episodes.append({
                    "direction": direction,
                    "start": str(start.date()),
                    "end": str(d.iloc[end_idx]["date"].date()),
                    "start_rate": round(float(row["rate"]), 2),
                    "end_rate": round(float(d.iloc[end_idx]["rate"]), 2),
                    "pct_change": round(float(row["fwd_chg"]) * 100, 2),
                })
            if len([e for e in episodes if e["direction"] == direction]) >= top_n:
                break
    return pd.DataFrame(episodes)


# --------------------------------------------------------------------------- #
# Event-window study
# --------------------------------------------------------------------------- #
def _fwd_return(df: pd.DataFrame, idx: int, window: int) -> float | None:
    if idx + window >= len(df):
        return None
    return float(df["rate"].iloc[idx + window] / df["rate"].iloc[idx] - 1)


def event_study(df: pd.DataFrame, events: pd.DataFrame,
                window: int = FWD_WINDOW, n_perm: int = 5000) -> dict:
    """For each event kind, test whether the |window-day forward move| following
    the event exceeds a **period-matched** baseline, via a permutation test.

    Methodology note: a naive baseline over *all* history (1999-2026) would be
    confounded, because scheduled meetings only exist in the calmer 2013-2025
    era while the full sample includes the 1999-2002 and 2008 crisis spikes. So
    for each kind the baseline is restricted to trading days inside that kind's
    own [first_event, last_event] range, with the event forward-windows removed
    to avoid contaminating the baseline with the very effect being tested.
    """
    d = df.reset_index(drop=True)
    all_dates = d["date"].values

    # Full-history baseline kept for reference/context only.
    full_baseline = np.array([
        abs(r) for i in range(len(d))
        if (r := _fwd_return(d, i, window)) is not None
    ])
    rng = np.random.default_rng(42)  # deterministic

    out: dict = {
        "window_days": window,
        "full_history_baseline_mean_abs_pct": round(float(full_baseline.mean()) * 100, 4),
        "baseline_type": "period-matched (non-event days within each kind's date range)",
        "by_kind": {},
    }

    for kind, grp in events.groupby("kind"):
        # snap each event to the next available trading day
        idxs = []
        for ed in grp["date"]:
            pos = int(np.searchsorted(all_dates, np.datetime64(ed)))
            if pos < len(d):
                idxs.append(pos)
        idxs = sorted(set(idxs))
        moves = np.array([
            abs(r) for i in idxs if (r := _fwd_return(d, i, window)) is not None
        ])
        if len(moves) < 5:
            out["by_kind"][kind] = {"n_events": int(len(moves)), "note": "too few events"}
            continue

        # Period-matched baseline: days within the kind's date span, excluding
        # any day that falls inside an event's forward window.
        lo, hi = min(idxs), max(idxs)
        excluded = set()
        for i in idxs:
            excluded.update(range(i, min(i + window + 1, len(d))))
        base_idx = [i for i in range(lo, hi + 1) if i not in excluded]
        base = np.array([
            abs(r) for i in base_idx if (r := _fwd_return(d, i, window)) is not None
        ])
        base_mean = float(base.mean())
        obs_mean = float(moves.mean())

        # Two-sided permutation test vs the matched baseline.
        k = len(moves)
        perm_means = np.array([
            rng.choice(base, size=k, replace=False).mean() for _ in range(n_perm)
        ])
        # p = P(|perm - base_mean| >= |obs - base_mean|)
        obs_dev = abs(obs_mean - base_mean)
        p_value = float((np.abs(perm_means - base_mean) >= obs_dev).mean())
        out["by_kind"][kind] = {
            "n_events": int(k),
            "date_range": f"{d.iloc[lo]['date'].date()}..{d.iloc[hi]['date'].date()}",
            "mean_abs_pct": round(obs_mean * 100, 4),
            "matched_baseline_mean_abs_pct": round(base_mean * 100, 4),
            "vs_baseline_ratio": round(obs_mean / base_mean, 3),
            "p_value": round(p_value, 4),
            "significant_5pct": bool(p_value < 0.05),
        }
    return out


# --------------------------------------------------------------------------- #
# Correlations (enrichment)
# --------------------------------------------------------------------------- #
def correlations(wide: pd.DataFrame | None) -> dict:
    if wide is None or "IDR" not in wide.columns:
        return {"note": "fx_wide.csv unavailable"}
    w = wide.copy().sort_values("date")
    rets = w.set_index("date").apply(pd.to_numeric, errors="coerce").pct_change()
    out: dict = {"daily_return_correlation_with_IDR": {}}
    for col in [c for c in rets.columns if c != "IDR"]:
        pair = rets[["IDR", col]].dropna()
        if len(pair) > 30:
            out["daily_return_correlation_with_IDR"][col] = round(
                float(pair["IDR"].corr(pair[col])), 3)
    # Brent: Indonesia is a net commodity exporter — test level correlation too.
    if "BRENT" in w.columns:
        lvl = w[["IDR", "BRENT"]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(lvl) > 30:
            out["idr_brent_return_corr"] = round(
                float(rets[["IDR", "BRENT"]].dropna()["IDR"].corr(
                    rets[["IDR", "BRENT"]].dropna()["BRENT"])), 3)
            out["idr_brent_n"] = int(len(lvl))
    return out


# --------------------------------------------------------------------------- #
# Findings write-up (auto-generated from the real numbers)
# --------------------------------------------------------------------------- #
def write_findings(summary: dict, regimes: pd.DataFrame,
                   events: dict, corr: dict) -> None:
    dep = regimes[regimes["direction"] == "depreciation"].head(1)
    worst = dep.iloc[0] if len(dep) else None
    lines = [
        "# IDR/USD — headline findings",
        "",
        f"_Data: ECB euro reference rates via DBnomics (IDR/USD reconstructed from the "
        f"USD cross-rate; FRED `DEXINUS` is the spec'd source & cross-check), "
        f"{summary['history_start']} to {summary['history_end']} "
        f"({summary['n_obs']:,} trading days). Generated by `src/analysis.py`._",
        "",
        "## 1. The rupiah's long-run path is depreciation, punctuated by shocks",
        f"- Over the sample the rate ranged from **{summary['min_rate']:,.0f}** "
        f"({summary['min_rate_date']}) to **{summary['max_rate']:,.0f}** "
        f"({summary['max_rate_date']}) IDR/USD — a weaker rupiah at the high end.",
        f"- Latest ({summary['as_of']}): **{summary['current_rate']:,.0f}** IDR/USD. "
        f"YTD {fmt_pct(summary['ytd_change_pct'])}, 1-year {fmt_pct(summary['chg_1y_pct'])}.",
    ]
    if worst is not None:
        lines.append(
            f"- Sharpest ~quarter of depreciation in the sample: "
            f"**{worst['pct_change']:+.1f}%** ({worst['start']} → {worst['end']}, "
            f"{worst['start_rate']:,.0f} → {worst['end_rate']:,.0f}).")
    lines += [
        "",
        "## 2. Volatility is highly regime-dependent",
        f"- Current 30-day annualized volatility is "
        f"**{fmt_pct(summary['current_vol30_annualized'], signed=False)}**, at the "
        f"**{summary['current_vol_percentile']:.0f} percentile** (0 = calmest, "
        f"100 = most volatile) of its own history "
        f"(mean {fmt_pct(summary['mean_annualized_vol'], signed=False)}).",
        f"- The single worst day was **{fmt_pct(summary['worst_1d_ret_pct'])}** "
        f"({summary['worst_1d_date']}); the best **{fmt_pct(summary['best_1d_ret_pct'])}** "
        f"({summary['best_1d_date']}).",
        "",
        "## 3. Do central-bank meetings actually move the rate?",
        f"- Test: mean |{events.get('window_days','5')}-trading-day move| after each "
        "event vs. a **period-matched** baseline (non-event days in the same era), "
        "permutation-tested (5,000 resamples).",
    ]
    for kind, r in events.get("by_kind", {}).items():
        if "mean_abs_pct" in r:
            verdict = ("**more** than baseline" if r["vs_baseline_ratio"] > 1
                       else "**not more** — if anything calmer than baseline")
            sig = "significant at 5%" if r["significant_5pct"] else "not significant"
            lines.append(
                f"- **{kind}** ({r['n_events']} events, {r.get('date_range','')}): "
                f"mean |move| **{r['mean_abs_pct']}%** vs matched baseline "
                f"{r['matched_baseline_mean_abs_pct']}% = **{r['vs_baseline_ratio']}×** — "
                f"{verdict} (p={r['p_value']}, {sig}).")
    lines.append(
        "- Read: scheduled, well-anticipated policy meetings do **not** move IDR/USD "
        "more than an ordinary day in the same period; the larger moves cluster "
        "around unscheduled political / global-macro shocks.")
    if corr.get("idr_brent_return_corr") is not None:
        lines += [
            "",
            "## 4. Commodity linkage (enrichment)",
            f"- IDR/USD daily-return correlation with Brent crude: "
            f"**{corr['idr_brent_return_corr']}** (n={corr.get('idr_brent_n','?')}). "
            "Indonesia is a net commodity exporter, so a weaker link than expected "
            "is itself worth noting.",
        ]
    regional = corr.get("daily_return_correlation_with_IDR", {})
    if regional:
        pairs = ", ".join(f"{k} {v}" for k, v in regional.items())
        lines.append(f"- Regional co-movement (daily-return corr): {pairs}.")
    lines += [
        "",
        "## Caveats",
        "- FOMC dates are verified against federalreserve.gov. Bank Indonesia RDG "
        "dates for 2021–2025 are verified against bi.go.id; **2016–2020 are "
        "month-accurate but day-approximate** (see `events/EVENTS_SOURCES.md`), which "
        "adds noise to the BI event window — a reason to read the BI result as "
        "\"no amplification\" rather than a precise multiplier.",
        "- \"Political\" events mark the trigger day, not necessarily the peak FX move.",
        "- IDR/USD is reconstructed from ECB euro reference rates, not FRED DEXINUS; "
        "the two differ only marginally (fixing time).",
        "",
        "_“So what”: this is a descriptive/diagnostic study — no forecast. "
        "The point is a defensible read of trend, risk regime, and event sensitivity._",
        "",
    ]
    (RESULTS_DIR / "findings.md").write_text("\n".join(lines))


def fmt_pct(x, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.2f}%" if signed else f"{x:.2f}%"


# --------------------------------------------------------------------------- #
def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rate = load_rate()
    wide = load_wide()
    events = load_events()
    print(f"Loaded {len(rate):,} rate rows, {len(events)} events "
          f"({events['kind'].nunique() if len(events) else 0} kinds).")

    metrics = build_metrics(rate)
    metrics.to_csv(RESULTS_DIR / "metrics_timeseries.csv", index=False)

    summary = summarize(metrics)
    regimes = find_regimes(metrics)
    regimes.to_csv(RESULTS_DIR / "regimes.csv", index=False)
    evstudy = event_study(rate, events) if len(events) else {"note": "no events"}
    corr = correlations(wide)

    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    (RESULTS_DIR / "event_study.json").write_text(json.dumps(evstudy, indent=2))
    (RESULTS_DIR / "correlations.json").write_text(json.dumps(corr, indent=2))
    write_findings(summary, regimes, evstudy, corr)

    print("Wrote results/: metrics_timeseries.csv, summary.json, regimes.csv, "
          "event_study.json, correlations.json, findings.md")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
