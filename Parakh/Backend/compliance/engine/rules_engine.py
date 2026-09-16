"""
compliance/engine/rules_engine.py
---------------------------------

Runs the project's Legal Metrology packaged-commodity checks against the
structured dictionary produced by aggregator.py.

Important engineering rule:

An OCR "missing" result is NOT automatically the same thing as a legal
violation.

The engine therefore:
- keeps the existing `passed` field for compatibility
- emits `review_required` where photograph/OCR evidence is insufficient
- does not treat missing OCR evidence as automatic legal non-compliance
- uses product type from product_data whenever available
- does not apply FSSAI checks to non-food products
- keeps MRP font-size checking disabled for the prototype

"""

import re


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Legacy fallback only.
# A legally meaningful physical font-size check requires calibrated image
# scale / physical reference information.
DPI_ASSUMED = 300

# User requested that MRP numeral-size checking be disabled for now.
ENABLE_MRP_SIZE_RULE = False


# ---------------------------------------------------------------------------
# RULE 7 MRP NUMERAL HEIGHT TABLES
# ---------------------------------------------------------------------------

MRP_HEIGHT_TABLE_WEIGHT_VOLUME = [
    (50, 1.0),
    (100, 1.5),
    (500, 2.5),
    (2500, 4.0),
    (float("inf"), 6.0),
]

MRP_HEIGHT_TABLE_NUMBER = [
    (100, 1.0),
    (500, 2.0),
    (2500, 4.0),
    (float("inf"), 6.0),
]


# ---------------------------------------------------------------------------
# REGEX / CONSTANTS
# ---------------------------------------------------------------------------

APPROX_RE = re.compile(
    r"\bapprox(?:\.|\s|$)|\babout\b|\bnearly\b",
    re.IGNORECASE,
)

STANDARD_UNITS = {
    "kg",
    "g",
    "mg",
    "l",
    "ml",
    "n",
    "nos",
    "no",
}


DATE_PATTERNS = [
    r"^\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}$",
    r"^\d{1,2}\s?[A-Za-z]{3,4}\s?\d{2,4}$",
]


# Tax-inclusion wording can be OCR'd with several punctuation variations.
MRP_TAX_PATTERNS = [
    r"\bincl\.?\s*of\s*all\s*taxes\b",
    r"\binclusive\s+of\s+all\s+taxes\b",
    r"\bincluding\s+all\s+taxes\b",
    r"\bincl\.?\s*all\s*taxes\b",
    r"\bincl\.?\s*taxes\b",
]


FOOD_HINTS = (
    "food",
    "snack",
    "biscuit",
    "wafer",
    "namkeen",
    "chips",
    "noodles",
    "ingredients",
    "ingredient",
    "nutrition",
    "calories",
    "protein",
    "carbohydrate",
    "serving size",
    "energy",
    "sodium",
    "sugars",
)


NON_FOOD_HINTS = (
    "mosquito coil",
    "household insecticide",
    "insecticide",
    "transfluthrin",
    "pesticide",
    "repellent",
    "detergent",
    "disinfectant",
    "cleaner",
    "shampoo",
    "soap",
    "toothpaste",
    "body lotion",
    "lotion",
    "cosmetic",
    "battery",
    "stationery",
    "electronics",
)


LEGIBILITY_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# OCR HELPERS
# ---------------------------------------------------------------------------

def _all_ocr_text(product_data):
    """
    Return all OCR text from the scan as one normalized string.
    """

    lines = product_data.get("ocr_lines", []) or []

    return " ".join(
        str(line.get("text") or "").strip()
        for line in lines
        if str(line.get("text") or "").strip()
    )


def _normalize_ocr_text(text):
    """
    Normalize common OCR punctuation/spacing differences.

    Example:
        "INCL. OF ALL TAXES"
        "INCL OF ALL TAXES"
        "INCL.OF ALL TAXES"

    all become easier to match.
    """

    text = str(text or "").upper()

    # Normalize common punctuation to spaces.
    text = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", text)
    text = text.replace("₹", " RS ")

    # Normalize dots around abbreviations.
    text = re.sub(r"\bINCL\s*\.\s*", "INCL ", text)
    text = re.sub(r"\bINC\s*\.\s*", "INC ", text)

    # Collapse repeated whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ---------------------------------------------------------------------------
# PRODUCT TYPE
# ---------------------------------------------------------------------------

def _infer_product_type(product_data):
    """
    Determine whether the package is FOOD, NON_FOOD, or UNKNOWN.

    Explicit product_data classification always wins.
    """

    explicit = str(
        product_data.get("product_type") or ""
    ).strip().upper()

    if explicit in {"FOOD", "NON_FOOD"}:
        return explicit

    text = _all_ocr_text(product_data).lower()

    # Strong non-food cues win over generic words.
    non_food_hits = sum(
        1 for cue in NON_FOOD_HINTS
        if cue in text
    )

    food_hits = sum(
        1 for cue in FOOD_HINTS
        if cue in text
    )

    if non_food_hits and non_food_hits >= food_hits:
        return "NON_FOOD"

    if food_hits:
        return "FOOD"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# FONT SIZE
# ---------------------------------------------------------------------------

def _font_size_mm(box, dpi=None):
    """
    Estimate text height in mm from an OCR bounding box.

    NOTE:
    This is only meaningful if the image DPI/scale is actually calibrated.
    """

    if not box or len(box) < 4:
        return None

    try:
        height_px = float(box[3]) - float(box[1])

        if height_px <= 0:
            return None

        dpi = float(dpi or DPI_ASSUMED)

        return round(
            (height_px / dpi) * 25.4,
            2,
        )

    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# DATE
# ---------------------------------------------------------------------------

def _looks_like_date(text):
    """
    Check whether a value looks like a date.
    """

    text = str(text or "").strip()

    return any(
        re.fullmatch(pattern, text)
        for pattern in DATE_PATTERNS
    )


# ---------------------------------------------------------------------------
# CONTACT
# ---------------------------------------------------------------------------

def _looks_like_contact(text):
    """
    Detect a phone number or email address.
    """

    if not text:
        return False

    text = str(text)

    digits = re.sub(r"\D", "", text)

    if 7 <= len(digits) <= 15:
        return True

    return bool(
        re.search(
            r"[\w.+-]+@[\w-]+\.[a-z]{2,}",
            text,
            re.IGNORECASE,
        )
    )


# ---------------------------------------------------------------------------
# NET QUANTITY
# ---------------------------------------------------------------------------

def _get_net_quantity_kind(product_data):
    """
    Return:
        "number"
        "weight_volume"
        None

    Rule 7 uses different minimum numeral-height tables depending on
    declaration type.
    """

    qty = product_data.get("net_quantity") or {}

    unit = str(
        qty.get("unit") or ""
    ).strip().lower()

    if unit in {
        "n",
        "nos",
        "no",
        "number",
        "numbers",
    }:
        return "number"

    if unit in {
        "kg",
        "g",
        "mg",
        "l",
        "ml",
    }:
        return "weight_volume"

    return None


# ---------------------------------------------------------------------------
# MRP HEIGHT
# ---------------------------------------------------------------------------

def _required_mrp_height_mm(product_data):
    """
    Calculate the Rule 7 MRP numeral-height threshold when the caller
    supplies principal_display_panel_area_cm2.

    Without package area and calibrated scale, the threshold cannot be
    determined defensibly from a photograph alone.
    """

    area = product_data.get(
        "principal_display_panel_area_cm2"
    )

    if area is None:
        return None

    try:
        area = float(area)

    except (TypeError, ValueError):
        return None

    if area <= 0:
        return None

    kind = _get_net_quantity_kind(product_data)

    if kind == "number":
        table = MRP_HEIGHT_TABLE_NUMBER

    elif kind == "weight_volume":
        table = MRP_HEIGHT_TABLE_WEIGHT_VOLUME

    else:
        return None

    for upper, minimum in table:
        if area <= upper:
            return minimum

    return None


# ---------------------------------------------------------------------------
# MRP TAX-INCLUSION DETECTION
# ---------------------------------------------------------------------------

def _scan_contains_tax_inclusion(product_data):
    """
    Search the ENTIRE OCR output for tax-inclusion wording.

    If the wording is found anywhere in the package OCR, it is considered
    sufficient evidence for LM-007.
    """

    text = _all_ocr_text(product_data)

    if not text:
        return False

    # Normalize OCR punctuation and whitespace.
    text = text.upper()
    text = re.sub(r"\s+", " ", text)

    # Check every OCR line as well as the combined text.
    for line in product_data.get("ocr_lines", []) or []:
        line_text = str(line.get("text") or "").upper()
        line_text = re.sub(r"\s+", " ", line_text).strip()

        for pattern in MRP_TAX_PATTERNS:
            if re.search(pattern, line_text, re.IGNORECASE):
                return True

    # Finally check the complete OCR scan.
    for pattern in MRP_TAX_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


# ---------------------------------------------------------------------------
# RESULT HELPER
# ---------------------------------------------------------------------------

def _add_result(
    results,
    code,
    passed,
    details,
    review_required=False,
):
    """
    Preserve the original result structure while explicitly recording
    whether human review is required.
    """

    results.append({
        "rule_code": code,
        "passed": bool(passed),
        "details": details,
        "review_required": bool(review_required),
    })


# ---------------------------------------------------------------------------
# MAIN RULE ENGINE
# ---------------------------------------------------------------------------

def run_rules(
    product_data,
    ocr_confidence_avg=None,
    is_likely_food=None,
):
    """
    Run Legal Metrology checks.

    Parameters
    ----------
    product_data:
        Dictionary returned by aggregator.aggregate_lines().

    ocr_confidence_avg:
        Mean OCR confidence. Used only as an engineering legibility proxy.

    is_likely_food:
        Backward-compatible food override.

        If None:
            product_data["product_type"] is used.

        Otherwise:
            the supplied boolean is used.

    Returns
    -------
    list
        Each item contains:

            rule_code
            passed
            details
            review_required
    """

    product_data = product_data or {}

    results = []

    # -----------------------------------------------------------------------
    # PRODUCT TYPE
    # -----------------------------------------------------------------------

    product_type = _infer_product_type(product_data)

    if is_likely_food is None:
        food_applicable = product_type == "FOOD"

    else:
        food_applicable = bool(is_likely_food)


    # -----------------------------------------------------------------------
    # LM-001: MANUFACTURER NAME
    # -----------------------------------------------------------------------

    mfr = product_data.get("manufacturer")

    if (
        mfr
        and mfr.get("raw_text")
    ):
        _add_result(
            results,
            "LM-001",
            True,
            (
                f'Manufacturer name detected: '
                f'"{mfr["raw_text"]}".'
            ),
        )

    else:
        _add_result(
            results,
            "LM-001",
            False,
            "No manufacturer/packer name was detected on the package.",
        )


    # -----------------------------------------------------------------------
    # LM-002: MANUFACTURER ADDRESS
    # -----------------------------------------------------------------------

    addr = product_data.get(
        "manufacturer_address"
    )

    if (
        addr
        and addr.get("raw_text")
    ):
        _add_result(
            results,
            "LM-002",
            True,
            (
                f'Manufacturer/packer address detected: '
                f'"{addr["raw_text"]}".'
            ),
        )

    else:
        brand_note = ""

        pname = product_data.get(
            "product_name"
        )

        if (
            pname
            and pname.get("raw_text")
        ):
            brand_note = (
                " Only a brand name/product name was detected."
            )

        _add_result(
            results,
            "LM-002",
            False,
            (
                "The package does not display the complete name and "
                "address of the manufacturer or packer."
                f"{brand_note}"
            ),
        )


    # -----------------------------------------------------------------------
    # LM-003: PRODUCT IDENTITY
    # -----------------------------------------------------------------------

    pname = product_data.get(
        "product_name"
    )

    if (
        pname
        and pname.get("raw_text")
    ):
        _add_result(
            results,
            "LM-003",
            True,
            (
                f'Product identity detected: '
                f'"{pname["raw_text"]}".'
            ),
        )

    else:
        _add_result(
            results,
            "LM-003",
            False,
            "No common/generic product name was detected on the package.",
        )


    # -----------------------------------------------------------------------
    # LM-004: NET QUANTITY
    # -----------------------------------------------------------------------

    qty = product_data.get(
        "net_quantity"
    )

    if (
        not qty
        or qty.get("value") is None
    ):
        _add_result(
            results,
            "LM-004",
            False,
            (
                "No valid net quantity declaration "
                "(value + standard unit) was detected."
            ),
            review_required=True,
        )

    elif APPROX_RE.search(
        qty.get("raw_text") or ""
    ):
        _add_result(
            results,
            "LM-004",
            False,
            (
                f'Net quantity is declared as '
                f'"{qty["raw_text"]}" - an approximate value '
                "is not permitted; the exact net quantity in "
                "a standard unit must be stated."
            ),
        )

    elif str(
        qty.get("unit") or ""
    ).lower() not in STANDARD_UNITS:
        _add_result(
            results,
            "LM-004",
            False,
            (
                f'Net quantity "{qty.get("raw_text")}" does not '
                "use a recognized standard unit."
            ),
        )

    else:
        _add_result(
            results,
            "LM-004",
            True,
            (
                f'Net quantity detected: '
                f'{qty["value"]} {qty["unit"]}.'
            ),
        )


    # -----------------------------------------------------------------------
    # LM-005: MANUFACTURING / PACKING DATE
    # -----------------------------------------------------------------------

    mdate = product_data.get(
        "manufacturing_date"
    )

    if (
        mdate
        and mdate.get("raw_text")
    ):
        _add_result(
            results,
            "LM-005",
            True,
            (
                f'Manufacturing/packing date detected: '
                f'"{mdate["raw_text"]}".'
            ),
        )

    else:
        _add_result(
            results,
            "LM-005",
            False,
            "No month/year of manufacture or packing was detected.",
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-006: MRP
    # -----------------------------------------------------------------------

    mrp = product_data.get(
        "mrp"
    )

    if (
        mrp
        and mrp.get("value") is not None
        and mrp["value"] > 0
    ):
        _add_result(
            results,
            "LM-006",
            True,
            (
                f'MRP detected: '
                f'Rs. {mrp["value"]:.2f}.'
            ),
        )

    else:
        _add_result(
            results,
            "LM-006",
            False,
            "No valid Maximum Retail Price declaration was detected.",
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-007: MRP TAX INCLUSION
    # -----------------------------------------------------------------------
    #
    # IMPORTANT:
    #
    # We search the WHOLE OCR scan.
    #
    # Example:
    #
    #   OCR line 1 -> "MRP ₹10"
    #   OCR line 2 -> "INCL. OF ALL TAXES"
    #
    # The two declarations may be separate OCR boxes.
    #
    # Also:
    #
    # Missing wording from OCR is NOT treated as definite legal
    # non-compliance.
    #
    # It becomes review_required=True.
    #
    # -----------------------------------------------------------------------

    if (
        not mrp
        or mrp.get("value") is None
        or mrp.get("value") <= 0
    ):
        _add_result(
            results,
            "LM-007",
            False,
            (
                "MRP is missing or invalid, so tax inclusion "
                "could not be verified."
            ),
            review_required=True,
        )

    elif _scan_contains_tax_inclusion(
        product_data
    ):
        _add_result(
            results,
            "LM-007",
            True,
            "Tax-inclusion wording was detected somewhere on the package.",
        )

    else:
        _add_result(
            results,
            "LM-007",
            False,
            (
                "MRP was detected, but explicit tax-inclusion wording "
                "was not found by OCR. Manual verification is required; "
                "OCR absence of this phrase is not, by itself, proof "
                "of non-compliance."
            ),
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-008: CONSUMER CONTACT
    # -----------------------------------------------------------------------

    contact = product_data.get(
        "consumer_contact"
    )

    if (
        contact
        and _looks_like_contact(
            contact.get("raw_text")
        )
    ):
        _add_result(
            results,
            "LM-008",
            True,
            (
                "Consumer complaint/customer-care contact detected: "
                f'"{contact["raw_text"]}".'
            ),
        )

    else:
        _add_result(
            results,
            "LM-008",
            False,
            (
                "No consumer complaint/customer-care contact "
                "(phone or email) was detected."
            ),
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-009: MRP NUMERAL HEIGHT
    # -----------------------------------------------------------------------
    #
    # DISABLED FOR PROTOTYPE.
    #
    # Set ENABLE_MRP_SIZE_RULE = True only after calibrated physical
    # measurement is implemented.
    #
    # -----------------------------------------------------------------------

    if ENABLE_MRP_SIZE_RULE:

        if (
            not mrp
            or not mrp.get("box")
        ):
            _add_result(
                results,
                "LM-009",
                False,
                (
                    "MRP numeral height could not be measured because "
                    "no MRP measurement box was located."
                ),
                review_required=True,
            )

        else:
            area = product_data.get(
                "principal_display_panel_area_cm2"
            )

            required_mm = _required_mrp_height_mm(
                product_data
            )

            dpi = (
                product_data.get("ocr_dpi")
                or product_data.get("dpi")
            )

            size_mm = _font_size_mm(
                mrp.get("measurement_box")
                or mrp.get("box"),
                dpi=dpi,
            )

            if (
                area is None
                or required_mm is None
                or dpi is None
            ):
                _add_result(
                    results,
                    "LM-009",
                    False,
                    (
                        "MRP numeral was located, but a legally "
                        "defensible font-size decision requires "
                        "principal display panel area and calibrated "
                        "image scale."
                    ),
                    review_required=True,
                )

            elif size_mm is None:
                _add_result(
                    results,
                    "LM-009",
                    False,
                    (
                        "MRP numeral box was found, but its physical "
                        "height could not be calculated from the "
                        "available image calibration."
                    ),
                    review_required=True,
                )

            elif size_mm >= required_mm:
                _add_result(
                    results,
                    "LM-009",
                    True,
                    (
                        f"MRP numeral height is approximately "
                        f"{size_mm} mm; the calculated Rule 7 "
                        f"minimum is {required_mm} mm."
                    ),
                )

            else:
                _add_result(
                    results,
                    "LM-009",
                    False,
                    (
                        f"MRP numeral height is approximately "
                        f"{size_mm} mm, below the calculated Rule 7 "
                        f"minimum of {required_mm} mm."
                    ),
                )


    # -----------------------------------------------------------------------
    # LM-010: FSSAI LICENCE
    # -----------------------------------------------------------------------

    if not food_applicable:

        _add_result(
            results,
            "LM-010",
            True,
            (
                "FSSAI licence check not applicable because the "
                f"package is classified as "
                f"{product_type or 'NON_FOOD/UNKNOWN'}."
            ),
        )

    else:

        fssai = product_data.get(
            "fssai_license"
        )

        if (
            fssai
            and re.search(
                r"\d{5,14}",
                fssai.get("raw_text") or "",
            )
        ):
            _add_result(
                results,
                "LM-010",
                True,
                (
                    f'FSSAI licence number detected: '
                    f'"{fssai["raw_text"]}".'
                ),
            )

        else:
            _add_result(
                results,
                "LM-010",
                False,
                "No FSSAI licence number was detected on the package.",
                review_required=True,
            )


    # -----------------------------------------------------------------------
    # LM-011: BATCH / LOT NUMBER
    # -----------------------------------------------------------------------

    batch = product_data.get(
        "batch_number"
    )

    if (
        batch
        and batch.get("raw_text")
    ):
        _add_result(
            results,
            "LM-011",
            True,
            (
                f'Batch/lot number detected: '
                f'"{batch["raw_text"]}".'
            ),
        )

    else:
        _add_result(
            results,
            "LM-011",
            False,
            "No batch or lot number was detected on the package.",
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-012: OCR LEGIBILITY PROXY
    # -----------------------------------------------------------------------

    if (
        ocr_confidence_avg is not None
        and ocr_confidence_avg >= LEGIBILITY_THRESHOLD
    ):
        _add_result(
            results,
            "LM-012",
            True,
            (
                f"OCR evidence "
                f"(avg. confidence {ocr_confidence_avg:.0%}) "
                "indicates that much of the declaration text "
                "was legible."
            ),
        )

    else:

        conf_str = (
            f"{ocr_confidence_avg:.0%}"
            if ocr_confidence_avg is not None
            else "unavailable"
        )

        _add_result(
            results,
            "LM-012",
            False,
            (
                f"OCR confidence ({conf_str}) is below the engineering "
                "legibility threshold used by this automated check - "
                "the photo may be blurry, low-resolution, or text may "
                "be too small/low-contrast."
            ),
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # LM-013: DECLARATION LANGUAGE
    # -----------------------------------------------------------------------

    all_text = _all_ocr_text(
        product_data
    )

    has_english = bool(
        re.search(
            r"[A-Za-z]",
            all_text,
        )
    )

    has_hindi = bool(
        re.search(
            r"[\u0900-\u097F]",
            all_text,
        )
    )

    if has_english or has_hindi:

        _add_result(
            results,
            "LM-013",
            True,
            (
                "Declaration text in English or Hindi "
                "(Devanagari) was detected."
            ),
        )

    else:

        _add_result(
            results,
            "LM-013",
            False,
            (
                "No declaration text in English or Hindi "
                "was detected."
            ),
            review_required=True,
        )


    # -----------------------------------------------------------------------
    # RETURN
    # -----------------------------------------------------------------------

    return results