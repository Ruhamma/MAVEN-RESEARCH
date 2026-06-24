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