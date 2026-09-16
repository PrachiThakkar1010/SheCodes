import cv2
import json
import os
import time

from paddleocr import PaddleOCR


# ============================================================
# CONFIG
# ============================================================

ZONES_JSON = "region_zones_output/text_zones.json"

# Original product image
IMAGE_PATH = "product36_img2.jpeg"

OUTPUT_DIR = "selective_ocr_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# OCR MODEL
# ============================================================

print("=" * 70)
print("PARAKH SELECTIVE OCR")
print("=" * 70)

print("\nLoading PaddleOCR...")

model_start = time.perf_counter()

ocr = PaddleOCR(
    lang="en",
    device="cpu",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

model_time = time.perf_counter() - model_start

print(
    f"Model initialization: "
    f"{model_time:.2f} seconds"
)


# ============================================================
# LOAD IMAGE + ZONES
# ============================================================

with open(
    ZONES_JSON,
    "r",
    encoding="utf-8"
) as f:
    zone_data = json.load(f)


image = cv2.imread(IMAGE_PATH)

if image is None:
    raise FileNotFoundError(
        f"Could not load image:\n{IMAGE_PATH}"
    )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_result_value(res, key, default=None):
    """
    Safely retrieve a value from PaddleOCR's result object.
    """

    try:
        return res[key]
    except Exception:
        pass

    try:
        return res.get(key, default)
    except Exception:
        return default


def convert_box_to_list(box):
    """
    Convert PaddleOCR box data into a normal Python list.

    Supported formats:

    Rectangle:
        [x1, y1, x2, y2]

    Polygon:
        [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    """

    try:

        if hasattr(box, "tolist"):
            box = box.tolist()

        # Polygon
        if (
            isinstance(box, list)
            and len(box) > 0
            and isinstance(box[0], (list, tuple))
        ):

            return [
                [
                    float(point[0]),
                    float(point[1])
                ]
                for point in box
            ]

        # Rectangle
        if (
            isinstance(box, (list, tuple))
            and len(box) == 4
        ):

            return [
                float(value)
                for value in box
            ]

    except Exception:
        pass

    return None


def polygon_to_absolute_box(
    box,
    zone_x1,
    zone_y1
):
    """
    PaddleOCR performs recognition on the cropped zone.

    Therefore the OCR coordinates are relative to the crop.

    This function converts them back to coordinates
    relative to the ORIGINAL product image.
    """

    if box is None:
        return None

    try:

        # ----------------------------------------------------
        # Polygon
        # ----------------------------------------------------

        if (
            isinstance(box, list)
            and len(box) > 0
            and isinstance(box[0], list)
        ):

            absolute_polygon = []

            for point in box:

                absolute_polygon.append([
                    float(point[0]) + zone_x1,
                    float(point[1]) + zone_y1
                ])

            return absolute_polygon


        # ----------------------------------------------------
        # Rectangle
        # ----------------------------------------------------

        if (
            isinstance(box, list)
            and len(box) == 4
        ):

            return [
                float(box[0]) + zone_x1,
                float(box[1]) + zone_y1,
                float(box[2]) + zone_x1,
                float(box[3]) + zone_y1
            ]

    except Exception:
        pass

    return None


# ============================================================
# PROCESS ONE ZONE
# ============================================================

def process_zone(zone):

    zone_id = zone["zone_id"]

    x1, y1, x2, y2 = zone["box"]

    crop = image[y1:y2, x1:x2]

    if crop.size == 0:

        return {
            "zone_id": zone_id,
            "box": zone["box"],
            "text": "",
            "texts": [],
            "scores": [],
            "boxes": [],
            "items": [],
            "time_seconds": 0,
            "error": "Empty crop"
        }


    # --------------------------------------------------------
    # Save crop
    # --------------------------------------------------------

    crop_path = os.path.join(
        OUTPUT_DIR,
        f"zone_{zone_id:02d}.jpg"
    )

    cv2.imwrite(
        crop_path,
        crop
    )


    # --------------------------------------------------------
    # OCR
    # --------------------------------------------------------

    start = time.perf_counter()

    result = ocr.predict(crop)

    elapsed = (
        time.perf_counter()
        - start
    )


    # --------------------------------------------------------
    # Storage
    # --------------------------------------------------------

    texts = []
    scores = []
    boxes = []


    # ========================================================
    # READ PADDLEOCR RESULT
    # ========================================================

    for res in result:

        try:

            # ------------------------------------------------
            # Recognized text
            # ------------------------------------------------

            rec_texts = get_result_value(
                res,
                "rec_texts",
                []
            )

            if rec_texts is None:
                rec_texts = []

            try:
                rec_texts = list(rec_texts)
            except Exception:
                rec_texts = []


            # ------------------------------------------------
            # Recognition confidence
            # ------------------------------------------------

            rec_scores = get_result_value(
                res,
                "rec_scores",
                []
            )

            if rec_scores is None:
                rec_scores = []

            try:
                rec_scores = list(rec_scores)
            except Exception:
                rec_scores = []


            # ------------------------------------------------
            # Recognition boxes
            #
            # PaddleOCR v3/v6 commonly provides rec_boxes.
            # ------------------------------------------------

            rec_boxes = get_result_value(
                res,
                "rec_boxes",
                None
            )


            # ------------------------------------------------
            # Fallback to dt_polys if rec_boxes unavailable
            # ------------------------------------------------

            if rec_boxes is None:

                rec_boxes = get_result_value(
                    res,
                    "dt_polys",
                    None
                )


            if rec_boxes is None:

                rec_boxes = []

            else:

                try:
                    rec_boxes = list(rec_boxes)
                except Exception:
                    rec_boxes = []


            # =================================================
            # PROCESS EACH TEXT ITEM
            # =================================================

            for i, text in enumerate(rec_texts):

                text = str(text)

                texts.append(text)


                # ---------------------------------------------
                # Confidence
                # ---------------------------------------------

                if i < len(rec_scores):

                    try:

                        score = float(
                            rec_scores[i]
                        )

                    except Exception:

                        score = None

                else:

                    score = None


                scores.append(score)


                # ---------------------------------------------
                # Bounding box
                # ---------------------------------------------

                box = None

                if i < len(rec_boxes):

                    raw_box = convert_box_to_list(
                        rec_boxes[i]
                    )

                    box = polygon_to_absolute_box(
                        raw_box,
                        x1,
                        y1
                    )


                boxes.append(box)


        except Exception as e:

            print(
                f"Warning while reading OCR result "
                f"for zone {zone_id}: {e}"
            )


    # ========================================================
    # CREATE TEXT ITEMS
    # ========================================================

    items = []


    for i, text in enumerate(texts):

        if i < len(scores):

            confidence = scores[i]

        else:

            confidence = None


        if i < len(boxes):

            box = boxes[i]

        else:

            box = None


        items.append({
            "text": text,
            "confidence": confidence,
            "box": box
        })


    # ========================================================
    # COMBINED TEXT
    # ========================================================

    combined_text = "\n".join(
        texts
    )


    # ========================================================
    # AVERAGE CONFIDENCE
    # ========================================================

    valid_scores = [
        score
        for score in scores
        if score is not None
    ]


    average_confidence = None


    if valid_scores:

        average_confidence = (
            sum(valid_scores)
            / len(valid_scores)
        )


    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print("\n" + "-" * 70)

    print(
        f"ZONE {zone_id}"
    )

    print(
        f"Box: "
        f"[{x1}, {y1}, {x2}, {y2}]"
    )

    print(
        f"OCR time: "
        f"{elapsed:.3f} seconds"
    )

    print(
        f"Detected text items: "
        f"{len(items)}"
    )

    print(
        f"Average confidence: "
        f"{average_confidence}"
    )

    print("\nTEXT + BOXES:")


    for item in items:

        print(
            f"  {item['text']!r}"
            f" | confidence={item['confidence']}"
            f" | box={item['box']}"
        )


    if not items:

        print(
            "  [NO TEXT]"
        )


    # ========================================================
    # RETURN
    # ========================================================

    return {

        # Zone ID
        "zone_id": zone_id,

        # Zone box in ORIGINAL image
        "box": zone["box"],

        # Saved crop
        "crop": crop_path,

        # Combined text
        "text": combined_text,

        # Individual texts
        "texts": texts,

        # Individual confidence scores
        "scores": scores,

        # Individual OCR boxes
        "boxes": boxes,

        # Text + confidence + box
        "items": items,

        # Average confidence
        "average_confidence":
            average_confidence,

        # Processing time
        "time_seconds":
            elapsed
    }


# ============================================================
# PROCESS ALL ZONES
# ============================================================

overall_start = time.perf_counter()

results = []


for zone in zone_data["zones"]:

    result = process_zone(zone)

    results.append(result)


overall_time = (
    time.perf_counter()
    - overall_start
)


# ============================================================
# SAVE JSON
# ============================================================

output_path = os.path.join(
    OUTPUT_DIR,
    "selective_ocr_results.json"
)


output_data = {

    "image":
        os.path.basename(
            IMAGE_PATH
        ),

    "model_initialization_seconds":
        model_time,

    "ocr_processing_seconds":
        overall_time,

    "zones_processed":
        len(results),

    "results":
        results
}


with open(
    output_path,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output_data,
        f,
        indent=4,
        ensure_ascii=False
    )


# ============================================================
# SUMMARY
# ============================================================

print("\n")

print("=" * 70)

print(
    "SELECTIVE OCR SUMMARY"
)

print("=" * 70)

print(
    f"\nModel initialization: "
    f"{model_time:.2f}s"
)

print(
    f"OCR processing: "
    f"{overall_time:.2f}s"
)

print(
    f"Zones processed: "
    f"{len(results)}"
)

print(
    "\nResults saved to:"
    f"\n{output_path}"
)

print("=" * 70)