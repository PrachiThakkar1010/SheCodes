"""
ocr/ocrspace.py

OCR.space backend for Parakh.

Why this exists
---------------
PaddleOCR needs roughly 1.2 GB of RAM on Linux, which does not fit
in Railway's 1 GB free container. OCR.space does the reading on
their servers, so the container needs almost nothing.

This module returns EXACTLY the same line format as
ocr/services.py, so labeler.py, aggregator.py and pipeline.py
need no changes:

    {
        "text":       str,
        "box":        [x1, y1, x2, y2],
        "confidence": float,
        "image_id":   str,
        "width":      float,
        "height":     float,
    }

Set OCR_SPACE_API_KEY in the environment before use.
"""

import io
import os
import time

import requests
from PIL import Image


API_URL = "https://api.ocr.space/parse/image"

# Free tier rejects files over ~1 MB.
MAX_UPLOAD_BYTES = 1000 * 1024

# OCR.space does not return per-line confidence scores.
#
# labeler.py branches on confidence at 0.55, 0.75, 0.80 and 0.85,
# so every line has to be given a value. 0.90 is used so that
# lines behave like "clean" PaddleOCR output and pass those gates.
#
# CONSEQUENCE: confidence-based filtering is effectively disabled
# on this backend. _looks_like_gibberish() will no longer reject
# short low-confidence fragments, and _refine_product_name() will
# consider every candidate line. Watch for junk being promoted to
# PRODUCT_NAME, and tighten the text-shape rules in labeler.py
# rather than the confidence thresholds if it happens.
ASSUMED_CONFIDENCE = 0.90


class OCRSpaceError(RuntimeError):
    """Raised when OCR.space cannot process an image."""


# ============================================================
# IMAGE PREPARATION
# ============================================================

def _prepare_upload(image_path):
    """
    Return (jpeg_bytes, scale) for upload.

    The free tier caps uploads at about 1 MB, so large phone
    photos are shrunk until they fit. `scale` records how much
    the image was reduced, so the boxes OCR.space returns can be
    mapped back onto the ORIGINAL image coordinates - the rest of
    Parakh expects original-image geometry.
    """
    original_size = os.path.getsize(image_path)

    img = Image.open(image_path).convert("RGB")

    original_width = img.size[0]

    # Small enough already: send the file untouched.
    if original_size <= MAX_UPLOAD_BYTES:
        with open(image_path, "rb") as handle:
            return handle.read(), 1.0

    # Step the long edge down until the encoded JPEG fits.
    for long_edge in (2400, 2000, 1600, 1280, 1024):

        candidate = img.copy()
        candidate.thumbnail(
            (long_edge, long_edge),
            Image.Resampling.LANCZOS,
        )

        buffer = io.BytesIO()
        candidate.save(
            buffer,
            format="JPEG",
            quality=85,
            optimize=True,
        )

        data = buffer.getvalue()

        if len(data) <= MAX_UPLOAD_BYTES:
            scale = candidate.size[0] / original_width
            return data, scale

    # Last resort: smallest size, lowest quality.
    candidate = img.copy()
    candidate.thumbnail(
        (1024, 1024),
        Image.Resampling.LANCZOS,
    )

    buffer = io.BytesIO()
    candidate.save(
        buffer,
        format="JPEG",
        quality=60,
        optimize=True,
    )

    scale = candidate.size[0] / original_width

    return buffer.getvalue(), scale


# ============================================================
# API CALL
# ============================================================

def _call_api(image_bytes, api_key, engine):
    """
    POST one image to OCR.space and return the parsed result.

    `isOverlayRequired` is what makes the API return word
    positions; without it there are no boxes and the geometry
    passes in labeler.py cannot run.
    """
    response = requests.post(
        API_URL,
        files={
            "file": ("label.jpg", image_bytes, "image/jpeg"),
        },
        data={
            "apikey": api_key,
            "isOverlayRequired": True,
            "OCREngine": engine,
            "scale": True,
            "detectOrientation": True,
        },
        timeout=120,
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("IsErroredOnProcessing"):

        message = payload.get("ErrorMessage")

        if isinstance(message, list):
            message = " | ".join(str(m) for m in message)

        raise OCRSpaceError(
            message or "OCR.space reported an unknown error"
        )

    results = payload.get("ParsedResults") or []

    if not results:
        raise OCRSpaceError("OCR.space returned no parsed results")

    return results[0]


# ============================================================
# RESPONSE MAPPING
# ============================================================

def _lines_from_result(result, image_scale, image_id):
    """
    Convert OCR.space's overlay into Parakh line dictionaries.

    OCR.space gives each line as a list of words, each with
    Left/Top/Width/Height. The line box is the bounding box of
    its words. Coordinates are divided by image_scale to undo
    any shrinking done before upload.
    """
    overlay = result.get("TextOverlay") or {}

    raw_lines = overlay.get("Lines") or []

    lines = []

    for raw in raw_lines:

        text = str(raw.get("LineText") or "").strip()

        if not text:
            continue

        words = raw.get("Words") or []

        if not words:
            continue

        lefts = []
        tops = []
        rights = []
        bottoms = []

        for word in words:

            try:
                left = float(word["Left"])
                top = float(word["Top"])
                width = float(word["Width"])
                height = float(word["Height"])
            except (KeyError, TypeError, ValueError):
                continue

            lefts.append(left)
            tops.append(top)
            rights.append(left + width)
            bottoms.append(top + height)

        if not lefts:
            continue

        x1 = min(lefts)
        y1 = min(tops)
        x2 = max(rights)
        y2 = max(bottoms)

        # Undo the pre-upload shrink.
        if image_scale != 1.0:
            x1 /= image_scale
            y1 /= image_scale
            x2 /= image_scale
            y2 /= image_scale

        lines.append({
            "text": text,
            "box": [
                float(x1),
                float(y1),
                float(x2),
                float(y2),
            ],
            "confidence": ASSUMED_CONFIDENCE,
            "image_id": image_id,
            "width": float(x2 - x1),
            "height": float(y2 - y1),
        })

    return lines


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def extract_lines_from_image(image_path, image_id):
    """
    OCR one image via OCR.space.

    Returns the same line dictionaries as the PaddleOCR backend.
    Raises OCRSpaceError if the key is missing or the API fails,
    so the caller can decide whether to fall back or surface the
    problem to the user.
    """
    api_key = os.getenv("OCR_SPACE_API_KEY")

    if not api_key:
        raise OCRSpaceError(
            "OCR_SPACE_API_KEY is not set"
        )

    engine = os.getenv("OCR_SPACE_ENGINE", "2")

    total_start = time.perf_counter()

    image_bytes, image_scale = _prepare_upload(image_path)

    upload_kb = len(image_bytes) / 1024

    result = _call_api(image_bytes, api_key, engine)

    lines = _lines_from_result(
        result,
        image_scale,
        image_id,
    )

    total_time = time.perf_counter() - total_start

    print(
        f"[OCR.SPACE] {image_id}: "
        f"upload={upload_kb:.0f}KB | "
        f"scale={image_scale:.2f} | "
        f"total={total_time:.2f}s | "
        f"lines={len(lines)}",
        flush=True,
    )

    return lines