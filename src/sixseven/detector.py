"""Ties the pieces together: media -> frames -> OCR -> (vision) -> match.

Hybrid strategy: run local OCR on every sampled frame first; the moment a frame
reads as a 'six seven', report it (no API call). If no frame matches and vision
is enabled, escalate a small number of representative frames to the vision model.
One hit per message is enough — a video full of 6 7s counts once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import media
from .matcher import find_matches
from .ocr import OcrEngine
from .vision import VisionEngine

log = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    matched: bool
    kinds: list[str] = field(default_factory=list)  # ["67"] and/or ["69"]


class Detector:
    def __init__(
        self,
        ocr: OcrEngine,
        vision: VisionEngine,
        video_frame_samples: int,
        vision_max_frames: int,
    ) -> None:
        self._ocr = ocr
        self._vision = vision
        self._video_frame_samples = video_frame_samples
        self._vision_max_frames = vision_max_frames

    def detect(self, path: str, kind: str) -> DetectionResult:
        """Blocking; call via asyncio.to_thread from the async bot handlers."""
        log.info("detect: %s frames=%s", path, self._video_frame_samples)
        frames = media.extract_frames(path, kind, self._video_frame_samples)
        if not frames:
            log.info("detect: no frames extracted")
            return DetectionResult(False)

        # Pass 1 — local OCR on every frame.
        kinds: set[str] = set()
        for i, frame in enumerate(frames):
            text = self._ocr.extract_text(frame)
            log.info("detect: ocr frame %d text=%r", i, text[:80] if text else "(empty)")
            for result in find_matches(text):
                kinds.add(result.kind)
                log.info("detect: ocr match kind=%s", result.kind)
                if len(kinds) == 2:  # found both 67 and 69
                    break
            if len(kinds) == 2:
                break

        if kinds:
            return DetectionResult(True, kinds=sorted(kinds))

        # Pass 2 — escalate representative frames to the vision model.
        if self._vision.enabled and self._vision_max_frames > 0:
            for i, frame in enumerate(self._representative_frames(frames)):
                log.info("detect: vision check frame %d", i)
                if self._vision.frame_contains_six_seven(frame):
                    log.info("detect: vision match")
                    return DetectionResult(True, kinds=["67"])
                log.info("detect: vision no match")

        log.info("detect: no match")
        return DetectionResult(False)

    def _representative_frames(self, frames):
        """Pick up to vision_max_frames frames spread across the clip."""
        n = min(self._vision_max_frames, len(frames))
        if n <= 0:
            return []
        if n == 1:
            return [frames[len(frames) // 2]]
        step = len(frames) / n
        return [frames[int(i * step)] for i in range(n)]
