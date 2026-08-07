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
| **ECB euro reference rates** (via [DBnomics](https://db.nomics.world), no API key) | `ECB/EXR` IDR, USD, MYR, THB, SGD, PHP per EUR | **Implemented** primary + regional rates |
| FRED (Federal Reserve Economic Data) | `DEXINUS` | Spec'd primary source; used as an independent cross-check |
| federalreserve.gov / bi.go.id | meeting calendars | FOMC & Bank Indonesia event dates |

**On the source substitution:** the project spec names FRED `DEXINUS` as the
primary series, but FRED's public CSV endpoint tarpits repeated automated requests
(the connection opens, then no response body is ever returned), so it was not
reliably reachable from the build environment. To keep the pipeline reproducible
for anyone, the *implemented* source is the **ECB euro reference rates** — an
official, widely-cited daily FX series back to 1999 — pulled via DBnomics, with the
USD cross-rate reconstructed as `IDR/USD = (IDR per EUR) / (USD per EUR)`. ECB and
FRED differ only marginally (fixing time). When FRED is reachable, `pipeline.py`
uses it to cross-check the reconstructed series automatically. A bonus of ECB: it
also covers the Philippine peso (PHP), which FRED's daily series does not.

Provenance and confidence of the hand-curated event dates — including an explicit
flag that **Bank Indonesia dates for 2016–2020 are month-accurate but
day-approximate** — are documented in
[`events/EVENTS_SOURCES.md`](events/EVENTS_SOURCES.md).

### Cleaning decisions
- The source marks non-trading days (weekends, TARGET/bank holidays) as null.
  These rows are **dropped, not forward-filled**, so every observation is real.
  All returns and volatility are therefore computed on **trading days only**.
- Volatility is the standard deviation of daily returns, **annualized with √252**.
- Full cleaning notes are written to [`data/data_notes.md`](data/data_notes.md).

---

## Methodology (Phase 2)

- **Returns & trend:** daily % change, 30/90-day rolling moving averages.
- **Volatility regimes:** 30- and 90-day rolling annualized volatility, plus each
  day's current volatility expressed as a percentile of its own history.
- **Regime episodes:** the sharpest non-overlapping ~quarter (63-trading-day)
  depreciation and appreciation windows — the "find the story" step.
- **Event-window study:** for each FOMC / BI / political event, the |5-trading-day
  forward move| is compared against a **period-matched baseline** (non-event days
  within that event kind's own date range — so the calm 2013–2025 era is not
  compared against the 1999–2008 crisis spikes) using a two-sided **permutation
  test** (5,000 resamples, fixed seed), reported with a p-value.
- **Enrichment:** IDR/USD daily-return correlation with the regional Southeast
  Asian currencies (MYR, THB, SGD, PHP) as a co-movement check.

---

## Project structure

```
idr-usd-fx/
├── src/
│   ├── pipeline.py     # Phase 1 — fetch (ECB via DBnomics) + clean, FRED cross-check
│   └── analysis.py     # Phase 2 — metrics, regimes, event study, findings
├── app.py              # Phase 3 — Streamlit dashboard
├── data/
│   ├── idr_usd_daily.csv   # cleaned primary series (date, rate)
│   ├── fx_wide.csv         # IDR + regional FX (MYR, THB, SGD, PHP), aligned
│   ├── raw/                # cached raw downloads (reproducibility / offline)
│   └── data_notes.md       # source + cleaning documentation
├── events/                 # curated FOMC / BI / political event dates + sources
├── results/                # generated analysis artifacts + findings.md
├── scripts/fetch_fred.sh   # optional patient FRED downloader (cross-check only)
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

`pipeline.py` pulls the ECB reference rates from DBnomics (no API key) and caches
the raw payload to `data/raw/ecb_exr.json`, so subsequent runs work offline. It
then tries FRED `DEXINUS` as a cross-check; if FRED is unreachable that step is
skipped and noted in `data/data_notes.md` rather than failing. The bundled
`scripts/fetch_fred.sh` is an optional patient downloader for populating the FRED
cross-check cache where FRED is reachable.

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
