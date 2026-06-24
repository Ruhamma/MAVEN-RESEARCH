"""
analyze.py — Sentiment + theme analysis of cached Reddit EHR mentions.

Reads data/raw_data.json (produced by fetch.py), runs VADER sentiment and
simple keyword-based theme extraction, aggregates per EHR, and writes
data/analyzed_data.json for the dashboard to load instantly.

Run:  python analyze.py
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

from nltk.sentiment.vader import SentimentIntensityAnalyzer

RAW_DATA_PATH = os.path.join("data", "raw_data.json")
REVIEWS_DATA_PATH = os.path.join("data", "reviews_data.json")
PLAYSTORE_DATA_PATH = os.path.join("data", "playstore_data.json")
TRUSTPILOT_DATA_PATH = os.path.join("data", "trustpilot_data.json")
MANUAL_DATA_PATH = os.path.join("data", "manual_data.json")
ANALYZED_DATA_PATH = os.path.join("data", "analyzed_data.json")

# Keep the full EHR roster so zero-mention vendors still appear downstream.
EHR_ORDER = [
    "AthenaHealth", "NextGen", "eClinicalWorks", "Tebra",
    "DrChrono", "ModMed", "Practice Fusion", "CharmHealth",
]

# Telehealth / home-care competitors (from competitor_matrix.xlsx).
from competitors import (TELEHEALTH_ORDER, CATEGORY_EHR,  # noqa: E402
                         CATEGORY_TELEHEALTH)

# Full entity roster + name -> category map.
ENTITY_ORDER = EHR_ORDER + TELEHEALTH_ORDER
ENTITY_CATEGORY = {**{e: CATEGORY_EHR for e in EHR_ORDER},
                   **{e: CATEGORY_TELEHEALTH for e in TELEHEALTH_ORDER}}

# VADER compound thresholds (standard).
POS_THRESHOLD = 0.05
NEG_THRESHOLD = -0.05

# --------------------------------------------------------------------------- #
# Theme keyword maps — simple case-insensitive substring matching.
# A mention can match multiple themes. Intentionally not over-engineered.
# --------------------------------------------------------------------------- #

COMPLAINT_THEMES = {
    "support": ["no support", "lack of support", "unresponsive", "no help",
                "support ticket", "poor support", "bad support"],
    "billing": ["billing", "invoice", "overcharge", "double charge",
                "billing issue", "billing error"],
    "expensive/cost": ["expensive", "costly", "pricey", "overpriced",
                       "too much money", "high cost", "price hike"],
    "slow/performance": ["slow", "laggy", "sluggish", "freeze", "freezing",
                         "downtime", "crashes", "crashing", "loading"],
    "data export/lock-in": ["export", "lock-in", "lock in", "locked in",
                            "migrate", "migration", "data hostage",
                            "hold your data", "can't get my data"],
    "denials": ["denial", "denied", "rejected claim", "claim rejection",
                "claim denied", "rejection"],
    "training/learning curve": ["learning curve", "hard to learn", "steep",
                                "confusing", "not intuitive", "training"],
    "bugs/glitches": ["bug", "buggy", "glitch", "glitchy", "broken",
                      "error message", "errors"],
    "customer service": ["customer service", "rude", "poor service",
                        "horrible service", "terrible service", "no one answers"],
    "contract/cancellation": ["contract", "cancel", "cancellation",
                             "termination fee", "locked into a contract",
                             "can't cancel", "stuck in contract"],
    # Telehealth / home-care specific frustrations (harmless for EHRs — they
    # simply won't match). These surface "most frustrating points" for the
    # marketplace competitors.
    "caregiver no-show/reliability": ["no show", "no-show", "didn't show",
                                      "never showed", "late", "unreliable",
                                      "flaked", "cancelled on me", "ghosted"],
    "scheduling/availability": ["no availability", "can't book", "couldn't book",
                               "no appointments", "fully booked", "waitlist",
                               "hard to schedule", "reschedule"],
    "wait time": ["long wait", "waiting", "hours to", "took forever",
                  "still waiting", "on hold"],
    "refund/charge dispute": ["refund", "won't refund", "charged me",
                             "charged twice", "no refund", "dispute",
                             "money back"],
    "caregiver/provider quality": ["unqualified", "incompetent", "rude nurse",
                                   "bad caregiver", "not vetted", "untrained",
                                   "rude doctor", "dismissive"],
    "insurance/coverage": ["not covered", "doesn't take insurance",
                          "out of network", "denied coverage",
                          "insurance won't"],
    "prescription/pharmacy": ["prescription", "pharmacy", "refill", "meds",
                             "didn't send", "wrong medication", "delivery"],
}

PRAISE_THEMES = {
    "easy/intuitive": ["easy to use", "intuitive", "user friendly",
                      "user-friendly", "simple to use", "easy"],
    "mobile/iPad": ["mobile", "ipad", "iphone", "tablet", "mobile app",
                   "phone app"],
    "fast": ["fast", "quick", "snappy", "responsive", "speedy"],
    "customizable": ["customizable", "customize", "customisable", "flexible",
                    "configurable", "templates"],
    "good support": ["great support", "good support", "helpful support",
                    "responsive support", "excellent support",
                    "support is great"],
    "integration": ["integration", "integrate", "interoperability",
                   "interface", "api", "connects with"],
}


# --------------------------------------------------------------------------- #
# Switching / churn signals — phrases that suggest a user is leaving or
# shopping for an alternative. A mention flagged here for EHR X means X is
# (likely) being abandoned → a customer MavenMD could poach.
# --------------------------------------------------------------------------- #

SWITCHING_PHRASES = [
    "switch from", "switching from", "switched from", "switch away",
    "moving off", "moved off", "move away from", "migrate off",
    "migrating off", "migrate away", "migrating away",
    "leaving", "ditch", "ditched", "dumping", "dumped", "get rid of",
    "looking for an alternative", "looking for alternatives",
    "alternative to", "alternatives to", "anything better than",
    "replace our", "replacing our", "fed up with", "done with",
    "regret choosing", "regret going", "regret switching",
    "want to switch", "thinking of switching", "considering switching",
]


def match_themes(text_lower, theme_map):
    """Return list of theme names whose any keyword appears in text."""
    hits = []
    for theme, keywords in theme_map.items():
        if any(kw in text_lower for kw in keywords):
            hits.append(theme)
    return hits


def detect_switching(text_lower):
    """Return list of switching/churn phrases found in the text."""
    return [p for p in SWITCHING_PHRASES if p in text_lower]


def classify(compound):
    if compound >= POS_THRESHOLD:
        return "positive"
    if compound <= NEG_THRESHOLD:
        return "negative"
    return "neutral"


def empty_ehr_record(category=CATEGORY_EHR):
    return {
        "category": category,
        "total": 0,
        "positive": 0, "neutral": 0, "negative": 0,
        "pct_positive": 0.0, "pct_neutral": 0.0, "pct_negative": 0.0,
        "avg_compound": 0.0,
        "top_complaints": [],
        "top_praises": [],
        "complaint_counts": {},
        "switching_count": 0,
        "mentions": [],
        "has_data": False,
    }


def analyze():
    if not os.path.exists(RAW_DATA_PATH):
        raise SystemExit(
            f"{RAW_DATA_PATH} not found. Run fetch.py first.")

    with open(RAW_DATA_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    mentions = list(raw.get("mentions", []))

    # Optionally fold in free app-store reviews (reviews.py = Apple,
    # playstore.py = Google Play). Same schema, so they flow through sentiment +
    # theme analysis like any other mention.
    for label, path in (("App Store", REVIEWS_DATA_PATH),
                        ("Google Play", PLAYSTORE_DATA_PATH),
                        ("Trustpilot", TRUSTPILOT_DATA_PATH),
                        ("manual (G2/Capterra/etc)", MANUAL_DATA_PATH)):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                extra = json.load(fh)
            extra_mentions = extra.get("reviews", [])
            mentions.extend(extra_mentions)
            print(f"Merged {len(extra_mentions)} {label} reviews into analysis.")

    sia = SentimentIntensityAnalyzer()

    # Per-entity accumulators (EHR + telehealth competitors).
    records = {e: empty_ehr_record(ENTITY_CATEGORY.get(e, CATEGORY_EHR))
               for e in ENTITY_ORDER}
    complaint_counters = {e: Counter() for e in ENTITY_ORDER}
    praise_counters = {e: Counter() for e in ENTITY_ORDER}
    compound_sums = {e: 0.0 for e in ENTITY_ORDER}

    for m in mentions:
        ehr = m.get("ehr")
        if ehr not in records:
            # Unknown entity label — register it so nothing is silently dropped.
            cat = m.get("category") or ENTITY_CATEGORY.get(ehr, CATEGORY_EHR)
            records[ehr] = empty_ehr_record(cat)
            complaint_counters[ehr] = Counter()
            praise_counters[ehr] = Counter()
            compound_sums[ehr] = 0.0

        text = m.get("text", "") or ""
        text_lower = text.lower()

        compound = sia.polarity_scores(text)["compound"]
        sentiment = classify(compound)

        complaints = match_themes(text_lower, COMPLAINT_THEMES)
        praises = match_themes(text_lower, PRAISE_THEMES)
        switching = detect_switching(text_lower)

        rec = records[ehr]
        rec["total"] += 1
        rec[sentiment] += 1
        compound_sums[ehr] += compound
        complaint_counters[ehr].update(complaints)
        praise_counters[ehr].update(praises)
        if switching:
            rec["switching_count"] += 1

        # Light per-mention record for the dashboard (no usernames stored).
        rec["mentions"].append({
            "text": text,
            "score": m.get("score", 0),
            "subreddit": m.get("subreddit", ""),
            "permalink": m.get("permalink", ""),
            "created_utc": m.get("created_utc", 0),
            "kind": m.get("kind", ""),
            "source": m.get("source", "reddit"),
            "star_rating": m.get("star_rating"),     # set for App Store reviews
            "matched_term": m.get("matched_term", ""),
            "sentiment": sentiment,
            "compound": round(compound, 4),
            "complaints": complaints,
            "praises": praises,