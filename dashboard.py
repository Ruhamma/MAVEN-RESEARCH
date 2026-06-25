"""
dashboard.py — Streamlit market-research dashboard for EHR Reddit sentiment.

Loads data/analyzed_data.json (built by analyze.py) — never hits the API.
Four views via sidebar: Overview, Per-System, Comparison, Gap Analysis.

Run:  streamlit run dashboard.py
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ANALYZED_DATA_PATH = os.path.join("data", "analyzed_data.json")
GAPS_CSV_PATH = os.path.join("data", "gaps.csv")
CHPL_DATA_PATH = os.path.join("data", "chpl_data.json")
REVIEWS_DATA_PATH = os.path.join("data", "reviews_data.json")
PLAYSTORE_DATA_PATH = os.path.join("data", "playstore_data.json")
MATRIX_JSON_PATH = os.path.join("data", "competitor_matrix.json")
LOWSTAR_DATA_PATH = os.path.join("data", "lowstar_data.json")

CATEGORY_EHR = "EHR"
CATEGORY_TELEHEALTH = "Telehealth/Home-Care"

LOW_VOLUME_THRESHOLD = 15  # below this, interpret cautiously

SENTIMENT_COLORS = {
    "positive": "#2ca02c",
    "neutral": "#999999",
    "negative": "#d62728",
}

st.set_page_config(page_title="EHR Market Research", layout="wide")


# --------------------------------------------------------------------------- #
# Data loading (cached)
# --------------------------------------------------------------------------- #

@st.cache_data
def load_analyzed():
    if not os.path.exists(ANALYZED_DATA_PATH):
        return None
    with open(ANALYZED_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def load_gaps():
    if not os.path.exists(GAPS_CSV_PATH):
        return None
    return pd.read_csv(GAPS_CSV_PATH)


@st.cache_data
def load_chpl():
    if not os.path.exists(CHPL_DATA_PATH):
        return None
    with open(CHPL_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def load_reviews():
    if not os.path.exists(REVIEWS_DATA_PATH):
        return None
    with open(REVIEWS_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def load_playstore():
    if not os.path.exists(PLAYSTORE_DATA_PATH):
        return None
    with open(PLAYSTORE_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def load_matrix():
    if not os.path.exists(MATRIX_JSON_PATH):
        return None
    with open(MATRIX_JSON_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def load_lowstar():
    if not os.path.exists(LOWSTAR_DATA_PATH):
        return None
    with open(LOWSTAR_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def fmt_epoch(epoch):
    if not epoch:
        return "n/a"
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return "n/a"


def overview_df(data):
    """Flat per-EHR dataframe for charts/tables."""
    rows = []
    for ehr in data["ehr_order"]:
        rec = data["ehrs"].get(ehr, {})
        rows.append({
            "EHR": ehr,
            "mentions": rec.get("total", 0),
            "pct_positive": rec.get("pct_positive", 0.0),
            "pct_neutral": rec.get("pct_neutral", 0.0),
            "pct_negative": rec.get("pct_negative", 0.0),
            "avg_sentiment": rec.get("avg_compound", 0.0),
            "has_data": rec.get("has_data", False),
        })
    return pd.DataFrame(rows)
