"""
compliance/engine/aggregator.py
-------------------------------

Turns labeled OCR lines into structured product data.

Important:

This layer does NOT decide legal compliance.

It only extracts structured information from OCR output.
"""

import re


# ---------------------------------------------------------------------------
# LABEL → FIELD
# ---------------------------------------------------------------------------

LABEL_TO_FIELD = {
    "PRODUCT_NAME": "product_name",
    "MANUFACTURER_NAME": "manufacturer",
    "MANUFACTURER_ADDRESS": "manufacturer_address",
    "NET_QUANTITY": "net_quantity",
    "MANUFACTURING_DATE": "manufacturing_date",
    "EXPIRY_DATE": "expiry_date",
    "BATCH_NUMBER": "batch_number",
    "MRP": "mrp",
    "UNIT_SALE_PRICE": "unit_sale_price",
    "FSSAI_LICENSE_NO": "fssai_license",
    "CONSUMER_CONTACT": "consumer_contact",
    "NUTRITION": "nutrition",
}


# ---------------------------------------------------------------------------
# REGEX
# ---------------------------------------------------------------------------

QTY_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(kgs?|g|gm|gms|mg|l|ltrs?|litres?|ml|"
    r"n|nos\.?|pcs\.?|pieces?|units?)\b",
    re.IGNORECASE,
)


# Supports:
#
#   01/08/2026
#   28-01-2027
#   01.AUG.2026
#   28/JAN/2027
#   09/25
#
DATE_RE = re.compile(
    r"\b"
    r"(?:"
        # DD/MM/YYYY
        r"(?:0[1-9]|[12]\d|3[01])"
        r"[/\-.]"
        r"(?:0[1-9]|1[0-2])"
        r"[/\-.]"
        r"(?:\d{2}|\d{4})"

        r"|"

        # DD/MON/YYYY
        r"(?:0[1-9]|[12]\d|3[01])"
        r"[/\-. ]"
        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"[/\-. ]"
        r"(?:\d{2}|\d{4})"

        r"|"

        # MM/YY or MM/YYYY
        r"(?:0[1-9]|1[0-2])"
        r"[/\-.]"
        r"(?:\d{2}|\d{4})"
    ")"
    r"\b",
    re.IGNORECASE,
)


UNIT_SALE_PRICE_RE = re.compile(
    r"(?:₹|Rs\.?)?\s*"
    r"(\d+(?:[.,]\d+)?)"
    r"\s*(?:/|per\s+)"
    r"(kg|g|l|ml|unit|piece|pc|pcs|no\.?)",
    re.IGNORECASE,
)


UNIT_MAP = {
    "kg": "kg",
    "kgs": "kg",
    "g": "g",
    "gm": "g",
    "gms": "g",
    "mg": "mg",
    "l": "l",
    "ltr": "l",
    "ltrs": "l",
    "litre": "l",
    "litres": "l",
    "ml": "ml",

    # Count-based declarations.
    "n": "n",
    "nos": "n",
    "nos.": "n",
    "pcs": "n",
    "pcs.": "n",
    "piece": "n",
    "pieces": "n",
    "unit": "n",
    "units": "n",
}


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------

def _reading_order_key(item):
    box = item.get("box") or [0, 0, 0, 0]

    return (
        item.get("image_id", ""),
        box[1],
        box[0],
    )


def _group_by_label(items):
    grouped = {}

    for item in items:
        grouped.setdefault(
            item["label"],
            [],
        ).append(item)

    for label in grouped:
        grouped[label].sort(
            key=_reading_order_key
        )

    return grouped


def _combine_text(items):
    return " | ".join(
        item["text"].strip()
        for item in items
        if item.get("text", "").strip()
    )


def _first_box(items):
    return (
        items[0]["box"]
        if items
        else None
    )


# ---------------------------------------------------------------------------
# NEAREST VALUE SEARCH
# ---------------------------------------------------------------------------

def _nearest_raw_value(
    all_items,
    keyword_res,
    value_re,
):
    """
    Find a value close to a keyword.

    Supports:

        keyword + value on same row

    and:

        keyword
        value

    on consecutive/nearby lines.
    """

    best = None
    best_score = None

    for anchor in all_items:

        text = str(
            anchor.get("text") or ""
        ).upper()

        if not any(
            re.search(
                keyword,
                text,
                re.IGNORECASE,
            )
            for keyword in keyword_res
        ):
            continue

        ax1, ay1, ax2, ay2 = (
            anchor.get("box")
            or [0, 0, 0, 0]
        )

        a_height = max(
            1,
            ay2 - ay1,
        )

        a_center_y = (
            ay1 + ay2
        ) / 2

        for candidate in all_items:

            if candidate is anchor:
                continue

            if (
                candidate.get("image_id")
                != anchor.get("image_id")
            ):
                continue

            candidate_text = str(
                candidate.get("text") or ""
            )

            if not value_re.search(
                candidate_text
            ):
                continue

            cx1, cy1, cx2, cy2 = (
                candidate.get("box")
                or [0, 0, 0, 0]
            )

            c_center_y = (
                cy1 + cy2
            ) / 2

            same_row = (
                abs(
                    c_center_y
                    - a_center_y
                )
                <= 0.7 * a_height
            )

            to_right = (
                cx1 >= ax2 - 5
            )

            below = (
                cy1 >= ay2 - 5
            )

            if not (
                (same_row and to_right)
                or below
            ):
                continue

            distance = (
                (
                    (cx1 - ax2) ** 2
                    + (cy1 - ay2) ** 2
                )
                ** 0.5
            )

            score = distance

            if (
                same_row
                and to_right
            ):
                score -= 200

            if (
                best_score is None
                or score < best_score
            ):
                best = candidate
                best_score = score

    return best


# ---------------------------------------------------------------------------
# NET QUANTITY
# ---------------------------------------------------------------------------

def _parse_net_quantity(
    items,
    all_items,
):
    combined = _combine_text(items)

    non_serving = [
        item
        for item in items
        if "serving"
        not in item["text"].lower()
    ]

    search_pool = (
        non_serving
        if non_serving
        else items
    )

    match = None
    matched_box = _first_box(items)

    for item in search_pool:

        match = QTY_RE.search(
            item["text"]
        )

        if match:
            matched_box = item["box"]
            break

    if match:

        value = float(
            match.group(1).replace(
                ",",
                ".",
            )
        )

        unit = UNIT_MAP.get(
            match.group(2).lower(),
            match.group(2).lower(),
        )

        return {
            "value": value,
            "unit": unit,
            "raw_text": combined,
            "box": matched_box,
        }

    # Raw OCR fallback.
    if all_items:

        candidate = _nearest_raw_value(
            all_items,
            [
                r"NET\s*(QTY|QUANTITY|WT|WEIGHT)",
                r"NET\s*WEIGHT",
            ],
            QTY_RE,
        )

        if candidate:

            match2 = QTY_RE.search(
                candidate["text"]
            )

            if match2:

                value = float(
                    match2.group(1).replace(
                        ",",
                        ".",
                    )
                )

                unit = UNIT_MAP.get(
                    match2.group(2).lower(),
                    match2.group(2).lower(),
                )

                return {
                    "value": value,
                    "unit": unit,
                    "raw_text": (
                        combined
                        + " | "
                        + candidate["text"]
                    ),
                    "box": candidate["box"],
                }

    return {
        "value": None,
        "unit": None,
        "raw_text": combined,
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# MRP
# ---------------------------------------------------------------------------

def _parse_mrp(
    items,
    all_items,
):
    combined = _combine_text(items)

    value = None
    value_box = None

    mrp_literal_re = re.compile(
        r"\bmrp\b|m\.r\.p",
        re.IGNORECASE,
    )

    price_num_re = re.compile(
        r"(?:₹|Rs\.?|MRP\s*[:₹]?)"
        r"\s*"
        r"(\d+(?:[.,]\d+)?)",
        re.IGNORECASE,
    )

    pointer_text_re = re.compile(
        r"see\s*(below|side|panel)"
        r"|printed\s*below"
        r"|mentioned\s*below"
        r"|^for\s+mrp\b",
        re.IGNORECASE,
    )

    # ---------------------------------------------------------------
    # Pass 1:
    # A single line containing MRP + number.
    # ---------------------------------------------------------------

    for item in items:

        text = item["text"]

        if (
            mrp_literal_re.search(text)
            and not pointer_text_re.search(text)
        ):

            match = (
                price_num_re.search(text)
                or re.search(
                    r"(\d+(?:[.,]\d+)?)",
                    text,
                )
            )

            if match:

                value = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                value_box = item["box"]

                break

    # ---------------------------------------------------------------
    # Pass 2:
    # Any explicit price in MRP group.
    # ---------------------------------------------------------------

    if value is None:

        for item in items:

            if pointer_text_re.search(
                item["text"]
            ):
                continue

            match = price_num_re.search(
                item["text"]
            )

            if match:

                value = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                value_box = item["box"]

                break

    # ---------------------------------------------------------------
    # Pass 3:
    # MRP keyword and bare number are separate OCR boxes.
    # ---------------------------------------------------------------

    if value is None:

        mrp_anchor = next(
            (
                item
                for item in items
                if (
                    mrp_literal_re.search(
                        item["text"]
                    )
                    and not pointer_text_re.search(
                        item["text"]
                    )
                )
            ),
            None,
        )

        if mrp_anchor:

            bare_number_re = re.compile(
                r"^[₹Rr\s.]*"
                r"\d+(?:[.,]\d+)?"
                r"\s*/?-?\s*$"
            )

            ax1, ay1, ax2, ay2 = (
                mrp_anchor["box"]
            )

            anchor_height = max(
                1,
                ay2 - ay1,
            )

            anchor_center_y = (
                ay1 + ay2
            ) / 2

            best_item = None
            best_distance = None

            for item in items:

                if item is mrp_anchor:
                    continue

                if not bare_number_re.match(
                    item["text"].strip()
                ):
                    continue

                cy1, cy2 = (
                    item["box"][1],
                    item["box"][3],
                )

                distance = abs(
                    ((cy1 + cy2) / 2)
                    - anchor_center_y
                )

                if (
                    distance
                    <= 3 * anchor_height
                    and (
                        best_distance is None
                        or distance
                        < best_distance
                    )
                ):
                    best_item = item
                    best_distance = distance

            if best_item:

                match = re.search(
                    r"(\d+(?:[.,]\d+)?)",
                    best_item["text"],
                )

                if match:

                    value = float(
                        match.group(1).replace(
                            ",",
                            ".",
                        )
                    )

                    value_box = best_item["box"]

    # ---------------------------------------------------------------
    # Pass 4:
    # Raw OCR fallback.
    # ---------------------------------------------------------------

    if value is None and all_items:

        search_items = [
            item
            for item in all_items
            if not pointer_text_re.search(
                item["text"]
            )
        ]

        candidate = _nearest_raw_value(
            search_items,
            [
                r"\bMRP\b",
                r"M\.R\.P",
            ],
            re.compile(
                r"^\s*[₹Rr]?"
                r"\.?\s*"
                r"\d+(?:[.,]\d+)?"
                r"\s*/?-?\s*$"
            ),
        )

        if candidate:

            match = re.search(
                r"(\d+(?:[.,]\d+)?)",
                candidate["text"],
            )

            if match:

                value = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                value_box = candidate["box"]

                combined = (
                    combined
                    + " | "
                    + candidate["text"]
                )

    return {
        "value": value,
        "raw_text": combined,
        "box": (
            value_box
            if value is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# UNIT SALE PRICE
# ---------------------------------------------------------------------------

def _parse_unit_sale_price(
    items,
    all_items,
):
    """
    Extract:

        1.23/ml
        ₹1.23/ml
        Rs. 1.23 per ml
        1.23 per ml
    """

    combined = _combine_text(items)

    # First search the labeled group.
    for item in items:

        text = str(
            item.get("text") or ""
        ).strip()

        match = UNIT_SALE_PRICE_RE.search(
            text
        )

        if match:

            return {
                "value": float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                ),
                "unit": match.group(2)
                .lower()
                .rstrip("."),
                "raw_text": text,
                "box": item.get("box"),
            }

    # Raw OCR fallback.
    if all_items:

        for item in all_items:

            text = str(
                item.get("text") or ""
            ).strip()

            if not re.search(
                r"unit\s*(?:sale|selling)\s*price",
                text,
                re.IGNORECASE,
            ):
                continue

            match = UNIT_SALE_PRICE_RE.search(
                text
            )

            if match:

                return {
                    "value": float(
                        match.group(1).replace(
                            ",",
                            ".",
                        )
                    ),
                    "unit": match.group(2)
                    .lower()
                    .rstrip("."),
                    "raw_text": text,
                    "box": item.get("box"),
                }

    return {
        "value": None,
        "unit": None,
        "raw_text": combined,
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# DATE
# ---------------------------------------------------------------------------

def _parse_date(
    items,
    all_items,
    keyword_res,
):
    """
    Extract a date while preferring the actual declaration.

    Manufacturing:

        PKD
        MFD
        MFG
        PACKED ON

    Expiry:

        EXP
        EXPIRY
        USE BY
        BEST BEFORE
    """

    combined = _combine_text(items)

    # ---------------------------------------------------------------
    # First: exact date in labeled item.
    # Prefer lines that contain the relevant keyword.
    # ---------------------------------------------------------------

    keyword_items = []

    for item in items:

        text = str(
            item.get("text") or ""
        )

        if any(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
            for pattern in keyword_res
        ):
            keyword_items.append(item)

    for item in keyword_items:

        match = DATE_RE.search(
            item["text"]
        )

        if match:

            return {
                "raw_text": item["text"].strip(),
                "box": item["box"],
            }

    # ---------------------------------------------------------------
    # Second: date in any labeled item.
    # ---------------------------------------------------------------

    for item in items:

        match = DATE_RE.search(
            item["text"]
        )

        if match:

            return {
                "raw_text": item["text"].strip(),
                "box": item["box"],
            }

    # ---------------------------------------------------------------
    # Third: raw OCR fallback near keyword.
    # ---------------------------------------------------------------

    if all_items:

        candidate = _nearest_raw_value(
            all_items,
            keyword_res,
            DATE_RE,
        )

        if candidate:

            match = DATE_RE.search(
                candidate["text"]
            )

            if match:

                # Return only the actual declaration/value,
                # rather than the entire explanatory paragraph.
                keyword_match = re.search(
                    r"(PKD|MFD|MFG|EXP|EXPIRY|"
                    r"USE\s*BY|BEST\s*BEFORE)",
                    candidate["text"],
                    re.IGNORECASE,
                )

                if keyword_match:

                    return {
                        "raw_text": (
                            keyword_match.group(1)
                            + " "
                            + match.group(0)
                        ),
                        "box": candidate["box"],
                    }

                return {
                    "raw_text": match.group(0),
                    "box": candidate["box"],
                }

    return {
        "raw_text": combined,
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# PRODUCT NAME
# ---------------------------------------------------------------------------

def _parse_product_name(items):
    """
    For multiple images, use the image that has the strongest/tallest
    product-name candidate instead of joining product-name fragments from
    every image.
    """

    if not items:
        return {
            "raw_text": None,
            "box": None,
        }

    by_image = {}

    for item in items:

        by_image.setdefault(
            item["image_id"],
            [],
        ).append(item)

    best_image_id = max(
        by_image,
        key=lambda image_id: max(
            (
                item["box"][3]
                - item["box"][1]
            )
            for item in by_image[image_id]
            if item.get("box")
        ),
    )

    best_items = sorted(
        by_image[best_image_id],
        key=_reading_order_key,
    )

    text = " ".join(
        item["text"].strip()
        for item in best_items
        if item.get("text", "").strip()
    )

    return {
        "raw_text": text,
        "box": best_items[0]["box"],
    }


# ---------------------------------------------------------------------------
# CONSUMER CONTACT
# ---------------------------------------------------------------------------

def _parse_consumer_contact(
    items,
    all_items,
):
    combined = _combine_text(items)

    has_digits_or_email = re.search(
        r"\d{7,}|@",
        combined,
    )

    if (
        has_digits_or_email
        or not all_items
    ):
        return {
            "raw_text": combined,
            "box": _first_box(items),
        }

    candidate = _nearest_raw_value(
        all_items,
        [
            r"CONSUMER\s*CARE",
            r"CUSTOMER\s*CARE",
            r"CALL\s*US",
            r"WRITE\s*TO\s*US",
            r"HELPLINE",
        ],
        re.compile(
            r"^\+?[\d\-\s]{7,17}$"
            r"|"
            r"[\w.+-]+@[\w-]+\.[a-z]{2,}",
            re.IGNORECASE,
        ),
    )

    if candidate:

        return {
            "raw_text": (
                combined
                + " | "
                + candidate["text"]
            ),
            "box": candidate["box"],
        }

    return {
        "raw_text": combined,
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# BATCH
# ---------------------------------------------------------------------------

def _looks_like_batch_code(text):
    """
    Conservative standalone batch-code detector.

    Accepts examples such as:

        BBF2131
        BR2E2584
        310CT26
        ABC12345

    Rejects obvious:

        dates
        quantities
        phone numbers
        addresses
    """

    if not text:
        return False

    value = (
        str(text)
        .strip()
        .upper()
        .strip(" :;,.#*-")
    )

    if not value:
        return False

    if len(value) < 5 or len(value) > 20:
        return False

    # Batch codes should not contain spaces.
    if " " in value:
        return False

    # Must contain letters AND numbers.
    if not re.search(r"[A-Z]", value):
        return False

    if not re.search(r"\d", value):
        return False

    # Quantity.
    if re.fullmatch(
        r"\d+(?:[.,]\d+)?\s*"
        r"(?:MG|G|GM|GMS|KG|ML|L|"
        r"LITRE|LITRES|LITER|LITERS|"
        r"PCS?|PC|NO)",
        value,
        re.IGNORECASE,
    ):
        return False

    # Numeric date.
    if re.fullmatch(
        r"\d{1,2}[/\-.]\d{1,2}"
        r"(?:[/\-.]\d{2,4})?",
        value,
    ):
        return False

    # Month-name date.
    if re.fullmatch(
        r"\d{1,2}"
        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\d{2,4}",
        value,
        re.IGNORECASE,
    ):
        return False

    digits = re.sub(
        r"\D",
        "",
        value,
    )

    # Long numeric sequences are more likely phone/license/address data.
    if len(digits) >= 10:
        return False

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

    if any(
        word in value
        for word in bad_words
    ):
        return False

    return True


def _parse_batch_number(items):
    """
    Extract batch/lot number.

    The labeler is expected to have already identified the relevant lines.

    This function also recognizes a standalone alphanumeric batch code such
    as BBF2131 or BR2E2584 if the labeler classified it correctly.
    """

    combined = _combine_text(items)

    # ---------------------------------------------------------------
    # 1. Explicit BATCH / LOT / BN declaration.
    # ---------------------------------------------------------------

    explicit_pattern = re.compile(
        r"\b(?:BATCH|LOT|BN|B\.?N\.?)"
        r"\s*(?:NO\.?)?"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9./\-]{4,19})\b",
        re.IGNORECASE,
    )

    for item in items:

        text = str(
            item.get("text") or ""
        ).strip()

        match = explicit_pattern.search(
            text
        )

        if match:

            return {
                "raw_text": match.group(1),
                "box": item.get("box"),
            }

    # ---------------------------------------------------------------
    # 2. Standalone batch code.
    # ---------------------------------------------------------------

    for item in items:

        text = str(
            item.get("text") or ""
        ).strip()

        if _looks_like_batch_code(text):

            return {
                "raw_text": text,
                "box": item.get("box"),
            }

    return {
        "raw_text": combined,
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# GENERIC
# ---------------------------------------------------------------------------

def _parse_generic(items):
    return {
        "raw_text": _combine_text(items),
        "box": _first_box(items),
    }


# ---------------------------------------------------------------------------
# MAIN AGGREGATOR
# ---------------------------------------------------------------------------

def aggregate_lines(labeled_lines):
    """
    Convert labeler output into structured product data.

    MRP font-size compliance is NOT evaluated here.
    """

    grouped = _group_by_label(
        labeled_lines
    )

    data = {}

    for label, field in LABEL_TO_FIELD.items():

        group_items = grouped.get(
            label,
            [],
        )

        # -----------------------------------------------------------
        # NET QUANTITY
        # -----------------------------------------------------------

        if field == "net_quantity":

            data[field] = _parse_net_quantity(
                group_items,
                labeled_lines,
            )

        # -----------------------------------------------------------
        # MRP
        # -----------------------------------------------------------

        elif field == "mrp":

            data[field] = _parse_mrp(
                group_items,
                labeled_lines,
            )

        # -----------------------------------------------------------
        # UNIT SALE PRICE
        # -----------------------------------------------------------

        elif field == "unit_sale_price":

            data[field] = _parse_unit_sale_price(
                group_items,
                labeled_lines,
            )

        # -----------------------------------------------------------
        # MANUFACTURING DATE
        # -----------------------------------------------------------

        elif field == "manufacturing_date":

            data[field] = _parse_date(
                group_items,
                labeled_lines,
                [
                    r"\bPKD\b",
                    r"\bMFG\b",
                    r"\bMFD\b",
                    r"MANUFACTUR",
                    r"DATE\s*OF\s*MFG",
                    r"PACKED\s*ON",
                    r"PACKAGING\s*DATE",
                    r"PKG\s*DATE",
                    r"DATE\s*OF\s*PACK",
                ],
            )

        # -----------------------------------------------------------
        # EXPIRY DATE
        # -----------------------------------------------------------

        elif field == "expiry_date":

            data[field] = _parse_date(
                group_items,
                labeled_lines,
                [
                    r"\bEXP\b",
                    r"EXPIRY",
                    r"USE\s*BY",
                    r"BEST\s*BEFORE",
                ],
            )

        # -----------------------------------------------------------
        # BATCH
        # -----------------------------------------------------------

        elif field == "batch_number":

            data[field] = _parse_batch_number(
                group_items
            )

        # -----------------------------------------------------------
        # Empty field
        # -----------------------------------------------------------

        elif not group_items:

            data[field] = None

        # -----------------------------------------------------------
        # NUTRITION
        # -----------------------------------------------------------

        elif field == "nutrition":

            data[field] = [
                {
                    "text": item["text"],
                    "box": item["box"],
                }
                for item in group_items
            ]

        # -----------------------------------------------------------
        # PRODUCT NAME
        # -----------------------------------------------------------

        elif field == "product_name":

            data[field] = _parse_product_name(
                group_items
            )

        # -----------------------------------------------------------
        # CONSUMER CONTACT
        # -----------------------------------------------------------

        elif field == "consumer_contact":

            data[field] = _parse_consumer_contact(
                group_items,
                labeled_lines,
            )

        # -----------------------------------------------------------
        # GENERIC FIELD
        # -----------------------------------------------------------

        else:

            data[field] = _parse_generic(
                group_items
            )

    # ----------------------------------------------------------------
    # PRODUCT TYPE
    #
    # Keep the existing downstream behavior.
    # ----------------------------------------------------------------

    all_text = " ".join(
        str(item.get("text") or "")
        for item in labeled_lines
    )

    food_signal = bool(
        re.search(
            r"(?:in)?gredients?\b",
            all_text,
            re.IGNORECASE,
        )
    )

    nutrition_signal = bool(
        grouped.get("NUTRITION")
    )

    product_type = (
        "FOOD"
        if food_signal or nutrition_signal
        else "NON_FOOD"
    )

    data["product_type"] = product_type

    data["fssai_applicable"] = (
        product_type == "FOOD"
    )

    if not data["fssai_applicable"]:

        data["fssai_license"] = {
            "raw_text": None,
            "box": None,
            "status": "NOT_APPLICABLE",
        }

    # Keep all OCR lines for debugging/report JSON.
    data["ocr_lines"] = labeled_lines

    return data