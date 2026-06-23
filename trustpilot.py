"""
trustpilot.py — Trustpilot review scraper (free, via Playwright headless).

Trustpilot sits behind Cloudflare, so plain requests get a 403. A real browser
engine (Playwright/Chromium) renders the page and we read the reviews embedded
in the page's __NEXT_DATA__ JSON. Output goes to data/trustpilot_data.json in
the SAME mention schema as the rest of the pipeline, so analyze.py merges it.

NOTE: this is SCRAPING (Trustpilot ToS forbids it). Unlike the App Store /
PullPush sources, use at your own discretion, for research only. Be polite:
there is a delay between requests and page counts are capped.

Setup (one time):
    pip install playwright
    playwright install chromium

Run:  python trustpilot.py        (then re-run analyze.py)
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

TRUSTPILOT_DATA_PATH = os.path.join("data", "trustpilot_data.json")

MAX_PAGES = 5            # 20 reviews/page -> ~100 reviews per company
PAGE_DELAY = 2.0         # polite delay between page loads (seconds)
NAV_TIMEOUT = 40000      # ms
RENDER_WAIT = 3500       # ms to let the JS challenge / hydration settle

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

# Entity name (matches competitors.py / EHR list) -> Trustpilot domain slug.
# analyze.py infers the category from the entity name, so EHR + telehealth can
# share this map. Wrong/empty domains just yield "no reviews" and are skipped.
DOMAINS = {
    # Telehealth / home-care
    "Zocdoc": "zocdoc.com",
    "Healthgrades": "healthgrades.com",
    "Solv Health": "solvhealth.com",
    "Teladoc": "teladoc.com",
    "MDLive": "mdlive.com",
    "Amwell": "amwell.com",
    "Doctor on Demand": "doctorondemand.com",
    "HealthTap": "healthtap.com",
    "PlushCare": "plushcare.com",
    "Hims & Hers": "hims.com",
    "One Medical": "onemedical.com",
    "Forward Health": "goforward.com",
    "Parsley Health": "parsleyhealth.com",
    "Sesame": "sesamecare.com",
    "DispatchHealth": "dispatchhealth.com",
    "Heal": "heal.com",
    "Included Health": "includedhealth.com",
    "Honor": "joinhonor.com",
    "Care.com": "care.com",
    "Papa": "papa.com",
    "Home Instead": "homeinstead.com",
    "Visiting Angels": "visitingangels.com",
    "Bayada": "bayada.com",
    "Capsule": "capsule.com",
    "Alto Pharmacy": "alto.com",
    # EHRs (Trustpilot coverage is thinner here, but harmless to try)
    "AthenaHealth": "athenahealth.com",
    "NextGen": "nextgen.com",
    "eClinicalWorks": "eclinicalworks.com",
    "Tebra": "tebra.com",
    "DrChrono": "drchrono.com",
}


def parse_reviews(html, entity, domain):
    """Extract normalized review mentions from a page's __NEXT_DATA__."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        return [], None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return [], None
    props = data.get("props", {}).get("pageProps", {})
    bu = props.get("businessUnit", {}) or {}
    bu_meta = {
        "name": bu.get("displayName"),
        "trust_score": bu.get("trustScore"),
        "total_reviews": bu.get("numberOfReviews"),
    }

    out = []
    for r in props.get("reviews", []) or []:
        text_body = (r.get("text") or "").strip()
        title = (r.get("title") or "").strip()
        text = (title + ". " + text_body).strip(". ").strip() if title else text_body
        if not text:
            continue
        try:
            rating = int(r.get("rating") or 0)
        except (ValueError, TypeError):
            rating = 0
        published = (r.get("dates") or {}).get("publishedDate") or ""
        created_utc = 0
        if published:
            try:
                created_utc = int(datetime.fromisoformat(
                    published.replace("Z", "+00:00")).timestamp())
            except ValueError:
                created_utc = 0
        rid = str(r.get("id", "") or "")
        # Link straight to the exact review when we have its id, else the page.
        permalink = (f"https://www.trustpilot.com/reviews/{rid}" if rid
                     else f"https://www.trustpilot.com/review/{domain}")
        out.append({
            "ehr": entity,
            "matched_term": "Trustpilot",
            "kind": "trustpilot_review",
            "source": "trustpilot",
            "text": text,
            "score": (r.get("likes") or 0),
            "star_rating": rating,
            "subreddit": "Trustpilot",          # reuse 'subreddit' as source tag
            "permalink": permalink,
            "created_utc": created_utc,
            "id": "tp::" + rid,
        })
    return out, bu_meta


def scrape_entity(page, entity, domain):
    """Scrape up to MAX_PAGES of reviews for one company."""
    reviews, bu_meta, seen = [], None, set()
    for pno in range(1, MAX_PAGES + 1):
        url = f"https://www.trustpilot.com/review/{domain}"
        if pno > 1:
            url += f"?page={pno}"
        try: