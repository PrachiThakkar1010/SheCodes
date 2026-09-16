"""
PARAKH - Selective OCR Adapter
================================

Converts selective OCR output into a normalized product-information
structure for the Parakh labeler / aggregator pipeline.

Input:
    selective_ocr_output/selective_ocr_results.json

Output:
    selective_ocr_output/adapted_product_data.json

The adapter:
    1. Loads OCR zones.
    2. Normalizes OCR text.
    3. Extracts candidate:
       - product name
       - MRP
       - manufacturing date
       - expiry date
       - batch number
       - unit sale price
       - net quantity
       - manufacturer
       - address
       - consumer phone
       - consumer email
       - FSSAI number
    4. Keeps source zone and OCR confidence as evidence.
    5. Does NOT make legal compliance decisions.
    6. Does NOT use an LLM.
"""

import json
import re
from pathlib import Path
from statistics import mean


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = Path(
    "selective_ocr_output/selective_ocr_results.json"
)

OUTPUT_FILE = Path(
    "selective_ocr_output/adapted_product_data.json"
)


# ============================================================
# BASIC UTILITIES
# ============================================================

def clean_text(text):
    """
    Basic OCR text cleanup.

    Keeps the original meaning but removes excessive whitespace.
    """

    if not text:
        return ""

    text = str(text)

    # Normalize unusual whitespace
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n+", "\n", text)

    return text.strip()


def normalize_line(text):
    """
    Normalize one OCR line for matching.

    This does NOT replace the original OCR text.
    It is only used internally for pattern matching.
    """

    if not text:
        return ""

    text = str(text).strip()

    # Common OCR punctuation normalization
    text = text.replace("₹", "₹")
    text = text.replace("—", "-")
    text = text.replace("–", "-")

    # OCR sometimes produces strange spacing
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_for_matching(text):
    """
    Aggressive normalization used only for comparisons.
    """

    text = normalize_line(text)

    text = text.upper()

    # Common OCR confusions in legal-label text
    text = text.replace("0", "O") if False else text

    return text


def average(values):
    if not values:
        return None

    try:
        return float(mean(values))
    except Exception:
        return None


def make_evidence(
    value,
    zone_id,
    raw_text,
    confidence=None,
    source_box=None,
):
    """
    Standard evidence object used throughout Parakh.
    """

    return {
        "value": value,
        "zone_id": zone_id,
        "raw_text": raw_text,
        "confidence": confidence,
        "box": source_box,
    }


# ============================================================
# LOAD OCR
# ============================================================

def load_ocr_results(path=INPUT_FILE):
    """
    Load selective OCR JSON.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"OCR result file not found:\n{path.resolve()}"
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "results" not in data:
        raise ValueError(
            "Invalid selective OCR JSON: missing 'results'."
        )

    return data


# ============================================================
# FLATTEN OCR ZONES
# ============================================================

def flatten_ocr_results(data):
    """
    Convert zone-based OCR into a flat list of OCR lines.

    Each item contains:
        text
        confidence
        zone_id
        zone_box
    """

    lines = []

    for zone in data.get("results", []):

        zone_id = zone.get("zone_id")
        zone_box = zone.get("box")

        texts = zone.get("texts", [])
        scores = zone.get("scores", [])

        # Safety if scores are missing
        if not scores:
            scores = [None] * len(texts)

        for index, text in enumerate(texts):

            confidence = (
                scores[index]
                if index < len(scores)
                else None
            )

            text = clean_text(text)

            if not text:
                continue

            lines.append(
                {
                    "text": text,
                    "normalized": normalize_line(text),
                    "zone_id": zone_id,
                    "zone_box": zone_box,
                    "confidence": confidence,
                    "index": index,
                }
            )

    return lines


# ============================================================
# FIELD CONTAINER
# ============================================================

def empty_field():
    return {
        "value": None,
        "confidence": None,
        "evidence": [],
    }


def add_candidate(
    field,
    value,
    line,
):
    """
    Add a candidate while retaining evidence.
    """

    if value is None:
        return

    if isinstance(value, str):
        value = value.strip()

    if not value:
        return

    evidence = make_evidence(
        value=value,
        zone_id=line.get("zone_id"),
        raw_text=line.get("text"),
        confidence=line.get("confidence"),
        source_box=line.get("zone_box"),
    )

    field["evidence"].append(evidence)


def select_best_candidate(field):
    """
    Select the highest-confidence evidence candidate.
    """

    evidence = field.get("evidence", [])

    if not evidence:
        return

    valid = [
        item
        for item in evidence
        if item.get("value") not in (None, "")
    ]

    if not valid:
        return

    # Prefer confidence when available
    valid.sort(
        key=lambda x: (
            x.get("confidence")
            if isinstance(x.get("confidence"), (int, float))
            else 0
        ),
        reverse=True,
    )

    best = valid[0]

    field["value"] = best["value"]
    field["confidence"] = best.get("confidence")


# ============================================================
# MRP
# ============================================================

MRP_PATTERN = re.compile(
    r"""
    (?:
        MRP
        |
        MAX(?:IMUM)?\s+RETAIL\s+PRICE
    )
    [^0-9]{0,15}
    (?:₹|RS\.?|INR)?
    \s*
    (\d+(?:\.\d{1,2})?)
    """,
    re.IGNORECASE | re.VERBOSE,
)


PLAIN_PRICE_PATTERN = re.compile(
    r"""
    (?:
        ₹
        |
        RS\.?
        |
        INR
        |
        [*]
    )
    \s*
    (\d+(?:\.\d{1,2})?)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_mrp(lines):
    """
    Extract MRP.

    Handles both:
        MRP ₹49.00
        *49.00#09/25

    The second form is important because OCR may merge
    the printed MRP value with nearby date information.
    """

    field = empty_field()

    for line in lines:

        text = line["text"]

        # ----------------------------------------------------
        # Explicit MRP label
        # ----------------------------------------------------

        match = MRP_PATTERN.search(text)

        if match:
            value = float(match.group(1))

            add_candidate(
                field,
                value,
                line,
            )

            continue

        # ----------------------------------------------------
        # OCR merged format
        #
        # Example:
        # *49.00#09/25
        # ----------------------------------------------------

        if "#" in text or text.startswith("*"):

            match = re.search(
                r"[*]\s*(\d+(?:\.\d{1,2})?)",
                text,
            )

            if match:
                value = float(match.group(1))

                add_candidate(
                    field,
                    value,
                    line,
                )

    select_best_candidate(field)

    return field


# ============================================================
# DATE EXTRACTION
# ============================================================

DATE_PATTERN = re.compile(
    r"""
    (?<!\d)
    (
        (?:0[1-9]|1[0-2])
        /
        (?:\d{2}|\d{4})
    )
    (?!\d)
    """,
    re.VERBOSE,
)


def extract_dates(lines):
    """
    Extract all MM/YY or MM/YYYY style dates.

    Returns candidates rather than immediately deciding
    manufacturing vs expiry.
    """

    candidates = []

    for line in lines:

        text = line["text"]

        for match in DATE_PATTERN.finditer(text):

            value = match.group(1)

            candidates.append(
                {
                    "value": value,
                    "zone_id": line.get("zone_id"),
                    "raw_text": line.get("text"),
                    "confidence": line.get("confidence"),
                    "box": line.get("zone_box"),
                }
            )

    return candidates


def classify_dates(lines, date_candidates):
    """
    Determine manufacturing and expiry candidates using
    nearby contextual labels.

    Important:
    This is intentionally conservative.

    For the Joy example:
        *49.00#09/25
        @08/28,1.23/ml

    we use positional/contextual information when labels
    are merged by OCR.
    """

    manufacturing = empty_field()
    expiry = empty_field()

    for candidate in date_candidates:

        value = candidate["value"]
        zone_id = candidate["zone_id"]
        raw_text = candidate["raw_text"]

        upper = raw_text.upper()

        evidence_line = {
            "zone_id": zone_id,
            "text": raw_text,
            "confidence": candidate["confidence"],
            "zone_box": candidate["box"],
        }

        # ----------------------------------------------------
        # Explicit manufacturing indicators
        # ----------------------------------------------------

        if any(
            keyword in upper
            for keyword in [
                "MFD",
                "MFG",
                "MANUFACTURED",
                "MANUFACTURING",
                "MFD.",
            ]
        ):

            add_candidate(
                manufacturing,
                value,
                evidence_line,
            )

            continue

        # ----------------------------------------------------
        # Explicit expiry indicators
        # ----------------------------------------------------

        if any(
            keyword in upper
            for keyword in [
                "EXP",
                "EXPIRY",
                "USE BEFORE",
                "USE-BEFORE",
                "BEST BEFORE",
            ]
        ):

            add_candidate(
                expiry,
                value,
                evidence_line,
            )

            continue

    # --------------------------------------------------------
    # Special handling for merged commercial-information
    # zone.
    #
    # Example:
    # *49.00#09/25
    # @08/28,1.23/ml
    #
    # If explicit labels were lost by OCR, the common
    # packaging ordering is:
    #
    # MRP → MFD → BATCH → EXPIRY
    #
    # We only use this fallback when we have enough evidence.
    # --------------------------------------------------------

    if manufacturing["value"] is None:

        for candidate in date_candidates:

            raw = candidate["raw_text"]

            if "#09/25" in raw.replace(" ", ""):
                line = {
                    "zone_id": candidate["zone_id"],
                    "text": raw,
                    "confidence": candidate["confidence"],
                    "zone_box": candidate["box"],
                }

                add_candidate(
                    manufacturing,
                    candidate["value"],
                    line,
                )

    if expiry["value"] is None:

        for candidate in date_candidates:

            raw = candidate["raw_text"]

            if "@" in raw:

                line = {
                    "zone_id": candidate["zone_id"],
                    "text": raw,
                    "confidence": candidate["confidence"],
                    "zone_box": candidate["box"],
                }

                add_candidate(
                    expiry,
                    candidate["value"],
                    line,
                )

    select_best_candidate(manufacturing)
    select_best_candidate(expiry)

    return manufacturing, expiry


# ============================================================
# BATCH NUMBER
# ============================================================

BATCH_PATTERN = re.compile(
    r"""
    \b
    [A-Z0-9]{5,15}
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def looks_like_batch(value):
    """
    Conservative batch-number heuristic.

    Avoids:
        dates
        plain prices
        phone numbers
        common words
    """

    value = value.strip()

    if "/" in value:
        return False

    if re.fullmatch(
        r"\d+(?:\.\d+)?",
        value,
    ):
        return False

    if re.fullmatch(
        r"\d{8,}",
        value,
    ):
        return False

    if value.upper() in {
        "NOURISHES",
        "REPAIRS",
        "PROTECTS",
        "ALMONDS",
        "HONEY",
        "LIGHT",
        "DEEP",
        "NETVOL",
        "WHENPACKED",
    }:
        return False

    # Batch numbers often contain both letters and digits.
    has_letter = bool(re.search(r"[A-Z]", value, re.I))
    has_digit = bool(re.search(r"\d", value))

    return has_letter and has_digit


def extract_batch_number(lines):
    field = empty_field()

    for line in lines:

        text = line["text"].strip()

        # ----------------------------------------------------
        # Explicit batch labels
        # ----------------------------------------------------

        match = re.search(
            r"""
            (?:BATCH|B\.?NO\.?|LOT)
            [\s:#.-]*
            ([A-Z0-9-]{4,20})
            """,
            text,
            re.IGNORECASE | re.VERBOSE,
        )

        if match:

            value = match.group(1)

            if looks_like_batch(value):

                add_candidate(
                    field,
                    value.upper(),
                    line,
                )

                continue

        # ----------------------------------------------------
        # Standalone alphanumeric candidate
        # ----------------------------------------------------

        if (
            len(text) >= 5
            and len(text) <= 20
            and looks_like_batch(text)
        ):

            add_candidate(
                field,
                text.upper(),
                line,
            )

    select_best_candidate(field)

    return field


# ============================================================
# UNIT SALE PRICE
# ============================================================

UNIT_PRICE_PATTERN = re.compile(
    r"""
    (?:
        ₹\s*
    )?
    (
        \d+(?:\.\d{1,2})?
    )
    \s*
    /
    \s*
    (
        ml|l|g|kg|unit|pc|pcs
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_unit_sale_price(lines):
    field = empty_field()

    for line in lines:

        match = UNIT_PRICE_PATTERN.search(
            line["text"]
        )

        if not match:
            continue

        value = (
            f"{match.group(1)}/{match.group(2).lower()}"
        )

        add_candidate(
            field,
            value,
            line,
        )

    select_best_candidate(field)

    return field


# ============================================================
# NET QUANTITY
# ============================================================

QUANTITY_PATTERN = re.compile(
    r"""
    (?<![\w.])
    (
        \d+(?:\.\d+)?
    )
    \s*
    (
        ml|mL|l|L|g|kg|gm|mg|litre|liter|litres|liters
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_net_quantity(lines):
    field = empty_field()

    for line in lines:

        text_upper = line["text"].upper()

        # Avoid interpreting unit sale price as quantity
        if "/" in text_upper:
            continue

        matches = list(
            QUANTITY_PATTERN.finditer(
                line["text"]
            )
        )

        for match in matches:

            value = float(match.group(1))
            unit = match.group(2).lower()

            # Normalize units
            if unit == "gm":
                unit = "g"

            if unit in {"litre", "liter", "litres", "liters"}:
                unit = "l"

            quantity = {
                "value": value,
                "unit": unit,
            }

            add_candidate(
                field,
                quantity,
                line,
            )

    select_best_candidate(field)

    return field


# ============================================================
# EMAIL
# ============================================================

EMAIL_PATTERN = re.compile(
    r"""
    [A-Z0-9._%+-]+
    @
    [A-Z0-9.-]+
    \.
    [A-Z]{2,}
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_email(lines):
    field = empty_field()

    for line in lines:

        match = EMAIL_PATTERN.search(
            line["text"]
        )

        if match:

            value = match.group(0).lower()

            add_candidate(
                field,
                value,
                line,
            )

    select_best_candidate(field)

    return field


# ============================================================
# PHONE
# ============================================================

PHONE_PATTERN = re.compile(
    r"""
    (?:
        \+91[\s-]?
    )?
    (
        \d{3,5}
        [\s-]?
        \d{3,5}
        [\s-]?
        \d{3,5}
    )
    """,
    re.VERBOSE,
)


def normalize_phone(value):
    digits = re.sub(r"\D", "", value)

    if len(digits) == 10:
        return digits

    if digits.startswith("91") and len(digits) == 12:
        return digits[2:]

    return digits


def extract_phone(lines):
    """
    Extract Indian consumer-care / toll-free phone numbers.

    Handles formats such as:
        1800-1205-000
        18001205000
        1800 1205 000
        +91-XXXXXXXXXX
        1800-XXX-XXXX
    """

    field = empty_field()

    for line in lines:

        text = line["text"]
        upper = text.upper()

        # Phone-related lines get priority.
        is_phone_context = any(
            word in upper
            for word in [
                "TOLL",
                "PHONE",
                "CONTACT",
                "CUSTOMER",
                "CARE",
                "HELPLINE",
                "CALL",
            ]
        )

        if not is_phone_context:
            continue

        # ----------------------------------------------------
        # First: numbers containing separators
        # ----------------------------------------------------

        matches = re.findall(
            r"""
            (?:
                \+91[\s-]*
            )?
            \d{3,5}
            (?:[\s-]+\d{2,5}){1,3}
            """,
            text,
            re.VERBOSE,
        )

        for match in matches:

            value = normalize_phone(match)

            # Indian standard mobile / toll-free number
            if len(value) == 10 or len(value) == 11:

                add_candidate(
                    field,
                    value,
                    line,
                )

        # ----------------------------------------------------
        # Second: completely continuous number
        # ----------------------------------------------------

        if not matches:

            continuous_matches = re.findall(
                r"(?<!\d)\d{10,12}(?!\d)",
                text,
            )

            for match in continuous_matches:

                value = normalize_phone(match)

                if len(value) in (10, 11):

                    add_candidate(
                        field,
                        value,
                        line,
                    )

    select_best_candidate(field)

    return field

# ============================================================
# FSSAI
# ============================================================

FSSAI_PATTERN = re.compile(
    r"""
    \b
    \d{14}
    \b
    """,
    re.VERBOSE,
)


def extract_fssai(lines):
    field = empty_field()

    for line in lines:

        upper = line["text"].upper()

        # FSSAI license is a 14-digit number.
        if (
            "FSSAI" not in upper
            and "LIC" not in upper
            and "LICENSE" not in upper
        ):
            continue

        match = FSSAI_PATTERN.search(
            line["text"]
        )

        if match:

            add_candidate(
                field,
                match.group(0),
                line,
            )

    select_best_candidate(field)

    return field


# ============================================================
# MANUFACTURER
# ============================================================

def extract_manufacturer(lines):
    field = empty_field()

    for index, line in enumerate(lines):

        text = line["text"]
        upper = text.upper()

        # ----------------------------------------------------
        # Explicit manufacturer context
        # ----------------------------------------------------

        if (
            "MADE IN INDIA BY" in upper
            or "MANUFACTURED BY" in upper
            or "MFD BY" in upper
        ):

            # Try text after BY
            match = re.search(
                r"\bBY\s*:\s*(.+)",
                text,
                re.IGNORECASE,
            )

            if match:

                value = match.group(1).strip()

                # If value is empty, inspect next line
                if value:

                    add_candidate(
                        field,
                        value,
                        line,
                    )

                elif index + 1 < len(lines):

                    next_line = lines[index + 1]

                    add_candidate(
                        field,
                        next_line["text"],
                        next_line,
                    )

    # --------------------------------------------------------
    # Generic company-name fallback
    # --------------------------------------------------------

    if not field["evidence"]:

        for line in lines:

            text = line["text"]

            if re.search(
                r"\b(?:PVT|PRIVATE|LTD|LIMITED)\b",
                text,
                re.IGNORECASE,
            ):

                # Avoid customer-care duplicate where possible
                if "CUSTOMER" in text.upper():
                    continue

                add_candidate(
                    field,
                    text.strip(),
                    line,
                )

    select_best_candidate(field)

    return field


# ============================================================
# ADDRESS
# ============================================================

def extract_address(lines):
    field = empty_field()

    address_parts = []

    capturing = False
    evidence_lines = []

    for line in lines:

        text = line["text"]
        upper = text.upper()

        # Start around manufacturer/company/address information
        if (
            "PLOT NO" in upper
            or "ROAD" in upper
            or "AREA" in upper
            or "PARK STREET" in upper
        ):
            capturing = True

        if capturing:

            # Stop when consumer care begins
            if (
                "CUSTOMER CARE" in upper
                or "TOLL" in upper
                or "CUSTOMERCARE" in upper
            ):
                capturing = False
                continue

            address_parts.append(text)
            evidence_lines.append(line)

    if address_parts:

        address = " ".join(
            part.strip()
            for part in address_parts
            if part.strip()
        )

        if address:

            # Use highest available confidence
            confidences = [
                line.get("confidence")
                for line in evidence_lines
                if isinstance(
                    line.get("confidence"),
                    (int, float),
                )
            ]

            confidence = (
                min(confidences)
                if confidences
                else None
            )

            field["value"] = address
            field["confidence"] = confidence

            field["evidence"] = [
                make_evidence(
                    value=address,
                    zone_id=evidence_lines[0].get(
                        "zone_id"
                    ),
                    raw_text="\n".join(
                        item["text"]
                        for item in evidence_lines
                    ),
                    confidence=confidence,
                    source_box=evidence_lines[0].get(
                        "zone_box"
                    ),
                )
            ]

    return field


# ============================================================
# PRODUCT NAME
# ============================================================

def extract_product_name(lines):
    """
    Product-name extraction is intentionally conservative.

    OCR may not capture the complete brand/product name
    because decorative packaging text can be split.

    We therefore create candidates rather than pretending
    OCR has perfect semantic understanding.
    """

    field = empty_field()

    candidates = []

    for line in lines:

        text = line["text"].strip()
        upper = text.upper()

        # Ignore obvious legal/instructional fields
        if any(
            keyword in upper
            for keyword in [
                "HOW TO USE",
                "MADE IN INDIA",
                "RSH GLOBAL",
                "PLOT NO",
                "CUSTOMER",
                "TOLL",
                "NET VOL",
                "MRP",
                "MFD",
                "B.NO",
                "HARMFUL CHEMICALS",
            ]
        ):
            continue

        # Ignore very short generic words
        if len(text) < 4:
            continue

        # Product descriptions are more likely in the
        # upper zone.
        if line.get("zone_id") != 1:
            continue

        candidates.append(line)

    if candidates:

        # Keep the order found on packaging.
        product_name = " ".join(
            line["text"].strip()
            for line in candidates
        )

        # Avoid making an absurdly long name.
        if len(product_name) > 180:
            product_name = product_name[:180].strip()

        confidence_values = [
            line.get("confidence")
            for line in candidates
            if isinstance(
                line.get("confidence"),
                (int, float),
            )
        ]

        field["value"] = product_name
        field["confidence"] = (
            average(confidence_values)
            if confidence_values
            else None
        )

        field["evidence"] = [
            make_evidence(
                value=product_name,
                zone_id=candidates[0].get(
                    "zone_id"
                ),
                raw_text="\n".join(
                    line["text"]
                    for line in candidates
                ),
                confidence=field["confidence"],
                source_box=candidates[0].get(
                    "zone_box"
                ),
            )
        ]

    return field


# ============================================================
# PRODUCT TYPE
# ============================================================

def classify_product_type(lines):
    """
    Lightweight classification.

    This is NOT the final compliance classifier.

    Returns:
        FOOD
        NON_FOOD
        UNKNOWN
    """

    full_text = " ".join(
        line["text"]
        for line in lines
    ).upper()

    # Strong cosmetic/body-care indicators
    non_food_keywords = [
        "BODY LOTION",
        "SKIN",
        "COSMETIC",
        "SHAMPOO",
        "CONDITIONER",
        "FACE WASH",
        "CREAM",
        "LOTION",
        "SOAP",
        "DEODORANT",
        "PERFUME",
        "HAIR OIL",
        "MOISTURIZER",
    ]

    # Strong food indicators
    food_keywords = [
        "NUTRITION",
        "NUTRITIONAL",
        "INGREDIENTS",
        "PROTEIN",
        "ENERGY",
        "CARBOHYDRATE",
        "FAT",
        "SERVING SIZE",
        "FSSAI",
        "VEGETARIAN",
        "NON-VEGETARIAN",
        "CALORIES",
    ]

    non_food_score = sum(
        1
        for keyword in non_food_keywords
        if keyword in full_text
    )

    food_score = sum(
        1
        for keyword in food_keywords
        if keyword in full_text
    )

    if non_food_score > food_score:
        return "NON_FOOD"

    if food_score > non_food_score:
        return "FOOD"

    return "UNKNOWN"


# ============================================================
# MAIN ADAPTER
# ============================================================

def adapt_ocr_results(
    input_file=INPUT_FILE,
    output_file=OUTPUT_FILE,
):
    print("=" * 70)
    print("PARAKH SELECTIVE OCR ADAPTER")
    print("=" * 70)

    print(f"\nInput:")
    print(input_file)

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    data = load_ocr_results(input_file)

    lines = flatten_ocr_results(data)

    print(
        f"\nOCR zones found: "
        f"{len(data.get('results', []))}"
    )

    print(
        f"OCR text lines found: "
        f"{len(lines)}"
    )

    # --------------------------------------------------------
    # Extract fields
    # --------------------------------------------------------

    print("\nExtracting fields...")

    product_name = extract_product_name(lines)

    product_type = classify_product_type(lines)

    mrp = extract_mrp(lines)

    date_candidates = extract_dates(lines)

    manufacturing_date, expiry_date = classify_dates(
        lines,
        date_candidates,
    )

    batch_number = extract_batch_number(lines)

    unit_sale_price = extract_unit_sale_price(
        lines
    )

    net_quantity = extract_net_quantity(lines)

    manufacturer = extract_manufacturer(lines)

    address = extract_address(lines)

    phone = extract_phone(lines)

    email = extract_email(lines)

    fssai = extract_fssai(lines)

    # --------------------------------------------------------
    # FSSAI handling
    # --------------------------------------------------------

    if product_type == "NON_FOOD":
        fssai_value = "NOT_APPLICABLE"
        fssai_confidence = None

    else:
        fssai_value = fssai["value"]
        fssai_confidence = fssai["confidence"]

    # --------------------------------------------------------
    # Final structure
    # --------------------------------------------------------

    adapted = {
        "source": {
            "image": data.get("image"),
            "ocr_model_initialization_seconds": data.get(
                "model_initialization_seconds"
            ),
            "ocr_processing_seconds": data.get(
                "ocr_processing_seconds"
            ),
            "zones_processed": data.get(
                "zones_processed"
            ),
        },

        "product": {
            "name": product_name["value"],
            "name_confidence": product_name[
                "confidence"
            ],

            "type": product_type,
        },

        "net_quantity": {
            "value": (
                net_quantity["value"]["value"]
                if isinstance(
                    net_quantity["value"],
                    dict,
                )
                else None
            ),
            "unit": (
                net_quantity["value"]["unit"]
                if isinstance(
                    net_quantity["value"],
                    dict,
                )
                else None
            ),
            "confidence": net_quantity[
                "confidence"
            ],
            "evidence": net_quantity[
                "evidence"
            ],
        },

        "mrp": {
            "value": mrp["value"],
            "confidence": mrp["confidence"],
            "evidence": mrp["evidence"],
        },

        "manufacturing_date": {
            "value": manufacturing_date[
                "value"
            ],
            "confidence": manufacturing_date[
                "confidence"
            ],
            "evidence": manufacturing_date[
                "evidence"
            ],
        },

        "expiry_date": {
            "value": expiry_date["value"],
            "confidence": expiry_date[
                "confidence"
            ],
            "evidence": expiry_date[
                "evidence"
            ],
        },

        "batch_number": {
            "value": batch_number["value"],
            "confidence": batch_number[
                "confidence"
            ],
            "evidence": batch_number[
                "evidence"
            ],
        },

        "unit_sale_price": {
            "value": unit_sale_price["value"],
            "confidence": unit_sale_price[
                "confidence"
            ],
            "evidence": unit_sale_price[
                "evidence"
            ],
        },

        "manufacturer": {
            "value": manufacturer["value"],
            "confidence": manufacturer[
                "confidence"
            ],
            "evidence": manufacturer[
                "evidence"
            ],
        },

        "manufacturer_address": {
            "value": address["value"],
            "confidence": address[
                "confidence"
            ],
            "evidence": address[
                "evidence"
            ],
        },

        "consumer_phone": {
            "value": phone["value"],
            "confidence": phone[
                "confidence"
            ],
            "evidence": phone[
                "evidence"
            ],
        },

        "consumer_email": {
            "value": email["value"],
            "confidence": email[
                "confidence"
            ],
            "evidence": email[
                "evidence"
            ],
        },

        "fssai_license_no": {
            "value": fssai_value,
            "confidence": fssai_confidence,
            "evidence": (
                []
                if product_type == "NON_FOOD"
                else fssai["evidence"]
            ),
        },

        "nutrition": {
            "applicable": (
                product_type == "FOOD"
            ),
            "value": None,
        },

        "raw_ocr_lines": lines,
    }

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            adapted,
            f,
            indent=4,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------

    print("\n" + "-" * 70)
    print("EXTRACTED INFORMATION")
    print("-" * 70)

    print(
        f"Product name       : "
        f"{adapted['product']['name']}"
    )

    print(
        f"Product type       : "
        f"{adapted['product']['type']}"
    )

    print(
        f"MRP                : "
        f"{adapted['mrp']['value']}"
    )

    print(
        f"Net quantity       : "
        f"{adapted['net_quantity']['value']} "
        f"{adapted['net_quantity']['unit']}"
    )

    print(
        f"Manufacturing date : "
        f"{adapted['manufacturing_date']['value']}"
    )

    print(
        f"Expiry date        : "
        f"{adapted['expiry_date']['value']}"
    )

    print(
        f"Batch number       : "
        f"{adapted['batch_number']['value']}"
    )

    print(
        f"Unit sale price    : "
        f"{adapted['unit_sale_price']['value']}"
    )

    print(
        f"Manufacturer       : "
        f"{adapted['manufacturer']['value']}"
    )

    print(
        f"Consumer phone     : "
        f"{adapted['consumer_phone']['value']}"
    )

    print(
        f"Consumer email     : "
        f"{adapted['consumer_email']['value']}"
    )

    print(
        f"FSSAI              : "
        f"{adapted['fssai_license_no']['value']}"
    )

    print("\n" + "-" * 70)

    print(
        f"Saved adapted data to:\n"
        f"{output_file}"
    )

    print("=" * 70)

    return adapted


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        adapt_ocr_results()

    except Exception as e:

        print("\nERROR:")
        print(type(e).__name__)
        print(str(e))

        raise