"""
Qwen3-VL service for Parakh.

This module loads Qwen3-VL once and provides reusable functions
for visual understanding tasks.

IMPORTANT:
- Qwen is NOT the primary OCR engine.
- PaddleOCR remains responsible for normal OCR.
- Qwen is used only for higher-level visual understanding.
"""

import time

from PIL import Image
from transformers import (
    Qwen3VLForConditionalGeneration,
    AutoProcessor,
)


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "Qwen/Qwen3-VL-4B-Instruct"


# ============================================================
# SINGLETON MODEL
# ============================================================

_qwen_model = None
_qwen_processor = None


def _load_qwen():
    """
    Load Qwen3-VL only once.

    Subsequent calls reuse the same model and processor.
    This is important because model loading is expensive on CPU.
    """

    global _qwen_model
    global _qwen_processor

    if _qwen_model is not None and _qwen_processor is not None:
        return _qwen_model, _qwen_processor

    print("\n" + "=" * 70)
    print("QWEN3-VL: LOADING MODEL")
    print("=" * 70)

    start = time.time()

    _qwen_model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL_NAME,
        dtype="auto",
        device_map="auto",
    )

    _qwen_processor = AutoProcessor.from_pretrained(
        MODEL_NAME
    )

    elapsed = time.time() - start

    print(f"Qwen3-VL model loaded in {elapsed:.2f} seconds")
    print("=" * 70 + "\n")

    return _qwen_model, _qwen_processor


# ============================================================
# IMAGE LOADING
# ============================================================

def _load_image(image_path):
    """
    Load an image as RGB.

    Qwen's processor accepts PIL images directly.
    """

    image = Image.open(image_path).convert("RGB")

    return image


# ============================================================
# GENERIC QWEN IMAGE QUERY
# ============================================================

def ask_qwen(image_paths, prompt, max_new_tokens=300):
    """
    Send one or more images plus a prompt to Qwen3-VL.

    Parameters
    ----------
    image_paths : list[str | Path]
        Paths to the images.

    prompt : str
        Instruction for Qwen.

    max_new_tokens : int
        Maximum number of generated tokens.

    Returns
    -------
    str
        Raw Qwen response.
    """

    model, processor = _load_qwen()

    # --------------------------------------------------------
    # Load images
    # --------------------------------------------------------

    images = []

    for image_path in image_paths:
        image = _load_image(image_path)
        images.append(image)

        print(
            f"[QWEN] Image loaded: "
            f"{image_path} | size={image.size}"
        )

    # --------------------------------------------------------
    # Build multimodal message
    # --------------------------------------------------------

    content = []

    for image in images:
        content.append(
            {
                "type": "image",
                "image": image,
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

    # --------------------------------------------------------
    # Prepare inputs
    # --------------------------------------------------------

    print("[QWEN] Preparing inputs...")

    start = time.time()

    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )

    # Some Transformers/Qwen combinations may provide this.
    # The Qwen3-VL generation path does not need it.
    inputs.pop("token_type_ids", None)

    inputs = inputs.to(model.device)

    preparation_time = time.time() - start

    print(
        f"[QWEN] Input preparation: "
        f"{preparation_time:.2f}s"
    )

    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    print("[QWEN] Running inference...")
    print("[QWEN] CPU inference may take some time.")

    start = time.time()

    generated_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )

    inference_time = time.time() - start

    # --------------------------------------------------------
    # Remove input tokens from generated output
    # --------------------------------------------------------

    generated_ids_trimmed = [
        output_ids[len(input_ids):]
        for input_ids, output_ids
        in zip(inputs.input_ids, generated_ids)
    ]

    # --------------------------------------------------------
    # Decode
    # --------------------------------------------------------

    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    print(
        f"[QWEN] Inference completed in "
        f"{inference_time:.2f}s"
    )

    return output_text.strip()


# ============================================================
# MODEL STATUS
# ============================================================

def is_qwen_loaded():
    """
    Return True if Qwen is already loaded in memory.
    """

    return (
        _qwen_model is not None
        and _qwen_processor is not None
    )


def unload_qwen():
    """
    Release the Qwen model from memory.

    Useful during development/testing if you need to free RAM.
    """

    global _qwen_model
    global _qwen_processor

    _qwen_model = None
    _qwen_processor = None

    print("[QWEN] Model references released.")