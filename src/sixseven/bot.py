"""Telegram bot: watch a group's media, count each member's 'six sevens'."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import tempfile
from datetime import time, timezone

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

_DETECT_MSGS = [
    "⁶🤷⁷ {user} just dropped 67 ×{count} time{plural}",
    "⁶🤷⁷ {user} is cooking with 67 ×{count}",
    "⁶🤷⁷ {user} hit the 67 again ×{count}",
    "⁶🤷⁷ {user} stays winning, 67 ×{count}",
    "⁶🤷⁷ {user} dropped another 67, that's ×{count}",
    "⁶🤷⁷ {user} cannot stop the 67 ×{count}",
    "⁶🤷⁷ {user} 67 streak continues ×{count}",
]

_NOTIFY_MODES = {"instant", "daily", "quiet"}


def build_application(config: Config, storage: Storage, detector: Detector) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["storage"] = storage
    app.bot_data["detector"] = detector

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("notify", cmd_notify))

    media_filter = (
        filters.PHOTO
        | filters.VIDEO
        | filters.VIDEO_NOTE
        | filters.ANIMATION
        | filters.Sticker.ALL
    )
    app.add_handler(MessageHandler(media_filter, on_media))

    # Daily summary at 0000 SGT = 1600 UTC
    app.job_queue.run_daily(
        daily_summary,
        time=time(hour=16, minute=0, tzinfo=timezone.utc),
        name="daily-67-summary",
    )

    return app


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "yo i'm the 67 bot. add me to a group and i'll watch every photo, "
        "video, gif, and sticker for 67. every time someone drops it, "
        "their counter goes up.\n\n"
        "commands:\n"
        "• /top — who's the 67 goat in this chat\n"
        "• /me — your 67 count\n"
        "• /notify — change how you get notified\n"
        "• /start — this"
    )


def _format_leaderboard(rows) -> str:
    if not rows:
        return "no 67s yet. skill issue 🫡"
    lines = ["67 leaderboard (who's the goat)", ""]
    for i, row in enumerate(rows):
        medal = _MEDALS[i] if i < len(_MEDALS) else f"{i + 1}."
        name = html.escape(row.display_name or (f"@{row.username}" if row.username else "Someone"))
        lines.append(f"{medal} {name} — {row.count} 67s")
    return "\n".join(lines)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.bot_data["storage"]
    rows = storage.leaderboard(update.effective_chat.id)
    await update.effective_message.reply_text(
        _format_leaderboard(rows), parse_mode=ParseMode.HTML
    )


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.bot_data["storage"]
    count = storage.user_count(update.effective_chat.id, update.effective_user.id)
    await update.effective_message.reply_text(
        f"you've dropped 67 {count} time{'s' if count != 1 else ''}. "
        f"{'keep going 🫡' if count > 0 else 'go touch grass and find 67'}"
    )


async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.bot_data["storage"]
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        # Show current mode
        mode = storage.get_notify_mode(chat_id)
        await update.effective_message.reply_text(
            f"current notify mode: {mode}\n\n"
            "options:\n"
            "• /notify instant — ping on every 67\n"
            "• /notify daily — daily recap at midnight\n"
            "• /notify quiet — only show on /top"
        )
        return

    mode = args[0].lower()
    if mode not in _NOTIFY_MODES:
        await update.effective_message.reply_text(
            f"'{mode}' ain't a mode. pick one: instant, daily, quiet"
        )
        return

    storage.set_notify_mode(chat_id, mode)
    labels = {"instant": "ping on every 67 ✨", "daily": "daily recap at midnight 🌙", "quiet": "only /top 🤫"}
    await update.effective_message.reply_text(f"notify mode set to: {labels[mode]}")


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

    # 69 gets a special response — no counter, no leaderboard
    if result.method == "ocr" and "69" in result.detail:
        await msg.reply_text("69. nice 😎👍")
        return

    new_count = storage.increment(
        update.effective_chat.id,
        user.id,
        user.full_name,
        user.username or "",
    )

    # Check notify mode
    mode = storage.get_notify_mode(update.effective_chat.id)
    if mode == "quiet":
        return
    if mode == "daily":
        return  # daily summary handled by the scheduled job

    # instant mode — reply right away
    plural = "s" if new_count != 1 else ""
    mention = user.mention_html()
    msg_text = random.choice(_DETECT_MSGS).format(
        user=mention, count=new_count, plural=plural
    )
    await msg.reply_text(msg_text, parse_mode=ParseMode.HTML)


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a 67 recap to every chat in 'daily' mode at midnight SGT."""
    storage: Storage = context.bot_data["storage"]
    for chat_id in storage.get_daily_chats():
        lb = storage.leaderboard(chat_id, limit=10)
        if lb:
            text = _format_daily_summary(lb)
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode=ParseMode.HTML
                )
            except Exception as exc:
                log.warning("failed to send daily summary to %d: %s", chat_id, exc)


def _format_daily_summary(rows) -> str:
    lines = ["🌙 daily 67 recap", ""]
    for i, row in enumerate(rows):
        medal = _MEDALS[i] if i < len(_MEDALS) else f"{i + 1}."
        name = html.escape(row.display_name or (f"@{row.username}" if row.username else "Someone"))
        lines.append(f"{medal} {name} — {row.count} 67s")
    return "\n".join(lines)