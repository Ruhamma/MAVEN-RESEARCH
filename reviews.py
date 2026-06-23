"""
reviews.py — FREE app-store review enrichment (Apple App Store).

Pulls real customer reviews (with 1-5 star ratings) for each EHR vendor's
mobile apps via two free, official, no-key Apple endpoints:
  - iTunes Search API   -> find each vendor's apps + overall rating
  - App Store RSS feed  -> individual review text + star rating

No paid services, no scraping, no API key. Reviews are written to
data/reviews_data.json in the SAME mention schema as fetch.py, so analyze.py
merges them automatically. Star ratings double as ground-truth to sanity-check
VADER sentiment.

Run:  python reviews.py     (after fetch.py; before analyze.py)
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

SEARCH_URL = "https://itunes.apple.com/search"
RSS_TMPL = ("https://itunes.apple.com/us/rss/customerreviews/"
            "id={app_id}/page={page}/sortBy=mostRecent/json")

REVIEWS_DATA_PATH = os.path.join("data", "reviews_data.json")

REQUEST_DELAY = 1.0
TIMEOUT = 25
MAX_RETRIES = 3
MAX_REVIEW_PAGES = 10        # Apple caps the RSS feed at ~10 pages (~500 reviews)

# Map each EHR to: brand search terms, and seller-name substrings used to
# confirm an app actually belongs to this vendor (avoids grabbing lookalikes).
EHR_APPS = {
    "AthenaHealth":    {"search": ["athenahealth", "athenaOne"],
                        "sellers": ["athenahealth"]},
    "NextGen":         {"search": ["NextGen Healthcare"],
                        "sellers": ["nextgen", "quality systems"]},
    "eClinicalWorks":  {"search": ["eClinicalWorks", "healow"],
                        "sellers": ["eclinicalworks", "healow"]},
    "Tebra":           {"search": ["Tebra", "Kareo"],
                        "sellers": ["tebra", "kareo"]},
    "DrChrono":        {"search": ["DrChrono"],
                        "sellers": ["drchrono"]},
    "ModMed":          {"search": ["ModMed", "Modernizing Medicine", "EMA"],
                        "sellers": ["modernizing medicine", "modmed"]},
    "Practice Fusion": {"search": ["Practice Fusion"],
                        "sellers": ["practice fusion", "veradigm", "allscripts"]},
    "CharmHealth":     {"search": ["CharmHealth", "Charm EHR"],
                        "sellers": ["charm", "medicalmine"]},
}

# Telehealth / home-care competitor apps. Entity names match competitors.py so
# analyze.py tags them as the Telehealth/Home-Care category automatically.
TELEHEALTH_APPS = {
    "Zocdoc":           {"search": ["Zocdoc"], "sellers": ["zocdoc"]},
    "Healthgrades":     {"search": ["Healthgrades"], "sellers": ["healthgrades"]},
    "Solv Health":      {"search": ["Solv"], "sellers": ["solv"]},
    "Teladoc":          {"search": ["Teladoc"], "sellers": ["teladoc"]},
    "MDLive":           {"search": ["MDLIVE"], "sellers": ["mdlive"]},
    "Amwell":           {"search": ["Amwell"],
                        "sellers": ["american well", "amwell"]},
    "Doctor on Demand": {"search": ["Doctor On Demand"],
                        "sellers": ["doctor on demand", "included health"]},
    "HealthTap":        {"search": ["HealthTap"], "sellers": ["healthtap"]},
    "PlushCare":        {"search": ["PlushCare"],
                        "sellers": ["plushcare", "accolade"]},
    "Hims & Hers":      {"search": ["Hims", "Hers"],
                        "sellers": ["hims", "for hims"]},
    "One Medical":      {"search": ["One Medical"],
                        "sellers": ["one medical", "1life"]},
    "Forward Health":   {"search": ["Forward Health"], "sellers": ["forward"]},
    "Parsley Health":   {"search": ["Parsley Health"], "sellers": ["parsley"]},
    "Sesame":           {"search": ["Sesame Care"], "sellers": ["sesame"]},
    "DispatchHealth":   {"search": ["DispatchHealth"],
                        "sellers": ["dispatchhealth"]},
    "Heal":             {"search": ["Heal doctor"], "sellers": ["heal"]},
    "Included Health":  {"search": ["Included Health"],
                        "sellers": ["included health"]},
    "Honor":            {"search": ["Honor Care"],
                        "sellers": ["honor technology", "honor"]},
    "Care.com":         {"search": ["Care.com"], "sellers": ["care.com"]},
    "Papa":             {"search": ["Papa Pals"], "sellers": ["papa"]},
    "Home Instead":     {"search": ["Home Instead"], "sellers": ["home instead"]},
    "Bayada":           {"search": ["BAYADA"], "sellers": ["bayada"]},
    "Amazon Pharmacy":  {"search": ["Amazon Pharmacy"],
                        "sellers": ["amazon"]},
    "Capsule":          {"search": ["Capsule Pharmacy"], "sellers": ["capsule"]},
    "Alto Pharmacy":    {"search": ["Alto Pharmacy"], "sellers": ["alto"]},
}
EHR_APPS.update(TELEHEALTH_APPS)
EHR_ORDER = list(EHR_APPS.keys())


def get_json(url, params=None):
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"      request error ({exc}); retry in {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            wait = 2 ** attempt
            print(f"      HTTP {resp.status_code}; backoff {wait}s")
            time.sleep(wait)
            continue
        return None
    return None


def find_apps(ehr, cfg):
    """Return list of {app_id, name, seller, avg_rating, rating_count}."""
    found = {}
    for term in cfg["search"]:
        time.sleep(REQUEST_DELAY)
        payload = get_json(SEARCH_URL, {
            "term": term, "entity": "software", "country": "us", "limit": 10})
        if not payload:
            continue
        for app in payload.get("results", []):
            seller = (app.get("sellerName") or "").lower()
            name = (app.get("trackName") or "")
            # Confirm the app belongs to this vendor by seller name.
            if not any(s in seller for s in cfg["sellers"]):
                continue
            app_id = app.get("trackId")
            if app_id and app_id not in found:
                found[app_id] = {
                    "app_id": app_id,
                    "name": name,
                    "seller": app.get("sellerName", ""),
                    "avg_rating": app.get("averageUserRating"),
                    "rating_count": app.get("userRatingCount", 0),
                    "url": app.get("trackViewUrl", ""),
                }
    return list(found.values())


def parse_review_entry(entry, ehr, app):
    """Normalize one RSS review entry into the shared mention schema."""
    if not isinstance(entry, dict):
        return None
    try:
        rating = int(entry.get("im:rating", {}).get("label", 0))
    except (ValueError, TypeError):
        rating = 0
    title = entry.get("title", {}).get("label", "") or ""
    body = entry.get("content", {}).get("label", "") or ""
    text = (title + ". " + body).strip(". ").strip()
    if not text:
        return None

    updated = entry.get("updated", {}).get("label", "")
    created_utc = 0
    if updated:
        try:
            created_utc = int(datetime.fromisoformat(
                updated.replace("Z", "+00:00")).timestamp())
        except ValueError:
            created_utc = 0

    return {
        "ehr": ehr,
        "matched_term": app["name"],
        "kind": "appstore_review",
        "source": "appstore",
        "text": text,
        "score": 0,                       # App Store has no upvotes
        "star_rating": rating,            # 1-5, ground-truth sentiment
        "subreddit": f"AppStore: {app['name']}",  # reuse 'subreddit' as source
        "permalink": app.get("url", ""),
        "created_utc": created_utc,
        "id": entry.get("id", {}).get("label", ""),
    }


def fetch_reviews(app):
    """Pull all available RSS review pages for one app."""
    reviews = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        time.sleep(REQUEST_DELAY)
        payload = get_json(RSS_TMPL.format(app_id=app["app_id"], page=page))
        if not payload:
            break
        entries = payload.get("feed", {}).get("entry", [])
        # Apple returns a single review as a dict, not a list — normalize.
        if isinstance(entries, dict):
            entries = [entries]
        if not entries:
            break
        # On page 1 the first entry is app metadata, not a review.
        if page == 1 and entries and "im:rating" not in entries[0]:
            entries = entries[1:]
        if not entries:
            break
        for e in entries:
            r = parse_review_entry(e, app["_ehr"], app)
            if r:
                reviews.append(r)
    return reviews


def main():
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ehr_order": EHR_ORDER,
        "apps": {},        # per-EHR app metadata (official ratings)
        "reviews": [],     # flat list, shared mention schema
    }
    seen_ids = set()

    for ehr, cfg in EHR_APPS.items():
        print(f"\n=== {ehr} ===")
        apps = find_apps(ehr, cfg)
        if not apps:
            print("  no matching apps found")
            out["apps"][ehr] = []
            continue

        out["apps"][ehr] = [{k: a[k] for k in
                             ("app_id", "name", "seller", "avg_rating",
                              "rating_count", "url")} for a in apps]

        for app in apps:
            app["_ehr"] = ehr
            rc = app.get("rating_count") or 0
            ar = app.get("avg_rating")
            print(f"  app '{app['name']}' "
                  f"(official {ar}★ / {rc} ratings)")
            try:
                revs = fetch_reviews(app)
            except Exception as exc:        # never let one app abort the run
                print(f"    skipped app ({exc})")
                revs = []
            added = 0
            for r in revs:
                if r["id"] and r["id"] in seen_ids:
                    continue
                seen_ids.add(r["id"])
                out["reviews"].append(r)
                added += 1
            print(f"    +{added} reviews pulled")

    # Safety: don't clobber a good cache with an empty pull (e.g. if the
    # network dropped mid-run). Keep the existing file instead.
    if not out["reviews"] and os.path.exists(REVIEWS_DATA_PATH):
        print("\nPulled 0 reviews (network issue?) — keeping existing "
              f"{REVIEWS_DATA_PATH}, not overwriting.")
        return

    os.makedirs("data", exist_ok=True)
    with open(REVIEWS_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"Saved {len(out['reviews'])} reviews to {REVIEWS_DATA_PATH}")
    print("Re-run analyze.py to fold these into the dashboard.")


if __name__ == "__main__":
    main()
