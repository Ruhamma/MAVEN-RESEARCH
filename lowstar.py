"""
lowstar.py — scrape ONLY 1-3 star Trustpilot reviews and mine the complaints.

Trustpilot lets you filter a company page by star rating
(?stars=1&stars=2&stars=3), so this pulls a deeper set of the unhappy reviews
than the general scrape, runs the same complaint-theme keyword analysis, and
writes data/lowstar_data.json:

    { entities: { "<name>": {
        category, count, avg_star,
        top_complaints: [[theme, n], ...],
        reviews: [ {star, text, permalink, complaints}, ... ]  # worst first
    }}}

The dashboard's "Pain Points (1-3★)" page reads this and shows, per competitor,
the usual reasons people are unhappy. Uses Playwright (same Cloudflare bypass
as trustpilot.py).

Run:  python lowstar.py
"""

import json
import os
import time
from datetime import datetime, timezone
from collections import Counter

from playwright.sync_api import sync_playwright

# Reuse the scraper helpers + the complaint keyword maps already defined.
from trustpilot import (DOMAINS, parse_reviews, NAV_TIMEOUT, RENDER_WAIT,
                        PAGE_DELAY)
from analyze import COMPLAINT_THEMES, match_themes, ENTITY_CATEGORY, CATEGORY_EHR

LOWSTAR_DATA_PATH = os.path.join("data", "lowstar_data.json")
MAX_PAGES = 6                       # ~20 low-star reviews/page
STAR_FILTER = "stars=1&stars=2&stars=3"


def scrape_lowstar(page, entity, domain):
    reviews, seen = [], set()
    for pno in range(1, MAX_PAGES + 1):
        url = f"https://www.trustpilot.com/review/{domain}?{STAR_FILTER}"
        if pno > 1:
            url += f"&page={pno}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(RENDER_WAIT)
            html = page.content()
        except Exception as exc:
            print(f"    page {pno} error ({type(exc).__name__}); stopping")
            break

        revs, _ = parse_reviews(html, entity, domain)
        if not revs:
            break
        new = 0
        for r in revs:
            # Safety: keep only 1-3 stars even if the filter leaks others.
            if not (1 <= (r.get("star_rating") or 0) <= 3):
                continue
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            reviews.append(r)
            new += 1
        if new == 0:
            break
        time.sleep(PAGE_DELAY)
    return reviews


def summarize(entity, reviews):
    complaint_counter = Counter()
    out_reviews = []
    star_sum = 0
    for r in reviews:
        text = r.get("text", "") or ""
        complaints = match_themes(text.lower(), COMPLAINT_THEMES)
        complaint_counter.update(complaints)
        star_sum += (r.get("star_rating") or 0)
        out_reviews.append({
            "star": r.get("star_rating"),
            "text": text,
            "permalink": r.get("permalink", ""),
            "complaints": complaints,
        })
    # Worst (lowest star) first.
    out_reviews.sort(key=lambda x: x.get("star") or 0)
    n = len(reviews)
    return {
        "category": ENTITY_CATEGORY.get(entity, CATEGORY_EHR),
        "count": n,
        "avg_star": round(star_sum / n, 2) if n else None,
        "top_complaints": complaint_counter.most_common(8),
        "reviews": out_reviews,
    }


def save(out):
    """Atomic write so a kill never leaves a half-written file."""
    os.makedirs("data", exist_ok=True)
    tmp = LOWSTAR_DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, LOWSTAR_DATA_PATH)


def main():