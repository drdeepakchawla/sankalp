# Sankalp newborn outcomes

Tools for following up the outcome of every baby enrolled in Sankalp (Khargone district):
neonatal mortality (NMR), where, when and why babies die, which babies die, SNCU outcomes,
and data errors to correct.

Three exports go in:

| File | What it is |
|---|---|
| `SankalpKhargone_DATA_LABELS_<date>.csv` | 2024 cohort (REDCap, labels export): one row per pregnancy, births 16 May–31 Dec 2024, outcomes collected retrospectively |
| `NHRPsankalpUpdated_DATA_LABELS_<date>.csv` | 2025–26 cohort (NHRP REDCap, labels export): birth notification, registration and day-28 phone follow-up, up to 3 babies per mother |
| `SNCU Admission Report_<range>.xlsx` | DH Khargone SNCU register: sheet `working` (all admissions) and the deaths sheet |

Two things come out:

1. **The dashboard**: a single HTML page with de-identified records embedded (no names,
   phones, villages or exact dates), published privately on claude.ai. It has a box for asking
   questions of the data in plain words.
2. **The local app**: a Streamlit app for the identifiable records, used to look records up
   and work through correction lists. It runs only on the computer that holds the exports.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Process new exports

Export both REDCap projects as **CSV (labels)**, then:

```bash
python -m sankalp.build \
  --k2024 "path/to/SankalpKhargone_DATA_LABELS_2026-10-13_1625.csv" \
  --nhrp  "path/to/NHRPsankalpUpdated_DATA_LABELS_2026-10-13_1543.csv" \
  --sncu  "path/to/SNCU Admission Report.xlsx" \
  --out output
```

`output/` (git-ignored) then holds:

- `babies.parquet`, `sncu.parquet`: full tables, identifiers included (local use only)
- `dashboard.html`: the dashboard with the new de-identified data embedded
- `summary.json`: headline numbers, SNCU match rates and data-quality counts

The export date is read from the REDCap file names (`--as-of` overrides it). It decides which
babies are still under 28 days old.

## Local app

```bash
streamlit run app/streamlit_app.py
```

Tabs: summary by period and block · find a record (Record ID, phone, parent's name, SNCU
admission ID) · worklists by data-quality check, with contacts, as CSV · suspected duplicate
registrations side by side · SNCU deaths missing from the cohort, and SNCU admissions not
found in the cohort with candidate matches.

## Definitions

- **Neonatal death**: live-born baby who died at 0–27 completed days. A death on the
  programme's "day 28" (DOB + 28) is post-neonatal. Early neonatal: 0–6 days.
- **NMR**: neonatal deaths per 1,000 live births whose day-28 outcome is known. Babies under
  28 days old ("pending"), not reachable or not followed up are left out and reported as
  follow-up completeness.
- **Stillbirth rate**: stillbirths per 1,000 total births. In the 2024 form stillbirths are
  also marked "not alive on day 28"; they are excluded from neonatal deaths.
- **2025–26 outcome**: a baby counts as dead if any form (notification, registration or any of
  the day-28 follow-ups) reports a death. The earliest death date is used, and disagreements
  are flagged. A baby counts as alive if a connected follow-up call reports them healthy or sick.
- **Gestation**: from LMP (2025–26: ultrasound first, then LMP, then clinical estimate). Values
  outside 22–44 weeks are treated as missing.
- **Block** is the block of residence. "Out of district" = not a usual resident of Khargone.

All limits (age windows, plausibility ranges, bands) are in `sankalp/config.py`.

## SNCU linkage

SNCU admissions are matched to cohort babies inside the pipeline:

1. same family phone number and date of birth within 2 days;
2. both parents' names similar and date of birth within 2 days;
3. same phone, date of birth within 7 days and one parent's name similar.

Twins are told apart by sex and weight. On the October 2026 data, 75% of admissions matched,
with 97% agreement on sex and a median weight difference of 80 g. The outputs keep only the link.

## Data-quality checks

Each baby and each SNCU admission gets a list of check codes (`sankalp/quality.py` holds the
full list with descriptions and severity): missing or impossible dates, unknown day-28
outcome, alive after a recorded death, stillbirths reported alive later, SNCU deaths not
recorded as deaths in the cohort, implausible weight or gestation, suspected duplicate
registrations, follow-up calls before day 28, and others.

## Code layout

```
sankalp/
  config.py      definitions and limits
  harmonise.py   dates, phones, block and facility names, bands
  cohort2024.py  2024 export -> one row per baby
  cohort2025.py  NHRP export (14 REDCap forms) -> one row per baby
  outcomes.py    neonatal outcome, NMR
  sncu.py        SNCU register
  link.py        SNCU <-> cohort matching
  quality.py     data-quality checks
  export.py      de-identified dashboard payload
  build.py       runs everything
dashboard/index.html   dashboard template (data is injected by build.py)
app/streamlit_app.py   local app
tests/                 unit tests on synthetic data (pytest)
```

## Privacy

Never commit or share the exports or anything in `output/` other than the dashboard. The
dashboard carries REDCap Record IDs and SNCU admission IDs, so errors can be found in REDCap,
plus month of birth, block and facility. Staff appear only as codes (`R24-07`, `T25-03`).
