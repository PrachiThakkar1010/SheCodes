
import cv2
import json
import os


# ============================================================
# CONFIG
# ============================================================

INPUT_JSON = "region_detection_output/product36_img2_regions.json"
IMAGE_PATH = "product36_img2.jpeg"

OUTPUT_DIR = "region_zones_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

MIN_CONFIDENCE = 0.45

# Ignore extremely tiny symbols
MIN_WIDTH = 20
MIN_HEIGHT = 18

# Minimum vertical blank space required to split zones
MIN_GAP = 18

# Add some breathing room around each final zone
PADDING_X = 15
PADDING_Y = 15


# ============================================================
# LOAD DETECTIONS
# ============================================================

def load_regions():

    with open(
        INPUT_JSON,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    regions = []

    for r in data["regions"]:

        box = r["box"]
        confidence = r["confidence"]

        x1, y1, x2, y2 = box

        width = x2 - x1
        height = y2 - y1

        if confidence < MIN_CONFIDENCE:
            continue

        if width < MIN_WIDTH and height < MIN_HEIGHT:
            continue

        regions.append({
            "box": box,
            "confidence": confidence
        })

    return regions


# ============================================================
# BUILD VERTICAL TEXT DENSITY
# ============================================================

def build_vertical_density(regions, image_height):

    density = [0] * image_height

    for region in regions:

        x1, y1, x2, y2 = region["box"]

        y1 = max(0, int(y1))
        y2 = min(image_height, int(y2))

        for y in range(y1, y2 + 1):
            density[y] += 1

    return density


# ============================================================
# FIND CONTINUOUS TEXT BANDS
# ============================================================

def find_text_bands(density):

    bands = []

    in_band = False
    start = None

    for y, value in enumerate(density):

        if value > 0 and not in_band:

            start = y
            in_band = True

        elif value == 0 and in_band:

            end = y - 1

            bands.append(
                [start, end]
            )

            in_band = False

    if in_band:

        bands.append(
            [start, len(density) - 1]
        )

    return bands


# ============================================================
# MERGE BANDS WITH SMALL GAPS
# ============================================================

def merge_small_gaps(bands):

    if not bands:
        return []

    merged = [bands[0]]

    for current in bands[1:]:

        previous = merged[-1]

        gap = current[0] - previous[1] - 1

        if gap < MIN_GAP:

            previous[1] = current[1]

        else:

            merged.append(current)

    return merged


# ============================================================
# GET X RANGE FOR EACH ZONE
# ============================================================

def zone_box(
    zone,
    regions,
    image_width,
    image_height
):

    y1, y2 = zone

    matching = []

    for region in regions:

        x1, ry1, x2, ry2 = region["box"]

        # Does this text box intersect the zone?
        if ry2 >= y1 and ry1 <= y2:
            matching.append(region)

    if not matching:
        return None

    x1 = min(
        r["box"][0]
        for r in matching
    )

    x2 = max(
        r["box"][2]
        for r in matching
    )

    y1 = max(
        0,
        y1 - PADDING_Y
    )

    y2 = min(
        image_height,
        y2 + PADDING_Y
    )

    x1 = max(
        0,
        x1 - PADDING_X
    )

    x2 = min(
        image_width,
        x2 + PADDING_X
    )

    return [
        int(x1),
        int(y1),
        int(x2),
        int(y2)
    ]


# ============================================================
# CREATE OUTPUTS
# ============================================================

def create_outputs(
    image,
    zones,
    regions
):

    image_height, image_width = image.shape[:2]

    visualization = image.copy()

    output = []

    for index, zone in enumerate(
        zones,
        start=1
    ):

        box = zone_box(
            zone,
            regions,
            image_width,
            image_height
        )

        if box is None:
            continue

        x1, y1, x2, y2 = box

        crop = image[
            y1:y2,
            x1:x2
        ]

        crop_path = os.path.join(
            OUTPUT_DIR,
            f"zone_{index:02d}.jpg"
        )

        cv2.imwrite(
            crop_path,
            crop
        )

        # Draw rectangle
        cv2.rectangle(
            visualization,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )

        cv2.putText(
            visualization,
            f"ZONE {index}",
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        output.append({
            "zone_id": index,
            "box": box,
            "width": x2 - x1,
            "height": y2 - y1,
            "crop": crop_path
        })

    return visualization, output


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("PARAKH TEXT ZONE DETECTION")
    print("=" * 70)

    # --------------------------------------------------------
    # Load image
    # --------------------------------------------------------

    image = cv2.imread(
        IMAGE_PATH
    )

    if image is None:

        print(
            "\nERROR: Could not load image:"
        )

        print(IMAGE_PATH)

        return

    height, width = image.shape[:2]

    print(
        f"\nImage size: "
        f"{width} x {height}"
    )

    # --------------------------------------------------------
    # Load detector regions
    # --------------------------------------------------------

    regions = load_regions()

    print(
        f"Usable detector regions: "
        f"{len(regions)}"
    )

    # --------------------------------------------------------
    # Build vertical density
    # --------------------------------------------------------

    density = build_vertical_density(
        regions,
        height
    )

    # --------------------------------------------------------
    # Find raw text bands
    # --------------------------------------------------------

    bands = find_text_bands(
        density
    )

    print(
        f"Raw text bands: "
        f"{len(bands)}"
    )

    # --------------------------------------------------------
    # Merge only SMALL gaps
    # --------------------------------------------------------

    bands = merge_small_gaps(
        bands
    )

    print(
        f"Final text zones: "
        f"{len(bands)}"
    )

    print("\n" + "-" * 70)

    for i, band in enumerate(
        bands,
        start=1
    ):

        print(
            f"ZONE {i:02d} | "
            f"y={band[0]} → {band[1]} | "
            f"height={band[1] - band[0]}"
        )

    # --------------------------------------------------------
    # Create crops
    # --------------------------------------------------------

    visualization, output = create_outputs(
        image,
        bands,
        regions
    )

    visualization_path = os.path.join(
        OUTPUT_DIR,
        "text_zones.jpg"
    )

    cv2.imwrite(
        visualization_path,
        visualization
    )

    # --------------------------------------------------------
    # Save JSON
    # --------------------------------------------------------

    output_json = os.path.join(
        OUTPUT_DIR,
        "text_zones.json"
    )

    with open(
        output_json,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "image": os.path.basename(
                    IMAGE_PATH
                ),
                "detector_regions": len(
                    regions
                ),
                "zones": output
            },
            f,
            indent=4
        )

    print("\n" + "-" * 70)

    print(
        f"\nVisualization saved:"
        f"\n{visualization_path}"
    )

    print(
        f"\nJSON saved:"
        f"\n{output_json}"
    )

    print(
        f"\nCrops saved in:"
        f"\n{OUTPUT_DIR}"
    )

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()