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
fetch.py          ->  data/raw_data.json        (Reddit via PullPush)
reviews.py        ->  data/reviews_data.json    (Apple App Store — FREE)
playstore.py      ->  data/playstore_data.json  (Google Play — FREE)
manual_reviews.py ->  data/manual_data.json     (G2/Capterra/etc CSV import)
chpl.py           ->  data/chpl_data.json       (ONC cert data — free key)
analyze.py        ->  data/analyzed_data.json   (sentiment + themes; merges all)
dashboard.py      (Streamlit; reads the JSON files — never hits an API on load)
```

Data sources (all free):
- **Reddit** via PullPush — no key.
- **Apple App Store** reviews via iTunes Search + RSS — no key, official, real
  1-5★ ratings. `reviews.py` folds these into the same sentiment/theme pipeline.
- **ONC CHPL** certified-product registry — free API key required (see below).

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

# 2. (Optional, FREE) Pull app-store reviews — adds real star ratings.
python reviews.py        # Apple App Store
python playstore.py      # Google Play

# 2b. (Optional) Import hand-collected G2/Capterra/etc reviews:
#      drop CSVs in data/manual_reviews/ (see TEMPLATE.csv), then:
python manual_reviews.py

# 3. (Optional) Pull ONC CHPL certified-product data — needs a free key:
#      get key at https://chpl.healthit.gov/#/resources/api
#      export CHPL_API_KEY=your-key   (or put it in chpl_api_key.txt)
python chpl.py

# 4. Sentiment + theme analysis (merges reviews if present).
python analyze.py

# 5. Launch the dashboard.
streamlit run dashboard.py
```

## Dashboard views

- **Overview** — average sentiment per EHR (ranked best→worst) and mention
  volume. Low-volume vendors (under ~15 mentions) flagged as low-confidence.
- **Per-System** — pick one EHR: sentiment breakdown, top complaints/praises,
  and a scrollable table of real sample quotes with clickable Reddit links.
  Usernames are never shown.
- **Churn Signals** — mentions with switching/leaving language ("switching
  from", "looking for an alternative to"). High counts = vendors actively
  losing customers → poaching targets, with quotes as sales evidence.
- **Complaint Heatmap** — EHR × complaint-theme matrix. A theme hot across ALL
  vendors = a universal unmet need = the market gap. Auto-flags the biggest one.
- **Comparison** — side-by-side table of all 8 EHRs: mentions, % positive,
  % negative, avg sentiment, top complaint, top praise.
- **App Store** — official weighted avg star rating per EHR, plus sample
  reviews with stars next to VADER sentiment (ground-truth check).
- **Market Presence** — ONC CHPL: certified products, active vs declined
  certifications, latest cert date.
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
