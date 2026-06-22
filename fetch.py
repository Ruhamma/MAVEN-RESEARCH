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