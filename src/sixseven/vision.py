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

import httpx
from PIL import Image

log = logging.getLogger(__name__)

_PROMPT = (
    "Does this image contain the digits 6 and 7 adjacent to each other (as "
    '"67")? They can appear anywhere — inside a longer number like "467" or '
    '"6674K", as a standalone "67", or written as "six seven". Stylized, '
    "handwritten, printed, meme text — any format counts. Answer with exactly "
    "one word: YES or NO."
)


def _frame_to_png_b64(image: Image.Image, max_px: int = 1568) -> str:
    """Encode a frame as base64 PNG, downscaling to bound image-token cost."""
    buf = io.BytesIO()
    img = image
    if max(img.size) > max_px:
        img = img.copy()
        img.thumbnail((max_px, max_px))
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


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
        return _frame_to_png_b64(image)

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
                                    # detail=low pins this to a flat 85 image tokens
                                    # (vs 85 + 170/tile at high detail). The check is
                                    # a coarse yes/no on a two-character meme, so the
                                    # 512px downscale costs nothing in practice.
                                    "detail": "low",
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


# Jev (TypeSafe AI) is a decision model, not a chat model: you post state plus
# typed questions and get typed answers with calibrated probabilities. That maps
# onto this task better than parsing "YES" out of generated text — the answer is
# already a probability we can threshold on.
#
# Request shape (https://api.typesafe.ai/v1/systemone):
#   {model, state, assets:{ref:{type,format,data_base64}}, questions:{id:{type,instructions}}}
# Images ride in the top-level `assets` map and are referenced by name in text.
#
# Image input is behind TypeSafe's "danger zone" header and is explicitly
# flagged as not production-ready by the vendor, so this stays opt-in.
_JEV_REF = "frame"
_JEV_QUESTION = (
    "The image `frame` contains the digits 6 and 7 adjacent to each other (as "
    '"67"), anywhere, in any style: inside a longer number, standalone, '
    "handwritten, printed, or as meme text."
)


class JevVisionEngine:
    """Drop-in alternative to VisionEngine backed by the Jev decision API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        threshold: float,
        provider: str = "typesafe",
        max_px: int = 768,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._threshold = threshold
        self._provider = provider
        # Jev bills image tokens by pixel area, and recall falls off a cliff
        # below ~512px (text under 2% of frame height stops being readable).
        # 768 keeps a 1%-height "67" detectable at ~1/4 the tokens of 1568.
        self._max_px = max_px

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._base_url)

    def _frame_to_png_b64(self, image: Image.Image) -> str:
        return _frame_to_png_b64(image, self._max_px)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._provider == "typesafe":
            # Required for image input and the Box question type.
            headers["TypeSafe-Danger-Zone-Images"] = "true"
        return headers

    def _payload(self, data: str) -> dict:
        return {
            "model": self._model,
            "state": {"frame": _JEV_REF},
            "assets": {
                _JEV_REF: {
                    "type": "image",
                    "format": "png",
                    "data_base64": data,
                }
            },
            "questions": {
                "has_six_seven": {
                    "type": "noul",
                    "instructions": _JEV_QUESTION,
                }
            },
        }

    @staticmethod
    def _extract_probability(payload: dict) -> float | None:
        """Return the 0-1 noul for our question, or None if the shape is off.

        The documented shape is {"answers": {"has_six_seven": {"noul": 0.97}}}.
        A few older/alternate layouts are accepted too, but anything missing a
        usable number returns None so the caller fails closed (no match).
        """
        answers = payload.get("answers")
        if isinstance(answers, list):
            answers = {a.get("name"): a for a in answers if isinstance(a, dict)}
        if not isinstance(answers, dict):
            return None

        entry = answers.get("has_six_seven")
        if entry is None and len(answers) == 1:
            entry = next(iter(answers.values()))
        if not isinstance(entry, dict):
            return None

        for key in ("noul", "probability", "p", "value", "score"):
            val = entry.get(key)
            if isinstance(val, bool):
                return 1.0 if val else 0.0
            if isinstance(val, (int, float)):
                return float(val)
        return None

    def frame_contains_six_seven(self, image: Image.Image) -> bool:
        if not self.enabled:
            return False
        try:
            data = self._frame_to_png_b64(image)
            url = f"{self._base_url}/systemone"
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(
                    url,
                    headers=self._headers(),
                    json=self._payload(data),
                )
            if resp.status_code >= 400:
                # Body may echo request details; keep it short and key-free.
                log.warning("jev check failed: HTTP %s", resp.status_code)
                return False
            prob = self._extract_probability(resp.json())
            if prob is None:
                log.warning("jev: no probability in response, treating as no-match")
                return False
            log.info("jev: p=%.3f threshold=%.2f", prob, self._threshold)
            return prob >= self._threshold
        except Exception as exc:
            log.warning("jev check failed: %s", type(exc).__name__)
            return False


def build_vision_engine(config) -> "VisionEngine | JevVisionEngine":
    """Pick the vision backend from config, falling back to OpenAI if unset."""
    if config.vision_provider == "jev" and config.typesafe_api_key:
        log.info("vision provider: jev (%s via %s)", config.typesafe_model, config.typesafe_base_url)
        return JevVisionEngine(
            api_key=config.typesafe_api_key,
            model=config.typesafe_model,
            base_url=config.typesafe_base_url,
            threshold=config.typesafe_threshold,
            provider=config.typesafe_provider,
            max_px=config.typesafe_max_px,
        )
    return VisionEngine(config.openai_api_key, config.vision_model)
