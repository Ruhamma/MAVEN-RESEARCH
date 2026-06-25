# EHR & Telehealth Market Research Dashboard

Competitive market-research tool for **MavenMD**. It analyzes public discussion +
reviews about two competitor segments, scores sentiment with VADER, mines
complaint/praise themes, and presents everything in a Streamlit dashboard.

Two segments (toggle in the sidebar):

1. **EHR Systems** — AthenaHealth, NextGen, eClinicalWorks (eCW), Tebra (Kareo),
   DrChrono, ModMed (Modernizing Medicine), Practice Fusion, CharmHealth.
2. **Telehealth / Home-Care** — ~32 marketplace/telehealth/home-care competitors
   from `competitor_matrix.xlsx` (Zocdoc, Teladoc, One Medical, DispatchHealth,
   Honor, Care.com, Heal, Hims & Hers, Sesame, Amazon Pharmacy, …).

Data is gathered from **five free sources** and merged into one pipeline.

## Data sources (all free)

| Source | Module | Key? | Notes |
|---|---|---|---|
| Reddit (PullPush) | `fetch.py` | none | `q=` search, comments + submissions |
| Apple App Store | `reviews.py` | none | iTunes Search + RSS, real 1-5★ |
| Google Play | `playstore.py` | none | `google-play-scraper` lib |
| Trustpilot | `trustpilot.py`, `lowstar.py` | none | Playwright (Cloudflare bypass), 1-5★ |
| G2 / Capterra / etc. | `manual_reviews.py` | none | hand-collected CSV import |
| ONC CHPL (EHR market data) | `chpl.py` | free key | certified-product registry |

All review sources are normalized into the **same mention schema**, so
`analyze.py` merges them automatically and every dashboard view sees all of them.

## Pipeline

```
competitors.py    ->  data/competitor_matrix.json  (parsed from the xlsx)
fetch.py          ->  data/raw_data.json           (Reddit, EHR + telehealth)
reviews.py        ->  data/reviews_data.json       (Apple App Store)
playstore.py      ->  data/playstore_data.json     (Google Play)
trustpilot.py     ->  data/trustpilot_data.json    (Trustpilot, all stars)
lowstar.py        ->  data/lowstar_data.json        (Trustpilot 1-3★ only)
manual_reviews.py ->  data/manual_data.json        (G2/Capterra CSVs)
chpl.py           ->  data/chpl_data.json          (ONC cert data — free key)
analyze.py        ->  data/analyzed_data.json      (sentiment + themes; merges all)
dashboard.py      (Streamlit; reads the JSON files — never hits an API on load)
```

## Setup

```bash
pip install -r requirements.txt

# Trustpilot scraping needs a headless browser (one time):
playwright install chromium

# VADER lexicon (if not already present):
python -c "import nltk; nltk.download('vader_lexicon')"
```

## Run — in order

```bash
# 0. Parse the competitor matrix xlsx (telehealth segment config + matrix view).
python competitors.py

# 1. Reddit mentions (EHR + telehealth). Resumable + cached to raw_data.json;
#    delete raw_data.json (and raw_partial.json) to force a fresh pull.
python fetch.py

# 2. (FREE) App-store reviews — real star ratings.
python reviews.py        # Apple App Store
python playstore.py      # Google Play

# 3. (FREE) Trustpilot reviews via Playwright.
python trustpilot.py     # all reviews (overall ratings + samples)
python lowstar.py        # ONLY 1-3★ reviews -> Pain Points page

# 4. (Optional) Hand-collected G2/Capterra/etc reviews:
#    drop CSVs in data/manual_reviews/ (see TEMPLATE.csv), then:
python manual_reviews.py

# 5. (Optional, EHR only) ONC CHPL certified-product data — needs a free key:
#    get key at https://chpl.healthit.gov/#/resources/api
#    export CHPL_API_KEY=your-key   (or put it in chpl_api_key.txt)
python chpl.py

# 6. Sentiment + theme analysis (merges every source present).
python analyze.py

# 7. Launch the dashboard.
streamlit run dashboard.py
```

Most collectors are **resumable / cache-safe**: `fetch.py` and `lowstar.py` save
progress per item and skip what's done on re-run; `reviews.py` / `playstore.py`
won't overwrite a good cache with an empty pull (network blip protection).

## Dashboard views

Pick a **Segment** (EHR Systems / Telehealth & Home-Care) in the sidebar; the
view list adapts. Quote tables order sources **Trustpilot → App Store →
Google Play → manual → Reddit (last)**.

- **Per-System** — one entity: data volume + source breakdown, sentiment
  breakdown, top complaints/praises, scrollable sample quotes (clickable links,
  no usernames).
- **App Store** — official weighted avg star rating per entity (Apple vs Google
  Play), top complaints from app reviews, sample reviews with stars vs VADER.
- **Pain Points (1-3★)** — only the unhappy Trustpilot reviews: segment-wide top
  complaints, per-competitor complaint breakdown, and a table linking to the
  **exact** Trustpilot review (`/reviews/{id}`). Where each competitor loses
  people = where MavenMD can win.
- **Overview** — avg sentiment (best→worst) + mention volume; low-volume flag.
- **Churn Signals** — switching/leaving language ("switching from", "looking for
  an alternative to") → who's losing customers, with quotes as sales evidence.
- **Complaint Heatmap** — entity × complaint-theme matrix; a theme hot across all
  = a universal gap. Auto-flags the biggest one.
- **Comparison** — side-by-side table of all entities in the segment.
- **Competitor Matrix** (telehealth) — renders `competitor_matrix.xlsx`
  (matrix / your-build-vs-threats / gap analysis).
- **Market Presence** (EHR) — ONC CHPL: certified products, active vs declined
  certs, latest cert date.
- **Gap Analysis** (EHR) — competitor weakness → MavenMD opportunity, from
  `data/gaps.csv` (editable, not hardcoded).

## Configuration

- **Date window** — `DAYS_BACK` in `fetch.py` (default 365). Anchored on newest
  available data, robust to PullPush lag / clock skew (`ANCHOR_TO_LATEST_DATA`).
- **Tracked entities** — `EHR_TERMS` in `fetch.py`; `TELEHEALTH_TERMS` and the
  xlsx in `competitors.py`. App/domain maps in `reviews.py`, `playstore.py`,
  `trustpilot.py`.
- **Themes** — `COMPLAINT_THEMES` / `PRAISE_THEMES` in `analyze.py` (includes
  telehealth-specific themes: caregiver no-show, scheduling, refunds, etc.).
- **Low-volume threshold** — `LOW_VOLUME_THRESHOLD` in `dashboard.py`.
- **Gap mapping** — `data/gaps.csv` (`EHR, top_complaint, mavenmd_opportunity`).

## Notes & caveats

- **Reddit signal fluctuates** — volume/sentiment swing with a few vocal threads
  and PullPush's shifting coverage. Treat Reddit as directional; lean on the
  star-rated sources (Trustpilot, App Store, Google Play) for confidence.
- Sentiment is automated (VADER) — spot-check it; sarcasm/jargon can fool it.
- **Trustpilot is scraped** (ToS forbids scraping) via Playwright; the App
  Store / Google Play / PullPush / CHPL sources are official APIs. Use the
  scraped data for internal research only.
- Volume varies widely by platform popularity; cross-entity comparisons of
  low-volume names are unreliable.
- Collectors are polite: ~1s between requests, exponential backoff on 429 / 5xx.
- For competitive research only. Not an endorsement of any vendor.
