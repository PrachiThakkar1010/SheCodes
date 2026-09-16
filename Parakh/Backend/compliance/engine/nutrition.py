"""
compliance/engine/nutrition.py
--------------------------------
Parses food-label nutrition OCR into report-ready rows.

Design goals:
- Run nutrition extraction only when the package is food (when product_type
  is supplied by the pipeline).
- Match nutrient labels to values by OCR box geometry, not OCR reading order.
- Prefer same-row/right-hand values, while still allowing a value a few pixels
  above or below the nutrient label.
- Never let an implausible unit (e.g. "19 g" for Energy) win a match.
- Keep OCR-read values separate from any "likely OCR correction" suggestion.
- Recognise common nutrition-table basis headers such as "per 100 g" and
  "per serving" without accidentally using them as nutrient values.

This module does NOT decide Legal Metrology compliance. It only extracts
nutrition data for food products; the rule engine decides which checks apply.
"""

import re

# Reference values for an optional %DV display.
# These are reference-intake values for a 2,000 kcal diet, not a safety limit.
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
    r"(?<![\w.])([<>~]?\s*\d+(?:[.,]\d+)?)\s*(kcal|kj|mg|mcg|g|gm)\b",
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

# Vertical tolerance is intentionally a little wider than the old 1.5x rule:
# real photographed tables can have different baselines/heights. Horizontal
# geometry is used as a second signal so the wider tolerance does not cause
# a jump into the next nutrition row/column.
MAX_ROW_DISTANCE_FRAC = 2.25
MAX_HORIZONTAL_DISTANCE_FRAC = 12.0


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
    """Gap between x-ranges; 0 when the boxes overlap horizontally."""
    if box_a[2] < box_b[0]:
        return box_b[0] - box_a[2]
    if box_b[2] < box_a[0]:
        return box_a[0] - box_b[2]
    return 0.0


def _parse_number(text):
    return float(text.replace(",", ".").replace(" ", ""))


def _normalise_unit(unit):
    unit = (unit or "").lower()
    return "g" if unit == "gm" else unit


def _is_basis_line(text):
    text = (text or "").strip()
    return bool(BASIS_RE.search(text))


def _product_is_food(product_type):
    if product_type is None:
        return True  # backward compatible with old callers
    return str(product_type).strip().upper() == "FOOD"


def _extract_value_from_text(text, expected_units=None):
    m = VALUE_RE.search(text or "")
    if not m:
        return None
    unit = _normalise_unit(m.group(2))
    if expected_units and m.group(2).lower() not in expected_units and unit not in {
        _normalise_unit(x) for x in expected_units
    }:
        return None
    return _parse_number(m.group(1)), unit, m


def _candidate_score(anchor_box, candidate_box):
    """
    Lower is better.

    Vertical distance is the primary signal. A value to the right of the
    nutrient label is preferred because that is the common printed-table
    layout, but left/overlapping candidates remain possible.
    """
    a_h = _height(anchor_box)
    vertical = _row_distance(anchor_box, candidate_box) / a_h
    horizontal = _horizontal_distance(anchor_box, candidate_box) / max(a_h, 1.0)

    ax = _center(anchor_box)[0]
    cx = _center(candidate_box)[0]
    right_bonus = 0.0 if cx >= ax else 0.75

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

        raw_unit = m.group(2).lower()
        unit = _normalise_unit(raw_unit)
        normalised_expected = {_normalise_unit(x) for x in (expected_units or set())}
        if normalised_expected and unit not in normalised_expected:
            continue

        max_vertical = MAX_ROW_DISTANCE_FRAC * max(
            _height(anchor_box), _height(candidate_box)
        )
        vertical = _row_distance(anchor_box, candidate_box)
        if vertical > max_vertical:
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

        vertical = _row_distance(anchor_box, candidate_box)
        max_vertical = MAX_ROW_DISTANCE_FRAC * max(
            _height(anchor_box), _height(candidate_box)
        )
        if vertical > max_vertical:
            continue

        score = _candidate_score(anchor_box, candidate_box)
        if best is None or score < best[0]:
            best = (score, j, m)

    if best is None:
        return None, None

    _, j, m = best
    return j, _parse_number(m.group(1))


def _likely_decimal_repair(name, value, unit, pct):
    """
    Conservative suggestion only.

    If OCR dropped one decimal place, dividing by 10 can turn an obviously
    impossible %DV into a plausible value. The raw OCR value is never changed.
    """
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


def _basis_from_items(items):
    """Return a lightweight basis hint such as 'per 100 g' if OCR found one."""
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
    Parameters
    ----------
    items:
        OCR items labelled NUTRITION. Each item should contain text + box.
    product_type:
        "FOOD", "NON_FOOD", or None. NON_FOOD returns [] immediately.

    Returns
    -------
    list[dict]
        Nutrient rows containing the OCR value, unit, %DV, basis and flags.
    """
    if not items:
        return []

    if not _product_is_food(product_type):
        return []

    used = [False] * len(items)
    rows = []
    found_any_keyword = False
    basis = _basis_from_items(items)

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
                text, expected_units=EXPECTED_UNITS.get(name)
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
                items, used, anchor_idx, EXPECTED_UNITS.get(name)
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
            # We found the nutrient name but not a trustworthy amount.
            # Do not manufacture a row with an empty/wrong value.
            continue

        if pct is None and name in RDA:
            ref_value, ref_unit = RDA[name]
            if _normalise_unit(unit) == _normalise_unit(ref_unit):
                pct = round(100 * value / ref_value)

        implausible = bool(pct is not None and pct > 300)
        likely_correct_value = _likely_decimal_repair(
            name, value, unit, pct
        )

        rows.append({
            "nutrient": name,
            "amount": value,
            "unit": unit or "",
            "daily_value_pct": pct,
            "basis": basis,
            "high": bool(pct is not None and pct >= 20),
            "implausible": implausible,
            "likely_correct_value": likely_correct_value,
        })

    return rows if found_any_keyword else []
