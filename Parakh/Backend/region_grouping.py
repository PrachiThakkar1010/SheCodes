import cv2
import json
import os
import numpy as np


INPUT_JSON = "region_detection_output/product36_img2_regions.json"
IMAGE_PATH = "product36_img2.jpeg"

OUTPUT_DIR = "region_grouping_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# CONFIGURATION
# ============================================================

MIN_CONFIDENCE = 0.45

# Tiny detections below these dimensions are usually symbols/noise
MIN_WIDTH = 20
MIN_HEIGHT = 18

# Padding around final blocks
PADDING = 20


# ============================================================
# BASIC BOX FUNCTIONS
# ============================================================

def area(box):
    x1, y1, x2, y2 = box
    return max(0, x2 - x1) * max(0, y2 - y1)


def intersection(box1, box2):

    x1, y1, x2, y2 = box1
    a1, b1, a2, b2 = box2

    ix1 = max(x1, a1)
    iy1 = max(y1, b1)
    ix2 = min(x2, a2)
    iy2 = min(y2, b2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0

    return (ix2 - ix1) * (iy2 - iy1)


def iou(box1, box2):

    inter = intersection(box1, box2)

    if inter == 0:
        return 0

    union = area(box1) + area(box2) - inter

    return inter / union


def containment_ratio(box1, box2):

    """
    How much of the smaller box is contained
    inside the larger box.
    """

    inter = intersection(box1, box2)

    if inter == 0:
        return 0

    smaller = min(area(box1), area(box2))

    return inter / smaller


def merge_box(box1, box2):

    return [
        min(box1[0], box2[0]),
        min(box1[1], box2[1]),
        max(box1[2], box2[2]),
        max(box1[3], box2[3])
    ]


# ============================================================
# STEP 1 — FILTER RAW DETECTIONS
# ============================================================

def filter_regions(regions):

    filtered = []

    for region in regions:

        box = region["box"]
        confidence = region["confidence"]

        x1, y1, x2, y2 = box

        width = x2 - x1
        height = y2 - y1

        if confidence < MIN_CONFIDENCE:
            continue

        if width < MIN_WIDTH and height < MIN_HEIGHT:
            continue

        filtered.append(region)

    return filtered


# ============================================================
# STEP 2 — REMOVE DUPLICATE / HEAVILY OVERLAPPING BOXES
# ============================================================

def remove_duplicates(regions):

    regions = sorted(
        regions,
        key=lambda r: area(r["box"]),
        reverse=True
    )

    kept = []

    for region in regions:

        box = region["box"]

        duplicate = False

        for existing in kept:

            existing_box = existing["box"]

            overlap = iou(box, existing_box)
            containment = containment_ratio(box, existing_box)

            if overlap > 0.50 or containment > 0.80:

                duplicate = True
                break

        if not duplicate:
            kept.append(region)

    return kept


# ============================================================
# STEP 3 — DETERMINE WHETHER TWO TEXT LINES BELONG TOGETHER
# ============================================================

def should_merge(box1, box2):

    x1, y1, x2, y2 = box1
    a1, b1, a2, b2 = box2

    width1 = x2 - x1
    height1 = y2 - y1

    width2 = a2 - a1
    height2 = b2 - b1

    # --------------------------------------------------------
    # Vertical relationship
    # --------------------------------------------------------

    vertical_gap = max(
        0,
        max(y1, b1) - min(y2, b2)
    )

    # Horizontal overlap
    horizontal_overlap = max(
        0,
        min(x2, a2) - max(x1, a1)
    )

    smaller_width = max(
        1,
        min(width1, width2)
    )

    horizontal_overlap_ratio = (
        horizontal_overlap / smaller_width
    )

    # --------------------------------------------------------
    # Direct overlap
    # --------------------------------------------------------

    if iou(box1, box2) > 0.10:
        return True

    if containment_ratio(box1, box2) > 0.50:
        return True

    # --------------------------------------------------------
    # Same text line / nearby line
    # --------------------------------------------------------

    typical_height = max(
        18,
        min(height1, height2)
    )

    allowed_vertical_gap = max(
        12,
        int(typical_height * 0.75)
    )

    if vertical_gap <= allowed_vertical_gap:

        if horizontal_overlap_ratio >= 0.30:
            return True

        # Boxes can belong to the same paragraph even
        # when horizontal overlap is weak.
        horizontal_gap = max(
            0,
            max(a1, x1) - min(x2, a2)
        )

        if horizontal_gap <= 35:
            return True

    return False


# ============================================================
# STEP 4 — UNION-FIND GROUPING
# ============================================================

def group_regions(regions):

    n = len(regions)

    parent = list(range(n))

    def find(x):

        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]

        return x

    def union(a, b):

        root_a = find(a)
        root_b = find(b)

        if root_a != root_b:
            parent[root_b] = root_a

    # Compare every pair
    for i in range(n):

        for j in range(i + 1, n):

            box1 = regions[i]["box"]
            box2 = regions[j]["box"]

            if should_merge(box1, box2):
                union(i, j)

    grouped = {}

    for i in range(n):

        root = find(i)

        if root not in grouped:
            grouped[root] = []

        grouped[root].append(regions[i])

    groups = []

    for members in grouped.values():

        boxes = [
            r["box"]
            for r in members
        ]

        combined = boxes[0]

        for box in boxes[1:]:
            combined = merge_box(
                combined,
                box
            )

        confidence = np.mean([
            r["confidence"]
            for r in members
        ])

        groups.append({
            "box": combined,
            "members": members,
            "confidence": float(confidence)
        })

    return groups


# ============================================================
# STEP 5 — MERGE VERY CLOSE GROUPS
# ============================================================

def merge_close_groups(groups):

    changed = True

    while changed:

        changed = False

        new_groups = []

        used = set()

        for i in range(len(groups)):

            if i in used:
                continue

            current = groups[i]

            for j in range(i + 1, len(groups)):

                if j in used:
                    continue

                other = groups[j]

                if should_merge(
                    current["box"],
                    other["box"]
                ):

                    current["box"] = merge_box(
                        current["box"],
                        other["box"]
                    )

                    current["members"].extend(
                        other["members"]
                    )

                    current["confidence"] = float(
                        np.mean([
                            r["confidence"]
                            for r in current["members"]
                        ])
                    )

                    used.add(j)

                    changed = True

            new_groups.append(current)

        groups = new_groups

    return groups


# ============================================================
# STEP 6 — SORT GROUPS TOP TO BOTTOM
# ============================================================

def sort_groups(groups):

    return sorted(
        groups,
        key=lambda g: (
            g["box"][1],
            g["box"][0]
        )
    )


# ============================================================
# STEP 7 — CREATE CROPS + VISUALIZATION
# ============================================================

def create_outputs(image, groups):

    height, width = image.shape[:2]

    visualization = image.copy()

    output = []

    for index, group in enumerate(groups, start=1):

        x1, y1, x2, y2 = group["box"]

        # Add padding
        x1 = max(0, x1 - PADDING)
        y1 = max(0, y1 - PADDING)

        x2 = min(width, x2 + PADDING)
        y2 = min(height, y2 + PADDING)

        final_box = [
            int(x1),
            int(y1),
            int(x2),
            int(y2)
        ]

        crop = image[
            y1:y2,
            x1:x2
        ]

        crop_path = os.path.join(
            OUTPUT_DIR,
            f"region_{index:02d}.jpg"
        )

        cv2.imwrite(
            crop_path,
            crop
        )

        # Draw
        cv2.rectangle(
            visualization,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )

        cv2.putText(
            visualization,
            f"R{index}",
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )

        output.append({
            "region_id": index,
            "box": final_box,
            "width": int(x2 - x1),
            "height": int(y2 - y1),
            "source_region_count": len(
                group["members"]
            ),
            "confidence": group["confidence"],
            "crop": crop_path
        })

    return visualization, output


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("PARAKH SMART REGION GROUPING")
    print("=" * 70)

    # --------------------------------------------------------
    # Load JSON
    # --------------------------------------------------------

    with open(
        INPUT_JSON,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    regions = data["regions"]

    print(f"\nOriginal regions: {len(regions)}")

    # --------------------------------------------------------
    # Load image
    # --------------------------------------------------------

    image = cv2.imread(
        IMAGE_PATH
    )

    if image is None:

        print(
            f"\nERROR: Cannot load image:\n"
            f"{IMAGE_PATH}"
        )

        return

    height, width = image.shape[:2]

    print(
        f"Image size: {width} x {height}"
    )

    # --------------------------------------------------------
    # Filter
    # --------------------------------------------------------

    filtered = filter_regions(
        regions
    )

    print(
        f"After filtering: {len(filtered)}"
    )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    deduplicated = remove_duplicates(
        filtered
    )

    print(
        f"After duplicate removal: "
        f"{len(deduplicated)}"
    )

    # --------------------------------------------------------
    # Group
    # --------------------------------------------------------

    groups = group_regions(
        deduplicated
    )

    print(
        f"Initial groups: {len(groups)}"
    )

    # --------------------------------------------------------
    # Merge groups
    # --------------------------------------------------------

    groups = merge_close_groups(
        groups
    )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    groups = sort_groups(
        groups
    )

    print(
        f"Final logical blocks: "
        f"{len(groups)}"
    )

    print("\n" + "-" * 70)

    for i, group in enumerate(
        groups,
        start=1
    ):

        x1, y1, x2, y2 = group["box"]

        print(
            f"{i:03d} | "
            f"{len(group['members'])} text regions | "
            f"box=[{x1}, {y1}, {x2}, {y2}] | "
            f"size={x2-x1}x{y2-y1}"
        )

    # --------------------------------------------------------
    # Create crops
    # --------------------------------------------------------

    visualization, output = create_outputs(
        image,
        groups
    )

    visualization_path = os.path.join(
        OUTPUT_DIR,
        "grouped_regions.jpg"
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
        "grouped_regions.json"
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
                "original_regions": len(regions),
                "filtered_regions": len(filtered),
                "deduplicated_regions": len(
                    deduplicated
                ),
                "logical_blocks": len(groups),
                "regions": output
            },
            f,
            indent=4
        )

    print("\n" + "-" * 70)

    print(
        f"\nSaved visualization:\n"
        f"{visualization_path}"
    )

    print(
        f"\nSaved JSON:\n"
        f"{output_json}"
    )

    print(
        f"\nSaved crops:\n"
        f"{OUTPUT_DIR}\\region_XX.jpg"
    )

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()