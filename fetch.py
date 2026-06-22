"""
fetch.py — Pull Reddit mentions of EHR software systems from the PullPush API.

No authentication required. Caches raw results to data/raw_data.json so re-runs
do not re-hit the API (delete that file to force a fresh pull).

Run:  python fetch.py
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Date range to search. Default: last 12 months.
# Adjust DAYS_BACK to widen / narrow the window.
DAYS_BACK = 365
WINDOW_SECONDS = DAYS_BACK * 24 * 60 * 60

# IMPORTANT — clock skew / ingest lag handling.
# PullPush's dataset can lag well behind wall-clock time (and this machine's
# clock may itself be ahead). If we anchor the window to time.time(), a strict
# "last 365 days" filter can exclude every real result. So instead we fetch
# newest-first WITHOUT server-side date params, then filter client-side to the
# DAYS_BACK window anchored on the most recent timestamp actually seen in the
# data. Set ANCHOR_TO_LATEST_DATA = False to anchor on wall-clock now instead.
ANCHOR_TO_LATEST_DATA = True
NOW_EPOCH = int(time.time())

# Print the raw JSON of the first successful request once, for shape debugging.
DEBUG_RAW = True
_debug_printed = False

BASE_URL = "https://api.pullpush.io/reddit/search"
COMMENT_URL = f"{BASE_URL}/comment/"
SUBMISSION_URL = f"{BASE_URL}/submission/"

PAGE_SIZE = 100            # PullPush max
REQUEST_DELAY = 1.0        # polite delay between requests (seconds)
MAX_RETRIES = 2            # for 429 / 5xx / timeouts — fail fast, PullPush flaky
TIMEOUT = 20               # per-request timeout (seconds)

# PullPush `q=` already searches ALL of Reddit, so the global query per term
# already returns mentions from the priority subreddits. Running an extra
# filtered query per subreddit multiplies request count ~19x for almost no new
# data and makes runs take 30+ min against a slow/flaky API. Leave False.
# Set True only if you suspect a single sub has >100 mentions for a term and is
# being truncated out of the global newest-100 results.
FETCH_PER_SUBREDDIT = False

RAW_DATA_PATH = os.path.join("data", "raw_data.json")
PARTIAL_PATH = os.path.join("data", "raw_partial.json")  # resumable progress

# EHR systems → list of search terms (aliases included).
EHR_TERMS = {
    "AthenaHealth": ["AthenaHealth"],
    "NextGen": ["NextGen"],
    "eClinicalWorks": ["eClinicalWorks", "eCW"],
    "Tebra": ["Tebra", "Kareo"],
    "DrChrono": ["DrChrono"],
    "ModMed": ["ModMed", "Modernizing Medicine"],
    "Practice Fusion": ["Practice Fusion"],
    "CharmHealth": ["CharmHealth"],
}

# Telehealth / home-care competitors (from competitor_matrix.xlsx). Each is
# tracked under the "Telehealth/Home-Care" category so the dashboard can keep
# the EHR and telehealth segments separate.
from competitors import (TELEHEALTH_TERMS, CATEGORY_EHR,  # noqa: E402
                         CATEGORY_TELEHEALTH)

# (entity_name, category) -> search terms, for one combined fetch loop.
ENTITY_GROUPS = [(CATEGORY_EHR, EHR_TERMS),
                 (CATEGORY_TELEHEALTH, TELEHEALTH_TERMS)]

# Subreddits to prioritize. We run one filtered query per subreddit PLUS an
# unfiltered global query for each term to catch mentions outside these subs.
PRIORITY_SUBREDDITS = [
    "medicine",
    "familymedicine",
    "healthIT",
    "medicalbilling",
    "CodingandBilling",
    "physicianassistant",
    "nursing",
    "healthcare",
    "Residency",
]

REDDIT_BASE = "https://www.reddit.com"


# --------------------------------------------------------------------------- #
# HTTP helper with retry / backoff
# --------------------------------------------------------------------------- #

def get_with_retry(url, params):
    """GET with exponential backoff on 429 / 5xx. Returns parsed JSON or None.

    Quiet by design: transient timeouts/5xx are retried silently. Only a final
    give-up (after MAX_RETRIES) prints, so a slow PullPush doesn't spam the log
    with scary-looking 'Read timed out' lines on every attempt.
    """
    last_problem = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_problem = f"network ({type(exc).__name__})"
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                print("    bad JSON in 200 response; skipping")
                return None

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_problem = f"HTTP {resp.status_code}"
            time.sleep(2 ** attempt)
            continue

        # Other client error — no point retrying.
        print(f"    HTTP {resp.status_code}; giving up on this query")