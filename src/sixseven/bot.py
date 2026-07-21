"""Telegram bot: watch a group's media, count each member's 'six sevens'."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import tempfile

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import media
from .config import Config
from .detector import Detector
from .storage import Storage

log = logging.getLogger(__name__)

_MEDALS = ["🥇", "🥈", "🥉"]


def build_application(config: Config, storage: Storage, detector: Detector) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["storage"] = storage
    app.bot_data["detector"] = detector

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(
        CommandHandler(["leaderboard", "scoreboard", "sixseven"], cmd_leaderboard)
    )
    app.add_handler(CommandHandler("me", cmd_me))

    media_filter = (
        filters.PHOTO
        | filters.VIDEO
        | filters.VIDEO_NOTE
        | filters.ANIMATION
        | filters.Sticker.ALL
    )
    app.add_handler(MessageHandler(media_filter, on_media))
    return app


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "👋 I'm the six-seven bot.\n\n"
        "Add me to a group and I'll watch photos, videos, video notes, GIFs, "
        "and stickers for the numbers 6 and 7 together (\"67\", \"6 7\", or "
        "\"six seven\"). Every hit adds to the sender's running count.\n\n"
        "Commands:\n"
        "• /leaderboard — top six-seveners in this chat\n"
        "• /me — your own count\n"
    )


def _format_leaderboard(rows) -> str:
    if not rows:
        return "No six sevens yet. Get to it. 🫡"
    lines = ["🔢 <b>Six Seven Leaderboard</b>", ""]
    for i, row in enumerate(rows):
        medal = _MEDALS[i] if i < len(_MEDALS) else f"{i + 1}."
        name = html.escape(row.display_name or (f"@{row.username}" if row.username else "Someone"))
        lines.append(f"{medal} {name} — <b>{row.count}</b>")
    return "\n".join(lines)


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.bot_data["storage"]
    rows = storage.leaderboard(update.effective_chat.id)
    await update.effective_message.reply_text(
        _format_leaderboard(rows), parse_mode=ParseMode.HTML
    )


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.bot_data["storage"]
    count = storage.user_count(update.effective_chat.id, update.effective_user.id)
    await update.effective_message.reply_text(
        f"You've sent {count} six seven{'s' if count != 1 else ''}. 🔢"
    )


def _resolve_media(msg, config: Config):
    """Return (file_id, kind, size_bytes) or None if there's nothing to scan."""
    if msg.photo:
        photo = msg.photo[-1]  # largest available size
        return photo.file_id, media.KIND_IMAGE, photo.file_size
    if msg.video:
        return msg.video.file_id, media.KIND_VIDEO, msg.video.file_size
    if msg.video_note:
        return msg.video_note.file_id, media.KIND_VIDEO, msg.video_note.file_size
    if msg.animation:
        return msg.animation.file_id, media.KIND_VIDEO, msg.animation.file_size
    if msg.sticker:
        if not config.scan_stickers:
            return None
        st = msg.sticker
        if st.is_animated:  # .tgs (Lottie) — not a raster we can OCR
            return None
        kind = media.KIND_VIDEO if st.is_video else media.KIND_IMAGE
        return st.file_id, kind, st.file_size
    return None


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    storage: Storage = context.bot_data["storage"]
    detector: Detector = context.bot_data["detector"]

    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    resolved = _resolve_media(msg, config)
    if resolved is None:
        return
    file_id, kind, size = resolved

    if size and size > config.max_file_mb * 1024 * 1024:
        log.info("skipping %s: %d bytes exceeds limit", file_id, size)
        return

    path = None
    try:
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        path = tf.name
        tf.close()
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(path)

        result = await asyncio.to_thread(detector.detect, path, kind)
    except Exception as exc:
        log.warning("failed to process media %s: %s", file_id, exc)
        return
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    if not result.matched:
        return

    new_count = storage.increment(
        update.effective_chat.id,
        user.id,
        user.full_name,
        user.username or "",
    )
    plural = "s" if new_count != 1 else ""
    await msg.reply_text(
        f"🔢 <b>six seven</b> detected! {user.mention_html()} has now dropped "
        f"6 7 <b>×{new_count}</b> time{plural}.",
        parse_mode=ParseMode.HTML,
    )
