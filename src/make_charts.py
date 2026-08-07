"""
Generate static PNG charts for the README / one-page write-up, and serve as the
Phase-1 acceptance check ("a plotted line of the full history looks sane").

Reads results/metrics_timeseries.csv + results/*.json and writes to assets/.
Run:  python src/make_charts.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
EVENTS = ROOT / "events"
ASSETS = ROOT / "assets"

BLUE, ORANGE, AQUA, RED, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#898781"
plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": MUTED, "axes.grid": True, "grid.alpha": 0.25,
})


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    m = pd.read_csv(RESULTS / "metrics_timeseries.csv", parse_dates=["date"])

    # 1. Trend — full history + 90d MA.
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(m["date"], m["rate"], color=BLUE, lw=0.8, label="IDR/USD")
    ax.plot(m["date"], m["ma90"], color=ORANGE, lw=1.4, label="90-day MA")
    ax.set_title("IDR per USD — full history (ECB reference rate)", fontsize=12, loc="left")
    ax.set_ylabel("IDR per USD")
    ax.legend(frameon=False, loc="upper left")
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    fig.tight_layout(); fig.savefig(ASSETS / "01_trend.png"); plt.close(fig)

    # 2. Rolling annualized volatility.
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(m["date"], m["vol30"] * 100, color=RED, lw=0.8, label="30-day")
    ax.plot(m["date"], m["vol90"] * 100, color=BLUE, lw=1.2, label="90-day")
    ax.set_title("Rolling annualized volatility (%)", fontsize=12, loc="left")
    ax.set_ylabel("Annualized vol (%)")
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout(); fig.savefig(ASSETS / "02_volatility.png"); plt.close(fig)

    # 3. Event study — mean |move| vs matched baseline.
    ev = json.loads((RESULTS / "event_study.json").read_text())["by_kind"]
    kinds = [k for k, v in ev.items() if "mean_abs_pct" in v]
    obs = [ev[k]["mean_abs_pct"] for k in kinds]
    base = [ev[k]["matched_baseline_mean_abs_pct"] for k in kinds]
    x = range(len(kinds))
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.bar([i - 0.2 for i in x], obs, width=0.4, color=ORANGE, label="After event")
    ax.bar([i + 0.2 for i in x], base, width=0.4, color=MUTED, label="Matched baseline")
    for i, k in enumerate(kinds):
        star = " *" if ev[k].get("significant_5pct") else ""
        ax.text(i, max(obs[i], base[i]) + 0.03, f"{ev[k]['vs_baseline_ratio']}×{star}",
                ha="center", fontsize=9)
    ax.set_xticks(list(x)); ax.set_xticklabels(kinds)
    ax.set_ylabel("Mean |5-day move| (%)")
    ax.set_title("Do events move the rate? (* = sig. at 5%)", fontsize=12, loc="left")
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(ASSETS / "03_event_study.png"); plt.close(fig)

    print("Wrote assets/01_trend.png, 02_volatility.png, 03_event_study.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
