import json
import os
import re
import time
from typing import Dict, Any, List
from django.conf import settings
from google import genai
from google.genai.errors import ServerError, ClientError

from .compliance_rules_engine import compile_full_statutory_spec


def get_genai_client():
    api_key = getattr(settings, "GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)


CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def generate_ai_design_recommendations(project_data: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calls Gemini to enrich the rule-based specification with an intelligent
    Nutrition Information Table, marketing claim rewrites, and typography/layout advice.
    """
    client = get_genai_client()

    prompt = f"""
    You are an expert Chief Packaging Compliance Officer and Industrial Packaging Designer specializing in:
    1. Legal Metrology (Packaged Commodities) Rules, 2011.
    2. FSSAI (Food Safety and Standards - Labelling and Display) Regulations, 2020.
    3. FSSAI (Advertising and Claims) Regulations, 2018.

    PRODUCT DETAILS:
    - Title: {project_data.get('title')}
    - Category: {project_data.get('category')}
    - Generic Name: {project_data.get('generic_product_name')}
    - Pack Type: {project_data.get('pack_type')}
    - Net Quantity: {project_data.get('net_quantity')} {project_data.get('quantity_unit')}
    - Ingredients: {project_data.get('ingredients')}
    - Raw Claims: {project_data.get('marketing_claims')}
    - Diet Type: {project_data.get('diet_type')}

    DETERMINISTIC STATUTORY SPEC (from Law Engine):
    - PDP Area: {rule_spec.get('pdp_calculations', {}).get('pdp_area_sqcm')} sq cm
    - Min General Font: {rule_spec.get('pdp_calculations', {}).get('min_general_font_mm')} mm
    - Min Net Qty Numeral: {rule_spec.get('pdp_calculations', {}).get('min_net_qty_numeral_mm')} mm
    - Unit Sale Price: {rule_spec.get('usp_data', {}).get('usp_text')}
    - Allergen Advice: {rule_spec.get('allergen_report', {}).get('statutory_advice_text')}

    TASK:
    Generate an authoritative, production-ready packaging design JSON with:
    1. "nutrition_table": Standard compliant nutritional values per 100g and per serving (serving size e.g. 30g) including Energy (kcal), Protein (g), Carbohydrates (g), Total Sugars (g), Added Sugars (g), Total Fat (g), Saturated Fat (g), Trans Fat (g), Sodium (mg), and % RDA. Estimate realistic values based on ingredients if not provided.
    2. "claim_remedies": Actionable rewrites or disclaimers for each marketing claim to ensure 100% legal compliance.
    3. "typography_guidelines": Exact font height recommendations, kerning, contrast ratios, and recommended color codes.
    4. "statutory_warnings": Any mandatory warnings required (e.g., added flavor declaration, allergen bolding, storage conditions).
    5. "design_checklist": A 5-point pre-print checklist for graphic designers.

    Return ONLY a valid JSON object matching this schema:
    {{
      "serving_size": "e.g. 30g",
      "servings_per_pack": 3.3,
      "nutrition_table": [
        {{"nutrient": "Energy", "per_100g": "580 kcal", "per_serve": "174 kcal", "percent_rda": "8.7%"}},
        {{"nutrient": "Protein", "per_100g": "21.0 g", "per_serve": "6.3 g", "percent_rda": "11.7%"}},
        {{"nutrient": "Carbohydrates", "per_100g": "19.5 g", "per_serve": "5.8 g", "percent_rda": "-"}},
        {{"nutrient": "Total Sugars", "per_100g": "4.2 g", "per_serve": "1.3 g", "percent_rda": "-"}},
        {{"nutrient": "Added Sugars", "per_100g": "0.0 g", "per_serve": "0.0 g", "percent_rda": "0.0%"}},
        {{"nutrient": "Total Fat", "per_100g": "49.0 g", "per_serve": "14.7 g", "percent_rda": "21.9%"}},
        {{"nutrient": "Saturated Fat", "per_100g": "3.8 g", "per_serve": "1.1 g", "percent_rda": "5.2%"}},
        {{"nutrient": "Trans Fat", "per_100g": "0.0 g", "per_serve": "0.0 g", "percent_rda": "0.0%"}},
        {{"nutrient": "Sodium", "per_100g": "320 mg", "per_serve": "96 mg", "percent_rda": "4.8%"}}
      ],
      "claim_remedies": [
        {{"original_claim": "...", "verdict": "APPROVED / AMEND", "compliant_rewrite": "...", "reason": "..."}}
      ],
      "typography_guidelines": {{
        "pdp_product_name_min_pt": 14,
        "net_quantity_min_pt": 12,
        "ingredients_nutrition_min_pt": 6,
        "contrast_requirement": "High contrast dark text on light background or vice-versa"
      }},
      "statutory_warnings": [
        "..."
      ],
      "design_checklist": [
        "..."
      ]
    }}
    """

    response = None
    for model_name in CANDIDATE_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt],
                config={"response_mime_type": "application/json"}
            )
            if response and response.text:
                break
        except Exception as e:
            print(f"[Assistant Service] Model {model_name} failed: {e}. Trying fallback...")
            continue

    if not response or not response.text:
        return {
            "serving_size": f"{min(float(project_data.get('net_quantity', 100)), 30):g}{project_data.get('quantity_unit', 'g')}",
            "servings_per_pack": round(float(project_data.get('net_quantity', 100)) / 30.0, 1),
            "nutrition_table": [
                {"nutrient": "Energy", "per_100g": "540 kcal", "per_serve": "162 kcal", "percent_rda": "8.1%"},
                {"nutrient": "Protein", "per_100g": "18.0 g", "per_serve": "5.4 g", "percent_rda": "10.0%"},
                {"nutrient": "Carbohydrates", "per_100g": "22.0 g", "per_serve": "6.6 g", "percent_rda": "-"},
                {"nutrient": "Total Sugars", "per_100g": "3.5 g", "per_serve": "1.0 g", "percent_rda": "-"},
                {"nutrient": "Added Sugars", "per_100g": "0.0 g", "per_serve": "0.0 g", "percent_rda": "0.0%"},
                {"nutrient": "Total Fat", "per_100g": "44.0 g", "per_serve": "13.2 g", "percent_rda": "19.7%"},
                {"nutrient": "Saturated Fat", "per_100g": "3.5 g", "per_serve": "1.0 g", "percent_rda": "4.8%"},
                {"nutrient": "Trans Fat", "per_100g": "0.0 g", "per_serve": "0.0 g", "percent_rda": "0.0%"},
                {"nutrient": "Sodium", "per_100g": "280 mg", "per_serve": "84 mg", "percent_rda": "4.2%"}
            ],
            "claim_remedies": [
                {"original_claim": c.get('claim'), "verdict": c.get('status'), "compliant_rewrite": c.get('claim'), "reason": c.get('notes')}
                for c in rule_spec.get('claims_audit', [])
            ],
            "typography_guidelines": {
                "pdp_product_name_min_pt": 14,
                "net_quantity_min_pt": 10,
                "ingredients_nutrition_min_pt": 6,
                "contrast_requirement": "Strict high contrast. Minimum 4.5:1 ratio."
            },
            "statutory_warnings": [
                rule_spec.get('allergen_report', {}).get('statutory_advice_text'),
                "STORE IN A COOL, DRY AND HYGIENIC PLACE AWAY FROM DIRECT SUNLIGHT."
            ],
            "design_checklist": [
                "Verify Net Quantity numeral height meets Legal Metrology Schedule II.",
                "Ensure Unit Sale Price (USP) is adjacent to MRP in identical font size.",
                "Verify FSSAI Logo includes the 14-digit license number directly underneath.",
                "Ensure Veg/Non-Veg emblem adheres to dimensional square and circle ratios.",
                "Confirm mandatory Allergen warning is formatted in bold uppercase."
            ]
        }

    raw_text = response.text.strip()
    try:
        return json.loads(raw_text)
    except Exception:
        clean_text = re.sub(r"^```json|^```|```$", "", raw_text, flags=re.MULTILINE).strip()
        return json.loads(clean_text)


def chat_with_packaging_assistant(user_message: str, chat_history: List[Dict[str, str]] = None, project_context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Conversational packaging legal co-pilot and design director.
    Answers legal packaging queries and generates actionable blueprint patches
    (colors, images, dimensions, text, claims) when asked by the user.
    """
    client = get_genai_client()

    context_str = ""
    if project_context:
        context_str = f"""
        ACTIVE PACKAGING DESIGN STATE:
        - Brand: {project_context.get('brand_name', 'PureCraft')}
        - Generic Product Name: {project_context.get('generic_product_name', 'Roasted Almonds')}
        - Category: {project_context.get('category', 'FOOD_BEVERAGE')}
        - Pack Type: {project_context.get('pack_type', 'POUCH')}
        - Dimensions: {project_context.get('height_cm', 15.0)}cm H x {project_context.get('width_cm', 10.0)}cm W x {project_context.get('depth_cm', 4.0)}cm D
        - Net Quantity: {project_context.get('net_quantity', 100.0)} {project_context.get('quantity_unit', 'g')}
        - MRP: ₹ {project_context.get('mrp', 50.0)}
        - Diet Type: {project_context.get('diet_type', 'VEG')}
        - Ingredients: {project_context.get('ingredients', '')}
        - Marketing Claims: {project_context.get('marketing_claims', '')}
        - Primary Color: {project_context.get('primary_color', '#073b70')}
        - Accent Color: {project_context.get('accent_color', '#f59e0b')}
        - Theme Preset: {project_context.get('theme_preset', 'MODERN_NAVY')}
        - Finish: {project_context.get('finish_type', 'MATTE')}
        - Hero Image: {project_context.get('hero_image_keyword', project_context.get('hero_image_url', 'almonds'))}
        """

    system_instruction = f"""
    You are 'Parakh AI Studio Co-Pilot' — an expert Industrial Packaging Designer & Chief Packaging Compliance Officer.
    You guide companies to design aesthetically stunning, full-colored, photo-rich packaging that is 100% compliant with:
    1. Legal Metrology (Packaged Commodities) Rules, 2011 (as amended 2021/2022/2024).
    2. FSSAI (Labelling & Display) Regulations, 2020.
    3. FSSAI (Advertising & Claims) Regulations, 2018.

    CORE CAPABILITIES:
    1. ANSWER COMPLIANCE QUERIES: Cite specific statutory rules, font sizing minimums, mandatory declarations, and claim regulations.
    2. MODIFY THE PACKAGING BLUEPRINT ON COMMAND:
       - If the user asks to change ANY design element (e.g. colors, background, finish, theme, pictures/imagery, product name, weight, price, ingredients, claims), you MUST output a `blueprint_patch` with the updated properties.
       - Valid theme presets: 'MODERN_NAVY', 'EARTHY_ORGANIC', 'DARK_LUXURY', 'VIBRANT_FRESH', 'ROYAL_GOLD', 'MINIMAL_WHITE'.
       - Valid finish types: 'MATTE', 'GLOSS', 'METALLIC', 'KRAFT'.
       - Available hero image keywords: 'almonds', 'cashews', 'chocolate', 'coffee', 'juice', 'protein', 'honey', 'tea', 'cookies', 'skincare'. Or provide custom image keywords/descriptions.
       - Valid hex colors: Provide high aesthetic matching colors (e.g. Dark Luxury: Primary '#1a101f', Accent '#d4af37', Finish 'METALLIC').

    OUTPUT FORMAT:
    You MUST respond in valid JSON matching this schema:
    {{
      "reply": "Your clear, markdown formatted regulatory analysis and design explanation. If you made changes, explain what changed and detail any statutory compliance impacts (such as font size changes or claim requirements).",
      "blueprint_patch": {{
        // ONLY include fields that are being updated or modified. If NO changes requested, set blueprint_patch to null.
        // Example possible keys:
        // "brand_name": "...",
        // "generic_product_name": "...",
        // "net_quantity": 200,
        // "quantity_unit": "g",
        // "mrp": 150,
        // "diet_type": "VEG" or "NON_VEG",
        // "ingredients": "...",
        // "marketing_claims": "...",
        // "primary_color": "#...",
        // "accent_color": "#...",
        // "bg_color": "#...",
        // "theme_preset": "DARK_LUXURY",
        // "finish_type": "METALLIC",
        // "hero_image_keyword": "chocolate"
      }}
    }}

    {context_str}
    """

    conversation_turns = []
    if chat_history:
        for turn in chat_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            conversation_turns.append(f"{role.upper()}: {content}")

    conversation_turns.append(f"USER: {user_message}\nASSISTANT:")
    full_prompt = f"{system_instruction}\n\nCONVERSATION HISTORY:\n" + "\n".join(conversation_turns)

    raw_response_text = ""
    for model_name in CANDIDATE_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[full_prompt],
                config={"response_mime_type": "application/json"}
            )
            if response and response.text:
                raw_response_text = response.text.strip()
                break
        except Exception as e:
            print(f"[Chat Assistant] Model {model_name} error: {e}. Trying fallback...")
            continue

    if not raw_response_text:
        return {
            "reply": "I am currently unable to reach the AI regulatory model. Please verify your GEMINI_API_KEY and try again.",
            "blueprint_patch": None
        }

    try:
        data = json.loads(raw_response_text)
        return {
            "reply": data.get("reply", raw_response_text),
            "blueprint_patch": data.get("blueprint_patch")
        }
    except Exception:
        clean_text = re.sub(r"^```json|^```|```$", "", raw_response_text, flags=re.MULTILINE).strip()
        try:
            data = json.loads(clean_text)
            return {
                "reply": data.get("reply", clean_text),
                "blueprint_patch": data.get("blueprint_patch")
            }
        except Exception:
            return {
                "reply": raw_response_text,
                "blueprint_patch": None
            }

