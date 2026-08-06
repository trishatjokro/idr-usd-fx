"""
IDR/USD Exchange Rate Dashboard — Phase 3.

A Streamlit front-end over the pre-computed artifacts produced by
`src/analysis.py`. This module only *reads* those artifacts; it never
recomputes anything. If the artifacts are missing it explains how to
generate them and stops cleanly rather than crashing.

Run (after the pipeline has produced data):
    streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------- #
# Paths — resolved relative to this file so the app is location-independent.
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
EVENTS_DIR = ROOT / "events"

RATE_CSV = DATA_DIR / "idr_usd_daily.csv"
WIDE_CSV = DATA_DIR / "fx_wide.csv"
METRICS_CSV = RESULTS_DIR / "metrics_timeseries.csv"
SUMMARY_JSON = RESULTS_DIR / "summary.json"
REGIMES_CSV = RESULTS_DIR / "regimes.csv"
EVENT_STUDY_JSON = RESULTS_DIR / "event_study.json"
CORRELATIONS_JSON = RESULTS_DIR / "correlations.json"

# --------------------------------------------------------------------------- #
# Palette — from the data-viz reference instance (validated categorical hues).
# These light-mode steps read acceptably on both light and dark chart surfaces;
# Streamlit's own theme supplies the surface/background so we only set marks.
# Colour is never the *only* signal here: every series is also legend- and
# hover-labelled, and change is shown as a signed number, not just a hue.
# --------------------------------------------------------------------------- #
BLUE = "#2a78d6"     # slot 1
ORANGE = "#eb6834"   # slot 2
AQUA = "#1baf7a"     # slot 3
YELLOW = "#eda100"   # slot 4
MAGENTA = "#e87ba4"  # slot 5
VIOLET = "#4a3aa7"   # slot 7
RED = "#e34948"      # slot 8
MUTED = "#898781"    # axis / gridline ink (mode-invariant)

# Stable colour per event kind (falls back to the categorical order for
# any kind we haven't explicitly mapped).
EVENT_COLORS = {
    "FOMC": VIOLET,
    "BI": ORANGE,
    "Political": RED,
}
EVENT_FALLBACK_CYCLE = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET, RED]

# Regional-FX comparison colours (IDR always leads on slot 1 = blue).
REGIONAL_COLORS = {
    "IDR": BLUE,
    "MYR": ORANGE,
    "THB": AQUA,
    "SGD": YELLOW,
}

st.set_page_config(
    page_title="IDR/USD Exchange Rate Dashboard",
    layout="wide",
)


# --------------------------------------------------------------------------- #
# Cached loaders — each returns None when its file is absent so callers can
# degrade gracefully instead of raising.
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_metrics() -> pd.DataFrame | None:
    if not METRICS_CSV.exists():
        return None
    df = pd.read_csv(METRICS_CSV, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_summary() -> dict | None:
    if not SUMMARY_JSON.exists():
        return None
    return json.loads(SUMMARY_JSON.read_text())


@st.cache_data(show_spinner=False)
def load_regimes() -> pd.DataFrame | None:
    if not REGIMES_CSV.exists():
        return None
    return pd.read_csv(REGIMES_CSV)


@st.cache_data(show_spinner=False)
def load_event_study() -> dict | None:
    if not EVENT_STUDY_JSON.exists():
        return None
    return json.loads(EVENT_STUDY_JSON.read_text())


@st.cache_data(show_spinner=False)
def load_correlations() -> dict | None:
    if not CORRELATIONS_JSON.exists():
        return None
    return json.loads(CORRELATIONS_JSON.read_text())


@st.cache_data(show_spinner=False)
def load_wide() -> pd.DataFrame | None:
    if not WIDE_CSV.exists():
        return None
    return pd.read_csv(WIDE_CSV, parse_dates=["date"]).sort_values("date")


@st.cache_data(show_spinner=False)
def load_events() -> pd.DataFrame:
    """Concatenate all events/*.csv into (date, kind, label). Empty if none."""
    frames: list[pd.DataFrame] = []
    if EVENTS_DIR.exists():
        for path in sorted(EVENTS_DIR.glob("*.csv")):
            try:
                e = pd.read_csv(path, parse_dates=["date"])
            except Exception:
                continue
            if "kind" not in e.columns:
                e["kind"] = path.stem
            if "label" not in e.columns:
                e["label"] = path.stem
            keep = [c for c in ("date", "kind", "label") if c in e.columns]
            frames.append(e[keep])
    if not frames:
        return pd.DataFrame(columns=["date", "kind", "label"])
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def fmt_pct(x, signed: bool = True) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:+.2f}%" if signed else f"{x:.2f}%"


def fmt_rate(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:,.0f}"


def event_color(kind: str) -> str:
    if kind in EVENT_COLORS:
        return EVENT_COLORS[kind]
    # deterministic fallback by first-seen order
    idx = abs(hash(kind)) % len(EVENT_FALLBACK_CYCLE)
    return EVENT_FALLBACK_CYCLE[idx]


def style_layout(fig: go.Figure, y_title: str) -> go.Figure:
    """Common, theme-friendly chart chrome. Backgrounds stay transparent so
    Streamlit's light/dark surface shows through; only ink/grid are set."""
    fig.update_layout(
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(title=y_title, gridcolor="rgba(137,135,129,0.25)",
                   zeroline=False),
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif"),
    )
    return fig


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("IDR/USD Exchange Rate Dashboard")

metrics = load_metrics()
summary = load_summary()

# Hard requirement: metrics + summary are the backbone. Without them, guide the
# user to the pipeline and stop — never crash.
if metrics is None or summary is None or metrics.empty:
    st.caption("Source: FRED series **DEXINUS** (Indonesian Rupiah to US Dollar).")
    st.warning(
        "No analysis artifacts found yet. Generate them first, then reload:\n\n"
        "```\npython src/pipeline.py && python src/analysis.py\n```\n\n"
        f"Expected files under `{RESULTS_DIR.name}/` "
        "(`metrics_timeseries.csv`, `summary.json`, …) and "
        f"`{DATA_DIR.name}/` (`idr_usd_daily.csv`)."
    )
    st.stop()

as_of = summary.get("as_of", "n/a")
st.caption(
    f"Source: FRED series **DEXINUS** (IDR per USD). "
    f"Data as of **{as_of}** · "
    f"{summary.get('n_obs', 0):,} trading days "
    f"({summary.get('history_start', '?')} → {summary.get('history_end', '?')})."
)

# --------------------------------------------------------------------------- #
# Date-range filter (drives every chart below)
# --------------------------------------------------------------------------- #
min_d = metrics["date"].min().date()
max_d = metrics["date"].max().date()

if min_d >= max_d:
    date_range = (min_d, max_d)
else:
    date_range = st.slider(
        "Date range",
        min_value=min_d,
        max_value=max_d,
        value=(min_d, max_d),
        format="YYYY-MM-DD",
        help="Filters every chart and the regional comparison below.",
    )

start_d, end_d = date_range
mask = (metrics["date"].dt.date >= start_d) & (metrics["date"].dt.date <= end_d)
m = metrics.loc[mask].copy()

if m.empty:
    st.warning("No observations in the selected date range. Widen the range.")
    st.stop()

# --------------------------------------------------------------------------- #
# 3. Stat cards (headline metrics come straight from summary.json)
# --------------------------------------------------------------------------- #
st.subheader("Headline metrics")
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Current rate",
    fmt_rate(summary.get("current_rate")),
    help=f"IDR per USD, as of {as_of}.",
)
c2.metric(
    "YTD change",
    fmt_pct(summary.get("ytd_change_pct")),
    help="Year-to-date change in the rate. Positive = rupiah weaker vs USD.",
    delta_color="off",  # avoid misleading red/green: up ≠ 'good' for a weakening currency
)
c3.metric(
    "1-year change",
    fmt_pct(summary.get("chg_1y_pct")),
    help="Change vs ~365 days ago. Positive = rupiah weaker vs USD.",
    delta_color="off",
)
vol_pct = summary.get("current_vol_percentile")
vol_help = (
    f"30-day annualized volatility. Currently at the "
    f"{vol_pct:.0f}th percentile of its own history "
    f"(mean {fmt_pct(summary.get('mean_annualized_vol'), signed=False)})."
    if vol_pct is not None else "30-day annualized volatility."
)
c4.metric(
    "30d volatility (ann.)",
    fmt_pct(summary.get("current_vol30_annualized"), signed=False),
    delta=(f"{vol_pct:.0f}th pctile" if vol_pct is not None else None),
    delta_color="off",
    help=vol_help,
)

# --------------------------------------------------------------------------- #
# 4 + 5. Price chart with moving averages and toggleable event overlay
# --------------------------------------------------------------------------- #
st.subheader("Exchange rate & moving averages")

events = load_events()
event_kinds = sorted(events["kind"].dropna().unique().tolist()) if not events.empty else []

selected_kinds: list[str] = []
if event_kinds:
    selected_kinds = st.multiselect(
        "Overlay events",
        options=event_kinds,
        default=event_kinds,
        help="Toggle central-bank / political event markers on the price timeline.",
    )

price_fig = go.Figure()
price_fig.add_trace(go.Scatter(
    x=m["date"], y=m["rate"], name="Rate", mode="lines",
    line=dict(color=BLUE, width=2),
    hovertemplate="%{x|%Y-%m-%d}<br>Rate %{y:,.0f}<extra></extra>",
))
if "ma30" in m.columns:
    price_fig.add_trace(go.Scatter(
        x=m["date"], y=m["ma30"], name="30-day MA", mode="lines",
        line=dict(color=ORANGE, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>MA30 %{y:,.0f}<extra></extra>",
    ))
if "ma90" in m.columns:
    price_fig.add_trace(go.Scatter(
        x=m["date"], y=m["ma90"], name="90-day MA", mode="lines",
        line=dict(color=AQUA, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>MA90 %{y:,.0f}<extra></extra>",
    ))

# Event overlay: thin semi-transparent vertical lines + a hoverable marker row
# along the top of the plot (only events inside the selected date range).
if selected_kinds and not events.empty:
    ev = events[
        (events["kind"].isin(selected_kinds))
        & (events["date"].dt.date >= start_d)
        & (events["date"].dt.date <= end_d)
    ]
    if not ev.empty:
        y_top = float(m["rate"].max())
        y_min = float(m["rate"].min())
        # thin translucent guide lines (kept subtle so they never dominate)
        for _, row in ev.iterrows():
            price_fig.add_shape(
                type="line", x0=row["date"], x1=row["date"],
                y0=y_min, y1=y_top, yref="y",
                line=dict(color=event_color(row["kind"]), width=1),
                opacity=0.20, layer="below",
            )
        # one hoverable marker trace per kind (gives labels + a clean legend)
        for kind in selected_kinds:
            k = ev[ev["kind"] == kind]
            if k.empty:
                continue
            price_fig.add_trace(go.Scatter(
                x=k["date"], y=[y_top] * len(k),
                name=f"{kind} event", mode="markers",
                marker=dict(color=event_color(kind), size=9, symbol="triangle-down",
                            line=dict(width=0)),
                customdata=k["label"],
                hovertemplate="%{x|%Y-%m-%d}<br>" + f"{kind}: " +
                              "%{customdata}<extra></extra>",
            ))

style_layout(price_fig, "IDR per USD")
st.plotly_chart(price_fig, use_container_width=True)

# --------------------------------------------------------------------------- #
# 6. Rolling volatility (fractional → %)
# --------------------------------------------------------------------------- #
st.subheader("Rolling annualized volatility")

vol_fig = go.Figure()
if "vol30" in m.columns:
    vol_fig.add_trace(go.Scatter(
        x=m["date"], y=m["vol30"] * 100, name="30-day vol", mode="lines",
        line=dict(color=BLUE, width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>30d %{y:.1f}%<extra></extra>",
    ))
if "vol90" in m.columns:
    vol_fig.add_trace(go.Scatter(
        x=m["date"], y=m["vol90"] * 100, name="90-day vol", mode="lines",
        line=dict(color=ORANGE, width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>90d %{y:.1f}%<extra></extra>",
    ))
style_layout(vol_fig, "Annualized volatility (%)")
st.plotly_chart(vol_fig, use_container_width=True)

# --------------------------------------------------------------------------- #
# 7. Regimes — sharpest episodes
# --------------------------------------------------------------------------- #
st.subheader("Sharpest regime episodes")
regimes = load_regimes()
if regimes is None or regimes.empty:
    st.info("No regime episodes available (`results/regimes.csv` missing or empty).")
else:
    reg = regimes.copy()
    order = {"depreciation": 0, "appreciation": 1}
    if "direction" in reg.columns:
        reg["_o"] = reg["direction"].map(order).fillna(9)
        reg = reg.sort_values(["_o", "pct_change"],
                              ascending=[True, False]).drop(columns="_o")
    show = reg.rename(columns={
        "direction": "Direction", "start": "Start", "end": "End",
        "start_rate": "Start rate", "end_rate": "End rate",
        "pct_change": "% change",
    })
    st.caption(
        "Each row is a sharp ~one-quarter (63 trading-day) move. "
        "Depreciation = rupiah weakened (rate rose)."
    )
    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Start rate": st.column_config.NumberColumn(format="%.0f"),
            "End rate": st.column_config.NumberColumn(format="%.0f"),
            "% change": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

# --------------------------------------------------------------------------- #
# 8. Event study — do meetings move the rate more than baseline?
# --------------------------------------------------------------------------- #
st.subheader("Do events move the rate? (event-window study)")
evstudy = load_event_study()
if evstudy is None or "by_kind" not in evstudy or not evstudy.get("by_kind"):
    note = (evstudy or {}).get("note", "no event-study results available")
    st.info(f"Event study unavailable — {note}.")
else:
    window = evstudy.get("window_days", "?")
    rows = []
    sig_kinds, mover_kinds = [], []
    for kind, r in evstudy["by_kind"].items():
        if "mean_abs_pct" not in r:  # e.g. 'too few events'
            rows.append({
                "Kind": kind, "Events": r.get("n_events", 0), "Period": "—",
                "Mean |move| %": None, "Matched baseline %": None,
                "× baseline": None, "p-value": None,
                "Significant?": r.get("note", "n/a"),
            })
            continue
        ratio = r.get("vs_baseline_ratio")
        is_sig = r.get("significant_5pct", False)
        if ratio is not None and ratio > 1:
            mover_kinds.append(kind)
        if is_sig:
            sig_kinds.append(kind)
        rows.append({
            "Kind": kind,
            "Events": r.get("n_events"),
            "Period": r.get("date_range", "—"),
            "Mean |move| %": r.get("mean_abs_pct"),
            "Matched baseline %": r.get("matched_baseline_mean_abs_pct"),
            "× baseline": ratio,
            "p-value": r.get("p_value"),
            "Significant?": "Yes ✓" if is_sig else "No",
        })
    ev_df = pd.DataFrame(rows)
    st.caption(
        f"Mean |{window}-trading-day move| after each event vs. a **period-matched** "
        "baseline (non-event days within the same date range), so the calmer recent "
        "era isn't compared against the 1999–2008 crisis spikes. 'Significant?' is a "
        "two-sided permutation test (5,000 resamples) at the 5% level."
    )
    st.dataframe(
        ev_df, hide_index=True, use_container_width=True,
        column_config={
            "Mean |move| %": st.column_config.NumberColumn(format="%.3f"),
            "Matched baseline %": st.column_config.NumberColumn(format="%.3f"),
            "× baseline": st.column_config.NumberColumn(format="%.2f"),
            "p-value": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    # Plain-English verdict.
    if sig_kinds:
        st.markdown(
            f"**Read:** {', '.join(sig_kinds)} "
            f"{'meetings move' if len(sig_kinds) == 1 else 'move'} the rate "
            f"significantly more than a typical {window}-day window. "
            + (f"{', '.join(mover_kinds)} exceed baseline on average, but "
               "not all differences clear statistical significance."
               if mover_kinds else "")
        )
    elif mover_kinds:
        st.markdown(
            f"**Read:** {', '.join(mover_kinds)} show larger-than-baseline "
            f"average moves, but none clears the 5% significance bar — the "
            "evidence that these events reliably move the rate is weak."
        )
    else:
        st.markdown(
            "**Read:** no event kind moves the rate more than a typical "
            f"{window}-day window — meetings look like non-events for the rate."
        )

# --------------------------------------------------------------------------- #
# 9. Regional comparison (only if data present)
# --------------------------------------------------------------------------- #
wide = load_wide()
corr = load_correlations()

regional_cols_available = []
if wide is not None and "IDR" in wide.columns:
    regional_cols_available = [c for c in ("MYR", "THB", "SGD") if c in wide.columns]

if regional_cols_available and corr is not None:
    st.subheader("Regional comparison")
    st.caption(
        "All series indexed to 100 at the start of the selected range "
        "(units per USD). A rising line = that currency weakened vs USD."
    )

    w = wide[(wide["date"].dt.date >= start_d) & (wide["date"].dt.date <= end_d)].copy()
    cols = ["IDR"] + regional_cols_available
    reg_fig = go.Figure()
    plotted_any = False
    for col in cols:
        if col not in w.columns:
            continue
        s = pd.to_numeric(w[col], errors="coerce")
        base_idx = s.first_valid_index()
        if base_idx is None:
            continue
        base = s.loc[base_idx]
        if not base or np.isnan(base):
            continue
        indexed = s / base * 100.0
        reg_fig.add_trace(go.Scatter(
            x=w["date"], y=indexed, name=col, mode="lines",
            line=dict(color=REGIONAL_COLORS.get(col, MUTED),
                      width=2 if col == "IDR" else 1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>" + f"{col} " + "%{y:.1f}<extra></extra>",
        ))
        plotted_any = True

    if plotted_any:
        style_layout(reg_fig, "Indexed to 100 at range start")
        st.plotly_chart(reg_fig, use_container_width=True)

    # Correlation numbers.
    corr_map = corr.get("daily_return_correlation_with_IDR", {}) or {}
    if corr_map:
        st.markdown("**Daily-return correlation with IDR:**")
        cc = st.columns(len(corr_map))
        for col_widget, (k, v) in zip(cc, corr_map.items()):
            col_widget.metric(k, f"{v:.3f}", delta_color="off")
    brent = corr.get("idr_brent_return_corr")
    if brent is not None:
        st.markdown(
            f"IDR/USD vs **Brent** daily-return correlation: **{brent:.3f}** "
            f"(n={corr.get('idr_brent_n', '?')}). Indonesia is a net commodity "
            "exporter, so the strength of this link is itself informative."
        )

st.divider()
st.caption(
    "Descriptive/diagnostic study — no forecast. "
    "Artifacts produced by `src/analysis.py`; source data FRED DEXINUS."
)
