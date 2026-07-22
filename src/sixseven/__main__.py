"""Entry point: `python -m sixseven`."""

from __future__ import annotations

import faulthandler
import logging
import os

# Bound native thread pools BEFORE torch/OpenBLAS load (lazily via EasyOCR).
# The per-CPU default spikes memory/CPU during OCR inference and is the prime
# suspect for silent OOM kills of the container. Set before any heavy import.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from telegram import Update

from .config import Config
from .detector import Detector
from .ocr import OcrEngine
from .storage import Storage
from .vision import VisionEngine


def main() -> None:
    # Dump a C-level traceback on segfault/abort. Native crashes in
    # torch/OpenCV otherwise kill the process with no Python traceback, which
    # is exactly the "clean exit, no traceback" restart we're chasing.
    faulthandler.enable()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("sixseven")

    config = Config.from_env()
    log.info(
        "starting: ocr=%s vision=%s (model=%s)",
        config.ocr_enabled,
        config.vision_enabled,
        config.vision_model if config.vision_enabled else "-",
    )

    storage = Storage(config.db_path)
    ocr = OcrEngine(config.ocr_languages, enabled=config.ocr_enabled)
    # Build the EasyOCR model at startup: keeps the first image fast and makes
    # any init failure a clear boot-time log line rather than a mid-request one.
    ocr.warmup()
    vision = VisionEngine(config.openai_api_key, config.vision_model)
    detector = Detector(
        ocr=ocr,
        vision=vision,
        video_frame_samples=config.video_frame_samples,
        vision_max_frames=config.vision_max_frames,
    )

    # Imported here so config errors surface before we touch the Telegram stack.
    from .bot import build_application

    app = build_application(config, storage, detector)
    log.info("bot is up — polling for updates")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # If this line is the last thing in the logs, the bot stopped cleanly
        # (SIGTERM/Ctrl-C). If the logs just cut off without it, the process was
        # killed hard — OOM or native crash — which points the diagnosis.
        log.info("polling stopped — shutting down cleanly")


if __name__ == "__main__":
    main()
