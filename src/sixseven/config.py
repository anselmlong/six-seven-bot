"""Runtime configuration, loaded from environment / a local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass
class Config:
    telegram_bot_token: str
    openai_api_key: str = ""
    vision_model: str = "gpt-4o"
    ocr_enabled: bool = True
    ocr_languages: list[str] = field(default_factory=lambda: ["en"])
    # How many frames to sample from a video/animation for OCR.
    video_frame_samples: int = 4
    # How many frames to escalate to the vision model when OCR finds nothing.
    vision_max_frames: int = 1
    db_path: str = "sixseven.db"
    # Telegram's Bot API caps bot downloads at 20 MB.
    max_file_mb: int = 20

    @property
    def vision_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and "
                "put the token in your environment or a .env file."
            )
        langs = os.getenv("SIXSEVEN_OCR_LANGS", "en")
        return cls(
            telegram_bot_token=token,
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            vision_model=os.getenv("SIXSEVEN_VISION_MODEL", "gpt-4o").strip(),
            ocr_enabled=_bool("SIXSEVEN_OCR_ENABLED", True),
            ocr_languages=[s.strip() for s in langs.split(",") if s.strip()],
            video_frame_samples=_int("SIXSEVEN_VIDEO_FRAMES", 4),
            vision_max_frames=_int("SIXSEVEN_VISION_MAX_FRAMES", 1),
            db_path=os.getenv("SIXSEVEN_DB_PATH", "sixseven.db").strip(),
            max_file_mb=_int("SIXSEVEN_MAX_FILE_MB", 20),
        )
