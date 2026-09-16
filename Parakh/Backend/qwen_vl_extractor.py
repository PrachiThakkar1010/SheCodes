import json
import torch

from transformers import (
    Qwen3VLForConditionalGeneration,
    AutoProcessor,
)


MODEL_NAME = "Qwen/Qwen3-VL-4B-Instruct"


class QwenPackageAnalyzer:

    def __init__(self):

        print("=" * 60)
        print("Loading Qwen3-VL-4B-Instruct")
        print("=" * 60)

        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print("Device:", self.device)

        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_NAME,
            dtype="auto",
            device_map="auto",
        )

        self.processor = AutoProcessor.from_pretrained(
            MODEL_NAME
        )

        print("Qwen3-VL loaded.")
        print("=" * 60)

    def analyze(self, image_paths):

        prompt = """
You are a visual packaging-analysis system.

You are given photographs of the SAME product package.
Analyze ALL supplied images together.

Your job is to extract FACTS from the package.
Do NOT decide legal compliance.

Use the actual visual appearance of the package.
OCR-like mistakes may occur, so use visual context.

IMPORTANT:

1. Identify the complete product name.
2. Decide whether the product is FOOD or NON_FOOD.
3. Extract net quantity.
4. Find the Maximum Retail Price (MRP).
5. Find manufacturing/packing date.
6. Find expiry/use-before/best-before date.
7. Find batch/lot number.
8. Find manufacturer name.
9. Find manufacturer address.
10. Find consumer-care phone/email.
11. Find FSSAI license number if present.
12. Find nutrition information if present.
13. Find important packaging declarations.

VERY IMPORTANT:

- Do NOT confuse MRP with unit sale price.
- Do NOT confuse manufacturing date with expiry date.
- Do NOT confuse batch number with plot number.
- Do NOT confuse batch number with license number.
- Do NOT confuse telephone numbers with batch numbers.
- Do NOT invent information.
- If you cannot confidently determine something, return null.
- Search the ENTIRE supplied package, not just the front.

For every important field, provide the exact visual evidence.

Return ONLY valid JSON.

Use exactly this structure:

{
    "product": {
        "name": null,
        "type": null,
        "category": null
    },

    "net_quantity": {
        "value": null,
        "unit": null,
        "evidence": null
    },

    "mrp": {
        "value": null,
        "evidence": null
    },

    "manufacturing_date": {
        "value": null,
        "evidence": null
    },

    "expiry": {
        "value": null,
        "evidence": null
    },

    "batch_number": {
        "value": null,
        "evidence": null
    },

    "manufacturer": {
        "name": null,
        "address": null
    },

    "consumer_care": {
        "phone": null,
        "email": null
    },

    "fssai_license": null,

    "nutrition": [],

    "important_declarations": []
}
"""

        content = []

        for image_path in image_paths:

            content.append(
                {
                    "type": "image",
                    "image": image_path,
                }
            )

        content.append(
            {
                "type": "text",
                "text": prompt,
            }
        )

        messages = [
            {
                "role": "user",
                "content": content,
            }
        ]

        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )

        # Some Transformers/Qwen versions include this field,
        # which is not needed for generation.
        if "token_type_ids" in inputs:
            inputs.pop("token_type_ids")

        inputs = inputs.to(self.model.device)

        print("Running Qwen inference...")
        print("This may take a while on CPU.")

        with torch.inference_mode():

            outputs = self.model.generate(
                **inputs,
                max_new_tokens=1200,
            )

        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids
            in zip(inputs.input_ids, outputs)
        ]

        response = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]

        print("\n========== RAW QWEN RESPONSE ==========\n")
        print(response)

        return self._parse_json(response)

    @staticmethod
    def _parse_json(response):

        response = response.strip()

        if response.startswith("```json"):
            response = response[7:]

        elif response.startswith("```"):
            response = response[3:]

        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        try:

            return json.loads(response)

        except json.JSONDecodeError:

            return {
                "error": "Qwen did not return valid JSON",
                "raw_response": response,
            }