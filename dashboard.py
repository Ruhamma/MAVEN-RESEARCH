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


def top_theme_label(theme_list):
    if not theme_list:
        return "—"
    name, count = theme_list[0]
    return f"{name} ({count})"


# Source ordering for mixed-source quote tables:
# Trustpilot first, then App Store, Google Play, manual; Reddit always last.
_SOURCE_RANK = {"trustpilot": 0, "appstore": 1, "googleplay": 2,
                "manual": 3, "reddit": 4}


def source_rank(source):
    s = (source or "reddit")
    base = s.split(":", 1)[0]   # "manual:G2" -> "manual"
    return _SOURCE_RANK.get(base, 4)


def source_label(m):
    s = m.get("source") or "reddit"
    if s == "appstore":
        return "App Store"
    if s == "googleplay":
        return "Google Play"
    if s == "trustpilot":
        return "Trustpilot"
    if s.startswith("manual"):
        return s.split(":", 1)[1] if ":" in s else "manual"
    return "r/" + m.get("subreddit", "")


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

def view_churn(data):
    st.header("Churn Signals — who's bleeding customers")
    st.caption(
        "Mentions containing switching/leaving language (\"switching from\", "
        "\"looking for an alternative to\", \"fed up with\"…). High counts = "
        "active buyers leaving that vendor → MavenMD's poaching targets.")

    rows = []
    for ehr in data["ehr_order"]:
        rec = data["ehrs"].get(ehr, {})
        total = rec.get("total", 0)
        sc = rec.get("switching_count", 0)
        rows.append({
            "EHR": ehr,
            "switching_mentions": sc,
            "total": total,
            "churn_rate_%": round(100.0 * sc / total, 1) if total else 0.0,
            "has_data": rec.get("has_data", False),
        })
    df = pd.DataFrame(rows)
    has = df[df["has_data"]]

    if has.empty or has["switching_mentions"].sum() == 0:
        st.info("No switching signals detected.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Switching mentions (count)")
        d1 = has.sort_values("switching_mentions", ascending=True)
        fig = go.Figure(go.Bar(
            x=d1["switching_mentions"], y=d1["EHR"], orientation="h",
            marker_color="#d62728", text=d1["switching_mentions"],
            textposition="auto"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="switching mentions")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("Churn rate (% of mentions)")
        st.caption("Normalizes for popularity — better cross-vendor signal.")
        d2 = has.sort_values("churn_rate_%", ascending=True)
        fig2 = go.Figure(go.Bar(
            x=d2["churn_rate_%"], y=d2["EHR"], orientation="h",
            marker_color="#ff7f0e", text=[f"{v}%" for v in d2["churn_rate_%"]],
            textposition="auto"))
        fig2.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                           xaxis_title="% of mentions")
        st.plotly_chart(fig2, use_container_width=True)

    # The actual switching quotes — sales evidence, with links.
    st.subheader("Switching quotes (sales evidence)")
    target = st.selectbox("Vendor", [r["EHR"] for r in rows
                                     if r["has_data"] and r["switching_mentions"]])
    rec = data["ehrs"].get(target, {})
    quotes = [m for m in rec.get("mentions", []) if m.get("switching")]
    quotes.sort(key=lambda m: m.get("score", 0), reverse=True)
    if not quotes:
        st.write("No switching quotes for this vendor.")
    else:
        qrows = []
        for m in quotes:
            text = m["text"].replace("\n", " ").strip()
            if len(text) > 300:
                text = text[:300] + "…"
            qrows.append({
                "phrase": ", ".join(m.get("switching", [])),
                "sentiment": m["sentiment"],
                "score": m.get("score", 0),
                "subreddit": "r/" + m.get("subreddit", ""),
                "quote": text,
                "link": m.get("permalink", ""),
            })
        st.dataframe(
            pd.DataFrame(qrows), hide_index=True, use_container_width=True,
            height=400,
            column_config={
                "link": st.column_config.LinkColumn("thread", display_text="open"),
                "quote": st.column_config.TextColumn("quote", width="large"),
            })


def view_heatmap(data):
    st.header("Complaint Heatmap — where the whole market fails")
    st.caption(
        "Each cell = share of that vendor's mentions hitting a complaint theme. "
        "A row (theme) that's hot across ALL vendors = a universal unmet need = "
        "the market gap MavenMD can own. Read across, not down.")

    themes = data.get("complaint_theme_names", [])
    ehrs = [e for e in data["ehr_order"]
            if data["ehrs"].get(e, {}).get("has_data")]
    if not themes or not ehrs:
        st.info("No data available.")
        return

    normalize = st.radio(
        "Cell value",
        ["% of vendor's mentions", "raw count"],
        horizontal=True)

    matrix = []
    for theme in themes:
        row = []
        for ehr in ehrs:
            rec = data["ehrs"][ehr]
            cnt = rec.get("complaint_counts", {}).get(theme, 0)
            if normalize == "% of vendor's mentions":
                total = rec.get("total", 0)
                row.append(round(100.0 * cnt / total, 1) if total else 0.0)
            else:
                row.append(cnt)
        matrix.append(row)

    fig = go.Figure(go.Heatmap(
        z=matrix, x=ehrs, y=themes,
        colorscale="Reds",
        text=matrix, texttemplate="%{text}",
        colorbar_title="%" if normalize.startswith("%") else "count"))
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="", yaxis_title="complaint theme")
    st.plotly_chart(fig, use_container_width=True)

    # Auto-surface the universal gap: theme with highest mean % across vendors.
    means = []
    for i, theme in enumerate(themes):
        pcts = []
        for j, ehr in enumerate(ehrs):
            rec = data["ehrs"][ehr]
            total = rec.get("total", 0)
            cnt = rec.get("complaint_counts", {}).get(theme, 0)
            if total:
                pcts.append(100.0 * cnt / total)
        if pcts:
            means.append((theme, sum(pcts) / len(pcts)))
    means.sort(key=lambda x: x[1], reverse=True)
    if means:
        top = means[0]
        st.success(
            f"**Biggest cross-vendor gap:** `{top[0]}` — complained about in "
            f"~{top[1]:.1f}% of mentions on average across all vendors. "
            "Everyone fails here. Wedge candidate.")


def _store_avg_rows(store_data, name_key):
    """Per-EHR weighted-avg star rating from a store's app metadata."""
    rows = {}
    if not store_data:
        return rows
    for ehr in store_data.get("ehr_order", []):
        apps = store_data.get("apps", {}).get(ehr, [])
        # Apple uses rating_count; Play search gives only avg per app (weight 1).
        weights = [(a.get("rating_count") or 1) for a in apps]
        ratings = [a.get("avg_rating") for a in apps if a.get("avg_rating")]
        if not ratings:
            rows[ehr] = None
            continue
        tot_w = sum(w for a, w in zip(apps, weights) if a.get("avg_rating"))
        wavg = sum((a.get("avg_rating") or 0) * w
                   for a, w in zip(apps, weights) if a.get("avg_rating")) / tot_w
        rows[ehr] = round(wavg, 2)
    return rows


def view_appstore(data):
    st.header("App Reviews — official star ratings (free)")
    apple = load_reviews()
    play = load_playstore()
    if apple is None and play is None:
        st.info(
            "No app-review data found.\n\n"
            "Run `python reviews.py` (Apple) and/or `python playstore.py` "
            "(Google Play) — both free, no key — then `python analyze.py`, "
            "then reload.")
        return

    st.caption(
        "Real customer reviews + 1-5★ from Apple App Store and Google Play "
        "(free, official). Star ratings are ground-truth to sanity-check the "
        "automated VADER sentiment.")

    apple_avg = _store_avg_rows(apple, "name")
    play_avg = _store_avg_rows(play, "title")
    order = (apple or play).get("ehr_order", [])
    rows = []
    for ehr in order:
        rows.append({
            "EHR": ehr,
            "Apple ★": apple_avg.get(ehr),
            "Google Play ★": play_avg.get(ehr),
        })
    df = pd.DataFrame(rows)
    st.subheader("Official average star rating by store")
    st.dataframe(df, hide_index=True, use_container_width=True)

    # Grouped bar comparing the two stores.
    melt = df.melt(id_vars="EHR", value_vars=["Apple ★", "Google Play ★"],
                   var_name="store", value_name="rating").dropna()
    if not melt.empty:
        fig = px.bar(melt, x="rating", y="EHR", color="store",
                     orientation="h", barmode="group", range_x=[0, 5],
                     color_discrete_map={"Apple ★": "#1f77b4",
                                         "Google Play ★": "#2ca02c"})
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # Collect store-review mentions per vendor (Apple + Play).
    store_label = {"appstore": "Apple", "googleplay": "Google Play"}
    review_ms = {}
    for ehr in data["ehr_order"]:
        ms = [m for m in data["ehrs"].get(ehr, {}).get("mentions", [])
              if m.get("source") in store_label]
        if ms:
            review_ms[ehr] = ms
    if not review_ms:
        st.info("No store reviews in the analysis yet — run analyze.py after "
                "reviews.py / playstore.py.")
        return

    # Top complaints from app reviews (Apple + Play only).
    st.subheader("Top complaints (from app reviews)")
    overall = Counter()
    per_vendor = {}
    for ehr, ms in review_ms.items():
        c = Counter()
        for m in ms:
            for theme in m.get("complaints", []):
                c[theme] += 1
                overall[theme] += 1
        per_vendor[ehr] = c
    if overall:
        comp_df = pd.DataFrame(overall.most_common(10),
                               columns=["complaint theme", "mentions"])
        d = comp_df.sort_values("mentions", ascending=True)
        fig = go.Figure(go.Bar(
            x=d["mentions"], y=d["complaint theme"], orientation="h",
            marker_color="#d62728", text=d["mentions"], textposition="auto"))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="app-review mentions")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.write("No complaint themes detected in app reviews.")

    # Sample review quotes from analyzed mentions (Apple + Play).
    st.subheader("Sample reviews")
    pick = st.selectbox("Vendor", list(review_ms.keys()))
    pv = per_vendor.get(pick, Counter())
    if pv:
        st.caption("**" + pick + "** top app-review complaints: " +
                   ", ".join(f"{t} ({n})" for t, n in pv.most_common(5)))
    src_filter = st.multiselect("Store", ["Apple", "Google Play"],
                                default=["Apple", "Google Play"])
    ms = [m for m in review_ms[pick]
          if store_label.get(m.get("source")) in src_filter]
    ms.sort(key=lambda m: m.get("star_rating") or 0)
    qrows = []
    for m in ms:
        text = m["text"].replace("\n", " ").strip()
        if len(text) > 300:
            text = text[:300] + "…"
        qrows.append({
            "store": store_label.get(m.get("source"), ""),
            "stars": (m.get("star_rating") or 0),
            "VADER": m["sentiment"],
            "quote": text,
            "link": m.get("permalink", ""),
        })
    st.dataframe(
        pd.DataFrame(qrows), hide_index=True, use_container_width=True,
        height=400,
        column_config={
            "link": st.column_config.LinkColumn("app", display_text="open"),
            "quote": st.column_config.TextColumn("quote", width="large"),
        })
    fetched = (apple or {}).get("fetched_at") or (play or {}).get("fetched_at")
    st.caption(f"App-review data fetched: {fetched or 'n/a'}")


def view_market_presence(data):
    st.header("Market Presence — ONC CHPL certified products")
    chpl = load_chpl()
    if chpl is None:
        st.info(
            "CHPL data not configured. This is optional government data on "
            "certified EHR products.\n\n"
            "1. Get a free API key: https://chpl.healthit.gov/#/resources/api\n"
            "2. `export CHPL_API_KEY=your-key` (or put it in `chpl_api_key.txt`)\n"
            "3. Run `python chpl.py`, then reload this page.")
        return

    st.caption(
        "Official US registry of certified Health IT products. "
        "`declined` = withdrawn / retired / terminated certifications — a "
        "vendor decline signal. Latest cert date shows how actively a vendor "
        "still invests in certification.")

    rows = []
    for ehr in chpl.get("ehr_order", []):
        rec = chpl["ehrs"].get(ehr, {})
        rows.append({
            "EHR": ehr,
            "certified products": rec.get("total_products", 0),
            "active": rec.get("active_products", 0),
            "declined (withdrawn/retired)": rec.get("declined_products", 0),
            "latest cert date": rec.get("latest_cert_date") or "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)

    has = df[df["certified products"] > 0]
    if not has.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Active certified products")
            d = has.sort_values("active", ascending=True)
            fig = go.Figure(go.Bar(x=d["active"], y=d["EHR"], orientation="h",
                                   marker_color="#1f77b4", text=d["active"],
                                   textposition="auto"))
            fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("Declined certifications")
            d2 = has.sort_values("declined (withdrawn/retired)", ascending=True)
            fig2 = go.Figure(go.Bar(
                x=d2["declined (withdrawn/retired)"], y=d2["EHR"],
                orientation="h", marker_color="#d62728",
                text=d2["declined (withdrawn/retired)"], textposition="auto"))
            fig2.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig2, use_container_width=True)

    st.caption(f"CHPL data fetched: {chpl.get('fetched_at', 'n/a')}")


def view_overview(data):
    st.header("Overview")

    df = overview_df(data)
    has = df[df["has_data"]]

    if has.empty:
        st.info("No data available. Run fetch.py then analyze.py.")
        return

    st.caption(
        f"Low-volume EHRs (under ~{LOW_VOLUME_THRESHOLD} mentions) should be "
        "interpreted cautiously — a handful of comments is not a trend.")

    col1, col2 = st.columns(2)

    # Avg sentiment, ranked best -> worst.
    with col1:
        st.subheader("Average sentiment (best → worst)")
        ranked = has.sort_values("avg_sentiment", ascending=True)  # asc -> top=worst; plot grows up
        colors = ["#d62728" if v < 0 else "#2ca02c" for v in ranked["avg_sentiment"]]
        fig = go.Figure(go.Bar(
            x=ranked["avg_sentiment"],
            y=ranked["EHR"],
            orientation="h",
            marker_color=colors,
            text=[f"{v:+.2f}" for v in ranked["avg_sentiment"]],
            textposition="auto",
        ))
        fig.update_layout(
            xaxis_title="VADER compound (avg)",
            yaxis_title="",
            height=400,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Mention volume.
    with col2:
        st.subheader("Mention volume")
        vol = has.sort_values("mentions", ascending=True)
        fig2 = go.Figure(go.Bar(
            x=vol["mentions"],
            y=vol["EHR"],
            orientation="h",
            marker_color="#1f77b4",
            text=vol["mentions"],
            textposition="auto",
        ))
        fig2.add_vline(x=LOW_VOLUME_THRESHOLD, line_dash="dash",
                       line_color="gray",
                       annotation_text=f"~{LOW_VOLUME_THRESHOLD}",
                       annotation_position="top")
        fig2.update_layout(
            xaxis_title="mentions",
            yaxis_title="",
            height=400,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)


def view_per_system(data):
    st.header("Per-System Detail")

    ehr = st.selectbox("Select EHR", data["ehr_order"])
    rec = data["ehrs"].get(ehr, {})

    if not rec.get("has_data"):
        st.warning(f"No data available for {ehr}.")
        return

    total = rec["total"]
    if total < LOW_VOLUME_THRESHOLD:
        st.caption(f"⚠️ Only {total} mentions — interpret cautiously.")

    # Data volume + where it came from.
    st.subheader("Data volume & sources")
    src_counts = Counter()
    for m in rec.get("mentions", []):
        s = (m.get("source") or "reddit")
        if s == "appstore":
            src_counts["App Store"] += 1
        elif s == "googleplay":
            src_counts["Google Play"] += 1
        elif s == "trustpilot":
            src_counts["Trustpilot"] += 1
        elif s.startswith("manual"):
            src_counts["Manual (G2/Capterra)"] += 1
        else:
            src_counts["Reddit"] += 1

    # Fixed display order: Trustpilot, App Store, Google Play, manual, Reddit.
    label_order = ["Trustpilot", "App Store", "Google Play",
                   "Manual (G2/Capterra)", "Reddit"]
    ordered = sorted(src_counts.items(),
                     key=lambda kv: label_order.index(kv[0])
                     if kv[0] in label_order else 99)
    cols = st.columns(len(ordered) + 1)
    cols[0].metric(f"{ehr} total", total)
    for col, (label, n) in zip(cols[1:], ordered):
        pct = round(100.0 * n / total, 1) if total else 0
        col.metric(label, n, f"{pct}%")

    st.caption(
        f"Grand total across all vendors: "
        f"{sum(r.get('total', 0) for r in data['ehrs'].values())} data points "
        f"(Reddit + App Store + Google Play + any manual imports).")

    c1, c2 = st.columns([1, 1])

    # Sentiment breakdown pie.
    with c1:
        st.subheader("Sentiment breakdown")
        pie_df = pd.DataFrame({
            "sentiment": ["positive", "neutral", "negative"],
            "count": [rec["positive"], rec["neutral"], rec["negative"]],
        })
        fig = px.pie(pie_df, names="sentiment", values="count",
                     color="sentiment", color_discrete_map=SENTIMENT_COLORS,
                     hole=0.4)
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.metric("Total mentions", total)
        st.metric("Avg sentiment", f"{rec['avg_compound']:+.3f}")

    # Themes.
    with c2:
        st.subheader("Top complaints")
        if rec["top_complaints"]:
            comp_df = pd.DataFrame(rec["top_complaints"],
                                   columns=["theme", "count"])
            st.dataframe(comp_df, hide_index=True, use_container_width=True)
        else:
            st.write("— none detected —")

        st.subheader("Top praises")
        if rec["top_praises"]:
            praise_df = pd.DataFrame(rec["top_praises"],
                                     columns=["theme", "count"])
            st.dataframe(praise_df, hide_index=True, use_container_width=True)
        else:
            st.write("— none detected —")

    # Sample quotes with clickable links (anonymized — no usernames).
    st.subheader("Sample quotes")
    st.caption("App Store reviews first, then Google Play, then Reddit. "
               "Public content, usernames omitted. Click to open.")

    mentions = rec.get("mentions", [])
    sent_filter = st.multiselect(
        "Filter by sentiment",
        ["positive", "neutral", "negative"],
        default=["positive", "neutral", "negative"])
    filtered = [m for m in mentions if m["sentiment"] in sent_filter]
    # Order: App Store -> Google Play -> manual -> Reddit; within each, by
    # engagement (score) descending.
    filtered.sort(key=lambda m: (source_rank(m.get("source")),
                                 -(m.get("score", 0) or 0)))

    if not filtered:
        st.write("No quotes match the filter.")
    else:
        quote_rows = []
        for m in filtered:
            text = m["text"].replace("\n", " ").strip()
            if len(text) > 280:
                text = text[:280] + "…"
            quote_rows.append({
                "source": source_label(m),
                "sentiment": m["sentiment"],
                "stars": m.get("star_rating") if m.get("star_rating") else "",
                "score": m.get("score", 0),
                "quote": text,
                "link": m.get("permalink", ""),
            })
        quote_df = pd.DataFrame(quote_rows)
        st.dataframe(
            quote_df,
            hide_index=True,
            use_container_width=True,
            height=420,
            column_config={
                "link": st.column_config.LinkColumn("link", display_text="open"),
                "quote": st.column_config.TextColumn("quote", width="large"),
            },
        )


def view_comparison(data):
    st.header("Comparison — all EHRs")

    rows = []
    for ehr in data["ehr_order"]:
        rec = data["ehrs"].get(ehr, {})