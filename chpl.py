"""
chpl.py — OPTIONAL market-presence enrichment from ONC's CHPL.

CHPL = Certified Health IT Product List (chpl.healthit.gov), the official US
government registry of certified EHR products. For each tracked EHR vendor it
gives: how many certified products they have, how many are Active vs
Withdrawn/Retired (a decline signal), and the latest certification date.

This is OPTIONAL. The core Reddit pipeline (fetch -> analyze -> dashboard)
needs no key. CHPL requires a FREE API key:
    1. Visit https://chpl.healthit.gov/#/resources/api
    2. Request a key (instant, emailed).
    3. Provide it one of two ways:
         - env var:  export CHPL_API_KEY=your-key
         - or file:  put the key in  chpl_api_key.txt  (gitignored)

Then run:  python chpl.py
Writes data/chpl_data.json, which the dashboard's "Market Presence" view loads.
If no key / no data file, the dashboard simply shows "not configured".
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

CHPL_SEARCH_URL = "https://chpl.healthit.gov/rest/search/v3"
CHPL_DATA_PATH = os.path.join("data", "chpl_data.json")
KEY_FILE = "chpl_api_key.txt"

REQUEST_DELAY = 1.0
TIMEOUT = 30
MAX_RETRIES = 3
PAGE_SIZE = 100   # CHPL max per page

DEBUG_RAW = True

# Map each tracked EHR to the CHPL "developer" name(s) to match against.
# CHPL lists products under the legal developer/company name, which differs
# from the brand. Matching is case-insensitive substring on the developer field.
EHR_DEVELOPER_NAMES = {
    "AthenaHealth": ["athenahealth"],
    "NextGen": ["nextgen", "quality systems"],
    "eClinicalWorks": ["eclinicalworks"],
    "Tebra": ["tebra", "kareo"],
    "DrChrono": ["drchrono", "dr. chrono", "everhealth"],
    "ModMed": ["modernizing medicine", "modmed"],
    "Practice Fusion": ["practice fusion"],
    "CharmHealth": ["charmhealth", "medical information technology",
                    "ensoftek", "healthie"],  # CharmHealth = MedicalMine Inc.
}
# Note: CharmHealth's CHPL developer is "MedicalMine Inc." — adjust if needed.
EHR_DEVELOPER_NAMES["CharmHealth"] = ["medicalmine", "charm"]

EHR_ORDER = list(EHR_DEVELOPER_NAMES.keys())


def load_api_key():
    """Return CHPL API key from env or key file, or None."""
    key = os.environ.get("CHPL_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return None


def get_with_retry(params, headers):
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(CHPL_SEARCH_URL, params=params,
                                headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"    request error ({exc}); retry in {wait}s")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                print("    bad JSON in 200 response")
                return None
        if resp.status_code in (401, 403):
            raise SystemExit(
                f"CHPL returned {resp.status_code} — API key missing or "
                "invalid. Get a free key at "
                "https://chpl.healthit.gov/#/resources/api")
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            wait = 2 ** attempt
            print(f"    HTTP {resp.status_code}; backoff {wait}s")
            time.sleep(wait)
            continue
        print(f"    HTTP {resp.status_code}; giving up on this query")
        return None
    return None


def first(d, *keys, default=""):
    """Return the first present, non-empty value among keys (defensive)."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            # CHPL often nests, e.g. {"name": ...}
            v = v.get("name") or v.get("title")
        if v not in (None, "", []):
            return v
    return default


def fetch_developer(ehr, names, headers):
    """Pull ALL CHPL listings whose developer matches any alias for this EHR.

    Paginates through every page of the brand search (CHPL caps pageSize at
    100), then filters client-side by developer name. Without pagination the
    counts are truncated and meaningless.
    """
    global DEBUG_RAW
    matched = []
    page = 0
    record_count = None

    while True:
        params = {"searchTerm": names[0], "pageSize": PAGE_SIZE,
                  "pageNumber": page}
        time.sleep(REQUEST_DELAY)
        payload = get_with_retry(params, headers)
        if not payload:
            break

        results = payload.get("results") or payload.get("data") or []
        if record_count is None:
            record_count = payload.get("recordCount", len(results))

        if DEBUG_RAW and results:
            DEBUG_RAW = False
            print("\n--- DEBUG: raw CHPL first result ---")
            print(f"    top-level keys: {list(payload.keys())}")
            print(f"    recordCount: {record_count}")
            print(f"    result keys: {sorted(results[0].keys())}")
            print("--- END DEBUG ---\n")

        for r in results:
            dev = str(first(r, "developer", "developerName")).lower()
            if any(n in dev for n in names):
                matched.append({
                    "product": first(r, "product", "productName"),
                    "developer": first(r, "developer", "developerName"),
                    "edition": str(first(r, "edition", "certificationEdition")),
                    "status": first(r, "certificationStatus", "status"),
                    "cert_date": first(r, "certificationDate", "certDate"),
                })

        page += 1
        # Stop when we've walked all pages (or a safety cap of 30 pages).
        if not results or (page * PAGE_SIZE) >= (record_count or 0) or page > 30:
            break

    return matched


def summarize(listings):
    """Aggregate per-EHR market-presence stats."""
    total = len(listings)
    active = sum(1 for x in listings
                 if str(x.get("status", "")).lower().startswith("active"))
    declined = sum(1 for x in listings
                   if any(s in str(x.get("status", "")).lower()
                          for s in ("withdraw", "retire", "terminat",
                                    "suspend")))
    # Latest certification date (epoch ms or ISO — handle both).
    latest = ""
    for x in listings:
        cd = x.get("cert_date")
        if cd and str(cd) > str(latest):
            latest = cd
    return {
        "total_products": total,
        "active_products": active,
        "declined_products": declined,   # withdrawn/retired/terminated
        "latest_cert_date": _fmt_date(latest),
        "products": listings,
        "has_data": total > 0,
    }


def _fmt_date(val):
    if not val:
        return ""
    # CHPL cert dates are often epoch milliseconds.
    try:
        n = int(val)
        if n > 10_000_000_000:   # ms
            n //= 1000
        return datetime.fromtimestamp(n, timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(val)[:10]


def main():
    key = load_api_key()
    if not key:
        print("No CHPL API key found.")
        print("  Set env CHPL_API_KEY or create chpl_api_key.txt.")
        print("  Get a free key: https://chpl.healthit.gov/#/resources/api")
        print("Skipping CHPL enrichment (core pipeline unaffected).")
        return

    headers = {"API-Key": key, "Accept": "application/json"}
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ehr_order": EHR_ORDER,
        "ehrs": {},
    }

    print("Pulling CHPL certified-product data...")
    for ehr, names in EHR_DEVELOPER_NAMES.items():
        print(f"  {ehr} (dev match: {names})")
        listings = fetch_developer(ehr, names, headers)
        out["ehrs"][ehr] = summarize(listings)
        s = out["ehrs"][ehr]
        print(f"    products={s['total_products']} "
              f"active={s['active_products']} "
              f"declined={s['declined_products']} "
              f"latest={s['latest_cert_date'] or 'n/a'}")

    os.makedirs("data", exist_ok=True)
    with open(CHPL_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nSaved CHPL data to {CHPL_DATA_PATH}")


if __name__ == "__main__":
    main()
