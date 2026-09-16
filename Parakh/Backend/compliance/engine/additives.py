"""
compliance/engine/additives.py
--------------------------------
Scans OCR'd ingredient text for INS ("Indian Numbering System", used on
Indian labels) / E-number food-additive codes, and matches them against
a small curated reference of common ones. This is a labeling aid, not
an authoritative food-safety database - the description field says so
for every entry, and anything not in the curated dict is still surfaced
(as "unidentified, verify manually") rather than silently dropped.

BANNED_CODES is deliberately short and specific to substances actually
prohibited in India (e.g. potassium bromate in bread, since 2016) -
resist the temptation to pad it with "controversial" additives that are
legal; that's a different, more subjective claim than "banned".
"""

import re

ADDITIVE_DB = {
    "320": {"name": "Butylated Hydroxyanisole (BHA)",
            "description": "An antioxidant preservative used to prevent oxidation of fats. Some studies have raised concerns about long-term consumption; permitted in India within specified limits.",
            "banned": False},
    "321": {"name": "Butylated Hydroxytoluene (BHT)",
            "description": "An antioxidant preservative similar to BHA, used to prevent rancidity in fats and oils; permitted in India within specified limits.",
            "banned": False},
    "621": {"name": "Monosodium Glutamate (MSG)",
            "description": "A flavor enhancer. Generally recognized as safe by FSSAI, though some individuals report sensitivity with symptoms like headaches when consumed in large amounts.",
            "banned": False},
    "211": {"name": "Sodium Benzoate",
            "description": "A preservative used to prevent mold and bacterial growth, common in beverages and condiments; permitted in India within specified limits.",
            "banned": False},
    "223": {"name": "Sodium Metabisulphite",
            "description": "A preservative and antioxidant, common in dried fruits and processed foods; may trigger reactions in people with sulphite sensitivity.",
            "banned": False},
    "150": {"name": "Caramel Colour",
            "description": "A brown food colouring made by heating sugars; widely used and generally considered safe within permitted limits.",
            "banned": False},
    "102": {"name": "Tartrazine (Yellow 5)",
            "description": "A synthetic yellow food dye; permitted in India within specified limits, though linked to sensitivity in a small number of consumers.",
            "banned": False},
    "122": {"name": "Carmoisine (Azorubine)",
            "description": "A synthetic red food dye; permitted in India within specified limits.",
            "banned": False},
    "129": {"name": "Allura Red AC",
            "description": "A synthetic red food dye; permitted in India within specified limits.",
            "banned": False},
    "330": {"name": "Citric Acid",
            "description": "A natural acidity regulator found in citrus fruits, widely used and considered safe.",
            "banned": False},
    "500": {"name": "Sodium Carbonate",
             "description": "An acidity regulator / raising agent, widely used and considered safe.",
             "banned": False},
    "508": {"name": "Potassium Chloride",
            "description": "A salt substitute / firming agent, widely used and considered safe within permitted limits.",
            "banned": False},
    "924": {"name": "Potassium Bromate",
            "description": "A flour-treatment/oxidising agent. Banned for use in bread and bakery products in India (FSSAI, 2016) due to potential carcinogenicity.",
            "banned": True},
    "128": {"name": "Red 2G",
            "description": "A synthetic red food dye. Banned for use in food in India due to safety concerns (breaks down into a compound linked to cancer risk in animal studies).",
            "banned": True},
}

INS_RE = re.compile(r"\bINS\s*[:\-]?\s*(\d{3,4})\b", re.IGNORECASE)
E_RE = re.compile(r"\bE\s*[:\-]?\s*(\d{3,4})\b", re.IGNORECASE)


def detect_additives(all_text):
    """
    all_text: a single string containing all OCR'd text for the scan
    (ingredients line plus anything else - codes sometimes appear outside
    a cleanly-labeled "ingredients" line, e.g. next to an allergen note).

    Returns a list of {"code", "name", "description", "is_banned"} dicts,
    one per distinct code found, in the order first seen.
    """
    codes_seen = []
    for pattern in (INS_RE, E_RE):
        for m in pattern.finditer(all_text):
            code = m.group(1)
            if code not in codes_seen:
                codes_seen.append(code)

    results = []
    for code in codes_seen:
        entry = ADDITIVE_DB.get(code)
        if entry:
            results.append({
                "code": f"INS {code}",
                "name": entry["name"],
                "description": entry["description"],
                "is_banned": entry["banned"],
            })
        else:
            results.append({
                "code": f"INS {code}",
                "name": "Unidentified additive",
                "description": "This code was detected on the label but is not in our reference list yet - please verify it manually against the FSSAI additive schedule.",
                "is_banned": False,
            })
    return results
