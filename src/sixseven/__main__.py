"""Entry point: `python -m sixseven`."""

from __future__ import annotations

import logging

from telegram import Update

from .config import Config
from .detector import Detector
from .ocr import OcrEngine
from .storage import Storage
from .vision import VisionEngine


def main() -> None:
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
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
