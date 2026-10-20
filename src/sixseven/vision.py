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


def _frame_to_png_b64(image: Image.Image) -> str:
    """Encode a frame as base64 PNG, downscaling huge frames to bound cost."""
    buf = io.BytesIO()
    img = image
    if max(img.size) > 1568:
        img = img.copy()
        img.thumbnail((1568, 1568))
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
# already a boolean with a confidence we can threshold on.
#
# Image input is behind TypeSafe's "danger zone" header and is explicitly
# flagged as not production-ready by the vendor, so this stays opt-in.
_JEV_QUESTION = (
    "The image contains the digits 6 and 7 adjacent to each other (as \"67\"), "
    "anywhere, in any style: inside a longer number, standalone, handwritten, "
    "printed, or as meme text."
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
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._threshold = threshold
        self._provider = provider

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._base_url)

    def _frame_to_png_b64(self, image: Image.Image) -> str:
        return VisionEngine._frame_to_png_b64(self, image)  # same downscale rules

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
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "A frame from a chat message."},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{data}",
                        },
                    ],
                }
            ],
            "questions": [
                {
                    "type": "predicate",
                    "name": "has_six_seven",
                    "instructions": _JEV_QUESTION,
                }
            ],
        }

    @staticmethod
    def _extract_probability(payload: dict) -> float | None:
        """Pull a 0-1 probability out without pinning an exact response shape.

        The Decisions API has shipped a few answer layouts; rather than guess
        one, accept the common spellings and fail closed if none is present.
        """
        answers = payload.get("answers") or payload.get("results") or []
        if isinstance(answers, dict):
            answers = [answers]
        for ans in answers:
            if not isinstance(ans, dict):
                continue
            if ans.get("name") not in (None, "has_six_seven"):
                continue
            for key in ("probability", "p", "score", "value", "confidence"):
                val = ans.get(key)
                if isinstance(val, bool):
                    return 1.0 if val else 0.0
                if isinstance(val, (int, float)):
                    return float(val)
            nested = ans.get("answer")
            if isinstance(nested, dict):
                for key in ("probability", "p", "value"):
                    val = nested.get(key)
                    if isinstance(val, (int, float)):
                        return float(val)
                if isinstance(nested.get("probability"), bool):
                    return 1.0 if nested["probability"] else 0.0
        return None

    def frame_contains_six_seven(self, image: Image.Image) -> bool:
        if not self.enabled:
            return False
        try:
            data = self._frame_to_png_b64(image)
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{self._base_url}/decisions",
                    headers=self._headers(),
                    json=self._payload(data),
                )
            resp.raise_for_status()
            prob = self._extract_probability(resp.json())
            if prob is None:
                log.warning("jev: no probability in response, treating as no-match")
                return False
            log.info("jev: p=%.3f threshold=%.2f", prob, self._threshold)
            return prob >= self._threshold
        except Exception as exc:
            log.warning("jev check failed: %s", exc)
            return False


def build_vision_engine(config) -> "VisionEngine | JevVisionEngine":
    """Pick the vision backend from config, falling back to OCR-only if unset."""
    if config.vision_provider == "jev" and config.typesafe_api_key:
        log.info(
            "vision provider: jev (%s via %s)",
            config.typesafe_model,
            config.typesafe_base_url,
        )
        return JevVisionEngine(
            api_key=config.typesafe_api_key,
            model=config.typesafe_model,
            base_url=config.typesafe_base_url,
            threshold=config.typesafe_threshold,
            provider=config.typesafe_provider,
        )
    return VisionEngine(config.openai_api_key, config.vision_model)
