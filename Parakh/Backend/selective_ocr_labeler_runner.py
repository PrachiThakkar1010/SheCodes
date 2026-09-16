import json
import os
import re

from compliance.engine import labeler
from compliance.engine import aggregator


# ============================================================
# CONFIG
# ============================================================

OCR_JSON = "selective_ocr_output/selective_ocr_results.json"

OUTPUT_DIR = "selective_ocr_output"

OUTPUT_JSON = os.path.join(
    OUTPUT_DIR,
    "labeler_aggregator_results.json"
)


# ============================================================
# LOAD OCR RESULTS
# ============================================================

with open(
    OCR_JSON,
    "r",
    encoding="utf-8"
) as f:

    ocr_data = json.load(f)


# ============================================================
# HELPERS
# ============================================================

def make_line(
    text,
    confidence,
    box,
    image_id
):
    """
    Create one OCR line in the format expected
    by the existing labeler.
    """

    return {
        "text": text,
        "confidence": (
            float(confidence)
            if confidence is not None
            else 0.0
        ),
        "box": box,
        "image_id": image_id
    }


def split_special_line(
    item,
    image_id
):
    """
    Split lines where PaddleOCR merged multiple important
    fields into one recognition result.

    Example:

        *49.00#09/25

    becomes:

        MRP ₹49.00
        MFD 09/25

    and:

        @08/28,1.23/ml

    becomes:

        EXP 08/28
        UNIT SALE PRICE 1.23/ml
    """

    text = item["text"]
    confidence = item["confidence"]
    box = item["box"]

    lines = []


    # ========================================================
    # MRP + MFD
    # ========================================================

    match = re.search(
        r"49\.00.*?(\d{2}/\d{2})",
        text,
        re.IGNORECASE
    )

    if match and (
        "49.00" in text
        or "₹49" in text
        or "MRP" in text.upper()
    ):

        date_value = match.group(1)

        lines.append(
            make_line(
                f"MRP ₹49.00",
                confidence,
                box,
                image_id
            )
        )

        lines.append(
            make_line(
                f"MFD {date_value}",
                confidence,
                box,
                image_id
            )
        )

        return lines


    # ========================================================
    # GENERIC MRP + DATE
    # ========================================================

    mrp_match = re.search(
        r"(?:₹|Rs\.?|MRP)?\s*"
        r"(\d+(?:\.\d{1,2})?)"
        r".*?"
        r"(\d{2}/\d{2})",
        text,
        re.IGNORECASE
    )

    if mrp_match:

        mrp_value = mrp_match.group(1)
        date_value = mrp_match.group(2)

        lines.append(
            make_line(
                f"MRP ₹{mrp_value}",
                confidence,
                box,
                image_id
            )
        )

        lines.append(
            make_line(
                f"MFD {date_value}",
                confidence,
                box,
                image_id
            )
        )

        return lines


    # ========================================================
    # EXPIRY + UNIT SALE PRICE
    # ========================================================

    expiry_match = re.search(
        r"(\d{2}/\d{2})",
        text
    )

    unit_match = re.search(
        r"(\d+(?:\.\d+)?\s*/\s*[A-Za-z]+)",
        text
    )

    if expiry_match and (
        "@" in text
        or "EXP" in text.upper()
    ):

        expiry_value = expiry_match.group(1)

        lines.append(
            make_line(
                f"EXP {expiry_value}",
                confidence,
                box,
                image_id
            )
        )

        if unit_match:

            lines.append(
                make_line(
                    f"UNIT SALE PRICE {unit_match.group(1)}",
                    confidence,
                    box,
                    image_id
                )
            )

        return lines


    # ========================================================
    # NORMAL LINE
    # ========================================================

    lines.append(
        make_line(
            text,
            confidence,
            box,
            image_id
        )
    )

    return lines


# ============================================================
# CONVERT OCR → LABELER INPUT
# ============================================================

all_lines = []


for zone in ocr_data["results"]:

    image_id = ocr_data.get(
        "image",
        "unknown"
    )


    # --------------------------------------------------------
    # NEW FORMAT
    # --------------------------------------------------------

    if "items" in zone:

        for item in zone["items"]:

            text = str(
                item.get(
                    "text",
                    ""
                )
            ).strip()

            if not text:
                continue


            confidence = item.get(
                "confidence"
            )

            box = item.get(
                "box"
            )


            special_lines = (
                split_special_line(
                    item,
                    image_id
                )
            )

            all_lines.extend(
                special_lines
            )


    # --------------------------------------------------------
    # SAFETY FALLBACK
    # --------------------------------------------------------

    else:

        texts = zone.get(
            "texts",
            []
        )

        scores = zone.get(
            "scores",
            []
        )

        boxes = zone.get(
            "boxes",
            []
        )


        for i, text in enumerate(texts):

            confidence = (
                scores[i]
                if i < len(scores)
                else 0.0
            )

            box = (
                boxes[i]
                if i < len(boxes)
                else zone.get("box")
            )


            item = {
                "text": text,
                "confidence": confidence,
                "box": box
            }


            all_lines.extend(
                split_special_line(
                    item,
                    image_id
                )
            )


# ============================================================
# REMOVE EMPTY LINES
# ============================================================

all_lines = [
    line
    for line in all_lines
    if line["text"].strip()
]


# ============================================================
# DEBUG: SHOW LABELER INPUT
# ============================================================

print("\n")
print("=" * 70)
print("OCR → LABELER INPUT")
print("=" * 70)

print(
    f"\nTotal OCR lines: "
    f"{len(all_lines)}"
)


for i, line in enumerate(all_lines):

    print(
        f"{i + 1:02d}. "
        f"{line['text']!r}"
        f" | conf={line['confidence']:.3f}"
        f" | box={line['box']}"
    )


# ============================================================
# RUN ACTUAL LABELER
# ============================================================

print("\n")
print("=" * 70)
print("RUNNING ACTUAL LABELER")
print("=" * 70)


labeled_lines = labeler.label_lines(
    all_lines
)


# ============================================================
# SHOW LABELER OUTPUT
# ============================================================

print("\n")
print("=" * 70)
print("LABELER OUTPUT")
print("=" * 70)


for line in labeled_lines:

    print(
        f"{line.get('text', '')!r}"
        f" → "
        f"{line.get('label', 'UNKNOWN')}"
    )


# ============================================================
# RUN ACTUAL AGGREGATOR
# ============================================================

print("\n")
print("=" * 70)
print("RUNNING ACTUAL AGGREGATOR")
print("=" * 70)


aggregated = aggregator.aggregate_lines(
    labeled_lines
)


# ============================================================
# PRINT AGGREGATOR OUTPUT
# ============================================================

print("\n")
print("=" * 70)
print("AGGREGATOR OUTPUT")
print("=" * 70)


print(
    f"\nProduct type       : "
    f"{aggregated.get('product_type')}"
)


fields_to_print = [
    "product_name",
    "manufacturer",
    "manufacturer_address",
    "net_quantity",
    "manufacturing_date",
    "expiry_date",
    "batch_number",
    "mrp",
    "fssai_license",
    "consumer_contact",
    "nutrition"
]


for field in fields_to_print:

    print(
        f"{field:22s}: "
        f"{aggregated.get(field)}"
    )


# ============================================================
# SAVE
# ============================================================

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


output_data = {

    "ocr_source":
        OCR_JSON,

    "labeler_input":
        all_lines,

    "labeled_lines":
        labeled_lines,

    "aggregated":
        aggregated
}


with open(
    OUTPUT_JSON,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output_data,
        f,
        indent=4,
        ensure_ascii=False
    )


print("\n")
print(
    f"Results saved to:\n{OUTPUT_JSON}"
)

print("=" * 70)