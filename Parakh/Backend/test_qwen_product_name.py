import json
import time
from pathlib import Path

from compliance.engine.qwen_service import ask_qwen


IMAGE_1 = Path("product36_img1.jpeg").resolve()
IMAGE_2 = Path("product36_img2.jpeg").resolve()


def main():

    print("=" * 70)
    print("QWEN3-VL PRODUCT NAME TEST")
    print("=" * 70)

    if not IMAGE_1.exists():
        raise FileNotFoundError(
            f"Image 1 not found: {IMAGE_1}"
        )

    if not IMAGE_2.exists():
        raise FileNotFoundError(
            f"Image 2 not found: {IMAGE_2}"
        )

    print(f"Front image: {IMAGE_1}")
    print(f"Back image : {IMAGE_2}")

    prompt = """
You are a visual product-package inspector.

The two images show the FRONT and BACK of the SAME consumer
product package.

Your ONLY task is to identify the product's declared name.

IMPORTANT:
1. Use BOTH images together.
2. Identify the actual product/commodity name.
3. Do NOT include marketing slogans or claims.
4. Do NOT include ingredient information.
5. Do NOT include manufacturer information.
6. Do NOT include directions or instructions.
7. Do NOT include quantity, MRP, dates, batch number, or
   other packaging information.
8. If the product name cannot be determined confidently,
   return null.
9. Do not guess information that is not visible.
10. Return ONLY valid JSON.
11. Do not use markdown.
12. Do not provide explanations.

Return exactly:

{
    "product_name": null,
    "confidence": null,
    "evidence": null
}
"""

    print("\nSending images to Qwen...")
    print("Task: PRODUCT NAME ONLY")

    start = time.time()

    result = ask_qwen(
        [IMAGE_1, IMAGE_2],
        prompt,
        max_new_tokens=150,
    )

    elapsed = time.time() - start

    print("\n" + "=" * 70)
    print("QWEN RAW OUTPUT")
    print("=" * 70)

    print(result)

    print("=" * 70)
    print(f"Total Qwen time: {elapsed:.2f} seconds")
    print("=" * 70)

    # --------------------------------------------------------
    # Try to parse JSON
    # --------------------------------------------------------

    try:
        parsed = json.loads(result)

        print("\nParsed result:")
        print(
            json.dumps(
                parsed,
                indent=2,
                ensure_ascii=False,
            )
        )

    except json.JSONDecodeError:
        print("\nWARNING:")
        print("Qwen did not return valid JSON.")

    # --------------------------------------------------------
    # Save result
    # --------------------------------------------------------

    output_dir = Path("qwen_test")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "product_name_result.json"

    output_file.write_text(
        result,
        encoding="utf-8",
    )

    print(
        f"\nResult saved to: "
        f"{output_file.resolve()}"
    )


if __name__ == "__main__":
    main()