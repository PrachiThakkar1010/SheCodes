"""
compliance/engine/pipeline.py
----------------------------

Single entry point used by products/views.py:

    run_scan(scan_instance)

Pipeline:

1. OCR every image attached to the scan.
2. Normalize/split compound OCR declarations.
3. Classify OCR lines using labeler.py.
4. Aggregate labeled lines into structured fields.
5. Check whether photo coverage is sufficient.
6. Parse nutrition/additives.
7. Run Legal Metrology rules.
8. Save all results to the database.
"""

from django.utils.dateparse import parse_date
import re

from ocr.services import extract_lines_for_scan
from compliance.engine.labeler import label_lines
from compliance.engine.aggregator import aggregate_lines
from compliance.engine.rules_engine import run_rules
from compliance.engine.nutrition import parse_nutrition
from compliance.engine.additives import detect_additives


# ---------------------------------------------------------------------------
# COVERAGE
# ---------------------------------------------------------------------------

CORE_FIELDS = [
    "product_name",
    "manufacturer",
    "manufacturer_address",
    "net_quantity",
    "mrp",
    "manufacturing_date",
    "consumer_contact",
    "fssai_license",
]

MIN_IMAGES_RECOMMENDED = 2
MIN_CORE_FIELDS_FOUND = 3


def check_coverage(scan_instance, product_data):
    """
    Returns:

        (True, None)

    when enough information was found.

    Otherwise:

        (False, explanation)
    """

    image_count = scan_instance.images.count() or 1

    found = sum(
        1
        for field in CORE_FIELDS
        if product_data.get(field)
        and (
            product_data[field].get("raw_text")
            if isinstance(product_data[field], dict)
            else product_data[field]
        )
    )

    if (
        image_count < MIN_IMAGES_RECOMMENDED
        and found < MIN_CORE_FIELDS_FOUND
    ):
        return False, (
            f"Only {image_count} photo was provided and only {found} of the "
            f"{len(CORE_FIELDS)} core declarations could be located. "
            "Packaged-commodity declarations are usually spread across "
            "multiple panels (front, back, and sometimes a side seal). "
            "Please upload photos covering the whole pack, including the "
            "back/ingredients panel, for an accurate compliance check."
        )

    if found < MIN_CORE_FIELDS_FOUND:

        missing_readable = [
            field.replace("_", " ")
            for field in CORE_FIELDS
            if not (
                product_data.get(field)
                and (
                    product_data[field].get("raw_text")
                    if isinstance(product_data[field], dict)
                    else product_data[field]
                )
            )
        ]

        return False, (
            f"Only {found} of the {len(CORE_FIELDS)} core declarations "
            f"could be located across {image_count} photo(s) "
            f"(missing: {', '.join(missing_readable[:5])}"
            f"{'...' if len(missing_readable) > 5 else ''}). "
            "Please add photos of any panels not yet covered "
            "(front, back, and ingredients/nutrition panel) before "
            "we report this as non-compliant."
        )

    return True, None


# ---------------------------------------------------------------------------
# DATE HELPER
# ---------------------------------------------------------------------------

def _try_parse_date(raw_text):
    """
    Convert a DD/MM/YYYY-style date into a Python date.

    Examples:

        01/08/2026
        28-01-2027
        01.08.2026

    Also understands month names:

        01/AUG/2026
        28/JAN/2027
    """

    if not raw_text:
        return None

    text = str(raw_text).strip().upper()

    # Numeric date
    m = re.search(
        r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b",
        text,
    )

    if m:
        day, month, year = m.groups()

        year = int(year)

        if year < 100:
            year += 2000

        try:
            return parse_date(
                f"{year:04d}-{int(month):02d}-{int(day):02d}"
            )
        except (ValueError, TypeError):
            return None

    # Date with month name
    m = re.search(
        r"\b(\d{1,2})[/\-. ]"
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"[/\-. ](\d{2,4})\b",
        text,
        re.IGNORECASE,
    )

    if m:
        day, month_name, year = m.groups()

        months = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }

        year = int(year)

        if year < 100:
            year += 2000

        try:
            return parse_date(
                f"{year:04d}-{months[month_name]:02d}-{int(day):02d}"
            )
        except (ValueError, TypeError):
            return None

    return None


# ---------------------------------------------------------------------------
# OCR NORMALIZATION
# ---------------------------------------------------------------------------

def _clone_line(line, text):
    """
    Clone an OCR line while preserving:

        box
        confidence
        image_id
        width
        height
        any other metadata

    Only the text is changed.
    """

    new_line = dict(line)
    new_line["text"] = text
    return new_line


def _normalize_selective_ocr_lines(lines):
    """
    Split compound OCR declarations before they reach the labeler.

    This is important because PaddleOCR can correctly read the characters
    but return several legal declarations as ONE OCR line.

    Examples:

        *49.00#09/25

    becomes:

        MRP ₹49.00
        MFD 09/25

    And:

        @08/28,1.23/ml

    becomes:

        EXP 08/28
        UNIT SALE PRICE 1.23/ml

    Another real example:

        PKD:01/AUG/2026:EXP:28/JAN/2027

    becomes:

        PKD 01/AUG/2026
        EXP 28/JAN/2027

    And:

        MRP: E65:USP E 0.65/s: BN:BBF2131 L1 A3

    becomes:

        MRP ₹65
        UNIT SALE PRICE 0.65/g
        BATCH BBF2131

    The original OCR box is preserved because the information came from
    the same physical region.
    """

    normalized = []

    for line in lines:

        text = str(line.get("text") or "").strip()

        if not text:
            continue

        upper = text.upper()

        # ================================================================
        # CASE 1
        # MRP + MFD
        #
        # Examples:
        #   *49.00#09/25
        #   49.00 09/25
        #   MRP 49.00#09/25
        # ================================================================

        mrp_mfd = re.search(
            r"(?:\bMRP\s*[:\-]?\s*)?"
            r"(?:₹|RS\.?|E)?\s*"
            r"(\d+(?:[.,]\d+)?)"
            r"\s*"
            r"[*#@:\-]?\s*"
            r"(\d{1,2}/\d{2,4})\b",
            text,
            re.IGNORECASE,
        )

        if mrp_mfd:

            mrp_value = mrp_mfd.group(1)
            mfd_value = mrp_mfd.group(2)

            normalized.append(
                _clone_line(
                    line,
                    f"MRP ₹{mrp_value}",
                )
            )

            normalized.append(
                _clone_line(
                    line,
                    f"MFD {mfd_value}",
                )
            )

            continue

        # ================================================================
        # CASE 2
        # EXPIRY + UNIT SALE PRICE
        #
        # Examples:
        #   @08/28,1.23/ml
        #   08/28 1.23/ml
        # ================================================================

        expiry_unit = re.search(
            r"[@#*]?\s*"
            r"(\d{1,2}/\d{2,4})"
            r"\s*[,;:]?\s*"
            r"(?:₹|RS\.?)?\s*"
            r"(\d+(?:[.,]\d+)?)"
            r"\s*/\s*"
            r"(KG|G|L|ML|UNIT|PIECE|PC|PCS|NO\.?)",
            text,
            re.IGNORECASE,
        )

        if expiry_unit:

            expiry_value = expiry_unit.group(1)
            unit_price = expiry_unit.group(2)
            unit = expiry_unit.group(3)

            normalized.append(
                _clone_line(
                    line,
                    f"EXP {expiry_value}",
                )
            )

            normalized.append(
                _clone_line(
                    line,
                    f"UNIT SALE PRICE {unit_price}/{unit}",
                )
            )

            continue

        # ================================================================
        # CASE 3
        # PKD + EXP in the SAME OCR BOX
        #
        # Example:
        #
        # PKD:01/AUG/2026:EXP:28/JAN/2027
        # ================================================================

        pkd_exp = re.search(
            r"\bPKD\.?\s*[:\-]?\s*"
            r"(\d{1,2}[/\-.]"
            r"(?:\d{1,2}|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"[/\-.]\d{2,4})"
            r".*?"
            r"\bEXP(?:IRY)?\.?\s*[:\-]?\s*"
            r"(\d{1,2}[/\-.]"
            r"(?:\d{1,2}|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"[/\-.]\d{2,4})",
            upper,
            re.IGNORECASE,
        )

        if pkd_exp:

            pkd_value = pkd_exp.group(1)
            exp_value = pkd_exp.group(2)

            normalized.append(
                _clone_line(
                    line,
                    f"PKD {pkd_value}",
                )
            )

            normalized.append(
                _clone_line(
                    line,
                    f"EXP {exp_value}",
                )
            )

            continue

        # ================================================================
        # CASE 4
        # MRP + USP + BATCH
        #
        # Real OCR example:
        #
        # MRP: E65:USP E 0.65/s: BN:BBF2131 L1 A3
        #
        # OCR mistakes:
        #   E65  -> 65
        #   0.65/s -> 0.65/g
        #
        # The /s -> /g correction is deliberately restricted to this
        # specific USP context. We do NOT globally replace OCR letters.
        # ================================================================

        mrp_match = re.search(
            r"\bMRP\b\s*[:\-]?\s*"
            r"(?:₹|RS\.?|E)?\s*"
            r"(\d+(?:[.,]\d+)?)",
            upper,
            re.IGNORECASE,
        )

        usp_match = re.search(
            r"\bUSP\b\s*[:\-]?\s*"
            r"(?:₹|RS\.?|E)?\s*"
            r"(\d+(?:[.,]\d+)?)"
            r"\s*/\s*"
            r"(KG|G|L|ML|UNIT|PIECE|PC|PCS|NO\.?|S)\b",
            upper,
            re.IGNORECASE,
        )

        batch_match = re.search(
            r"\b(?:BN|B\.?N\.?|BATCH|LOT)\s*[:#\-]?\s*"
            r"([A-Z0-9][A-Z0-9./\-]{4,19})",
            upper,
            re.IGNORECASE,
        )

        if mrp_match or usp_match or batch_match:

            found_any = False

            if mrp_match:
                normalized.append(
                    _clone_line(
                        line,
                        f"MRP ₹{mrp_match.group(1)}",
                    )
                )
                found_any = True

            if usp_match:

                usp_value = usp_match.group(1)
                usp_unit = usp_match.group(2).lower()

                # Very narrow OCR-specific correction:
                #
                # In the observed Amul scan PaddleOCR returned:
                #
                #     0.65/s
                #
                # where the printed declaration is:
                #
                #     0.65/g
                #
                if usp_unit == "s":
                    usp_unit = "g"

                normalized.append(
                    _clone_line(
                        line,
                        f"UNIT SALE PRICE {usp_value}/{usp_unit}",
                    )
                )

                found_any = True

            if batch_match:

                batch_value = batch_match.group(1)

                normalized.append(
                    _clone_line(
                        line,
                        f"BATCH {batch_value}",
                    )
                )

                found_any = True

            if found_any:
                continue

        # ================================================================
        # CASE 5
        # Standalone BN:XXXX
        # ================================================================

        standalone_bn = re.search(
            r"\b(?:BN|B\.?N\.?)\s*[:#\-]?\s*"
            r"([A-Z0-9][A-Z0-9./\-]{4,19})\b",
            upper,
            re.IGNORECASE,
        )

        if standalone_bn:

            normalized.append(
                _clone_line(
                    line,
                    f"BATCH {standalone_bn.group(1)}",
                )
            )

            # Keep processing only the extracted declaration.
            continue

        # ================================================================
        # CASE 6
        # Otherwise preserve the original OCR line.
        # ================================================================

        normalized.append(line)

    return normalized


# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------

def run_scan(scan_instance):
    """
    Runs the complete OCR → normalization → labeler → aggregator →
    compliance pipeline for one ProductScan.
    """

    from products.models import ExtractedLabelData
    from compliance.models import (
        ComplianceRule,
        ComplianceReport,
        ComplianceViolation,
    )

    # ------------------------------------------------------------------
    # 1. START PROCESSING
    # ------------------------------------------------------------------

    scan_instance.status = "PROCESSING"
    scan_instance.save(update_fields=["status"])

    # ------------------------------------------------------------------
    # 2. OCR
    # ------------------------------------------------------------------

    lines = extract_lines_for_scan(scan_instance)

    if not lines:

        scan_instance.status = "FAILED"
        scan_instance.save(update_fields=["status"])

        return scan_instance

    print(
        f"[PIPELINE] Raw OCR lines: {len(lines)}"
    )

    # ------------------------------------------------------------------
    # 3. NORMALIZE COMPOUND OCR DECLARATIONS
    # ------------------------------------------------------------------

    lines = _normalize_selective_ocr_lines(lines)

    print(
        f"[PIPELINE] Normalized OCR lines: {len(lines)}"
    )

    # ------------------------------------------------------------------
    # 4. LABEL
    # ------------------------------------------------------------------

    labeled = label_lines(lines)

    # ------------------------------------------------------------------
    # 5. AGGREGATE
    # ------------------------------------------------------------------

    product_data = aggregate_lines(labeled)

    # ------------------------------------------------------------------
    # 6. OCR CONFIDENCE
    # ------------------------------------------------------------------

    confidences = [
        line["confidence"]
        for line in lines
        if line.get("text", "").strip()
        and line.get("confidence") is not None
    ]

    avg_conf = (
        sum(confidences) / len(confidences)
        if confidences
        else None
    )

    # ------------------------------------------------------------------
    # 7. COVERAGE
    # ------------------------------------------------------------------

    sufficient, coverage_message = check_coverage(
        scan_instance,
        product_data,
    )

    # ------------------------------------------------------------------
    # 8. ALL OCR TEXT
    # ------------------------------------------------------------------

    all_text = " ".join(
        str(line.get("text") or "")
        for line in lines
    )

    # ------------------------------------------------------------------
    # 9. ADDITIVES + NUTRITION
    # ------------------------------------------------------------------

    additives = detect_additives(all_text)

    nutrition_rows = parse_nutrition(
        product_data.get("nutrition") or []
    )

    # ------------------------------------------------------------------
    # 10. FOOD / NON-FOOD INFERENCE
    # ------------------------------------------------------------------

    has_ingredients_signal = bool(
        re.search(
            r"(?:in)?gredients?\b",
            all_text,
            re.IGNORECASE,
        )
    )

    has_nutrition_signal = bool(
        nutrition_rows
    ) or bool(
        product_data.get("nutrition")
    )

    is_likely_food = (
        has_ingredients_signal
        or has_nutrition_signal
    )

    # ------------------------------------------------------------------
    # 11. SAVE EXTRACTED DATA
    # ------------------------------------------------------------------

    def _rt(field):
        value = product_data.get(field)

        if isinstance(value, dict):
            return value.get("raw_text")

        return value

    label_data, _ = ExtractedLabelData.objects.update_or_create(
        scan=scan_instance,
        defaults={
            "raw_ocr_text": all_text,
            "labeled_lines_json": labeled,

            "product_name_declared": _rt("product_name"),

            "manufacturer_name": _rt("manufacturer"),

            "manufacturer_address": _rt(
                "manufacturer_address"
            ),

            "net_quantity_value": (
                product_data.get("net_quantity") or {}
            ).get("value"),

            "net_quantity_unit": (
                product_data.get("net_quantity") or {}
            ).get("unit"),

            "net_quantity_raw": _rt(
                "net_quantity"
            ),

            "mrp_value": (
                product_data.get("mrp") or {}
            ).get("value"),

            "mrp_raw": _rt("mrp"),

            "consumer_contact_raw": _rt(
                "consumer_contact"
            ),

            "nutritional_info": nutrition_rows,

            "additives_info": additives,

            "manufacturing_date_raw": _rt(
                "manufacturing_date"
            ),

            "manufacturing_date": _try_parse_date(
                _rt("manufacturing_date")
            ),

            "expiry_date_raw": _rt(
                "expiry_date"
            ),

            "expiry_date": _try_parse_date(
                _rt("expiry_date")
            ),

            "batch_number": _rt(
                "batch_number"
            ),

            "fssai_license_no": _rt(
                "fssai_license"
            ),
        },
    )

    # ------------------------------------------------------------------
    # 12. UPDATE PRODUCT NAME
    # ------------------------------------------------------------------

    if (
        product_data.get("product_name")
        and product_data["product_name"].get("raw_text")
    ):
        scan_instance.product_name = (
            product_data["product_name"]["raw_text"][:255]
        )

    # ------------------------------------------------------------------
    # 13. COVERAGE FAILURE
    # ------------------------------------------------------------------

    if not sufficient:

        scan_instance.status = "NEEDS_MORE_IMAGES"

        scan_instance.save(
            update_fields=[
                "status",
                "product_name",
            ]
        )

        ComplianceReport.objects.update_or_create(
            scan=scan_instance,
            defaults={
                "is_compliant": False,
                "overall_score": 0.0,
            },
        )

        return scan_instance

    # ------------------------------------------------------------------
    # 14. RUN LEGAL METROLOGY RULES
    # ------------------------------------------------------------------

    check_results = run_rules(
        product_data,
        ocr_confidence_avg=avg_conf,
        is_likely_food=is_likely_food,
    )

    failed = [
        result
        for result in check_results
        if not result["passed"]
    ]

    # ------------------------------------------------------------------
    # 15. LOAD SEEDED RULES
    # ------------------------------------------------------------------

    rules_by_code = {
        rule.rule_code: rule
        for rule in ComplianceRule.objects.filter(
            is_active=True
        )
    }

    unseeded_codes = (
        {result["rule_code"] for result in failed}
        - set(rules_by_code.keys())
    )

    if unseeded_codes:

        print(
            "WARNING: "
            f"{len(unseeded_codes)} rule code(s) failed but have "
            "no matching ComplianceRule row. "
            "Run 'python manage.py seed_rules'. "
            f"Missing codes: {sorted(unseeded_codes)}"
        )

    # ------------------------------------------------------------------
    # 16. SAVE ONLY SEEDED VIOLATIONS
    # ------------------------------------------------------------------

    saveable_failed = [
        result
        for result in failed
        if result["rule_code"] in rules_by_code
    ]

    is_compliant = (
        len(saveable_failed) == 0
    )

    score = round(
        100
        * (
            len(check_results)
            - len(saveable_failed)
        )
        / max(len(check_results), 1),
        1,
    )

    # ------------------------------------------------------------------
    # 17. SAVE COMPLIANCE REPORT
    # ------------------------------------------------------------------

    report, _ = ComplianceReport.objects.update_or_create(
        scan=scan_instance,
        defaults={
            "is_compliant": is_compliant,
            "overall_score": score,
        },
    )

    report.violations.all().delete()

    # ------------------------------------------------------------------
    # 18. SAVE VIOLATIONS
    # ------------------------------------------------------------------

    for result in saveable_failed:

        rule = rules_by_code[
            result["rule_code"]
        ]

        ComplianceViolation.objects.create(
            report=report,
            rule=rule,
            details=result["details"],
        )

    # ------------------------------------------------------------------
    # 19. FINAL STATUS
    # ------------------------------------------------------------------

    scan_instance.status = (
        "COMPLIANT"
        if is_compliant
        else "NON_COMPLIANT"
    )

    scan_instance.save(
        update_fields=[
            "status",
            "product_name",
        ]
    )

    return scan_instance