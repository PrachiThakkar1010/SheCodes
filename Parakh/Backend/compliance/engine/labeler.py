"""
compliance/engine/labeler.py
----------------------------
Rule-based classifier for OCR lines.

Input:
    {"text", "box", "confidence", "image_id"}

Output:
    same dicts with a "label" field.

OCR is responsible for reading text.
This module decides what each OCR line represents.
"""

import re
import statistics


LABELS = [
    "PRODUCT_NAME",
    "MANUFACTURER_NAME",
    "MANUFACTURER_ADDRESS",
    "NET_QUANTITY",
    "MANUFACTURING_DATE",
    "EXPIRY_DATE",
    "BATCH_NUMBER",
    "MRP",
    "UNIT_SALE_PRICE",
    "FSSAI_LICENSE_NO",
    "CONSUMER_CONTACT",
    "NUTRITION",
    "OTHER",
    "UNKNOWN",
]


RULES = [

    # ------------------------------------------------------------
    # FSSAI
    # ------------------------------------------------------------
    ("FSSAI_LICENSE_NO", [
        r"fssai",
        r"lic\.?\s*no",
        r"licen[cs]e\s*no",
        r"\b\d{14}\b",
    ]),

    # ------------------------------------------------------------
    # BATCH / LOT
    # ------------------------------------------------------------
    ("BATCH_NUMBER", [
        r"batch\s*no",
        r"\bb\.?\s*no\b",
        r"lot\s*no",
        r"batch\s*[:#]",
        r"batch\s*number",
        r"^code\s*[.:]",
    ]),

    # ------------------------------------------------------------
    # EXPIRY
    # ------------------------------------------------------------
    ("EXPIRY_DATE", [
        r"exp(?:iry)?\b",
        r"use\s*by",
        r"best\s*before",
        r"\.se\s*by",
        r"\bexp\.?\s*date",
    ]),

    # ------------------------------------------------------------
    # MANUFACTURING / PACKING DATE
    # ------------------------------------------------------------
    ("MANUFACTURING_DATE", [
        r"mfg\b",
        r"manufactur\w*\s*(date|on)",
        r"date\s*of\s*mfg",
        r"pkd\b",
        r"packed\s*on",
        r"packaging\s*date",
        r"mfd\s*(date|on)",
        r"\bmfd\b(?!\.?\s*by)",
        r"pkg\s*date",
        r"date\s*of\s*pack(?:ing|aging)?",
    ]),

    # ------------------------------------------------------------
    # NUTRITION
    # ------------------------------------------------------------
    ("NUTRITION", [
        r"nutrition\w*",
        r"energy",
        r"protein",
        r"carbohydrate",
        r"\bfat\b",
        r"sodium",
        r"\bsugars?\b",
        r"\bkcal\b",
        r"per\s*100\s*g",
        r"per\s*serving",
        r"dietary\s*allowance",
        r"rda\b",
        r"calories",
        r"saturated",
        r"trans\s*fat",
        r"added\s*sugars",
        r"vitamin",
        r"cholesterol",
        r"fibre|fiber",
    ]),

    # ------------------------------------------------------------
    # UNIT SALE PRICE
    #
    # IMPORTANT:
    # This must appear BEFORE MRP.
    #
    # Otherwise:
    #     UNIT SALE PRICE 1.23/ml
    #
    # can incorrectly become MRP.
    # ------------------------------------------------------------
    ("UNIT_SALE_PRICE", [
        r"unit\s*sale\s*price",
        r"unit\s*selling\s*price",
        r"(?:₹|rs\.?)\s*\d+(?:[.,]\d+)?\s*/\s*"
        r"(?:kg|g|l|ml|unit|piece|pc|no\.?)",
        r"\d+(?:[.,]\d+)?\s*/\s*"
        r"(?:kg|g|l|ml|unit|piece|pc|no\.?)",
    ]),

    # ------------------------------------------------------------
    # MRP
    # ------------------------------------------------------------
    ("MRP", [
        r"\bmrp\b",
        r"m\.r\.p",
        r"maximum\s*retail\s*price",
        r"inclusive\s*of\s*(all\s*)?taxes",
        r"₹\s*\d",
        r"\brs\.?\s*\d",
        r"\bincl\.?\s*(of\s*)?(all\s*)?tax",
        r"\bprice\b",
    ]),

    #-----------------------------------------------------------------
    # Unit Sale Price
    #-----------------------------------------------------------------
    (
    "UNIT_SALE_PRICE",
    [
        r"unit\s*(?:sale|selling)\s*price",
        r"\b(?:₹|rs\.?)?\s*\d+(?:[.,]\d+)?\s*/\s*(?:kg|g|l|ml|unit|piece|pc|no\.?)\b",
        r"\b(?:₹|rs\.?)?\s*\d+(?:[.,]\d+)?\s+per\s+(?:kg|g|l|ml|unit|piece|pc|no\.?)\b",
    ],
    ),

    # ------------------------------------------------------------
    # NET QUANTITY
    # ------------------------------------------------------------
    ("NET_QUANTITY", [
        r"net\s*(qty|quantity|wt|weight|contents)",
        r"\b\d+(\.\d+)?\s*"
        r"(g|gm|gms|kg|ml|l|litre|liters?)\b\s*$",
        r"\bnet\b.*\d",
    ]),

    # ------------------------------------------------------------
    # CONSUMER CONTACT
    # ------------------------------------------------------------
    ("CONSUMER_CONTACT", [
        r"customer\s*care",
        r"consumer\s*(care|complaint|feedback)",
        r"toll\s*free",
        r"\b1800\d{6,7}\b",
        r"\b1800\b",
        r"[\w.+-]+@[\w-]+\.[a-z]{2,}",
        r"www\.[\w.-]+\.\w+",
        r"\bcare\s*no\b",
        r"\bhelpline\b",
        r"customer\s*support",
        r"call\s*us\s*at",
        r"email\s*us\s*at",
        r"\bor\s*call\b",
        r"\bor\s*email\b",
    ]),

    # ------------------------------------------------------------
    # MANUFACTURER NAME
    # ------------------------------------------------------------
    ("MANUFACTURER_NAME", [
        r"mfd\.?\s*by",
        r"manufactured\s*by",
        r"marketed\s*by",
        r"packed\s*by",
        r"\bmfrs?\.?\s*by\b",
        r"(pvt\.?\s*ltd|private\s*limited|\bltd\b|"
        r"industries|enterprises|foods?\s*(pvt|ltd)|company)\b",
    ]),

    # ------------------------------------------------------------
    # MANUFACTURER ADDRESS
    # ------------------------------------------------------------
    ("MANUFACTURER_ADDRESS", [
        r"\b\d{6}\b",
        r"\b(road|street|nagar|industrial\s*area|estate|"
        r"district|dist\.?|taluka|village|plot\s*no)\b",
        r"\bp\.o\.|\bpo\s*box\b",
        r"\b(maharashtra|gujarat|delhi|mumbai|karnataka|"
        r"tamil\s*nadu|rajasthan|punjab|haryana|west\s*bengal|"
        r"kerala|telangana|andhra\s*pradesh|madhya\s*pradesh|"
        r"uttar\s*pradesh)\b",
    ]),
]


GENERIC_OTHER_HINTS = [
    r"ingredients?",
    r"contains?",
    r"allergen",
    r"veg\b",
    r"non[- ]?veg",
    r"product\s*of\s*india",
    r"suggested\s*usage",
    r"how\s*to\s*use",
    r"store\s*in",
    r"keep\s*away",
    r"disclaimer",
    r"fssai\s*logo",
    r"scan\s*now",
    r"recipe",
    r"www\.",
    r"packaging\s*material",
]


VALUE_LIKE_RE = re.compile(
    r"^[<>~]?\s*\d+([.,]\d+)?\s*"
    r"(g|gm|gms|mg|mcg|kcal|kj|iu|%|cal)?\s*[.,]?$",
    re.I,
)


# Supports:
#   14/08/26
#   31 OCT 26
#   310CT26
#   09/25
#   08-28
_DATE_PATTERN_STR = (
    r"\d{1,2}\s?[/\-.]\s?\d{1,2}\s?[/\-.]\s?\d{2,4}"
    r"|\d{1,2}\s?(?:[A-Za-z]{3,4}|0CT)\s?\d{2,4}"
    r"|\d{1,2}\s?[/\-.]\s?\d{2}"
)


ROW_VALUE_PATTERNS = {
    "MANUFACTURING_DATE": re.compile(
        _DATE_PATTERN_STR,
        re.IGNORECASE,
    ),

    "EXPIRY_DATE": re.compile(
        _DATE_PATTERN_STR,
        re.IGNORECASE,
    ),

    "CONSUMER_CONTACT": re.compile(
        r"^\+?[\d\-\s]{7,17}$"
    ),

    "BATCH_NUMBER": re.compile(
        r"^(?=.*\d)"
        r"(?!.*\d{1,2}[/\-.]?\s?[A-Za-z]{3,4}\s?\d{2,4})"
        r"(?!.*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})"
        r"[A-Za-z0-9][A-Za-z0-9./\- ]{1,18}$"
    ),

    "MRP": re.compile(
        r"^[₹Rr\s]*\d+([.,]\d+)?\s*/?-?$"
    ),

    "NET_QUANTITY": re.compile(
        r"^\d+([.,]\d+)?\s*"
        r"(g|gm|gms|kg|ml|l|litre|liters?)?$",
        re.I,
    ),

    "UNIT_SALE_PRICE": re.compile(
        r"^(?:₹|Rs\.?)?\s*"
        r"\d+(?:[.,]\d+)?\s*/\s*"
        r"(?:kg|g|l|ml|unit|piece|pc|no\.?)$",
        re.I,
    ),
}


def _looks_like_gibberish(text, confidence):
    t = text.strip()

    if not t:
        return True

    alnum = sum(ch.isalnum() for ch in t)

    if alnum == 0:
        return True

    if confidence < 0.55 and len(t) <= 3:
        return True

    if alnum / max(len(t), 1) < 0.4:
        return True

    return False

def _looks_like_standalone_batch_code(text):
    """
    Detect compact alphanumeric batch/lot codes such as:

        BR2E2584
        AB12345
        L24A0912

    Reject obvious quantities, dates, prices, phone numbers,
    and ordinary words.
    """

    if not text:
        return False

    s = str(text).strip().upper()

    # Remove surrounding OCR punctuation.
    s = s.strip(" :;,.#*-")

    if not s:
        return False

    # Batch codes are normally compact.
    if len(s) < 5 or len(s) > 20:
        return False

    # No spaces for a standalone batch code.
    if " " in s:
        return False

    # Must contain BOTH letters and digits.
    if not re.search(r"[A-Z]", s):
        return False

    if not re.search(r"\d", s):
        return False

    # --------------------------------------------------------
    # Reject quantities
    # --------------------------------------------------------
    if re.fullmatch(
        r"\d+(?:[.,]\d+)?\s*"
        r"(?:MG|G|GM|GMS|KG|ML|L|LITRE|LITRES|LITER|LITERS|"
        r"PCS?|PC|NO)",
        s,
        re.IGNORECASE,
    ):
        return False

    # --------------------------------------------------------
    # Reject dates such as:
    # 09/25
    # 09-25
    # 14/08/26
    # 31OCT26
    # 02JUL26
    # --------------------------------------------------------
    if re.fullmatch(
        r"\d{1,2}[/\-.]\d{1,2}"
        r"(?:[/\-.]\d{2,4})?",
        s,
    ):
        return False

    if re.fullmatch(
        r"\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,4}",
        s,
        re.IGNORECASE,
    ):
        return False

    # --------------------------------------------------------
    # Reject phone-number-like values
    # --------------------------------------------------------
    digits = re.sub(r"\D", "", s)

    if len(digits) >= 10:
        return False

    # --------------------------------------------------------
    # Reject obvious manufacturer/address text
    # --------------------------------------------------------
    bad_words = (
        "PLOT",
        "ROAD",
        "STREET",
        "AREA",
        "SECTOR",
        "BLOCK",
        "LANE",
        "NAGAR",
        "DIST",
        "CITY",
        "STATE",
        "PVT",
        "LTD",
        "LIMITED",
        "INDL",
    )

    if any(word in s for word in bad_words):
        return False

    return True

def _classify(text, confidence):
    """
    Classify one OCR line into one of the supported labels.

    Important:
    - Protects address-like text from being classified as BATCH_NUMBER.
    - Rejects isolated MFD/MFG/B.NO. fragments.
    - Keeps standalone mixed alphanumeric batch codes such as BR2E2584.
    """

    text = str(text or "").strip()

    if not text:
        return "UNKNOWN"

    # ---------------------------------------------------------
    # 1. Reject obvious OCR garbage
    # ---------------------------------------------------------
    if _looks_like_gibberish(text, confidence):
        return "UNKNOWN"

    # ---------------------------------------------------------
    # 2. Protect address/location text
    #
    # Example:
    #   PLOT NO. 74, DIC INDL. AREA,
    #
    # This must NOT become BATCH_NUMBER.
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # 3. Reject isolated manufacturing/batch-label fragments
    #
    # Example:
    #   ) #MFD.B.NO.,
    #
    # This is a label fragment, not the actual batch value.
    # ---------------------------------------------------------
    if re.fullmatch(
        r"[\s\W]*#?\s*"
        r"(?:MFD|MFG|MANUF(?:ACTURING)?)"
        r"\s*\.?\s*"
        r"B\.?\s*NO\.?"
        r"[\s\W]*",
        text,
        re.IGNORECASE,
    ):
        return "OTHER"

    # ---------------------------------------------------------
    # 4. High-priority labels
    # ---------------------------------------------------------
    priority_labels = [
        "FSSAI_LICENSE_NO",
        "BATCH_NUMBER",
        "EXPIRY_DATE",
        "MANUFACTURING_DATE",
        "MRP",
        "NET_QUANTITY",
        "UNIT_SALE_PRICE",
        "CONSUMER_CONTACT",
        "MANUFACTURER_NAME",
        "MANUFACTURER_ADDRESS",
    ]

    # ---------------------------------------------------------
    # 5. Apply explicit regex rules
    # ---------------------------------------------------------
    for label, patterns in RULES:
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    return label
            except re.error:
                continue
    # ---------------------------------------------------------
    # Protect address-like text from standalone batch detection.
    #
    # Explicit address/manufacturer rules have already been
    # checked above, so genuine addresses can still be labelled
    # correctly.
    # ---------------------------------------------------------
    address_like = re.search(
        r"\b("
        r"plot|road|street|area|sector|block|lane|nagar|"
        r"district|dist|city|state|industrial|indl"
        r")\b",
        text,
        re.IGNORECASE,
    )

    if address_like:
        return "OTHER"
    # ---------------------------------------------------------
    # 6. Strong standalone batch-code detection
    #
    # Example:
    #   BR2E2584 → BATCH_NUMBER
    #
    # This comes AFTER explicit rules but remains available
    # for batch values that have no "BATCH NO." text.
    # ---------------------------------------------------------
    if confidence >= 0.80 and _looks_like_standalone_batch_code(text):
        return "BATCH_NUMBER"

    # ---------------------------------------------------------
    # 7. Generic product-name / cosmetic / packaging hints
    # ---------------------------------------------------------
    lower = text.lower()

    product_name_hints = [
        "honey",
        "almond",
        "lotion",
        "body lotion",
        "shampoo",
        "soap",
        "toothpaste",
        "moisturizer",
        "moisturiser",
        "face wash",
        "body wash",
        "conditioner",
        "cream",
        "oil",
    ]

    if confidence >= 0.80:
        for hint in product_name_hints:
            if hint in lower:
                return "PRODUCT_NAME"

    # ---------------------------------------------------------
    # 8. Fallback
    # ---------------------------------------------------------
    if confidence >= 0.75:
        return "OTHER"

    return "UNKNOWN"


def _refine_nutrition_table(items):
    by_image = {}

    for it in items:
        by_image.setdefault(
            it["image_id"],
            [],
        ).append(it)

    for image_id, group in by_image.items():

        anchors = [
            it
            for it in group
            if it["label"] == "NUTRITION"
        ]

        if len(anchors) < 2:
            continue

        heights = [
            max(
                1,
                a["box"][3] - a["box"][1],
            )
            for a in anchors
        ]

        row_h = statistics.median(heights)

        pad_x = 3.0 * row_h
        pad_y = 1.5 * row_h

        min_x1 = (
            min(a["box"][0] for a in anchors)
            - pad_x
        )

        min_y1 = (
            min(a["box"][1] for a in anchors)
            - pad_y
        )

        max_x2 = (
            max(a["box"][2] for a in anchors)
            + pad_x
        )

        max_y2 = (
            max(a["box"][3] for a in anchors)
            + pad_y
        )

        for it in group:

            if it["label"] not in (
                "OTHER",
                "UNKNOWN",
                "NET_QUANTITY",
            ):
                continue

            x1, y1, x2, y2 = it["box"]

            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            if not (
                min_x1 <= cx <= max_x2
                and min_y1 <= cy <= max_y2
            ):
                continue

            text = it["text"].strip()

            if (
                VALUE_LIKE_RE.match(text)
                or re.search(
                    r"per\s*serv|per\s*100|"
                    r"%\s*rda|typical\s*value",
                    text,
                    re.I,
                )
            ):
                it["label"] = "NUTRITION"


def _refine_same_row_values(items):
    by_image = {}

    for it in items:
        by_image.setdefault(
            it["image_id"],
            [],
        ).append(it)

    anchor_labels = list(
        ROW_VALUE_PATTERNS.keys()
    )

    pointer_text_re = re.compile(
        r"see\s*(below|side|panel)|"
        r"printed\s*below|"
        r"mentioned\s*below|"
        r"^for\s+mrp\b",
        re.IGNORECASE,
    )

    for image_id, group in by_image.items():

        anchors = [
            it
            for it in group
            if it["label"] in anchor_labels
            and not (
                it["label"] == "MRP"
                and pointer_text_re.search(
                    it["text"]
                )
            )
        ]

        if not anchors:
            continue

        candidates = [
            it
            for it in group
            if it["label"] in (
                "OTHER",
                "UNKNOWN",
            )
        ]

        for cand in candidates:

            cx1, cy1, cx2, cy2 = cand["box"]
            cy_center = (cy1 + cy2) / 2

            best = None
            best_key = None

            for anchor in anchors:

                ax1, ay1, ax2, ay2 = anchor["box"]

                a_height = max(
                    1,
                    ay2 - ay1,
                )

                a_center_y = (
                    ay1 + ay2
                ) / 2

                y_dist = abs(
                    cy_center
                    - a_center_y
                )

                if y_dist > 0.6 * a_height:
                    continue

                gap = cx1 - ax2

                if gap < -5 or gap > 12 * a_height:
                    continue

                pattern = ROW_VALUE_PATTERNS[
                    anchor["label"]
                ]

                if not pattern.match(
                    cand["text"].strip()
                ):
                    continue

                key = (
                    y_dist,
                    gap,
                )

                if (
                    best_key is None
                    or key < best_key
                ):
                    best = anchor
                    best_key = key

            if best is not None:
                cand["label"] = best["label"]


def _refine_product_name(items):
    """
    Promote large, clean front-of-pack text to PRODUCT_NAME.

    Explicit packaging declarations such as:
        NET VOL
        WHEN PACKED
        MRP
        MFD
        EXP
        PRICE

    are deliberately excluded.
    """

    marketing_stopwords = {
        "we",
        "your",
        "you",
        "our",
        "appreciate",
        "feedback",
        "extraordinary",
        "symphony",
        "of",
        "the",
        "a",
        "an",
        "is",
        "are",
        "with",
        "for",
        "and",
        "enjoy",
        "taste",
        "delicious",
        "recipe",
        "recipes",
        "more",
        "at",
        "how",
        "to",
        "use",
        "store",
        "keep",
        "away",
        "from",
        "children",
        "read",
        "before",
        "opening",
        "each",
        "serving",
        "contains",

        # Packaging declarations.
        "lot",
        "batch",
        "batchno",
        "batchnumber",
        "net",
        "vol",
        "volume",
        "qty",
        "quantity",
        "when",
        "packed",
        "mfd",
        "mfg",
        "manufactured",
        "expiry",
        "exp",
        "mrp",
        "price",
        "taxes",
        "inclusive",
        "unit",
        "sale",
        "selling",
        "body",
        "made",
        "india",
        "by",
    }

    non_brand_tokens = {
        "fssai",
        "issai",
        "ssai",
        "other",
        "play",
        "recycle",
    }

    corporate_suffix_tokens = {
        "holdings",
        "holdingsp",
        "ltd",
        "limited",
        "pvt",
        "private",
        "industries",
        "enterprises",
        "company",
        "corp",
        "corporation",
    }

    plain_text_re = re.compile(
        r"^[A-Za-z' !?&-]+$"
    )

    by_image = {}

    for it in items:
        by_image.setdefault(
            it["image_id"],
            [],
        ).append(it)

    for image_id, group in by_image.items():

        candidates = []

        for it in group:

            if it["label"] not in (
                "OTHER",
                "UNKNOWN",
            ):
                continue

            text = it["text"].strip()

            if not (
                it["confidence"] >= 0.85
                and 2 <= len(text) <= 30
            ):
                continue

            if not plain_text_re.match(text):
                continue

            words = text.split()

            if len(words) > 4:
                continue

            lower_words = {
                w.lower().strip(
                    ".,:;!?-"
                )
                for w in words
            }

            if lower_words & marketing_stopwords:
                continue

            if lower_words & non_brand_tokens:
                continue

            if lower_words & corporate_suffix_tokens:
                continue

            if text[0].islower():
                continue

            candidates.append(it)

        if not candidates:
            continue

        candidates.sort(
            key=lambda it: (
                it["box"][3]
                - it["box"][1]
            ),
            reverse=True,
        )

        top_height = (
            candidates[0]["box"][3]
            - candidates[0]["box"][1]
        )

        for it in candidates:

            h = (
                it["box"][3]
                - it["box"][1]
            )

            if h >= 0.65 * top_height:
                it["label"] = "PRODUCT_NAME"


def label_lines(lines):
    """
    Classify OCR lines.

    Mutates and returns the supplied list for compatibility
    with the existing Django pipeline.
    """

    for it in lines:
        it["label"] = _classify(
            it["text"],
            it["confidence"],
        )

    _refine_nutrition_table(lines)
    _refine_same_row_values(lines)
    _refine_product_name(lines)

    return lines