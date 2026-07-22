"""Vision-model escalation for frames local OCR can't read.

When EasyOCR finds nothing, a representative frame is sent to an OpenAI vision
model with a strict yes/no question. This catches stylized, handwritten, or
meme-format "6 7" that OCR misses. Entirely optional — with no OPENAI_API_KEY
the detector runs OCR-only.
"""

from __future__ import annotations

import base64
import io
import logging

from PIL import Image

log = logging.getLogger(__name__)

_PROMPT = (
    "Does this image visually contain the numbers 6 and 7 together — as the "
    'digits "67" / "6 7", or the words "six seven" — whether printed, '
    "handwritten, stylized, drawn, or as a meme? Answer with exactly one "
    "word: YES or NO."
)


class VisionEngine:
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = None
        self._init_failed = False
        if api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=api_key)
            except Exception as exc:
                self._init_failed = True
                log.warning("OpenAI client unavailable, vision disabled: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _frame_to_png_b64(self, image: Image.Image) -> str:
        buf = io.BytesIO()
        # Downscale very large frames to keep image-token cost sane.
        img = image
        if max(img.size) > 1568:
            img = img.copy()
            img.thumbnail((1568, 1568))
        img.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    def frame_contains_six_seven(self, image: Image.Image) -> bool:
        if not self.enabled:
            return False
        try:
            data = self._frame_to_png_b64(image)
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=5,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{data}",
                                },
                            },
                            {"type": "text", "text": _PROMPT},
                        ],
                    }
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            return text.upper().startswith("YES")
        except Exception as exc:
            log.warning("vision check failed: %s", exc)
            return False
