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
        return None

    print(f"    skipped query after {MAX_RETRIES} tries ({last_problem})")
    return None


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def normalize_comment(item, ehr, term):
    body = (item.get("body") or "").strip()
    if not body or body in ("[removed]", "[deleted]"):
        return None
    permalink = item.get("permalink") or ""
    return {
        "ehr": ehr,
        "matched_term": term,
        "kind": "comment",
        "text": body,
        "score": item.get("score", 0),
        "subreddit": item.get("subreddit", ""),
        "permalink": REDDIT_BASE + permalink if permalink else "",
        "created_utc": item.get("created_utc", 0),
        "id": item.get("id", ""),
    }


def normalize_submission(item, ehr, term):
    title = (item.get("title") or "").strip()
    selftext = (item.get("selftext") or "").strip()
    if selftext in ("[removed]", "[deleted]"):
        selftext = ""
    text = (title + "\n\n" + selftext).strip()
    if not text:
        return None
    permalink = item.get("permalink") or ""
    return {
        "ehr": ehr,
        "matched_term": term,
        "kind": "submission",
        "text": text,
        "score": item.get("score", 0),
        "subreddit": item.get("subreddit", ""),
        "permalink": REDDIT_BASE + permalink if permalink else "",
        "created_utc": item.get("created_utc", 0),
        "id": item.get("id", ""),
    }


# --------------------------------------------------------------------------- #
# Query runners
# --------------------------------------------------------------------------- #

def run_query(url, term, normalizer, ehr, subreddit=None):
    """Run a single PullPush query, return list of normalized mentions.

    No server-side after/before — PullPush returns newest-first and we filter
    to the date window client-side (see filter_to_window). This avoids losing
    everything when the dataset lags behind the machine clock.
    """
    global _debug_printed
    params = {
        "q": term,
        "size": PAGE_SIZE,
    }
    if subreddit:
        params["subreddit"] = subreddit

    time.sleep(REQUEST_DELAY)
    payload = get_with_retry(url, params)
    if not payload:
        return []

    items = payload.get("data") or []

    # One-time raw shape dump for debugging.
    if DEBUG_RAW and not _debug_printed and items:
        _debug_printed = True
        sample = items[0]
        print("\n--- DEBUG: raw first item ---")
        print(f"    top-level JSON keys: {list(payload.keys())}")
        print(f"    reading items from payload['data'] ({len(items)} items)")
        for field in ("body", "title", "selftext", "score", "subreddit",
                      "permalink", "created_utc"):
            if field in sample:
                val = sample[field]
                if isinstance(val, str) and len(val) > 60:
                    val = val[:60] + "..."
                print(f"    {field!r}: {val!r}")
        print("--- END DEBUG ---\n")

    out = []
    for item in items:
        mention = normalizer(item, ehr, term)
        if mention:
            out.append(mention)
    return out


def filter_to_window(mentions):
    """Keep only mentions within DAYS_BACK of the anchor timestamp.

    Anchor is the newest created_utc in the data (ANCHOR_TO_LATEST_DATA=True)
    or wall-clock now. Returns (kept_mentions, anchor_epoch, cutoff_epoch).
    """
    if not mentions:
        return [], NOW_EPOCH, NOW_EPOCH - WINDOW_SECONDS

    timestamps = [int(m.get("created_utc") or 0) for m in mentions]
    latest_data = max(timestamps)

    if ANCHOR_TO_LATEST_DATA:
        anchor = max(latest_data, 0)
        if latest_data < NOW_EPOCH - WINDOW_SECONDS:
            print(f"\nNOTE: newest available data "
                  f"({datetime.fromtimestamp(latest_data, timezone.utc):%Y-%m-%d}) "
                  f"is older than the wall-clock window. Anchoring the "
                  f"{DAYS_BACK}-day window on the newest data instead of 'now'.")
    else:
        anchor = NOW_EPOCH

    cutoff = anchor - WINDOW_SECONDS
    kept = [m for m in mentions if int(m.get("created_utc") or 0) >= cutoff]
    return kept, anchor, cutoff


def load_partial():
    """Load resumable progress: completed (ehr, term) pairs + their mentions."""
    if not os.path.exists(PARTIAL_PATH):
        return set(), []
    try:
        with open(PARTIAL_PATH, "r", encoding="utf-8") as fh: