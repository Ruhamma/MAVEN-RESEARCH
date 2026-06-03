# EHR Market Research Dashboard

Competitive market-research tool that analyzes public Reddit discussion about
EHR (electronic health record) software vendors. It pulls mentions from the free
**PullPush** Reddit API (no auth, no keys), scores sentiment with VADER, extracts
complaint/praise themes by keyword, and presents everything in a Streamlit
dashboard.

EHR systems tracked: AthenaHealth, NextGen, eClinicalWorks (eCW), Tebra (Kareo),
DrChrono, ModMed (Modernizing Medicine), Practice Fusion, CharmHealth.

## Pipeline

```
fetch.py   ->  data/raw_data.json       (Reddit mentions, cached)
analyze.py ->  data/analyzed_data.json  (sentiment + themes, aggregated)
dashboard.py (Streamlit, reads analyzed_data.json — never hits the API)
```

## Setup

```bash
pip install -r requirements.txt
```

The VADER lexicon is required by `analyze.py`. If it is not already present:

```bash
python -c "import nltk; nltk.download('vader_lexicon')"
```

## Run — in order

```bash
# 1. Pull Reddit mentions (caches to data/raw_data.json).
#    Re-runs load the cache instead of re-hitting the API.
#    Delete data/raw_data.json to force a fresh pull.
python fetch.py

# 2. Sentiment + theme analysis (writes data/analyzed_data.json).
python analyze.py

# 3. Launch the dashboard.
streamlit run dashboard.py
```

## Dashboard views

- **Overview** — average sentiment per EHR (ranked best→worst) and mention
  volume. Low-volume vendors (under ~15 mentions) flagged as low-confidence.
- **Per-System** — pick one EHR: sentiment breakdown, top complaints/praises,
  and a scrollable table of real sample quotes with clickable Reddit links.
  Usernames are never shown.
- **Comparison** — side-by-side table of all 8 EHRs: mentions, % positive,
  % negative, avg sentiment, top complaint, top praise.
- **Gap Analysis** — competitor weakness → MavenMD opportunity, loaded from
  `data/gaps.csv` (edit that file freely; not hardcoded).

## Configuration

- **Date window** — `DAYS_BACK` at the top of `fetch.py` (default 365 days).
  The window is anchored on the newest available data, not the wall clock, so
  it is robust to PullPush ingest lag and machine clock skew. Set
  `ANCHOR_TO_LATEST_DATA = False` to anchor on "now" instead.
- **Subreddits / search terms** — `PRIORITY_SUBREDDITS` and `EHR_TERMS` in
  `fetch.py`.
- **Themes** — `COMPLAINT_THEMES` / `PRAISE_THEMES` keyword maps in `analyze.py`.
- **Low-volume threshold** — `LOW_VOLUME_THRESHOLD` in `dashboard.py`.
- **Gap mapping** — `data/gaps.csv` (columns: `EHR, top_complaint,
  mavenmd_opportunity`).

## Notes & caveats

- Data is public Reddit discussion via PullPush. PullPush is a community service
  and its dataset can lag behind real time; `fetch.py` handles this.
- Sentiment is automated (VADER) and should be spot-checked — sarcasm, context,
  and clinical jargon can fool it.
- Mention counts vary widely by vendor popularity; cross-vendor comparisons of
  low-volume EHRs are unreliable.
- The tool is polite to the API: ~1s between requests, exponential backoff on
  HTTP 429 / 5xx.
- For competitive research only. Not an endorsement of any vendor.
