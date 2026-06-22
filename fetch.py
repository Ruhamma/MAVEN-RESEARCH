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
            p = json.load(fh)
        done = {tuple(pair) for pair in p.get("completed", [])}
        return done, p.get("mentions", [])
    except (ValueError, OSError):
        return set(), []


def save_partial(done, mentions):
    """Persist progress so a killed run can resume and loses at most one term."""
    os.makedirs("data", exist_ok=True)
    tmp = PARTIAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"completed": [list(d) for d in done],
                   "mentions": mentions}, fh, ensure_ascii=False)
    os.replace(tmp, PARTIAL_PATH)   # atomic — never leaves a half-written file


def fetch_all():
    """Fetch every EHR across comments + submissions. Resumable per term.

    Saves progress to PARTIAL_PATH after each term so a kill / timeout loses at
    most one term's work; re-running skips already-completed terms.
    """
    done, all_mentions = load_partial()
    seen_ids = {(m["kind"], m["id"]) for m in all_mentions if m.get("id")}
    if done:
        print(f"Resuming: {len(done)} terms already done, "
              f"{len(all_mentions)} mentions cached.")

    for category, term_map in ENTITY_GROUPS:
        for ehr, terms in term_map.items():
            print(f"\n=== {ehr} [{category}] ===", flush=True)

            for term in terms:
                if (ehr, term) in done:
                    print(f"  term '{term}' — already done, skipping")
                    continue
                print(f"  term '{term}'", flush=True)

                # Query plan: global (no subreddit) for comments + submissions.
                # Global `q=` already covers the priority subs. Only add per-sub
                # queries if FETCH_PER_SUBREDDIT is explicitly enabled.
                query_plan = [(COMMENT_URL, normalize_comment, None),
                              (SUBMISSION_URL, normalize_submission, None)]
                if FETCH_PER_SUBREDDIT:
                    for sub in PRIORITY_SUBREDDITS:
                        query_plan.append((COMMENT_URL, normalize_comment, sub))
                        query_plan.append(
                            (SUBMISSION_URL, normalize_submission, sub))

                term_count = 0
                for url, normalizer, sub in query_plan:
                    mentions = run_query(url, term, normalizer, ehr,
                                         subreddit=sub)
                    for m in mentions:
                        dedupe_key = (m["kind"], m["id"])
                        if m["id"] and dedupe_key in seen_ids:
                            continue
                        m["category"] = category
                        seen_ids.add(dedupe_key)
                        all_mentions.append(m)
                        term_count += 1

                done.add((ehr, term))
                save_partial(done, all_mentions)
                print(f"    +{term_count} new (saved progress)", flush=True)

    return all_mentions


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    if os.path.exists(RAW_DATA_PATH):
        print(f"Cache found at {RAW_DATA_PATH}.")
        print("Delete it to force a fresh pull. Loading cached summary...")
        with open(RAW_DATA_PATH, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        print_summary(cached.get("mentions", []), cached.get("fetched_at"))
        return

    print("No cache. Pulling from PullPush API...")
    print(f"Fetching newest-first, then filtering to last {DAYS_BACK} days "
          f"(anchored on {'latest data' if ANCHOR_TO_LATEST_DATA else 'now'}).")

    raw_mentions = fetch_all()
    mentions, anchor, cutoff = filter_to_window(raw_mentions)

    print(f"\nWindow kept: "
          f"{datetime.fromtimestamp(cutoff, timezone.utc):%Y-%m-%d} to "
          f"{datetime.fromtimestamp(anchor, timezone.utc):%Y-%m-%d}")
    print(f"  {len(raw_mentions)} fetched -> {len(mentions)} within window")

    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "window_after": cutoff,
        "window_before": anchor,
        "mentions": mentions,
    }
    os.makedirs("data", exist_ok=True)
    with open(RAW_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    # Full run finished — drop the resumable partial file.
    if os.path.exists(PARTIAL_PATH):
        os.remove(PARTIAL_PATH)

    print(f"\nSaved {len(mentions)} mentions to {RAW_DATA_PATH}")
    print_summary(mentions, out["fetched_at"])


def print_summary(mentions, fetched_at):
    counts = {}
    for m in mentions:
        counts[m["ehr"]] = counts.get(m["ehr"], 0) + 1
    for category, term_map in ENTITY_GROUPS:
        print("\n" + "=" * 40)
        print(f"SUMMARY — mentions per entity [{category}]")
        print("=" * 40)
        for ehr in term_map:
            print(f"  {ehr:<20} {counts.get(ehr, 0)}")
    print("-" * 40)
    print(f"  {'TOTAL':<20} {len(mentions)}")
    if fetched_at:
        print(f"\nFetched at: {fetched_at}")


if __name__ == "__main__":
    main()
