"""
dashboard.py — Streamlit market-research dashboard for EHR Reddit sentiment.

Loads data/analyzed_data.json (built by analyze.py) — never hits the API.
Four views via sidebar: Overview, Per-System, Comparison, Gap Analysis.

Run:  streamlit run dashboard.py
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ANALYZED_DATA_PATH = os.path.join("data", "analyzed_data.json")
GAPS_CSV_PATH = os.path.join("data", "gaps.csv")
CHPL_DATA_PATH = os.path.join("data", "chpl_data.json")
REVIEWS_DATA_PATH = os.path.join("data", "reviews_data.json")

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


def view_appstore(data):
    st.header("App Store Reviews — official star ratings (free)")
    reviews = load_reviews()
    if reviews is None:
        st.info(
            "App Store review data not found.\n\n"
            "Run `python reviews.py` (free, no key) then `python analyze.py`, "
            "then reload.")
        return

    st.caption(
        "Real customer reviews + 1-5★ ratings from Apple's App Store "
        "(free, official). Star ratings are ground-truth to sanity-check the "
        "automated VADER sentiment.")

    # Official weighted avg rating per EHR (weight each app by its rating count).
    rows = []
    for ehr in reviews.get("ehr_order", []):
        apps = reviews.get("apps", {}).get(ehr, [])
        tot_w = sum((a.get("rating_count") or 0) for a in apps)
        if tot_w:
            wavg = sum((a.get("avg_rating") or 0) * (a.get("rating_count") or 0)
                       for a in apps) / tot_w
        else:
            wavg = None
        rows.append({
            "EHR": ehr,
            "official avg ★": round(wavg, 2) if wavg is not None else None,
            "total ratings": tot_w,
            "apps": ", ".join(a["name"] for a in apps) or "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)

    rated = df[df["official avg ★"].notna()]
    if not rated.empty:
        st.subheader("Official average star rating")
        d = rated.sort_values("official avg ★", ascending=True)
        colors = ["#d62728" if v < 3 else ("#ff7f0e" if v < 4 else "#2ca02c")
                  for v in d["official avg ★"]]
        fig = go.Figure(go.Bar(
            x=d["official avg ★"], y=d["EHR"], orientation="h",
            marker_color=colors, text=[f"{v}★" for v in d["official avg ★"]],
            textposition="auto"))
        fig.update_layout(height=360, xaxis_range=[0, 5],
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # Sample review quotes (from analyzed mentions tagged source=appstore).
    st.subheader("Sample reviews")
    appstore_ms = {}
    for ehr in data["ehr_order"]:
        ms = [m for m in data["ehrs"].get(ehr, {}).get("mentions", [])
              if m.get("source") == "appstore"]
        if ms:
            appstore_ms[ehr] = ms
    if not appstore_ms:
        st.info("No App Store reviews in the analysis yet — run analyze.py "
                "after reviews.py.")
        return
    pick = st.selectbox("Vendor", list(appstore_ms.keys()))
    ms = sorted(appstore_ms[pick], key=lambda m: m.get("star_rating") or 0)
    qrows = []
    for m in ms:
        text = m["text"].replace("\n", " ").strip()
        if len(text) > 300:
            text = text[:300] + "…"
        qrows.append({
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
    st.caption(f"App Store data fetched: {reviews.get('fetched_at', 'n/a')}")


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
    st.caption("Public Reddit content, usernames omitted. Click to open thread.")

    mentions = rec.get("mentions", [])
    sent_filter = st.multiselect(
        "Filter by sentiment",
        ["positive", "neutral", "negative"],
        default=["positive", "neutral", "negative"])
    filtered = [m for m in mentions if m["sentiment"] in sent_filter]
    # Show most-upvoted first.
    filtered.sort(key=lambda m: m.get("score", 0), reverse=True)

    if not filtered:
        st.write("No quotes match the filter.")
    else:
        quote_rows = []
        for m in filtered:
            text = m["text"].replace("\n", " ").strip()
            if len(text) > 280:
                text = text[:280] + "…"
            quote_rows.append({
                "sentiment": m["sentiment"],
                "score": m.get("score", 0),
                "subreddit": "r/" + m.get("subreddit", ""),
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
                "link": st.column_config.LinkColumn("thread", display_text="open"),
                "quote": st.column_config.TextColumn("quote", width="large"),
            },
        )


def view_comparison(data):
    st.header("Comparison — all EHRs")

    rows = []
    for ehr in data["ehr_order"]:
        rec = data["ehrs"].get(ehr, {})
        if not rec.get("has_data"):
            rows.append({
                "EHR": ehr, "mentions": 0, "% positive": "—",
                "% negative": "—", "avg sentiment": "—",
                "top complaint": "no data", "top praise": "no data",
            })
            continue
        rows.append({
            "EHR": ehr,
            "mentions": rec["total"],
            "% positive": rec["pct_positive"],
            "% negative": rec["pct_negative"],
            "avg sentiment": rec["avg_compound"],
            "top complaint": top_theme_label(rec["top_complaints"]),
            "top praise": top_theme_label(rec["top_praises"]),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption(
        f"Cells show '—' / 'no data' where a vendor had zero mentions. "
        f"Mentions under ~{LOW_VOLUME_THRESHOLD} are low-confidence.")


def view_gap_analysis(data):
    st.header("Gap Analysis — competitor weakness → MavenMD opportunity")

    gaps = load_gaps()
    if gaps is None:
        st.error(f"{GAPS_CSV_PATH} not found. Create it with columns: "
                 "EHR, top_complaint, mavenmd_opportunity.")
        return

    st.caption("Source: data/gaps.csv (editable). Maps each competitor's key "
               "weakness to a MavenMD product opportunity.")

    styled = gaps.style.set_properties(**{
        "white-space": "normal",
        "text-align": "left",
        "vertical-align": "top",
    }).set_table_styles([
        {"selector": "th", "props": [("text-align", "left"),
                                     ("background-color", "#1f3b57"),
                                     ("color", "white")]},
    ])
    st.table(styled)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    st.sidebar.title("EHR Market Research")
    data = load_analyzed()

    if data is None:
        st.title("EHR Market Research Dashboard")
        st.error("data/analyzed_data.json not found. "
                 "Run `python fetch.py` then `python analyze.py` first.")
        return

    view = st.sidebar.radio(
        "View",
        ["Overview", "Churn Signals", "Complaint Heatmap",
         "Per-System", "Comparison", "App Store", "Market Presence",
         "Gap Analysis"])

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Data window: {fmt_epoch(data.get('window_after'))} "
                       f"→ {fmt_epoch(data.get('window_before'))}")
    st.sidebar.caption(f"Last updated: {data.get('analyzed_at', 'n/a')}")

    if view == "Overview":
        view_overview(data)
    elif view == "Churn Signals":
        view_churn(data)
    elif view == "Complaint Heatmap":
        view_heatmap(data)
    elif view == "Per-System":
        view_per_system(data)
    elif view == "Comparison":
        view_comparison(data)
    elif view == "App Store":
        view_appstore(data)
    elif view == "Market Presence":
        view_market_presence(data)
    elif view == "Gap Analysis":
        view_gap_analysis(data)

    # Footer disclaimer (every view).
    st.markdown("---")
    st.caption(
        "**Disclaimer:** Data is from public Reddit discussion via the PullPush "
        "API. Sentiment is automated (VADER) and should be spot-checked — "
        "sarcasm, context, and clinical jargon can fool it. Mention counts vary "
        "widely by vendor popularity, so cross-vendor comparisons of low-volume "
        "EHRs are unreliable. For competitive research only, not an endorsement.")


if __name__ == "__main__":
    main()
