# IDR/USD Exchange Rate Analysis

End-to-end analysis of the **Indonesian Rupiah vs. US Dollar** exchange rate: a
clean historical data pipeline, a set of defensible analytical findings (trend,
volatility regimes, central-bank event sensitivity, commodity linkage), and an
interactive Streamlit dashboard that presents them.

This is a **descriptive / diagnostic** study — not a forecasting model and not a
trading signal. The goal is correctness and clear reasoning end to end.

> **Quote convention:** the rate is quoted as **IDR per 1 USD** (FRED `DEXINUS`).
> A *higher* number means a *weaker* rupiah.

---

## Findings

The headline findings, regenerated from the data on every run, live in
**[`results/findings.md`](results/findings.md)** (a one-page analyst-style memo).
They cover: the rupiah's long-run depreciation path and its sharpest episodes,
how regime-dependent volatility is, whether FOMC / Bank Indonesia meetings move
the rate more than an average day (permutation-tested), and the IDR–Brent link.

The interactive dashboard presents the same story with adjustable date ranges and
toggleable event overlays.

---

## Data sources

| Source | Series | Use |
| --- | --- | --- |
| **FRED** (Federal Reserve Economic Data) | `DEXINUS` | Primary IDR/USD daily rate |
| FRED | `DEXMAUS`, `DEXTHUS`, `DEXSIUS` | Regional FX comparison (MYR, THB, SGD) |
| FRED | `DCOILBRENTEU` | Brent crude — commodity-linkage enrichment |
| yfinance | `IDR=X` | Independent cross-check of the recent window |
| federalreserve.gov / bi.go.id | meeting calendars | FOMC & Bank Indonesia event dates |

FRED is treated as the source of truth; yfinance is used only to sanity-check the
most recent window. Provenance and confidence of the hand-curated event dates are
documented in [`events/EVENTS_SOURCES.md`](events/EVENTS_SOURCES.md).

### Cleaning decisions
- FRED marks non-trading days (weekends, US bank holidays) with `.`. These rows
  are **dropped, not forward-filled**, so every observation is real. All returns
  and volatility are therefore computed on **trading days only**.
- Volatility is the standard deviation of daily returns, **annualized with √252**.
- Full cleaning notes are written to [`data/data_notes.md`](data/data_notes.md).

---

## Methodology (Phase 2)

- **Returns & trend:** daily % change, 30/90-day rolling moving averages.
- **Volatility regimes:** 30- and 90-day rolling annualized volatility, plus each
  day's current volatility expressed as a percentile of its own history.
- **Regime episodes:** the sharpest non-overlapping ~quarter (63-trading-day)
  depreciation and appreciation windows — the "find the story" step.
- **Event-window study:** for each FOMC / BI meeting, the |5-trading-day forward
  move| is compared against a baseline of *all* trading days using a
  **permutation test** (5,000 resamples, fixed seed) — testing whether meetings
  actually move the rate more than an average day, with a p-value.
- **Enrichment:** IDR/USD daily-return correlation with Brent crude and with
  regional Southeast Asian currencies.

---

## Project structure

```
idr-usd-fx/
├── src/
│   ├── pipeline.py     # Phase 1 — fetch + clean FRED data, cross-check yfinance
│   └── analysis.py     # Phase 2 — metrics, regimes, event study, findings
├── app.py              # Phase 3 — Streamlit dashboard
├── data/
│   ├── idr_usd_daily.csv   # cleaned primary series (date, rate)
│   ├── fx_wide.csv         # IDR + regional FX + Brent, aligned
│   ├── raw/                # cached raw FRED downloads (reproducibility)
│   └── data_notes.md       # source + cleaning documentation
├── events/                 # curated FOMC / BI / political event dates
├── results/                # generated analysis artifacts + findings.md
├── scripts/fetch_fred.sh   # patient FRED downloader (see note below)
└── requirements.txt
```

---

## Running it locally

Requires **Python 3.10–3.12** (the data stack does not yet support 3.13+).

```bash
# 1. environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Phase 1 — pull + clean the data  (writes data/)
python src/pipeline.py

# 3. Phase 2 — run the analysis        (writes results/)
python src/analysis.py

# 4. Phase 3 — launch the dashboard
streamlit run app.py
```

`pipeline.py` downloads directly from FRED. If your network throttles the FRED
endpoint, run the bundled patient downloader first — it caches the raw CSVs into
`data/raw/`, which the pipeline then reads offline:

```bash
bash scripts/fetch_fred.sh
```

---

## Deployment

The dashboard is a single self-contained Streamlit app and deploys to
**Streamlit Community Cloud** (point it at `app.py`) or Railway. The committed
`data/` and `results/` artifacts mean the deployed app renders without needing to
re-pull FRED at boot.

<!-- Add the live dashboard URL here once deployed. -->

---

## Non-goals (kept out of scope on purpose)

- No predictive/forecasting model — this is descriptive/diagnostic.
- No live/real-time streaming — a daily batch pull is sufficient.
- No authentication or multi-user infrastructure — it's a portfolio piece.
