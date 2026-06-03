"""
manual_reviews.py — import hand-collected reviews (G2, Capterra, TrustRadius,
Software Advice, GetApp, KLAS, anywhere) from CSV files.

Those sites have no free API and forbid scraping, so the zero-cost / zero-risk
path is: copy reviews by hand (or export if you have an account) into a CSV,
drop it in data/manual_reviews/, and run this. It normalizes them into the same
mention schema as everything else, so analyze.py merges them automatically.

HOW TO USE
  1. Put one or more .csv files in:  data/manual_reviews/
  2. Each row = one review. Columns (header names are case-insensitive and
     flexible — synonyms in COLUMN_ALIASES below):
         ehr       (REQUIRED) one of the tracked vendor names
         text      (REQUIRED) the review body (pros/cons/comments)
         rating    (optional) 1-5 stars
         source    (optional) e.g. G2, Capterra, TrustRadius  (defaults to file)
         date      (optional) YYYY-MM-DD
         url        (optional) link to the review
         title     (optional) review headline (prepended to text)
  3. Run:  python manual_reviews.py
  4. Run:  python analyze.py     (folds them into the dashboard)

A starter template is written to data/manual_reviews/TEMPLATE.csv on first run.
"""

import csv
import glob
import json
import os
from datetime import datetime, timezone

MANUAL_DIR = os.path.join("data", "manual_reviews")
MANUAL_DATA_PATH = os.path.join("data", "manual_data.json")
TEMPLATE_PATH = os.path.join(MANUAL_DIR, "TEMPLATE.csv")

VALID_EHRS = {
    "athenahealth", "nextgen", "eclinicalworks", "tebra", "drchrono",
    "modmed", "practice fusion", "charmhealth",
}
# Canonical display names keyed by lowercase.
CANONICAL = {
    "athenahealth": "AthenaHealth", "nextgen": "NextGen",
    "eclinicalworks": "eClinicalWorks", "tebra": "Tebra",
    "drchrono": "DrChrono", "modmed": "ModMed",
    "practice fusion": "Practice Fusion", "charmhealth": "CharmHealth",
}

# Accept common header variants → canonical field name.
COLUMN_ALIASES = {
    "ehr": "ehr", "vendor": "ehr", "product": "ehr", "system": "ehr",
    "text": "text", "review": "text", "body": "text", "comment": "text",
    "comments": "text", "content": "text", "pros_cons": "text",
    "rating": "rating", "stars": "rating", "score": "rating",
    "star_rating": "rating", "overall": "rating",
    "source": "source", "site": "source", "platform": "source",
    "date": "date", "created": "date", "review_date": "date",
    "url": "url", "link": "url", "permalink": "url",
    "title": "title", "headline": "title", "summary": "title",
}

TEMPLATE_ROWS = [
    ["ehr", "rating", "source", "date", "url", "title", "text"],
    ["AthenaHealth", "2", "G2", "2025-03-14",
     "https://www.g2.com/products/athenahealth/reviews/example",
     "Support went downhill",
     "Billing support takes days to respond. We are evaluating alternatives."],
    ["Tebra", "4", "Capterra", "2025-01-09",
     "https://www.capterra.com/p/000000/Tebra/reviews/example",
     "Good for small practice",
     "Easy to use and the mobile app is solid, but pricing crept up."],
]


def normalize_header(name):
    key = (name or "").strip().lower().replace(" ", "_")
    return COLUMN_ALIASES.get(key, key)


def parse_date_epoch(val):
    if not val:
        return 0
    val = str(val).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
                "%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return 0


def parse_rating(val):
    if val in (None, ""):
        return None
    try:
        n = float(str(val).strip().split("/")[0])  # handle "4/5"
        return int(round(n))
    except (ValueError, TypeError):
        return None


def load_csv(path):
    out = []
    fname = os.path.basename(path)
    if fname == os.path.basename(TEMPLATE_PATH):
        return out
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return out
        header_map = {h: normalize_header(h) for h in reader.fieldnames}
        for i, raw in enumerate(reader):
            row = {}
            for orig, val in raw.items():
                row[header_map.get(orig, orig)] = val

            ehr_raw = (row.get("ehr") or "").strip().lower()
            if ehr_raw not in VALID_EHRS:
                if ehr_raw:
                    print(f"  {fname} row {i+2}: unknown EHR "
                          f"'{row.get('ehr')}' — skipped")
                continue
            title = (row.get("title") or "").strip()
            body = (row.get("text") or "").strip()
            text = (title + ". " + body).strip(". ").strip() if title else body
            if not text:
                continue

            source = (row.get("source") or "").strip() or fname.rsplit(".", 1)[0]
            out.append({
                "ehr": CANONICAL[ehr_raw],
                "matched_term": source,
                "kind": "manual_review",
                "source": "manual:" + source,
                "text": text,
                "score": 0,
                "star_rating": parse_rating(row.get("rating")),
                "subreddit": source,                 # reuse 'subreddit' as source
                "permalink": (row.get("url") or "").strip(),
                "created_utc": parse_date_epoch(row.get("date")),
                "id": f"manual::{fname}::{i}",
            })
    return out


def write_template():
    os.makedirs(MANUAL_DIR, exist_ok=True)
    if os.path.exists(TEMPLATE_PATH):
        return
    with open(TEMPLATE_PATH, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(TEMPLATE_ROWS)
    print(f"Wrote starter template: {TEMPLATE_PATH}")


def main():
    write_template()
    csv_files = sorted(glob.glob(os.path.join(MANUAL_DIR, "*.csv")))
    real = [f for f in csv_files
            if os.path.basename(f) != os.path.basename(TEMPLATE_PATH)]

    if not real:
        print(f"No CSVs in {MANUAL_DIR}/ yet (besides TEMPLATE.csv).")
        print("Add files like the template, then re-run.")
        return

    all_reviews = []
    for path in real:
        rows = load_csv(path)
        print(f"  {os.path.basename(path)}: {len(rows)} reviews")
        all_reviews.extend(rows)

    out = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "files": [os.path.basename(f) for f in real],
        "reviews": all_reviews,
    }
    os.makedirs("data", exist_ok=True)
    with open(MANUAL_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    # Summary per EHR.
    counts = {}
    for r in all_reviews:
        counts[r["ehr"]] = counts.get(r["ehr"], 0) + 1
    print(f"\nImported {len(all_reviews)} manual reviews to {MANUAL_DATA_PATH}")
    for ehr, n in sorted(counts.items()):
        print(f"  {ehr:<18} {n}")
    print("Re-run analyze.py to fold these into the dashboard.")


if __name__ == "__main__":
    main()
