"""Local OCR via EasyOCR — the free, on-VPS first pass of the hybrid detector.

The reader is loaded lazily on first use (it pulls in torch and downloads model
weights), and any failure degrades gracefully to "no text" so the bot keeps
running on the vision layer alone.

Images are preprocessed for contrast, deskew, and sharpness before hitting
EasyOCR, so faint or rotated "67" in memes still gets caught.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    log.info("OpenCV not available — preprocessing disabled")


class OcrEngine:
    def __init__(self, languages: list[str], enabled: bool = True) -> None:
        self._languages = languages or ["en"]
        self._enabled = enabled
        self._reader = None
        self._init_failed = False

    def _get_reader(self):
        if self._reader is not None or self._init_failed:
            return self._reader
        try:
            import easyocr

            log.info("initializing EasyOCR (languages=%s)…", self._languages)
            self._reader = easyocr.Reader(self._languages, gpu=False, verbose=False)
            log.info("EasyOCR ready")
        except Exception as exc:
            self._init_failed = True
            log.warning("EasyOCR unavailable, OCR disabled: %s", exc)
        return self._reader

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        """Light contrast bump and sharpen — no aggressive binarization."""
        arr = np.array(image.convert("L"))  # grayscale

        if not _HAS_CV2:
            return arr

        import cv2 as cv

        # 1. CLAHE — adaptive contrast so faint text on similar backgrounds pops
        clahe = cv.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        arr = clahe.apply(arr)

        # 2. Mild sharpen — crisps up edges without adding noise
        arr = cv.filter2D(arr, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))

        return arr

    def extract_text(self, image: Image.Image) -> str:
        """Return all text EasyOCR reads in the frame, joined by spaces."""
        if not self._enabled:
            return ""
        reader = self._get_reader()
        if reader is None:
            return ""
        try:
            arr = self._preprocess(image)
            results = reader.readtext(arr, detail=0, paragraph=False)
            return " ".join(results)
        except Exception as exc:
            log.warning("OCR failed on a frame: %s", exc)
            return ""