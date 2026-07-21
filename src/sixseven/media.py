"""Download helpers turn a file on disk into a list of frames to analyze.

Photos and static stickers yield a single frame; videos, video notes,
animations (GIFs), and video stickers are sampled at a few evenly spaced
frames so we look at the whole clip without OCR-ing every frame.
"""

from __future__ import annotations

import logging

from PIL import Image

log = logging.getLogger(__name__)

# Media "kinds" the detector understands.
KIND_IMAGE = "image"
KIND_VIDEO = "video"


def _load_image(path: str) -> list[Image.Image]:
    try:
        with Image.open(path) as img:
            return [img.convert("RGB")]
    except Exception as exc:
        log.warning("could not open image %s: %s", path, exc)
        return []


def _sample_video(path: str, samples: int) -> list[Image.Image]:
    try:
        import cv2  # imported lazily so the image path works without OpenCV
    except Exception as exc:
        log.warning("OpenCV unavailable, cannot sample video frames: %s", exc)
        return []

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        log.warning("could not open video %s", path)
        return []

    frames: list[Image.Image] = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            # Some containers don't report a frame count; grab sequentially.
            grabbed = 0
            while grabbed < samples:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(_bgr_to_pil(cv2, frame))
                grabbed += 1
            return frames

        count = max(1, min(samples, total))
        # Evenly spaced indices across the clip, skipping the very last frame.
        indices = [int(total * (i + 1) / (count + 1)) for i in range(count)]
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                frames.append(_bgr_to_pil(cv2, frame))
    finally:
        cap.release()
    return frames


def _bgr_to_pil(cv2, frame) -> Image.Image:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def extract_frames(path: str, kind: str, samples: int) -> list[Image.Image]:
    """Return RGB PIL frames for the given media file."""
    if kind == KIND_IMAGE:
        return _load_image(path)
    if kind == KIND_VIDEO:
        return _sample_video(path, samples)
    log.warning("unknown media kind %r", kind)
    return []
