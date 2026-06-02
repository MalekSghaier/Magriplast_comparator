import cv2
import numpy as np
from PIL import Image
import io
from app.core.logging import get_logger

logger = get_logger(__name__)


def preprocess_page_image(image_bytes: bytes) -> bytes:
    """
    Full preprocessing pipeline for scanned document pages.
    Returns cleaned PNG bytes ready for OCR.

    Steps (in order):
      1. upscale   — if image height < 2000 px (low DPI scan), scale 2× with
                     bicubic interpolation so Tesseract operates at ≥300 DPI.
      2. deskew    — Hough line rotation correction (±15°).
      3. contrast  — CLAHE for adaptive local contrast under uneven lighting.
      4. denoise   — fast NL-means (h=10) preserving fine strokes and decimal dots.
      5. sharpen   — unsharp mask to crisp thin strokes before binarisation.
      6. morphology — remove small noise while preserving text.
      7. binarise  — adaptive Gaussian threshold (blockSize=25, C=15).
      8. border    — crop 10 px scanner-edge artefacts.

    Adaptive thresholding is used instead of global Otsu so that small features
    (decimal points, dots) survive under uneven scanner lighting.
    Denoising strength is increased (h=10) for better noise removal.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Failed to decode image bytes")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Step 1: upscale before deskew so Hough lines are more detectable at low DPI
    gray = _upscale_if_needed(gray)

    gray = _deskew(gray)

    # Step 3: CLAHE contrast — improves local contrast especially for faded prints
    gray = _enhance_contrast(gray)

    # Step 4: Stronger denoising — h=10 removes more noise while preserving text
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # Step 5: Unsharp mask — sharpen edges so thin strokes and decimal points are crisper
    blurred = cv2.GaussianBlur(denoised, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(denoised, 1.5, blurred, -0.5, 0)

    # Step 6: Morphological operations to remove small noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morphed = cv2.morphologyEx(sharpened, cv2.MORPH_CLOSE, kernel)

    # Step 7: Adaptive Gaussian thresholding handles uneven scanner lighting better than
    # global Otsu — blockSize=25 and C=15 work well for A4 documents at 300-400 DPI
    binary = cv2.adaptiveThreshold(
        morphed, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=25,
        C=15,
    )
    binary = _remove_borders(binary)
    success, encoded = cv2.imencode(".png", binary)
    if not success:
        raise ValueError("Failed to encode preprocessed image")
    return encoded.tobytes()


def _upscale_if_needed(gray: np.ndarray, min_height: int = 2000) -> np.ndarray:
    """
    Scale up image if resolution appears too low for reliable OCR.

    Tesseract performs best at ≥300 DPI. For an A4 page at 300 DPI the image
    height is about 3508 px; at 150 DPI it is ~1754 px.  If height < min_height
    we scale up 2× with bicubic interpolation (INTER_CUBIC) which preserves
    edges better than nearest-neighbour or bilinear for text.

    min_height=2000 px catches 150-DPI and lower scans while leaving
    standard 300-400 DPI scans untouched.
    """
    h, w = gray.shape
    if h < min_height:
        scale = min_height / h
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        logger.debug("image_upscaled", original=(h, w), new=(new_h, new_w), scale=round(scale, 2))
    return gray


def _enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization) for local contrast.

    Improves legibility of faded prints, uneven scanner illumination, and
    documents scanned through coloured covers.  clipLimit=2.0 keeps contrast
    amplification modest to avoid noise boosting; tileGridSize=(8, 8) divides
    an A4 scan into ~450 cells (fine enough for column-level contrast differences).
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """
    Detect and correct document skew using Hough line detection.
    Corrects angles up to ±15 degrees.
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

    if lines is None:
        return gray
    angles = []
    for line in lines[:20]: 
        rho, theta = line[0]
        angle = (theta * 180 / np.pi) - 90
        if -15 < angle < 15:
            angles.append(angle)

    if not angles:
        return gray

    median_angle = np.median(angles)

    if abs(median_angle) < 0.5: 
        return gray
    h, w = gray.shape
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        gray, rotation_matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    logger.debug("deskew_applied", angle=float(median_angle))
    return rotated


def _remove_borders(binary: np.ndarray, border_size: int = 10) -> np.ndarray:
    """Remove scanner border artifacts by cropping a small margin."""
    h, w = binary.shape
    return binary[border_size:h-border_size, border_size:w-border_size]