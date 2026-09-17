import json
import os
import re
import time
from PIL import Image
from google import genai
from google.genai.errors import ServerError, ClientError
from django.conf import settings


def audit_compliance_vision(image_sources: list) -> dict:
    api_key = getattr(settings, "GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    loaded_images = []
    for src in image_sources:
        try:
            img = Image.open(src)
            img.thumbnail((1600, 1600))
            loaded_images.append(img)
        except Exception as e:
            print(f"Error loading image: {e}")

    if not loaded_images:
        return {
            "product_name": "Unknown Product",
            "is_compliant": False,
            "violations": [],
            "nutritional_values": [],
            "additives": []
        }

    prompt = """
        You are an expert Indian packaging compliance auditor under:
        1. Legal Metrology (Packaged Commodities) Rules, 2011.
        2. FSSAI (Food Safety and Standards - Labelling and Display) Regulations, 2020.

        CRITICAL RULES FOR MULTI-PANEL EVALUATION:
        1. ZERO FALSE POSITIVES ON MULTI-PANEL PACKAGING:
           - Standard Indian commercial products (like Parle-G, Britannia, Amul) place information across different panels.
           - Declarations (MRP, Dates, Batch No., Net Weight, Manufacturer Details, Ingredients, Nutrition Table, Veg/Non-Veg Symbol, FSSAI License Number) are legally valid whether they appear on the front, back, side flaps, or bottom.
           - DO NOT invent "Principal Display Panel (PDP)" violations if the required information is present anywhere across the provided images.
           - If an item is visible on ANY photo, it is FULLY COMPLIANT. Mark it as present.

        2. ONLY FLAG TRUE DEFECTS:
           - Only report a violation if a mandatory declaration is completely absent across ALL 4 images, completely unreadable, or contains a direct factual contradiction (e.g. contradictory expiry dates).
           - If all mandatory details are present across the pack, "violations" MUST be an empty list [] and "is_compliant" must be true.

        3. TASKS:
           - COMPLIANCE AUDIT: Verify mandatory statutory declarations across all panels.
           - NUTRITIONAL VALUES: Extract per 100g data visible on the pack.
           - ADDITIVES: Extract INS numbers / ingredients declared on the pack.

        Return ONLY valid JSON matching this schema:
        {
          "product_name": "Brand and full product name",
          "is_compliant": true,
          "summary_text": "Brief factual summary of compliance status across all inspected panels.",
          "violations": [
            {
              "title": "Short title of actual missing item or violation",
              "description": "Factual description of what is missing across all panels.",
              "violated_rule": "Exact Act and Rule clause"
            }
          ],
          "serving_basis": "Per 100g or per serving as declared on package",
          "nutritional_values": [
            {"nutrient": "Energy", "amount": "...", "daily_value": "..."}
          ],
          "additives": [
            {"code_name": "...", "note": "..."}
          ],
          "no_banned_substances": true
        }
        """

    contents = [prompt] + loaded_images

    # Iterate through models sequentially (model parameter must be a string)
    candidate_models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.6-flash",
    ]

    response = None
    last_error = None

    for model_name in candidate_models:
        for attempt in range(2):
            try:
                print(f"[Compliance Engine] Querying {model_name} (attempt {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    break
            except ServerError as err:
                print(f"[Compliance Engine] 503 spike on {model_name}: {err}. Retrying in 2s...")
                last_error = err
                time.sleep(2)
            except ClientError as err:
                print(f"[Compliance Engine] {model_name} unavailable ({err}). Falling back...")
                last_error = err
                break

        if response and response.text:
            break

    if not response or not response.text:
        raise last_error or RuntimeError("Failed to obtain a response from Gemini models.")

    raw_text = response.text.strip()
    try:
        return json.loads(raw_text)
    except Exception:
        clean_text = re.sub(r"^```json|^```|```$", "", raw_text, flags=re.MULTILINE).strip()
        return json.loads(clean_text)