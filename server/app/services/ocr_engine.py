import pytesseract
from pytesseract import Output
import numpy as np
import cv2
from dataclasses import dataclass, field
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OCRResult:
    full_text: str
    word_confidences: list[int]      # 0-100 per word
    mean_confidence: float
    lines: list[str]                  # text split by line
    raw_data: dict = field(default_factory=dict)  # full pytesseract output (image_to_data)
    words: list[dict] = field(default_factory=list)  # per-word: {text,x,y,w,h,conf,line_num,block_num,par_num}


def run_tesseract(image_bytes: bytes) -> OCRResult:
    """
    Run Tesseract OCR on preprocessed image bytes.
    Returns structured result with per-word confidence scores.
    Language: French (fra) — handles accents, currency symbols, French/TND number formats.

    OEM 1 (LSTM only) is used instead of OEM 3 (combined legacy+LSTM) because
    LSTM-only mode is significantly more accurate on modern scanned documents and
    handles decimal points in numbers ("4.0", "122.341") more reliably.
    PSM 6 (uniform block) works well for structured accounting documents.
    """
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)

    if img is None:
        raise ValueError("Cannot decode image for OCR")

    # OEM 1 = LSTM only (more accurate than combined OEM 3 for scanned documents)
    # PSM 6 = uniform block of text (suitable for invoice/order pages)
    # preserve_interword_spaces=1 keeps column spacing visible to the LLM
    config = (
        f"--oem 1 --psm 6 -l {settings.tesseract_language} "
        f"--dpi 300 "
        f"-c preserve_interword_spaces=1"
    )
    data = pytesseract.image_to_data(
        img,
        config=config,
        output_type=Output.DICT
    )
    word_confidences = []
    word_texts = []
    word_boxes: list[dict] = []
    for i, word in enumerate(data["text"]):
        conf = int(data["conf"][i])
        if conf >= 0 and word.strip():
            word_confidences.append(conf)
            word_texts.append(word)
            word_boxes.append({
                "text": word.strip(),
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "conf": conf,
                "line_num": int(data["line_num"][i]),
                "block_num": int(data["block_num"][i]),
                "par_num": int(data["par_num"][i]),
            })

    mean_conf = (sum(word_confidences) / len(word_confidences) / 100.0) if word_confidences else 0.0
    full_text = pytesseract.image_to_string(img, config=config)  # same config as image_to_data
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

    result = OCRResult(
        full_text=full_text,
        word_confidences=word_confidences,
        mean_confidence=mean_conf,
        lines=lines,
        raw_data=data,
        words=word_boxes,
    )



    return result


def get_field_confidence(ocr_data: dict, field_text: str) -> float:
    """
    Given OCR raw data and an extracted field value,
    estimate the confidence of that specific field by
    finding the words that compose it and averaging their confidence.
    """
    if not field_text or not ocr_data:
        return 0.5

    field_words = field_text.strip().upper().split()
    matched_confidences = []

    for i, word in enumerate(ocr_data.get("text", [])):
        if word.strip().upper() in field_words:
            conf = int(ocr_data["conf"][i])
            if conf > 0:
                matched_confidences.append(conf)

    if not matched_confidences:
        return 0.7

    return sum(matched_confidences) / len(matched_confidences) / 100.0