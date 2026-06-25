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