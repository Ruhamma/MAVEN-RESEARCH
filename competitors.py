"""
competitors.py — Telehealth / home-care competitor config + xlsx reader.

Two jobs:
  1. TELEHEALTH_TERMS — the ~32 marketplace/telehealth/home-care competitors
     from competitor_matrix.xlsx, with curated Reddit search terms (generic
     names like "Heal", "Honor", "Papa", "Vitals" are disambiguated so we
     don't drown in unrelated hits).
  2. read_matrix() — parse competitor_matrix.xlsx into JSON for the dashboard's
     Competitor Matrix view (matrix + your-build-vs-threats + gap analysis).

Run `python competitors.py` to (re)generate data/competitor_matrix.json.
"""

import json
import os

CATEGORY_TELEHEALTH = "Telehealth/Home-Care"
CATEGORY_EHR = "EHR"

MATRIX_XLSX = "competitor_matrix.xlsx"
MATRIX_JSON = os.path.join("data", "competitor_matrix.json")

# Company -> curated Reddit/app search terms. Generic words disambiguated.
TELEHEALTH_TERMS = {
    "Zocdoc": ["Zocdoc"],
    "Healthgrades": ["Healthgrades"],
    "Vitals": ["Vitals.com doctor"],
    "Solv Health": ["Solv Health"],
    "Teladoc": ["Teladoc"],
    "MDLive": ["MDLive"],
    "Amwell": ["Amwell"],
    "Doctor on Demand": ["Doctor on Demand"],
    "HealthTap": ["HealthTap"],
    "PlushCare": ["PlushCare"],
    "Hims & Hers": ["Hims and Hers", "Hims & Hers"],
    "One Medical": ["One Medical"],
    "Forward Health": ["Forward Health primary care"],
    "Parsley Health": ["Parsley Health"],
    "Sesame": ["Sesame Care"],
    "DispatchHealth": ["DispatchHealth"],
    "MedArrive": ["MedArrive"],
    "Landmark Health": ["Landmark Health"],
    "Heal": ["Heal house call doctor"],
    "Included Health": ["Included Health"],
    "CareMore Health": ["CareMore Health"],
    "Contessa Health": ["Contessa Health"],
    "WellBe Senior": ["WellBe Senior Medical"],
    "Honor": ["Honor home care"],
    "Care.com": ["Care.com"],
    "Papa": ["Papa Pals senior"],
    "Home Instead": ["Home Instead"],
    "Visiting Angels": ["Visiting Angels"],
    "Bayada": ["Bayada home health"],
    "Hometeam": ["Hometeam home care"],
    "Amazon Pharmacy": ["Amazon Pharmacy"],
    "Capsule": ["Capsule pharmacy"],
    "Alto Pharmacy": ["Alto Pharmacy"],
}

TELEHEALTH_ORDER = list(TELEHEALTH_TERMS.keys())

