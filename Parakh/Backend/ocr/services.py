"""
ocr/services.py

Fast selective-OCR service for Parakh.

Pipeline:
    image
      ↓
    fast text detection
      ↓
    group detected text regions into zones
      ↓
    OCR only those zones
      ↓
    return line-level text + box + confidence

The returned line format is intentionally compatible with:
    labeler.py
    aggregator.py
    pipeline.py
"""

import os
import time

import cv2
import numpy as np
from PIL import Image

_detector_engine = None
_ocr_engine = None


# ============================================================
# MODEL SINGLETONS
# ============================================================

def _get_detector():
    """
    Load the lightweight PaddleOCR text detector once per process.

    Detection only gives us WHERE text exists.
    Recognition is performed later only on selected zones.
    """
    global _detector_engine

    if _detector_engine is None:
        from paddleocr import TextDetection

        print("[OCR] Loading lightweight text detector...")

        _detector_engine = TextDetection(
            model_name="PP-OCRv6_tiny_det"
        )

        print("[OCR] Text detector ready.")

    return _detector_engine


def _get_ocr_engine():
    """
    Load PaddleOCR recognition pipeline once per process.

    This is deliberately separate from the detector.
    """
    global _ocr_engine

    if _ocr_engine is None:
        from paddleocr import PaddleOCR

        print("[OCR] Loading recognition engine...")

        _ocr_engine = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

        print("[OCR] Recognition engine ready.")

    return _ocr_engine


# ============================================================
# IMAGE PREPARATION
# ============================================================

def _load_image(image_path):
    """
    Load image and resize only if it is excessively large.

    We cap the long edge at 2000 px because large phone images
    unnecessarily increase CPU inference time.
    """
    img = Image.open(image_path).convert("RGB")

    original_width, original_height = img.size

    MAX_LONG_EDGE = 2000

    long_edge = max(original_width, original_height)

    scale = 1.0

    if long_edge > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_edge

        new_width = int(original_width * scale)
        new_height = int(original_height * scale)

        img = img.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

    cv_img = cv2.cvtColor(
        np.array(img),
        cv2.COLOR_RGB2BGR,
    )

    return cv_img, scale


# ============================================================
# DETECTION
# ============================================================

def _detect_text_regions(image):
    """
    Detect text regions without performing recognition.

    Returns bounding boxes in the resized-image coordinate system.
    """
    detector = _get_detector()

    start = time.perf_counter()

    result = detector.predict(
        image,
        batch_size=1,
    )

    detection_time = time.perf_counter() - start

    # PaddleOCR 3.x returns a list of OCRResult-like objects.
    if not result:
        return [], detection_time

    res = result[0]

    polys = res.get("dt_polys", [])
    scores = res.get("dt_scores", [])

    regions = []

    for polygon, score in zip(polys, scores):

        confidence = float(score)

        # Ignore extremely weak detections.
        if confidence < 0.45:
            continue

        polygon = np.asarray(polygon)

        if polygon.ndim != 2 or polygon.shape[0] < 4:
            continue

        xs = polygon[:, 0]
        ys = polygon[:, 1]

        x1 = int(max(0, np.min(xs)))
        y1 = int(max(0, np.min(ys)))
        x2 = int(max(x1 + 1, np.max(xs)))
        y2 = int(max(y1 + 1, np.max(ys)))

        width = x2 - x1
        height = y2 - y1

        # Ignore tiny noise boxes.
        if width < 10 or height < 8:
            continue

        regions.append({
            "box": [x1, y1, x2, y2],
            "confidence": confidence,
        })

    return regions, detection_time


# ============================================================
# ZONE BUILDING
# ============================================================

def _build_text_zones(regions, image_width, image_height):
    """
    Group nearby detected text regions into larger OCR zones.

    The purpose is NOT to make one crop per word.

    Instead, nearby lines are grouped together so PaddleOCR
    can recognize several declarations in one call.
    """

    if not regions:
        return []

    # Sort top-to-bottom.
    regions = sorted(
        regions,
        key=lambda r: (
            r["box"][1],
            r["box"][0],
        ),
    )

    zones = []

    # Vertical gap threshold.
    # Larger than a normal line gap but small enough to avoid
    # combining completely separate package panels.
    GAP_THRESHOLD = 45

    for region in regions:

        x1, y1, x2, y2 = region["box"]

        placed = False

        for zone in zones:

            zx1, zy1, zx2, zy2 = zone["box"]

            vertical_gap = max(
                0,
                max(y1, zy1) - min(y2, zy2)
            )

            horizontal_overlap = max(
                0,
                min(x2, zx2) - max(x1, zx1)
            )

            smaller_width = max(
                1,
                min(x2 - x1, zx2 - zx1)
            )

            overlap_ratio = horizontal_overlap / smaller_width

            # Join if vertically close and horizontally related.
            if (
                vertical_gap <= GAP_THRESHOLD
                and overlap_ratio >= 0.10
            ):
                zone["box"] = [
                    min(zx1, x1),
                    min(zy1, y1),
                    max(zx2, x2),
                    max(zy2, y2),
                ]

                zone["regions"].append(region)

                placed = True
                break

        if not placed:
            zones.append({
                "box": [x1, y1, x2, y2],
                "regions": [region],
            })

    # Add padding around each zone.
    PAD_X = 15
    PAD_Y = 12

    final_zones = []

    for zone in zones:

        x1, y1, x2, y2 = zone["box"]

        x1 = max(0, x1 - PAD_X)
        y1 = max(0, y1 - PAD_Y)
        x2 = min(image_width, x2 + PAD_X)
        y2 = min(image_height, y2 + PAD_Y)

        width = x2 - x1
        height = y2 - y1

        # Avoid absurdly tiny zones.
        if width < 30 or height < 15:
            continue

        final_zones.append({
            "box": [x1, y1, x2, y2],
            "regions": zone["regions"],
        })

    # Merge overlapping zones once more.
    merged = []

    for zone in final_zones:

        x1, y1, x2, y2 = zone["box"]

        merged_into_existing = False

        for existing in merged:

            ex1, ey1, ex2, ey2 = existing["box"]

            intersection_x = max(
                0,
                min(x2, ex2) - max(x1, ex1)
            )

            intersection_y = max(
                0,
                min(y2, ey2) - max(y1, ey1)
            )

            intersection = intersection_x * intersection_y

            area1 = max(1, (x2 - x1) * (y2 - y1))
            area2 = max(1, (ex2 - ex1) * (ey2 - ey1))

            if intersection / min(area1, area2) > 0.20:

                existing["box"] = [
                    min(ex1, x1),
                    min(ey1, y1),
                    max(ex2, x2),
                    max(ey2, y2),
                ]

                existing["regions"].extend(
                    zone["regions"]
                )

                merged_into_existing = True
                break

        if not merged_into_existing:
            merged.append(zone)

    return merged


# ============================================================
# ZONE OCR
# ============================================================

def _ocr_zone(
    engine,
    image,
    zone,
    image_scale,
    image_id,
):
    """
    OCR a single selected zone.

    Convert the OCR coordinates back into the original image
    coordinate system so the rest of Parakh sees useful boxes.
    """

    x1, y1, x2, y2 = zone["box"]

    crop = image[y1:y2, x1:x2]

    if crop.size == 0:
        return []

    try:
        results = engine.predict(crop)
    except Exception as exc:
        print(
            f"[OCR] Zone failed for {image_id}: {exc}"
        )
        return []

    if not results:
        return []

    lines = []

    for res in results:

        texts = res.get("rec_texts", [])
        boxes = res.get("rec_boxes", [])
        scores = res.get("rec_scores", [])

        for text, box, score in zip(
            texts,
            boxes,
            scores,
        ):

            text = str(text or "").strip()

            if not text:
                continue

            box = list(box)

            if len(box) == 4:

                bx1, by1, bx2, by2 = [
                    float(v)
                    for v in box
                ]

            else:

                xs = [
                    float(point[0])
                    for point in box
                ]

                ys = [
                    float(point[1])
                    for point in box
                ]

                bx1 = min(xs)
                by1 = min(ys)
                bx2 = max(xs)
                by2 = max(ys)

            # Convert crop coordinates → resized image coordinates.
            rx1 = bx1 + x1
            ry1 = by1 + y1
            rx2 = bx2 + x1
            ry2 = by2 + y1

            # Convert resized image → original image coordinates.
            if image_scale != 1.0:
                rx1 /= image_scale
                ry1 /= image_scale
                rx2 /= image_scale
                ry2 /= image_scale

            lines.append({
                "text": text,
                "box": [
                    float(rx1),
                    float(ry1),
                    float(rx2),
                    float(ry2),
                ],
                "confidence": float(score),
                "image_id": image_id,
                "width": float(rx2 - rx1),
                "height": float(ry2 - ry1),
            })

    return lines


# ============================================================
# ONE IMAGE
# ============================================================

def _extract_lines_from_image(
    image_path,
    image_id,
):
    """
    Fast selective OCR for one image.
    """

    total_start = time.perf_counter()

    # --------------------------------------------------------
    # Load / resize
    # --------------------------------------------------------

    image, image_scale = _load_image(
        image_path
    )

    image_height, image_width = image.shape[:2]

    # --------------------------------------------------------
    # Detection
    # --------------------------------------------------------

    regions, detection_time = _detect_text_regions(
        image
    )

    # --------------------------------------------------------
    # Zone construction
    # --------------------------------------------------------

    zone_start = time.perf_counter()

    zones = _build_text_zones(
        regions,
        image_width,
        image_height,
    )

    zone_time = time.perf_counter() - zone_start

    print(
        f"[OCR] {image_id}: "
        f"{len(regions)} text regions → "
        f"{len(zones)} zones"
    )

    # --------------------------------------------------------
    # Recognition
    # --------------------------------------------------------

    engine = _get_ocr_engine()

    recognition_start = time.perf_counter()

    lines = []

    for zone in zones:

        zone_lines = _ocr_zone(
            engine,
            image,
            zone,
            image_scale,
            image_id,
        )

        lines.extend(zone_lines)

    recognition_time = (
        time.perf_counter()
        - recognition_start
    )

    total_time = (
        time.perf_counter()
        - total_start
    )

    print(
        f"[OCR TIMING] {image_id}: "
        f"detection={detection_time:.2f}s | "
        f"zones={zone_time:.2f}s | "
        f"recognition={recognition_time:.2f}s | "
        f"total={total_time:.2f}s | "
        f"lines={len(lines)}"
    )

    return lines


# ============================================================
# FULL SCAN
# ============================================================

def extract_lines_for_scan(scan_instance):
    """
    Run selective OCR across every image attached to a scan.

    Returns one combined list of line dictionaries.
    """

    total_start = time.perf_counter()

    all_lines = []

    image_qs = scan_instance.images.all()

    if not image_qs.exists():

        # Backward compatibility for old single-image scans.
        if scan_instance.image:

            print(
                "[OCR] No ProductScanImage rows found; "
                "using legacy scan.image"
            )

            all_lines.extend(
                _extract_lines_from_image(
                    scan_instance.image.path,
                    "primary",
                )
            )

        total_time = (
            time.perf_counter()
            - total_start
        )

        print(
            f"[OCR TOTAL] {total_time:.2f}s | "
            f"lines={len(all_lines)}"
        )

        return all_lines

    image_records = list(
        image_qs.order_by("order", "id")
    )

    print(
        f"\n[OCR] Starting selective OCR "
        f"for {len(image_records)} image(s)"
    )

    for image_record in image_records:

        image_id = f"img{image_record.id}"

        print(
            f"\n[OCR] PROCESSING {image_id}"
        )

        lines = _extract_lines_from_image(
            image_record.image.path,
            image_id,
        )

        all_lines.extend(lines)

    total_time = (
        time.perf_counter()
        - total_start
    )

    print(
        f"\n[OCR TOTAL] "
        f"{total_time:.2f}s | "
        f"{len(image_records)} image(s) | "
        f"{len(all_lines)} OCR lines\n"
    )

    return all_lines


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

def process_image_ocr(scan_instance):
    """
    Backward-compatible helper.

    Runs the new selective OCR pipeline and saves the flattened
    OCR text into ExtractedLabelData.raw_ocr_text.
    """

    from products.models import ExtractedLabelData

    lines = extract_lines_for_scan(
        scan_instance
    )

    extracted_text = "\n".join(
        line["text"]
        for line in lines
    )

    label_data, created = (
        ExtractedLabelData.objects.get_or_create(
            scan=scan_instance,
            defaults={
                "raw_ocr_text": extracted_text
            },
        )
    )

    if not created:

        label_data.raw_ocr_text = extracted_text

        label_data.save(
            update_fields=["raw_ocr_text"]
        )

    return extracted_text