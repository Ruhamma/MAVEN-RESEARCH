"""
playstore.py — FREE Google Play review enrichment.

Companion to reviews.py (Apple). Uses the free `google-play-scraper` library
(no API key) to find each EHR vendor's Android apps and pull their reviews with
1-5 star ratings. Output goes to data/playstore_data.json in the SAME mention
schema as fetch.py / reviews.py, so analyze.py merges it automatically.

No paid services, no API key.

Run:  python playstore.py     (then re-run analyze.py)
"""

import json
import os
import time
from datetime import datetime, timezone

from google_play_scraper import search, reviews, Sort

PLAYSTORE_DATA_PATH = os.path.join("data", "playstore_data.json")

REVIEW_CAP = 200          # reviews per app (polite; Play has plenty)
REQUEST_DELAY = 1.0
PLAY_URL = "https://play.google.com/store/apps/details?id={app_id}"

# Same vendor → search terms + developer-name substrings as reviews.py, used to
# confirm an app truly belongs to the vendor (Play search is fuzzy).
EHR_APPS = {
    "AthenaHealth":    {"search": ["athenahealth", "athenaOne"],
                        "devs": ["athenahealth"]},
    "NextGen":         {"search": ["NextGen Healthcare"],
                        "devs": ["nextgen", "quality systems"]},
    "eClinicalWorks":  {"search": ["eClinicalWorks", "healow"],
                        "devs": ["eclinicalworks"]},
    "Tebra":           {"search": ["Tebra", "Kareo"],
                        "devs": ["tebra", "kareo"]},
    "DrChrono":        {"search": ["DrChrono"],
                        "devs": ["drchrono", "everhealth"]},
    "ModMed":          {"search": ["ModMed", "Modernizing Medicine", "EMA"],
                        "devs": ["modernizing medicine", "modmed"]},
    "Practice Fusion": {"search": ["Practice Fusion"],
                        "devs": ["practice fusion", "veradigm", "allscripts"]},
    "CharmHealth":     {"search": ["CharmHealth", "Charm EHR"],
                        "devs": ["charm", "medicalmine"]},
}
EHR_ORDER = list(EHR_APPS.keys())


def find_apps(cfg):
    """Return {app_id: {app_id, title, developer}} matched by developer name."""
    found = {}
    for term in cfg["search"]:
        time.sleep(REQUEST_DELAY)
        try:
            hits = search(term, n_hits=8, lang="en", country="us")
        except Exception as exc:
            print(f"      search error ({exc})")
            continue
        for a in hits:
            app_id = a.get("appId")
            dev = (a.get("developer") or "").lower()
            if not app_id:
                continue
            if not any(d in dev for d in cfg["devs"]):
                continue
            if app_id not in found:
                found[app_id] = {
                    "app_id": app_id,
                    "title": a.get("title", ""),
                    "developer": a.get("developer", ""),
                    "avg_rating": a.get("score"),
                }
    return found


def pull_reviews(app_id):
    """Pull up to REVIEW_CAP newest reviews for one app."""
    try:
        res, _ = reviews(app_id, count=REVIEW_CAP, lang="en", country="us",
                         sort=Sort.NEWEST)
        return res
    except Exception as exc:
        print(f"      reviews error ({exc})")
        return []


def to_epoch(dt):
    if not isinstance(dt, datetime):
        return 0
    try:
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, OverflowError):
        return 0


def normalize(r, ehr, app):
    text = (r.get("content") or "").strip()
    if not text:
        return None
    try:
        rating = int(r.get("score") or 0)
    except (ValueError, TypeError):
        rating = 0
    return {
        "ehr": ehr,
        "matched_term": app["title"],
        "kind": "playstore_review",
        "source": "googleplay",
        "text": text,
        "score": r.get("thumbsUpCount", 0) or 0,
        "star_rating": rating,
        "subreddit": f"GooglePlay: {app['title']}",  # reuse 'subreddit' as source
        "permalink": PLAY_URL.format(app_id=app["app_id"]),
        "created_utc": to_epoch(r.get("at")),
        "id": r.get("reviewId", ""),
    }


def main():
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ehr_order": EHR_ORDER,
        "apps": {},
        "reviews": [],
    }
    seen = set()

    for ehr, cfg in EHR_APPS.items():
        print(f"\n=== {ehr} ===")
        apps = find_apps(cfg)
        if not apps:
            print("  no matching apps found")
            out["apps"][ehr] = []
            continue
        out["apps"][ehr] = list(apps.values())

        for app in apps.values():
            print(f"  app '{app['title']}' ({app.get('avg_rating')}★) "
                  f"[{app['app_id']}]")
            time.sleep(REQUEST_DELAY)
            added = 0
            for r in pull_reviews(app["app_id"]):
                m = normalize(r, ehr, app)
                if not m or (m["id"] and m["id"] in seen):
                    continue
                seen.add(m["id"])
                out["reviews"].append(m)
                added += 1
            print(f"    +{added} reviews pulled")

    os.makedirs("data", exist_ok=True)
    with open(PLAYSTORE_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n" + "=" * 50)
    print(f"Saved {len(out['reviews'])} reviews to {PLAYSTORE_DATA_PATH}")
    print("Re-run analyze.py to fold these into the dashboard.")


if __name__ == "__main__":
    main()
