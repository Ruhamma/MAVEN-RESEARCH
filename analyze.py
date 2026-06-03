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
ANALYZED_DATA_PATH = os.path.join("data", "analyzed_data.json")

# Keep the full EHR roster so zero-mention vendors still appear downstream.
EHR_ORDER = [
    "AthenaHealth", "NextGen", "eClinicalWorks", "Tebra",
    "DrChrono", "ModMed", "Practice Fusion", "CharmHealth",
]

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


def empty_ehr_record():
    return {
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

    # Optionally fold in free App Store reviews (reviews.py). Same schema, so
    # they flow through sentiment + theme analysis like any other mention.
    n_reviews = 0
    if os.path.exists(REVIEWS_DATA_PATH):
        with open(REVIEWS_DATA_PATH, "r", encoding="utf-8") as fh:
            rev = json.load(fh)
        review_mentions = rev.get("reviews", [])
        mentions.extend(review_mentions)
        n_reviews = len(review_mentions)
        print(f"Merged {n_reviews} App Store reviews into analysis.")

    sia = SentimentIntensityAnalyzer()

    # Per-EHR accumulators.
    records = {ehr: empty_ehr_record() for ehr in EHR_ORDER}
    complaint_counters = {ehr: Counter() for ehr in EHR_ORDER}
    praise_counters = {ehr: Counter() for ehr in EHR_ORDER}
    compound_sums = {ehr: 0.0 for ehr in EHR_ORDER}

    for m in mentions:
        ehr = m.get("ehr")
        if ehr not in records:
            # Unknown EHR label — register it so nothing is silently dropped.
            records[ehr] = empty_ehr_record()
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
            "switching": switching,
        })

    # Finalize aggregates.
    for ehr, rec in records.items():
        total = rec["total"]
        if total == 0:
            rec["has_data"] = False
            continue
        rec["has_data"] = True
        rec["pct_positive"] = round(100.0 * rec["positive"] / total, 1)
        rec["pct_neutral"] = round(100.0 * rec["neutral"] / total, 1)
        rec["pct_negative"] = round(100.0 * rec["negative"] / total, 1)
        rec["avg_compound"] = round(compound_sums[ehr] / total, 4)
        rec["top_complaints"] = complaint_counters[ehr].most_common(5)
        rec["top_praises"] = praise_counters[ehr].most_common(5)
        # Full per-theme complaint counts for the cross-vendor heatmap.
        rec["complaint_counts"] = dict(complaint_counters[ehr])

    out = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source_fetched_at": raw.get("fetched_at"),
        "window_after": raw.get("window_after"),
        "window_before": raw.get("window_before"),
        "ehr_order": EHR_ORDER,
        "complaint_theme_names": list(COMPLAINT_THEMES.keys()),
        "ehrs": records,
    }

    os.makedirs("data", exist_ok=True)
    with open(ANALYZED_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print_report(records)
    print(f"\nSaved analysis to {ANALYZED_DATA_PATH}")


def print_report(records):
    print("=" * 60)
    print(f"{'EHR':<18}{'mentions':>9}{'%pos':>7}{'%neg':>7}{'avg':>8}")
    print("-" * 60)
    for ehr in EHR_ORDER:
        rec = records.get(ehr, empty_ehr_record())
        if not rec["has_data"]:
            print(f"{ehr:<18}{'no data':>9}")
            continue
        print(f"{ehr:<18}{rec['total']:>9}{rec['pct_positive']:>7}"
              f"{rec['pct_negative']:>7}{rec['avg_compound']:>8}")
    print("=" * 60)


if __name__ == "__main__":
    analyze()
