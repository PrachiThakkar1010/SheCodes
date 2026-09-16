import sys
import time
import json
from pathlib import Path

import cv2
from paddleocr import TextDetection


MODEL_NAME = "PP-OCRv6_tiny_det"

OUTPUT_DIR = Path("region_detection_output")
OUTPUT_DIR.mkdir(exist_ok=True)


def resize_for_detection(image, max_side=1600):
    """
    Resize large camera images while preserving aspect ratio.
    """
    h, w = image.shape[:2]

    longest = max(h, w)

    if longest <= max_side:
        return image

    scale = max_side / longest

    new_w = int(w * scale)
    new_h = int(h * scale)

    return cv2.resize(
        image,
        (new_w, new_h),
        interpolation=cv2.INTER_AREA,
    )


def detect_regions(image_path, detector):

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError(f"Could not read image: {image_path}")

    original_h, original_w = image.shape[:2]

    print(f"\nImage: {image_path}")
    print(f"Original size: {original_w} x {original_h}")

    # Resize image for the detection stage.
    detection_image = resize_for_detection(image)

    detection_h, detection_w = detection_image.shape[:2]

    print(
        f"Detection size: "
        f"{detection_w} x {detection_h}"
    )

    # ---------------------------------------------------------
    # Run text detection
    # ---------------------------------------------------------

    start = time.perf_counter()

    results = detector.predict(
        detection_image,
        batch_size=1,
    )

    detection_time = time.perf_counter() - start

    print(
        f"Detection time: "
        f"{detection_time:.2f} seconds"
    )

    # ---------------------------------------------------------
    # Extract boxes
    # ---------------------------------------------------------

    all_regions = []

    for result in results:

        polys = result["dt_polys"]
        scores = result["dt_scores"]

        for poly, score in zip(polys, scores):

            points = poly.tolist()

            xs = [p[0] for p in points]
            ys = [p[1] for p in points]

            x1 = max(0, int(min(xs)))
            y1 = max(0, int(min(ys)))
            x2 = min(detection_w, int(max(xs)))
            y2 = min(detection_h, int(max(ys)))

            width = x2 - x1
            height = y2 - y1

            all_regions.append(
                {
                    "box": [
                        x1,
                        y1,
                        x2,
                        y2,
                    ],
                    "confidence": float(score),
                    "width": width,
                    "height": height,
                }
            )

    # ---------------------------------------------------------
    # Sort regions top-to-bottom, then left-to-right
    # ---------------------------------------------------------

    all_regions.sort(
        key=lambda r: (
            r["box"][1],
            r["box"][0],
        )
    )

    print(
        f"Detected text regions: "
        f"{len(all_regions)}"
    )

    # ---------------------------------------------------------
    # Draw visualization
    # ---------------------------------------------------------

    visual = detection_image.copy()

    for index, region in enumerate(
        all_regions,
        start=1,
    ):

        x1, y1, x2, y2 = region["box"]

        cv2.rectangle(
            visual,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2,
        )

        cv2.putText(
            visual,
            str(index),
            (
                x1,
                max(20, y1 - 5),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )

    # ---------------------------------------------------------
    # Save visualization
    # ---------------------------------------------------------

    output_name = Path(image_path).stem

    output_image = (
        OUTPUT_DIR
        / f"{output_name}_regions.jpg"
    )

    cv2.imwrite(
        str(output_image),
        visual,
    )

    # ---------------------------------------------------------
    # Save JSON
    # ---------------------------------------------------------

    output_json = (
        OUTPUT_DIR
        / f"{output_name}_regions.json"
    )

    with open(
        output_json,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "image": str(image_path),
                "original_size": [
                    original_w,
                    original_h,
                ],
                "detection_size": [
                    detection_w,
                    detection_h,
                ],
                "detection_time_seconds":
                    round(
                        detection_time,
                        3,
                    ),
                "regions": all_regions,
            },
            f,
            indent=2,
        )

    # ---------------------------------------------------------
    # Print regions
    # ---------------------------------------------------------

    print("\nDetected regions:")
    print("-" * 75)

    for i, region in enumerate(
        all_regions,
        start=1,
    ):

        print(
            f"{i:03d} | "
            f"box={region['box']} | "
            f"size="
            f"{region['width']}x"
            f"{region['height']} | "
            f"confidence="
            f"{region['confidence']:.3f}"
        )

    print("-" * 75)

    print(
        f"\nSaved visualization:\n"
        f"{output_image}"
    )

    print(
        f"\nSaved JSON:\n"
        f"{output_json}"
    )

    return all_regions


def main():

    if len(sys.argv) < 2:

        print(
            "\nUsage:\n"
            "python region_detection_poc.py "
            "<image_path>\n"
        )

        return

    image_path = Path(
        sys.argv[1]
    )

    if not image_path.exists():

        print(
            f"File not found: "
            f"{image_path}"
        )

        return

    print(
        "\n======================================"
    )
    print(
        " PARAKH REGION DETECTION POC"
    )
    print(
        "======================================"
    )

    print(
        f"\nLoading detector: "
        f"{MODEL_NAME}"
    )

    model_start = time.perf_counter()

    detector = TextDetection(
        model_name=MODEL_NAME,
        device="cpu",
    )

    model_time = (
        time.perf_counter()
        - model_start
    )

    print(
        f"Detector initialization: "
        f"{model_time:.2f} seconds"
    )

    detect_regions(
        image_path,
        detector,
    )


if __name__ == "__main__":
    main()