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