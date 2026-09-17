import math
import re
from typing import Dict, Any, List, Tuple


def calculate_pdp_area(pack_type: str, height_cm: float, width_cm: float, depth_cm: float = 0.0, diameter_cm: float = 0.0) -> float:
    """
    Calculates Principal Display Panel (PDP) area in square centimetres (sq cm)
    in accordance with Legal Metrology (Packaged Commodities) Rules, 2011, Rule 2(h) / Schedule II.
    """
    height = max(float(height_cm or 0.0), 0.1)
    width = max(float(width_cm or 0.0), 0.1)
    depth = max(float(depth_cm or 0.0), 0.0)
    diameter = max(float(diameter_cm or 0.0), 0.0)

    p_type = (pack_type or 'POUCH').upper()

    if p_type == 'BOX':
        # Rectangular package: Area of the largest single face
        faces = [height * width]
        if depth > 0:
            faces.append(height * depth)
            faces.append(width * depth)
        return round(max(faces), 2)

    elif p_type in ('CYLINDER', 'BOTTLE', 'CAN'):
        # Cylindrical / nearly cylindrical: 40% of (pi * diameter * height)
        eff_diameter = diameter if diameter > 0 else width
        curved_surface = math.pi * eff_diameter * height
        return round(0.40 * curved_surface, 2)

    elif p_type in ('JAR', 'TUB'):
        # Jar/Tub: 40% of cylindrical side, or lid area, whichever is intended display
        eff_diameter = diameter if diameter > 0 else width
        side_pdp = 0.40 * (math.pi * eff_diameter * height)
        lid_area = math.pi * ((eff_diameter / 2.0) ** 2)
        return round(max(side_pdp, lid_area), 2)

    else:
        # Flexible Pouch, Bag, Pillow Pouch: height * width of front face
        return round(height * width, 2)


def get_statutory_font_sizes(pdp_area_sqcm: float, net_qty: float = 100.0, qty_unit: str = 'g') -> Dict[str, Any]:
    """
    Determines mandatory minimum font and numeral heights under:
    1. Legal Metrology (Packaged Commodities) Rules, 2011, Schedule II, Tables 1 & 2.
    2. FSSAI (Labelling and Display) Regulations, 2020.
    """
    area = float(pdp_area_sqcm or 0.0)
    qty = float(net_qty or 0.0)
    unit = (qty_unit or 'g').lower()

    # Normalise quantity to grams/millilitres for Table 1 threshold comparison
    normalized_qty = qty
    if unit in ('kg', 'l', 'litre', 'litres', 'kilogram'):
        normalized_qty = qty * 1000.0

    # 1. Minimum Height of Numerals for Net Quantity (Table 1)
    if normalized_qty <= 50.0:
        min_net_qty_numeral = 1.0 if area <= 100 else 2.0
    elif 50.0 < normalized_qty <= 200.0:
        min_net_qty_numeral = 2.0
    elif 200.0 < normalized_qty <= 1000.0:
        min_net_qty_numeral = 4.0
    else:  # Above 1000g / 1000ml
        min_net_qty_numeral = 6.0

    # 2. Minimum Height of General Letters & Mandatory Declarations (Table 2)
    if area <= 50.0:
        min_general_font = 1.0
        blown_embossed_min = 1.5
    elif 50.0 < area <= 200.0:
        min_general_font = 2.0
        blown_embossed_min = 3.0
    elif 200.0 < area <= 1000.0:
        min_general_font = 4.0
        blown_embossed_min = 6.0
    else:  # Above 1000 sq cm
        min_general_font = 6.0
        blown_embossed_min = 8.0

    # 3. Veg / Non-Veg Symbol Dimensions (FSSAI 2020, Schedule II, Clause 5)
    # Returns (square_side_mm, inner_circle_diameter_mm)
    if area <= 100.0:
        veg_square_mm = 3.0
        veg_circle_mm = 1.5
    elif 100.0 < area <= 500.0:
        veg_square_mm = 4.0
        veg_circle_mm = 2.0
    elif 500.0 < area <= 2500.0:
        veg_square_mm = 6.0
        veg_circle_mm = 3.0
    else:
        veg_square_mm = 8.0
        veg_circle_mm = 4.0

    fssai_font_mm = max(1.5, min_general_font)

    return {
        "pdp_area_sqcm": round(area, 2),
        "min_general_font_mm": min_general_font,
        "min_net_qty_numeral_mm": min_net_qty_numeral,
        "blown_embossed_min_mm": blown_embossed_min,
        "veg_symbol": {
            "square_side_mm": veg_square_mm,
            "circle_diameter_mm": veg_circle_mm,
            "rule_citation": "FSSAI (Labelling and Display) Regulations, 2020, Schedule II"
        },
        "fssai_logo": {
            "min_font_mm": fssai_font_mm,
            "rule_citation": "FSSAI (Labelling and Display) Regulations, 2020, Regulation 5(4)"
        },
        "legal_metrology_citation": "Legal Metrology (Packaged Commodities) Rules, 2011, Schedule II (Tables 1 & 2)"
    }


def calculate_unit_sale_price(mrp: float, net_qty: float, qty_unit: str) -> Dict[str, Any]:
    """
    Computes Unit Sale Price (USP) as mandated by Rule 6(1)(n) of
    Legal Metrology (Packaged Commodities) Rules, 2011 (Amended).
    """
    mrp_val = float(mrp or 0.0)
    qty = float(net_qty or 1.0)
    unit = (qty_unit or 'g').strip().lower()

    if qty <= 0:
        return {"usp_text": "N/A", "per_unit_price": 0.0, "unit_basis": "unit"}

    if unit in ('g', 'gram', 'grams'):
        if qty < 1000:
            usp_per_g = mrp_val / qty
            usp_per_100g = usp_per_g * 100
            usp_text = f"₹ {usp_per_g:.2f} / g (₹ {usp_per_100g:.2f} / 100g)"
            return {"usp_text": usp_text, "per_unit_price": round(usp_per_g, 2), "unit_basis": "g"}
        else:
            usp_per_kg = mrp_val / (qty / 1000.0)
            usp_text = f"₹ {usp_per_kg:.2f} / kg"
            return {"usp_text": usp_text, "per_unit_price": round(usp_per_kg, 2), "unit_basis": "kg"}

    elif unit in ('kg', 'kilogram', 'kilograms'):
        usp_per_kg = mrp_val / qty
        usp_text = f"₹ {usp_per_kg:.2f} / kg"
        return {"usp_text": usp_text, "per_unit_price": round(usp_per_kg, 2), "unit_basis": "kg"}

    elif unit in ('ml', 'millilitre', 'millilitres'):
        if qty < 1000:
            usp_per_ml = mrp_val / qty
            usp_per_100ml = usp_per_ml * 100
            usp_text = f"₹ {usp_per_ml:.2f} / ml (₹ {usp_per_100ml:.2f} / 100ml)"
            return {"usp_text": usp_text, "per_unit_price": round(usp_per_ml, 2), "unit_basis": "ml"}
        else:
            usp_per_l = mrp_val / (qty / 1000.0)
            usp_text = f"₹ {usp_per_l:.2f} / L"
            return {"usp_text": usp_text, "per_unit_price": round(usp_per_l, 2), "unit_basis": "L"}

    elif unit in ('l', 'litre', 'litres'):
        usp_per_l = mrp_val / qty
        usp_text = f"₹ {usp_per_l:.2f} / L"
        return {"usp_text": usp_text, "per_unit_price": round(usp_per_l, 2), "unit_basis": "L"}

    else:
        usp_per_item = mrp_val / qty
        usp_text = f"₹ {usp_per_item:.2f} / {unit}"
        return {"usp_text": usp_text, "per_unit_price": round(usp_per_item, 2), "unit_basis": unit}


ALLERGEN_PATTERNS = {
    "Gluten / Wheat": [r'\bwheat\b', r'\bgluten\b', r'\bbarley\b', r'\brye\b', r'\boats\b', r'\bmaida\b', r'\bsemolina\b', r'\bsuji\b', r'\battah\b'],
    "Crustaceans": [r'\bcrustacean', r'\bprawn', r'\bshrimp', r'\bcrab\b', r'\blobster\b'],
    "Eggs": [r'\begg\b', r'\beggs\b', r'\balbumin\b', r'\begg yolk\b', r'\bovomucin\b'],
    "Fish": [r'\bfish\b', r'\bsalmon\b', r'\btuna\b', r'\bcod\b', r'\bgelatin\b'],
    "Peanuts": [r'\bpeanut', r'\bgroundnut'],
    "Soybeans": [r'\bsoy\b', r'\bsoya\b', r'\bsoybean', r'\bsoy lecithin\b'],
    "Milk & Dairy": [r'\bmilk\b', r'\bwhey\b', r'\bcasein', r'\blactose\b', r'\bbutter\b', r'\bghee\b', r'\bcheese\b', r'\byogurt\b', r'\bcurd\b', r'\bpaneer\b', r'\bmilk solids\b'],
    "Tree Nuts": [r'\balmond', r'\bwalnut', r'\bcashew', r'\bpistachio', r'\bhazelnut', r'\bpecan', r'\bmacadamia', r'\bbrazil nut'],
    "Sulphites": [r'\bsulphite', r'\bsulfite', r'\bsodium metabisulphite\b', r'\bins\s*22\d']
}


def detect_allergens(ingredients_text: str) -> Dict[str, Any]:
    """
    Detects statutory allergens mandated by FSSAI (Labelling and Display) Regulations, 2020,
    Regulation 5(3)(ix).
    """
    text = (ingredients_text or "").lower()
    detected = []

    for allergen, patterns in ALLERGEN_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                if allergen not in detected:
                    detected.append(allergen)
                break

    if detected:
        bold_allergens = ", ".join(detected)
        advice_text = f"CONTAINS: {bold_allergens.upper()}."
        cross_contact_note = "Processed in a facility that also handles Tree Nuts, Soy, Peanuts, and Dairy."
    else:
        advice_text = "No major statutory allergens detected from provided ingredient list."
        cross_contact_note = "If equipment is shared with common allergens, include: 'May contain traces of gluten, nuts, or milk.'"

    return {
        "detected_allergens": detected,
        "statutory_advice_text": advice_text,
        "cross_contact_disclaimer": cross_contact_note,
        "mandatory_bolding_required": len(detected) > 0,
        "regulation": "FSSAI (Labelling and Display) Regulations, 2020, Clause 5(3)(ix)"
    }


def validate_marketing_claims(claims_raw: str, nutrition_dict: Dict[str, Any] = None, ingredients_text: str = "") -> List[Dict[str, Any]]:
    """
    Evaluates marketing and nutritional claims against FSSAI (Advertising and Claims) Regulations, 2018.
    """
    nutrition = nutrition_dict or {}
    ingredients = (ingredients_text or "").lower()

    if isinstance(claims_raw, list):
        claims_list = claims_raw
    else:
        claims_list = [c.strip() for c in (claims_raw or "").split(",") if c.strip()]

    results = []

    for claim in claims_list:
        c_lower = claim.lower()
        status = "APPROVED"
        severity = "INFO"
        notes = ""
        citation = "FSSAI (Advertising and Claims) Regulations, 2018"

        # Sugar claims
        if "sugar free" in c_lower or "zero sugar" in c_lower:
            sugar_val = float(nutrition.get("sugars", nutrition.get("total_sugars", 999)))
            if sugar_val <= 0.5:
                status = "COMPLIANT"
                notes = f"Allowed: Declared sugar ({sugar_val}g/100g) is <= 0.5g per 100g threshold."
            else:
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = f"VIOLATION: 'Sugar Free' requires sugars <= 0.5g per 100g. Current: {sugar_val}g/100g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 4.1)"

        elif "no added sugar" in c_lower:
            prohibited_words = ["sugar", "sucrose", "glucose", "fructose", "corn syrup", "jaggery", "honey", "invert syrup"]
            found_sugars = [w for w in prohibited_words if w in ingredients]
            if found_sugars:
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = f"VIOLATION: Contains added sweeteners in ingredients: {', '.join(found_sugars)}. Must not contain any added monosaccharides or disaccharides."
            else:
                status = "COMPLIANT"
                notes = "Allowed: No added sugars detected in ingredients list. Note: If naturally occurring sugars are present, must add: 'CONTAINS NATURALLY OCCURRING SUGARS'."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 4.2)"

        # Protein claims
        elif "high protein" in c_lower or "rich in protein" in c_lower:
            protein_val = float(nutrition.get("protein", 0.0))
            if protein_val >= 10.8:
                status = "COMPLIANT"
                notes = f"Allowed: Protein content ({protein_val}g/100g) meets the 20% RDA threshold (>= 10.8g per 100g for solids)."
            elif protein_val >= 5.4:
                status = "WARNING"
                severity = "HIGH"
                notes = f"ADVISORY: Protein is {protein_val}g/100g. Qualifies for 'Source of Protein' (>= 10% RDA), but falls short of 'High Protein' (requires >= 20% RDA / 10.8g)."
            else:
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = f"VIOLATION: 'High Protein' requires at least 10.8g protein per 100g (20% RDA). Current declared: {protein_val}g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 3.2)"

        elif "source of protein" in c_lower:
            protein_val = float(nutrition.get("protein", 0.0))
            if protein_val >= 5.4:
                status = "COMPLIANT"
                notes = f"Allowed: Protein ({protein_val}g/100g) meets >= 10% RDA (5.4g/100g)."
            else:
                status = "NON_COMPLIANT"
                severity = "HIGH"
                notes = f"VIOLATION: Requires at least 5.4g protein per 100g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 3.1)"

        # Fat claims
        elif "low fat" in c_lower:
            fat_val = float(nutrition.get("fat", nutrition.get("total_fat", 999)))
            if fat_val <= 3.0:
                status = "COMPLIANT"
                notes = f"Allowed: Total fat ({fat_val}g/100g) is <= 3g per 100g."
            else:
                status = "NON_COMPLIANT"
                severity = "HIGH"
                notes = f"VIOLATION: 'Low Fat' requires total fat <= 3g/100g. Current: {fat_val}g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 1.1)"

        elif "fat free" in c_lower or "zero fat" in c_lower:
            fat_val = float(nutrition.get("fat", nutrition.get("total_fat", 999)))
            if fat_val <= 0.5:
                status = "COMPLIANT"
                notes = f"Allowed: Total fat is <= 0.5g per 100g."
            else:
                status = "NON_COMPLIANT"
                severity = "HIGH"
                notes = f"VIOLATION: 'Fat Free' requires <= 0.5g fat per 100g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 1.2)"

        elif "trans fat free" in c_lower or "zero trans fat" in c_lower:
            tf_val = float(nutrition.get("trans_fat", 0.0))
            if tf_val < 0.2:
                status = "COMPLIANT"
                notes = f"Allowed: Trans fat is < 0.2g per 100g. Note: Saturated fat must also not exceed 1.5g/100g to claim trans fat free."
            else:
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = f"VIOLATION: 'Trans Fat Free' requires < 0.2g trans fat per 100g. Current: {tf_val}g."
            citation = "FSSAI Claims Regs 2018, Schedule I (Clause 2.1)"

        # Natural / Pure claims
        elif "100% natural" in c_lower or "natural" in c_lower:
            additives = [r'\bins\s*\d+', r'preservative', r'added flavour', r'artificial', r'colour', r'synthetic', r'emulsifier']
            has_additives = any(re.search(p, ingredients) for p in additives)
            if has_additives:
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = "VIOLATION: The term 'Natural' cannot be used on foods with added flavours, synthetic colours, chemical preservatives, or food additives (FSSAI Reg 4(1))."
            else:
                status = "WARNING"
                severity = "MEDIUM"
                notes = "CONDITIONAL: Only allowed if food is single unrefined agricultural produce or processed solely by traditional physical methods without additives."
            citation = "FSSAI (Advertising and Claims) Regulations, 2018, Schedule V"

        elif "pure" in c_lower:
            status = "WARNING"
            severity = "MEDIUM"
            notes = "CONDITIONAL: 'Pure' may only be used for single-ingredient foods with no additives, unadulterated and unmodified."
            citation = "FSSAI Claims Regs 2018, Schedule V"

        elif "immunity" in c_lower or "boosts immunity" in c_lower or "cures" in c_lower:
            status = "NON_COMPLIANT"
            severity = "CRITICAL"
            notes = "HIGH REGULATORY RISK: Therapeutic claims ('Cures', 'Boosts Immunity', 'Disease Prevention') are strictly restricted under Consumer Protection Act & FSSAI unless supported by clinical human trials and prior FSSAI approval."
            citation = "FSSAI Claims Regs 2018, Regulation 5 & Consumer Protection Act 2019"

        elif "gluten free" in c_lower:
            gluten_words = ['wheat', 'barley', 'rye', 'spelt', 'maida']
            if any(w in ingredients for w in gluten_words):
                status = "NON_COMPLIANT"
                severity = "CRITICAL"
                notes = "VIOLATION: Ingredients contain gluten sources. 'Gluten Free' requires laboratory certified gluten content < 20 mg/kg."
            else:
                status = "COMPLIANT"
                notes = "Allowed with lab certification: Gluten must be verified < 20 mg/kg. Must be accompanied by the Gluten-Free Logo."
            citation = "FSSAI Food Safety Standards (Food Products Standards and Food Additives) Regulations"

        else:
            status = "NEUTRAL"
            notes = "General marketing claim. Ensure substantiated by scientific documentation and not misleading to consumers."

        results.append({
            "claim": claim,
            "status": status,
            "severity": severity,
            "notes": notes,
            "regulation": citation
        })

    return results


def compile_full_statutory_spec(project_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compiles the complete legal specification package for graphic designers and packaging engineers.
    """
    pack_type = project_data.get('pack_type', 'POUCH')
    h_cm = float(project_data.get('height_cm', 15.0))
    w_cm = float(project_data.get('width_cm', 10.0))
    d_cm = float(project_data.get('depth_cm', 0.0) or 0.0)
    dia_cm = float(project_data.get('diameter_cm', 0.0) or 0.0)

    net_qty = float(project_data.get('net_quantity', 100.0))
    qty_unit = project_data.get('quantity_unit', 'g')
    mrp = float(project_data.get('mrp', 50.0))

    diet_type = project_data.get('diet_type', 'VEG')
    brand_name = project_data.get('brand_name', 'PureCraft')
    generic_name = project_data.get('generic_product_name', 'Roasted Almonds')
    mfg_name = project_data.get('manufacturer_name', 'PureCraft Foods Pvt. Ltd.')
    mfg_addr = project_data.get('manufacturer_address', 'Plot 42, Food Park, Phase 1, Gurgaon - 122001')
    fssai_lic = project_data.get('fssai_license_no', '10021000000000')
    country = project_data.get('country_of_origin', 'India')
    shelf_life = project_data.get('shelf_life_months', 6)

    # 1. PDP and font sizes
    pdp_area = calculate_pdp_area(pack_type, h_cm, w_cm, d_cm, dia_cm)
    font_specs = get_statutory_font_sizes(pdp_area, net_qty, qty_unit)

    # 2. Unit Sale Price
    usp_info = calculate_unit_sale_price(mrp, net_qty, qty_unit)

    # 3. Allergen Analysis
    ingredients = project_data.get('ingredients', '')
    allergen_info = detect_allergens(ingredients)

    # 4. Marketing Claims Validation
    claims_raw = project_data.get('marketing_claims', '')
    nutrition_raw = project_data.get('nutrition_data', {})
    claims_report = validate_marketing_claims(claims_raw, nutrition_raw, ingredients)

    # 5. Formatted Mandatory Strings
    mrp_declaration = f"MRP ₹ {mrp:.2f} (incl. of all taxes)"
    usp_declaration = f"Unit Sale Price: {usp_info['usp_text']}"
    net_qty_declaration = f"Net Quantity: {net_qty:g} {qty_unit}"
    date_declaration = f"Mfg Date: DD/MM/YYYY | Best Before {shelf_life} Months from packaging"
    batch_declaration = "Batch No.: [Auto-assigned at packaging / e.g. PC-2026-A1]"
    fssai_declaration = f"fssai Lic. No. {fssai_lic}"

    # 6. Panel Layout Recommendations
    pdp_elements = [
        {"element": "Brand Name & Logo", "placement": "Top Center / Top Left", "status": "Mandatory Brand"},
        {"element": f"Generic Product Name: '{generic_name}'", "placement": "Directly below brand, bold", "min_height_mm": font_specs['min_general_font_mm']},
        {"element": "Veg / Non-Veg Symbol", "placement": "Prominently on PDP (near product name)", "specs": f"Square: {font_specs['veg_symbol']['square_side_mm']}mm, Circle: {font_specs['veg_symbol']['circle_diameter_mm']}mm"},
        {"element": net_qty_declaration, "placement": "Bottom Right or Bottom Left of PDP", "min_height_mm": font_specs['min_net_qty_numeral_mm'], "rule": "Legal Metrology Sched. II Table 1"}
    ]

    info_panel_elements = [
        {"element": "List of Ingredients", "placement": "Back Panel, descending order by weight", "min_height_mm": font_specs['min_general_font_mm']},
        {"element": "Allergen Declaration", "placement": "Directly below ingredients, in BOLD CAPITAL letters", "text": allergen_info['statutory_advice_text']},
        {"element": "Nutrition Information Table", "placement": "Back Panel, standard tabular format per 100g and per serve", "status": "Mandatory under FSSAI 2020"},
        {"element": f"{mrp_declaration} & {usp_declaration}", "placement": "Back Panel / Side Flap in high contrast rectangular box", "status": "Mandatory Rule 6"},
        {"element": f"{date_declaration} & {batch_declaration}", "placement": "Near MRP or dedicated stamp box", "status": "Mandatory Rule 6"},
        {"element": f"Manufactured by: {mfg_name}, {mfg_addr}", "placement": "Back Panel with complete postal PIN code", "status": "Mandatory Legal Metrology"},
        {"element": f"Country of Origin: {country}", "placement": "Back Panel clearly visible", "status": "Mandatory"},
        {"element": f"{fssai_declaration} with Logo", "placement": "Back Panel / side panel with FSSAI brand logo", "status": "Mandatory FSSAI"},
        {"element": f"Consumer Care: {project_data.get('consumer_care_email', 'care@company.com')}, Tel: {project_data.get('consumer_care_phone', '1800-00-0000')}", "placement": "In distinct boxed outline", "status": "Mandatory Rule 6(1)(f)"},
        {"element": "EPR / Plastic Waste Management Mark", "placement": "Bottom back panel (Recycling triangle + plastic thickness)", "status": "Mandatory under PWM Rules 2016"}
    ]

    return {
        "project_meta": {
            "title": project_data.get('title', 'Packaging Spec'),
            "category": project_data.get('category', 'FOOD_BEVERAGE'),
            "pack_type": pack_type,
            "dimensions_cm": {"height": h_cm, "width": w_cm, "depth": d_cm, "diameter": dia_cm},
            "finish_type": project_data.get('finish_type', 'MATTE'),
            "primary_color": project_data.get('primary_color', '#073b70'),
            "accent_color": project_data.get('accent_color', '#f59e0b'),
            "theme_preset": project_data.get('theme_preset', 'MODERN_NAVY'),
            "hero_image_url": project_data.get('hero_image_url', ''),
        },
        "pdp_calculations": font_specs,
        "usp_data": usp_info,
        "allergen_report": allergen_info,
        "claims_audit": claims_report,
        "statutory_strings": {
            "mrp": mrp_declaration,
            "usp": usp_declaration,
            "net_qty": net_qty_declaration,
            "date": date_declaration,
            "batch": batch_declaration,
            "fssai": fssai_declaration,
            "country_of_origin": f"Country of Origin: {country}"
        },
        "panel_blueprints": {
            "pdp_front": pdp_elements,
            "info_panel_back": info_panel_elements
        }
    }
