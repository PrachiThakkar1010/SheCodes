"""
compliance/engine/nutrition.py
--------------------------------
Parses food-label nutrition OCR into report-ready rows.

Keeps the existing output fields and adds conservative OCR-correction
metadata. Raw OCR values are NEVER silently overwritten.
"""

import re

RDA = {
    "Energy": (2000, "kcal"),
    "Total Fat": (65, "g"),
    "Saturated Fat": (20, "g"),
    "Total Carbohydrate": (300, "g"),
    "Protein": (50, "g"),
    "Cholesterol": (300, "mg"),
    "Sodium": (2000, "mg"),
}

EXPECTED_UNITS = {
    "Energy": {"kcal", "kj"},
    "Total Fat": {"g", "gm"},
    "Saturated Fat": {"g", "gm"},
    "Trans Fat": {"g", "gm"},
    "Added Sugars": {"g", "gm"},
    "Sugars": {"g", "gm"},
    "Total Carbohydrate": {"g", "gm"},
    "Dietary Fiber": {"g", "gm"},
    "Protein": {"g", "gm"},
    "Cholesterol": {"mg", "mcg"},
    "Sodium": {"mg", "mcg"},
}

NUTRIENT_PATTERNS = [
    ("Energy", r"\benergy\b|\bcalories?\b"),
    ("Saturated Fat", r"\bsaturated\s*fat\b"),
    ("Trans Fat", r"\btrans\s*fat\b"),
    ("Total Fat", r"\btotal\s*fat\b|\bfat\b"),
    ("Added Sugars", r"\badded\s*sugars?\b"),
    ("Sugars", r"\bsugars?\b"),
    ("Total Carbohydrate", r"\btotal\s*carbohydrate\b|\bcarbohydrate\b"),
    ("Dietary Fiber", r"\bdietary\s*fib(?:er|re)\b"),
    ("Protein", r"\bprotein\b"),
    ("Cholesterol", r"\bcholesterol\b"),
    ("Sodium", r"\bsodium\b"),
]

VALUE_RE = re.compile(
    r"(?<![\w.])([<>~]?\s*\d+(?:[.,]\d+)?)\s*"
    r"(kcal|kj|mg|mcg|g|gm)\b",
    re.IGNORECASE,
)
BARE_VALUE_RE = re.compile(
    r"^[<>~]?\s*(\d+(?:[.,]\d+)?)\s*(kcal|kj|mg|mcg|g|gm)\s*$",
    re.IGNORECASE,
)
PCT_RE = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*%")
BASIS_RE = re.compile(
    r"\b(per|for)\s*(100\s*(?:g|gm|ml)|serv(?:ing|e)|portion|pack)\b"
    r"|\bserving\s*size\b|\bamount\s*per\b",
    re.IGNORECASE,
)

MAX_ROW_DISTANCE_FRAC = 2.25
MAX_HORIZONTAL_DISTANCE_FRAC = 12.0

# child <= parent when both are on the same nutrition basis.
NUTRIENT_RELATIONSHIPS = [
    ("Saturated Fat", "Total Fat"),
    ("Trans Fat", "Total Fat"),
    ("Added Sugars", "Sugars"),
    ("Sugars", "Total Carbohydrate"),
    ("Dietary Fiber", "Total Carbohydrate"),
]


def _box(box):
    if not box or len(box) < 4:
        return None
    try:
        return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
    except (TypeError, ValueError):
        return None


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _height(box):
    return max(1.0, box[3] - box[1])


def _row_distance(box_a, box_b):
    return abs(_center(box_a)[1] - _center(box_b)[1])


def _horizontal_distance(box_a, box_b):
    if box_a[2] < box_b[0]:
        return box_b[0] - box_a[2]
    if box_b[2] < box_a[0]:
        return box_a[0] - box_b[2]
    return 0.0


def _parse_number(text):
    return float(str(text).replace(",", ".").replace(" ", "").strip().lstrip("<>~"))


def _normalise_unit(unit):
    return "g" if (unit or "").lower() == "gm" else (unit or "").lower()


def _is_basis_line(text):
    return bool(BASIS_RE.search((text or "").strip()))


def _product_is_food(product_type):
    if product_type is None:
        return True
    return str(product_type).strip().upper() == "FOOD"


def _extract_value_from_text(text, expected_units=None):
    m = VALUE_RE.search(text or "")
    if not m:
        return None

    unit = _normalise_unit(m.group(2))
    expected = {_normalise_unit(x) for x in (expected_units or set())}
    if expected and unit not in expected:
        return None

    return _parse_number(m.group(1)), unit, m


def _candidate_score(anchor_box, candidate_box):
    a_h = _height(anchor_box)
    vertical = _row_distance(anchor_box, candidate_box) / a_h
    horizontal = _horizontal_distance(anchor_box, candidate_box) / max(a_h, 1.0)
    right_bonus = 0.0 if _center(candidate_box)[0] >= _center(anchor_box)[0] else 0.75
    return vertical + 0.08 * min(horizontal, MAX_HORIZONTAL_DISTANCE_FRAC) + right_bonus


def _find_nearby_value(items, used, anchor_idx, expected_units):
    anchor_box = _box(items[anchor_idx].get("box"))
    if not anchor_box:
        return None, None

    best = None
    for j, item in enumerate(items):
        if j == anchor_idx or used[j]:
            continue

        text = (item.get("text") or "").strip()
        if _is_basis_line(text):
            continue

        candidate_box = _box(item.get("box"))
        if not candidate_box:
            continue

        m = BARE_VALUE_RE.fullmatch(text)
        if not m:
            continue

        unit = _normalise_unit(m.group(2))
        expected = {_normalise_unit(x) for x in (expected_units or set())}
        if expected and unit not in expected:
            continue

        max_vertical = MAX_ROW_DISTANCE_FRAC * max(_height(anchor_box), _height(candidate_box))
        if _row_distance(anchor_box, candidate_box) > max_vertical:
            continue

        score = _candidate_score(anchor_box, candidate_box)
        if best is None or score < best[0]:
            best = (score, j, m, unit)

    if best is None:
        return None, None

    _, j, m, unit = best
    return j, (_parse_number(m.group(1)), unit)


def _find_nearby_pct(items, used, anchor_idx):
    anchor_box = _box(items[anchor_idx].get("box"))
    if not anchor_box:
        return None, None

    best = None
    for j, item in enumerate(items):
        if j == anchor_idx or used[j]:
            continue

        text = (item.get("text") or "").strip()
        candidate_box = _box(item.get("box"))
        if not candidate_box:
            continue

        m = PCT_RE.fullmatch(text)
        if not m:
            continue

        max_vertical = MAX_ROW_DISTANCE_FRAC * max(_height(anchor_box), _height(candidate_box))
        if _row_distance(anchor_box, candidate_box) > max_vertical:
            continue

        score = _candidate_score(anchor_box, candidate_box)
        if best is None or score < best[0]:
            best = (score, j, m)

    if best is None:
        return None, None

    _, j, m = best
    return j, _parse_number(m.group(1))


def _decimal_candidates(value):
    """Generate conservative missing-decimal candidates: x, x/10 and x/100."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return []

    return sorted({
        round(value, 4),
        round(value / 10.0, 4),
        round(value / 100.0, 4),
    })


def _likely_decimal_repair(name, value, unit, pct):
    """Existing %DV-based repair; returns a suggestion only."""
    if name not in RDA or pct is None or pct <= 300:
        return None

    ref_value, ref_unit = RDA[name]
    if _normalise_unit(unit) != _normalise_unit(ref_unit):
        return None

    candidate = round(value / 10.0, 2)
    candidate_pct = round(100 * candidate / ref_value)
    if 0 <= candidate_pct <= 150:
        return candidate

    return None


def _candidate_is_reasonable(name, candidate, unit):
    if candidate is None or candidate < 0:
        return False

    unit = _normalise_unit(unit)

    if name == "Energy":
        return unit in {"kcal", "kj"} and candidate <= 10000
    if unit == "g":
        return candidate <= 1000
    if unit == "mg":
        return candidate <= 100000
    if unit == "mcg":
        return candidate <= 1000000

    return True


def _build_row_map(rows):
    result = {}
    for row in rows:
        name = row.get("nutrient")
        if name and name not in result:
            result[name] = row
    return result


def _set_correction(row, corrected, reason, confidence):
    """
    Record an OCR correction and make the corrected value the report-facing
    'amount'.

    The original OCR value is preserved separately as 'raw_ocr_amount', while
    'likely_correct_value' remains available for backward compatibility.
    """
    if row.get("raw_ocr_amount") is None:
        row["raw_ocr_amount"] = row.get("amount")

    row["likely_correct_value"] = corrected
    row["amount"] = corrected
    row["correction_reason"] = reason
    row["correction_confidence"] = confidence


def _try_relationship_repair(child_row, parent_row):
    child_value = child_row.get("amount")
    parent_value = parent_row.get("amount")

    if child_value is None or parent_value is None:
        return False

    child_unit = _normalise_unit(child_row.get("unit"))
    parent_unit = _normalise_unit(parent_row.get("unit"))

    if child_unit != parent_unit:
        return False

    # Already valid.
    if child_value <= parent_value:
        return False

    # Prefer a one-place decimal recovery (/10).
    # Example: 78 -> 7.8.
    divide_by_10 = round(child_value / 10.0, 4)

    if (
        divide_by_10 != child_value
        and _candidate_is_reasonable(
            child_row["nutrient"],
            divide_by_10,
            child_unit,
        )
        and divide_by_10 <= parent_value
    ):
        corrected = divide_by_10
        confidence = "high"
    else:
        # Only use /100 when /10 cannot satisfy the relationship.
        divide_by_100 = round(child_value / 100.0, 4)

        if (
            divide_by_100 != child_value
            and _candidate_is_reasonable(
                child_row["nutrient"],
                divide_by_100,
                child_unit,
            )
            and divide_by_100 <= parent_value
        ):
            corrected = divide_by_100
            confidence = "medium"
        else:
            return False

    _set_correction(
        child_row,
        corrected,
        (
            f"OCR value {child_value:g} {child_unit} exceeds "
            f"{parent_row['nutrient']} ({parent_value:g} {parent_unit}); "
            f"decimal recovery gives {corrected:g} {child_unit}"
        ),
        confidence,
    )

    return True



def _apply_cross_field_repairs(rows):
    row_map = _build_row_map(rows)

    for child_name, parent_name in NUTRIENT_RELATIONSHIPS:
        child_row = row_map.get(child_name)
        parent_row = row_map.get(parent_name)
        if not child_row or not parent_row:
            continue
        _try_relationship_repair(child_row, parent_row)

    return rows


def _apply_rda_repairs(rows):
    for row in rows:
        if row.get("likely_correct_value") is not None:
            continue

        correction = _likely_decimal_repair(
            row["nutrient"],
            row["amount"],
            row["unit"],
            row.get("daily_value_pct"),
        )
        if correction is None:
            continue

        raw = row["amount"]
        unit = row["unit"]
        _set_correction(
            row,
            correction,
            (
                f"OCR value {raw:g} {unit} is inconsistent with "
                f"the detected %DV ({row['daily_value_pct']:g}%); "
                f"dividing by 10 gives {correction:g} {unit}"
            ),
            "medium",
        )

    return rows


def _recalculate_daily_values(rows):
    for row in rows:
        name = row.get("nutrient")
        amount = row.get("amount")
        unit = row.get("unit")

        if name not in RDA or amount is None:
            continue

        ref_value, ref_unit = RDA[name]
        if _normalise_unit(unit) != _normalise_unit(ref_unit):
            continue

        row["daily_value_pct"] = round(100 * amount / ref_value)
        row["implausible"] = bool(row["daily_value_pct"] > 300)
        row["high"] = bool(row["daily_value_pct"] >= 20)

    return rows


def _basis_from_items(items):
    for item in items:
        text = (item.get("text") or "").strip()
        m = re.search(
            r"\bper\s*(100\s*(?:g|gm|ml)|serving|portion)\b",
            text,
            re.IGNORECASE,
        )
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


def parse_nutrition(items, product_type=None):
    """
    Existing output keys are preserved.

    New optional keys appear only when a correction is suggested:
        correction_reason
        correction_confidence

    'amount' is always the raw OCR value.
    'likely_correct_value' is an inferred value and never silently replaces it.
    """
    if not items or not _product_is_food(product_type):
        return []

    used = [False] * len(items)
    rows = []
    found_any_keyword = False
    basis = _basis_from_items(items)

    # Stage 1: geometry-based OCR extraction.
    for name, pattern in NUTRIENT_PATTERNS:
        anchor_idx = None
        value = None
        unit = None
        pct = None

        for i, item in enumerate(items):
            if used[i]:
                continue

            text = (item.get("text") or "").strip()
            if not re.search(pattern, text, re.IGNORECASE):
                continue

            found_any_keyword = True
            anchor_idx = i
            used[i] = True

            direct = _extract_value_from_text(
                text,
                expected_units=EXPECTED_UNITS.get(name),
            )
            if direct:
                value, unit, _ = direct

            pm = PCT_RE.search(text)
            if pm:
                pct = _parse_number(pm.group(1))
            break

        if anchor_idx is None:
            continue

        if value is None:
            j, parsed = _find_nearby_value(
                items,
                used,
                anchor_idx,
                EXPECTED_UNITS.get(name),
            )
            if j is not None:
                value, unit = parsed
                used[j] = True

        if pct is None:
            j, parsed_pct = _find_nearby_pct(items, used, anchor_idx)
            if j is not None:
                pct = parsed_pct
                used[j] = True

        if value is None:
            continue

        if pct is None and name in RDA:
            ref_value, ref_unit = RDA[name]
            if _normalise_unit(unit) == _normalise_unit(ref_unit):
                pct = round(100 * value / ref_value)

        rows.append({
            "nutrient": name,
            "amount": value,
            "unit": unit or "",
            "daily_value_pct": pct,
            "basis": basis,
            "high": bool(pct is not None and pct >= 20),
            "implausible": bool(pct is not None and pct > 300),
            "likely_correct_value": _likely_decimal_repair(
                name, value, unit, pct
            ),
        })

    if not found_any_keyword:
        return []

    # Stage 2: relationships such as Saturated Fat <= Total Fat.
    _apply_cross_field_repairs(rows)

    # Stage 3: existing %DV fallback.
    _apply_rda_repairs(rows)

    # Stage 4: keep the existing flags/%DV based on raw OCR.
    _recalculate_daily_values(rows)

    return rows
