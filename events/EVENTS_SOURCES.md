# Event-date datasets — sources & provenance

Compiled for the IDR/USD "event window" analysis. Guiding rule for this project:
**never present unverified data as if it were verified.** This file records exactly
which dates were confirmed against a primary/authoritative source and which come from
model knowledge and therefore need spot-checking.

Generated: 2026-08 (dates confirmed live where the network allowed; this environment's
outbound network was intermittently blocked, so some fallbacks to model knowledge were
necessary and are flagged below).

---

## 1. `fomc_dates.csv` — FOMC decision dates (103 rows, 2013–2025)

Column meaning: `date` = final day of each scheduled two-day FOMC meeting (statement
release / decision day), `kind` = `FOMC`, `label` = `FOMC decision`.

**Confidence: HIGH (verified from source).**

Sources reached successfully (federalreserve.gov):
- `fomccalendars.htm` — current calendar, covering 2023, 2024, 2025.
- `fomchistorical2013.htm` through `fomchistorical2020.htm` — years 2013–2020.
- 2021 and 2022: the Fed's historical pages for these years were **not yet published**
  (Fed keeps a rolling ~5-year window on the main calendar and releases full historical
  materials on a delay), so both returned HTTP 404. Their eight decision dates were
  instead confirmed via web search against federalreserve.gov press-conference /
  press-release URLs and reputable summaries. These are standard, widely-published dates
  and are treated as verified.

Notes / caveats:
- **2023** has 8 meetings. One automated fetch of the calendar page omitted the
  2023-09-20 meeting; it was added back from knowledge and is a well-documented date.
- **2020 has only 7 rows.** The scheduled March 17–18, 2020 meeting was overtaken by the
  pandemic: the Fed acted at **unscheduled** emergency meetings on 2020-03-03 (Tuesday)
  and 2020-03-15 (a **Sunday**). Both are excluded because (a) they were unscheduled and
  (b) the requirement is weekday scheduled-meeting decision dates. If your analysis wants
  the March 2020 shock captured, add 2020-03-15 manually and treat it as a special case.
- All 103 dates verified to fall on weekdays.

---

## 2. `bi_dates.csv` — Bank Indonesia RDG decision dates (120 rows, 2016–2025)

Column meaning: `date` = second/final day of each monthly Rapat Dewan Gubernur (RDG),
i.e. the BI-Rate announcement day; `kind` = `BI`, `label` = `BI RDG`.
BI holds RDG over two consecutive days and announces the decision on day 2 — that day 2
is what is recorded here.

**Confidence is MIXED. Read this before using pre-2021 rows.**

### VERIFIED (HIGH confidence) — 2021 through 2025 (60 rows)
Confirmed against Bank Indonesia's own annual-schedule press releases and/or reputable
Indonesian financial media reproducing them:
- **2025** — bi.go.id news-release `sp_2628124.aspx`; also infobanknews.com. (Full 12-month schedule.)
- **2024** — liputan6.com full-schedule article; corroborated by bi.go.id.
- **2023** — bi.go.id news-release `sp_2434922.aspx`; also bisnis.com. (Full 12-month schedule.)
- **2022** — bi.go.id news-release `sp_2334021.aspx`. (Full 12-month schedule; note the
  unusually early **Feb 9–10** meeting → decision 2022-02-10.)
- **2021** — bi.go.id schedule press release; also kontan.co.id. Note **October 2021 was
  rescheduled** from 17–18 to Mon–Tue 18–19 → decision 2021-10-19 (reflected in the file).

### UNVERIFIED (from model knowledge) — 2016 through 2020 (60 rows) — SPOT-CHECK THESE
The full annual RDG schedules for 2016–2020 could not be retrieved from bi.go.id in this
environment (older press releases did not surface in search, and several direct fetches
were blocked or 404'd). These 60 rows are **model-knowledge estimates**. Treat them as:
- **Month = reliable** (there was one RDG per month in each of these years).
- **Exact day = approximate.** BI mostly announced on a mid/late-month Wednesday or
  Thursday in this era, but the precise day for a given month may be off by a few days.
  For a ±window event study this can matter, so **please verify each 2016–2020 date
  against bi.go.id before relying on it.**

Individual dates in the 2016–2020 block that WERE independently corroborated (higher
confidence than the rest of the block):
- 2016-12-15 (Dec 14–15 RDG) — corroborated.
- 2018-09-27 (Sep 26–27) and 2018-11-15 (Nov 14–15) — corroborated.
- 2019-02-21 and 2019-04-25 — corroborated (TradingEconomics decision records).
- 2020-01-23 (Jan 22–23), 2020-07-16 (Jul 15–16), 2020-11-19 (Nov 18–19) — corroborated.

Other caveats for the unverified block:
- **2018** also had an **unscheduled** inter-meeting rate hike on **2018-05-30** (not in
  the file, which keeps to the regular monthly cadence). Add it if you want the May 2018
  defense of the rupiah represented.
- **2020** schedule was disrupted by COVID; some months were moved earlier than the usual
  slot. The April 2020 date in particular (recorded 2020-04-14) should be double-checked.
- All 120 rows are weekdays by construction, but a weekday landing is not proof the day is
  correct for the unverified block.

BI moved to the announced monthly-RDG cadence in this window; 2016 is the first full year
covered per the task spec.

---

## 3. `political_events.csv` — curated macro/political events (10 rows, 2013–2025)

Hand-picked events that plausibly moved IDR/USD. `kind` = `Political`, `label` ≤ 40 chars.
These are well-known dated events; dates are from general knowledge and are high
confidence, but they mark a *trigger day*, not necessarily the day of the largest FX move.

| date | label | note on dating |
|------|-------|----------------|
| 2013-05-22 | Fed taper tantrum begins | Bernanke testimony to Congress; the classic trigger. IDR sold off over the following months. |
| 2014-07-09 | Indonesia presidential election 2014 | Election (voting) day; Jokowi win officially confirmed 2014-07-22. |
| 2016-11-08 | US presidential election (Trump) | US election day. |
| 2018-08-13 | 2018 EM currency selloff | Peak of the Turkey/EM contagion (lira crash); IDR neared 15,000. Represents the broader 2018 EM stress. |
| 2019-04-17 | Indonesia presidential election 2019 | Election day; Jokowi re-elected. |
| 2020-03-11 | WHO declares COVID-19 pandemic | Trigger date; the sharpest IDR move (toward ~16,600) came ~2020-03-23. |
| 2022-02-24 | Russia invades Ukraine | Global risk-off / commodity shock. |
| 2022-03-16 | Fed begins 2022 hiking cycle | First hike of the cycle (same day as the FOMC decision in `fomc_dates.csv`). |
| 2024-02-14 | Indonesia presidential election 2024 | Election day; Prabowo won. |
| 2025-04-02 | US Liberation Day tariffs | Sweeping US tariff announcement; large EM/FX reaction. |

Selection is judgment-based; feel free to add/remove. All are within 2013–2025 and fall on
weekdays (not required for this file, but true here).

---

## Reproduce / regenerate
All three CSVs are emitted and self-validated (ascending sort, no duplicate dates,
weekday check for FOMC/BI, label-length check) by the generator script used to build them.
Validation performed with the project venv:

    .venv/bin/python -c "import pandas as pd; [print(f, len(pd.read_csv(f)),'rows') for f in ['events/fomc_dates.csv','events/bi_dates.csv','events/political_events.csv']]"
    # -> fomc_dates.csv 103 rows / bi_dates.csv 120 rows / political_events.csv 10 rows

## TL;DR for the analyst
- **FOMC (all years): trust it.**
- **BI 2021–2025: trust it.**
- **BI 2016–2020: verify each date against bi.go.id before using — month is right, day may be off.**
- **Political events: trigger dates, high confidence, but curated/subjective.**
