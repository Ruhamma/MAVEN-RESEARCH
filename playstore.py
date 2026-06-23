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

# Telehealth / home-care competitor apps (entity names match competitors.py).
TELEHEALTH_APPS = {
    "Zocdoc":           {"search": ["Zocdoc"], "devs": ["zocdoc"]},
    "Healthgrades":     {"search": ["Healthgrades"], "devs": ["healthgrades"]},
    "Solv Health":      {"search": ["Solv"], "devs": ["solv"]},
    "Teladoc":          {"search": ["Teladoc"], "devs": ["teladoc"]},
    "MDLive":           {"search": ["MDLIVE"], "devs": ["mdlive"]},
    "Amwell":           {"search": ["Amwell"],
                        "devs": ["american well", "amwell"]},
    "Doctor on Demand": {"search": ["Doctor On Demand"],
                        "devs": ["doctor on demand", "included health"]},
    "HealthTap":        {"search": ["HealthTap"], "devs": ["healthtap"]},
    "PlushCare":        {"search": ["PlushCare"],
                        "devs": ["plushcare", "accolade"]},
    "Hims & Hers":      {"search": ["Hims", "Hers"], "devs": ["hims"]},
    "One Medical":      {"search": ["One Medical"],
                        "devs": ["one medical", "1life"]},
    "Forward Health":   {"search": ["Forward Health"], "devs": ["forward"]},
    "Parsley Health":   {"search": ["Parsley Health"], "devs": ["parsley"]},
    "Sesame":           {"search": ["Sesame Care"], "devs": ["sesame"]},
    "DispatchHealth":   {"search": ["DispatchHealth"], "devs": ["dispatchhealth"]},
    "Heal":             {"search": ["Heal doctor"], "devs": ["heal"]},
    "Included Health":  {"search": ["Included Health"],
                        "devs": ["included health"]},
    "Honor":            {"search": ["Honor Care"],
                        "devs": ["honor technology", "honor"]},
    "Care.com":         {"search": ["Care.com"], "devs": ["care.com"]},
    "Papa":             {"search": ["Papa Pals"], "devs": ["papa"]},
    "Home Instead":     {"search": ["Home Instead"], "devs": ["home instead"]},
    "Bayada":           {"search": ["BAYADA"], "devs": ["bayada"]},
    "Amazon Pharmacy":  {"search": ["Amazon Pharmacy"], "devs": ["amazon"]},
    "Capsule":          {"search": ["Capsule Pharmacy"], "devs": ["capsule"]},
    "Alto Pharmacy":    {"search": ["Alto Pharmacy"], "devs": ["alto"]},
}
EHR_APPS.update(TELEHEALTH_APPS)
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