import json
import time
from pathlib import Path

from PIL import Image
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor

MODEL_NAME = "Qwen/Qwen3-VL-4B-Instruct"

IMAGE_1 = Path("qwen_test/product36_img1.jpeg").resolve()
IMAGE_2 = Path("qwen_test/product36_img2.jpeg").resolve()


def main():
    print("=" * 70)
    print("QWEN3-VL TEST")
    print("=" * 70)

    print(f"Image 1: {IMAGE_1}")
    print(f"Image 2: {IMAGE_2}")

    if not IMAGE_1.exists():
        raise FileNotFoundError(f"Image 1 not found: {IMAGE_1}")

    if not IMAGE_2.exists():
        raise FileNotFoundError(f"Image 2 not found: {IMAGE_2}")

    print("\nLoading Qwen3-VL 4B...")
    print("This may take a while on CPU.\n")

    start = time.time()

    model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL_NAME,
        dtype="auto",
        device_map="auto",
    )

    processor = AutoProcessor.from_pretrained(MODEL_NAME)

    print(f"Model loaded in {time.time() - start:.2f} seconds")

    # Load the actual images with PIL.
    # Passing PIL images directly avoids the Windows file:// issue.
    image1 = Image.open(IMAGE_1).convert("RGB")
    image2 = Image.open(IMAGE_2).convert("RGB")

    print(f"Image 1 size: {image1.size}")
    print(f"Image 2 size: {image2.size}")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image1,
                },
                {
                    "type": "image",
                    "image": image2,
                },
                {
                    "type": "text",
                    "text": """
You are analyzing photographs of the FRONT and BACK of the SAME consumer product package.

Your job is to visually understand the package like a human inspector.

Extract the information that is actually visible in the photographs.

IMPORTANT:
1. Use BOTH images together.
2. Do not assume that text belongs to a field just because it contains numbers.
3. Distinguish MRP from unit sale price.
4. Distinguish manufacturing/packing date from expiry/use-before date.
5. Distinguish batch number from plot number, license number, telephone number, PIN code, etc.
6. Do not confuse the manufacturer's address with the product name.
7. Determine whether this is FOOD or NON_FOOD.
8. For a cosmetic/body lotion, FSSAI should be NOT_APPLICABLE.
9. If a field is not visible or cannot be determined confidently, return null.
10. Do NOT make a legal compliance decision.
11. Return ONLY valid JSON. No markdown and no explanation.

Return exactly this structure:

{
  "product": {
    "name": null,
    "type": null,
    "category": null
  },
  "net_quantity": {
    "value": null,
    "unit": null,
    "evidence": null,
    "confidence": null
  },
  "mrp": {
    "value": null,
    "evidence": null,
    "confidence": null
  },
  "manufacturing_date": {
    "value": null,
    "evidence": null,
    "confidence": null
  },
  "expiry_date": {
    "value": null,
    "evidence": null,
    "confidence": null
  },
  "batch_number": {
    "value": null,
    "evidence": null,
    "confidence": null
  },
  "unit_sale_price": {
    "value": null,
    "evidence": null,
    "confidence": null
  },
  "manufacturer": {
    "name": null,
    "address": null,
    "evidence": null,
    "confidence": null
  },
  "consumer_care": {
    "phone": null,
    "email": null,
    "evidence": null,
    "confidence": null
  },
  "fssai": {
    "value": null,
    "confidence": null
  },
  "nutrition": null,
  "important_declarations": [],
  "uncertain_fields": []
}
""",
                },
            ],
        }
    ]

    print("\nPreparing images...")
    start_inference = time.time()

    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )

    # Some Transformers/Qwen combinations include this field,
    # but the Qwen3-VL generation path does not need it.
    inputs.pop("token_type_ids", None)

    inputs = inputs.to(model.device)

    print("Running Qwen3-VL inference...")
    print("CPU inference can take several minutes. Please let it finish.\n")

    generated_ids = model.generate(
        **inputs,
        max_new_tokens=1200,
        do_sample=False,
    )

    generated_ids_trimmed = [
        out_ids[len(in_ids):]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]

    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    elapsed = time.time() - start_inference

    print("=" * 70)
    print("QWEN OUTPUT")
    print("=" * 70)
    print(output_text)
    print("=" * 70)

    print(f"\nInference time: {elapsed:.2f} seconds")

    # Try to save the raw response
    output_file = Path("qwen_test/qwen_result.txt")
    output_file.write_text(output_text, encoding="utf-8")

    print(f"\nRaw result saved to:")
    print(output_file.resolve())


if __name__ == "__main__":
    main()