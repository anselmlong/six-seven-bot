"""Telegram bot: watch a group's media, count each member's 'six sevens'."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import re
import tempfile
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as _dt_time, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
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
_RESET_SCHEDULES = {"off", "daily", "weekly", "monthly"}
_CHANGELOG_CHATS = {495290408}  # anselm's DM
_ANNOUNCE_MSG, _ANNOUNCE_CONFIRM = range(2)


def build_application(config: Config, storage: Storage, detector: Detector) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["storage"] = storage
    app.bot_data["detector"] = detector
    app.bot_data["startup_time"] = datetime.now(timezone.utc)

    # All detection runs on one dedicated worker thread. EasyOCR/torch/OpenCV
    # native code is not guaranteed re-entrant, so serialising through a single
    # thread rules out concurrent-access crashes and caps memory to one image
    # at a time — regardless of the Application's concurrent_updates setting.
    app.bot_data["detect_executor"] = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="detect"
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("notify", cmd_notify))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("changelog", cmd_changelog))

    # Announce conversation (whitelisted only)
    announce_conv = ConversationHandler(
        entry_points=[CommandHandler("announce", cmd_announce)],
        states={
            _ANNOUNCE_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, announce_receive_message),
                CommandHandler("cancel", announce_cancel),
            ],
            _ANNOUNCE_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, announce_confirm),
                CommandHandler("cancel", announce_cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", announce_cancel)],
        name="announce_conversation",
    )
    app.add_handler(announce_conv)

    media_filter = (
        filters.PHOTO
        | filters.VIDEO
        | filters.VIDEO_NOTE
        | filters.ANIMATION
    )
    app.add_handler(MessageHandler(media_filter, on_media))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)\bscuba"), cmd_scuba))
    app.add_error_handler(on_error)

    # Daily summary at 0000 SGT = 1600 UTC
    app.job_queue.run_daily(
        daily_summary,
        time=_dt_time(hour=16, minute=0, tzinfo=timezone.utc),
        name="daily-67-summary",
    )

    # Auto-reset check every hour
    app.job_queue.run_repeating(
        auto_reset_check,
        interval=3600,
        first=300,  # first check 5 min after startup
        name="auto-reset-check",
    )

    return app


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "yo i'm the 67 bot. add me to a group and i'll watch every photo, "
        "video, and gif for 67. every time someone drops it, "
        "their counter goes up.\n\n"
        "commands:\n"
        "• /top — who's the 67 goat in this chat\n"
        "• /me — your 67 count\n"
        "• /notify — change how you get notified\n"
        "• /reset — leaderboard reset (admin only)\n"
        "• /start — this"
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log any error PTB catches so it lands in the container logs with a
    traceback, instead of being silently swallowed."""
    log.error("unhandled error while processing an update", exc_info=context.error)


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


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset the leaderboard for this chat (admin only)."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    # Only group admins (or the bot's DM)
    if chat.type != "private":
        member = await chat.get_member(user.id)
        if member.status not in ("administrator", "creator"):
            await update.effective_message.reply_text("only admins can reset the leaderboard")
            return

    storage: Storage = context.bot_data["storage"]
    args = context.args

    if not args:
        schedule = storage.get_reset_schedule(chat.id)
        await update.effective_message.reply_text(
            f"current reset schedule: {schedule}\n\n"
            "options:\n"
            "• /reset now — wipe the leaderboard (requires confirmation)\n"
            "• /reset daily — auto-reset every day\n"
            "• /reset weekly — auto-reset every Monday\n"
            "• /reset monthly — auto-reset every 1st of the month\n"
            "• /reset off — disable auto-reset"
        )
        return

    cmd = args[0].lower()

    if cmd == "now":
        context.bot_data["pending_reset"] = {
            "chat_id": chat.id,
            "user_id": user.id,
            "time": _time.time(),
        }
        await update.effective_message.reply_text(
            "this will wipe ALL 67 counts for this chat. "
            "type /reset confirm within 30 seconds to proceed."
        )
        return

    if cmd == "confirm":
        pending = context.bot_data.get("pending_reset")
        if not pending or pending["chat_id"] != chat.id or pending["user_id"] != user.id:
            await update.effective_message.reply_text("no pending reset. start with /reset now")
            return
        if _time.time() - pending["time"] > 30:
            await update.effective_message.reply_text("confirmation expired. start again with /reset now")
            return
        del context.bot_data["pending_reset"]
        storage.reset_leaderboard(chat.id)
        await update.effective_message.reply_text("leaderboard reset. everyone starts fresh 🫡")
        return

    if cmd in _RESET_SCHEDULES:
        storage.set_reset_schedule(chat.id, cmd)
        labels = {
            "off": "auto-reset disabled",
            "daily": "resets daily at midnight",
            "weekly": "resets weekly on Monday",
            "monthly": "resets monthly on the 1st",
        }
        await update.effective_message.reply_text(f"reset schedule set to: {labels[cmd]}")
        return

    await update.effective_message.reply_text(f"'{cmd}' ain't a valid option. try /reset for help")


async def cmd_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the changelog (whitelisted chats only)."""
    if update.effective_chat.id not in _CHANGELOG_CHATS:
        return
    await update.effective_message.reply_text(
        "what's new in 67 bot:\n\n"
        "• stickers removed from detection (no more false positives)\n"
        "• /reset — admins can reset the leaderboard\n"
        "  • /reset now — manual reset with confirmation\n"
        "  • /reset daily|weekly|monthly — auto-reset on schedule\n"
        "• message dedup — no more double-counting from restarts\n"
        "• better OCR — removed aggressive preprocessing\n"
        "• upgraded vision model to gpt-4o for better accuracy\n"
        "• both 69 and 67 — if an image contains both, both messages fire"
    )


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the announce flow (whitelisted only)."""
    if update.effective_chat.id not in _CHANGELOG_CHATS:
        return ConversationHandler.END
    await update.effective_message.reply_text("send me the message to announce:")
    return _ANNOUNCE_MSG


async def announce_receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the message and send a test preview."""
    msg = update.effective_message.text
    context.bot_data["announce_msg"] = msg
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"[TEST] this is what will be sent:\n\n{msg}",
    )
    await update.effective_message.reply_text(
        "reply 'confirm' to broadcast to all chats, or 'cancel' to stop."
    )
    return _ANNOUNCE_CONFIRM


async def announce_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Broadcast the saved message to all known chats."""
    text = update.effective_message.text.strip().lower()
    if text not in ("confirm", "yes", "send", "y"):
        await update.effective_message.reply_text("cancelled.")
        return ConversationHandler.END

    msg = context.bot_data.pop("announce_msg", None)
    if not msg:
        await update.effective_message.reply_text("nothing to announce.")
        return ConversationHandler.END

    storage: Storage = context.bot_data["storage"]
    chat_ids = storage.get_all_chat_ids()

    sent = 0
    failed = 0
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=msg)
            sent += 1
            await asyncio.sleep(0.05)  # be nice to Telegram
        except Exception:
            failed += 1

    await update.effective_message.reply_text(
        f"done. sent to {sent} chat(s), {failed} failed."
    )
    return ConversationHandler.END


async def announce_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the announce flow."""
    context.bot_data.pop("announce_msg", None)
    await update.effective_message.reply_text("cancelled.")
    return ConversationHandler.END


_SCUBA_PATH = "/data/scuba.mp4"


async def cmd_scuba(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the scuba reaction when someone says 'scuba'."""
    if not os.path.exists(_SCUBA_PATH):
        return
    try:
        with open(_SCUBA_PATH, "rb") as f:
            await update.effective_message.reply_animation(f)
    except Exception as exc:
        log.warning("failed to send scuba reaction: %s", exc)


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
    return None


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    storage: Storage = context.bot_data["storage"]
    detector: Detector = context.bot_data["detector"]

    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    # Skip messages sent before the bot started (old queued updates)
    if msg.date and msg.date.replace(tzinfo=timezone.utc) < context.bot_data["startup_time"]:
        return

    # Dedup: skip messages already processed (survives restarts, re-delivery)
    if not storage.is_first_time(update.effective_chat.id, msg.message_id):
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
        log.info("on_media: downloading %s (kind=%s, size=%d)", file_id, kind, size or 0)
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(path)

        loop = asyncio.get_running_loop()
        executor: ThreadPoolExecutor = context.bot_data["detect_executor"]
        result = await loop.run_in_executor(executor, detector.detect, path, kind)
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

    kinds = set(result.kinds)

    # 69 gets a special response — no counter, no leaderboard
    if "69" in kinds:
        await msg.reply_text("69. nice 😎👍")

    if "67" in kinds:
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


async def auto_reset_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic check: reset leaderboards for chats whose schedule is due."""
    storage: Storage = context.bot_data["storage"]
    now = _time.time()
    for chat_id in storage.get_chats_due_for_reset(now):
        storage.reset_leaderboard(chat_id)
        log.info("auto-reset leaderboard for chat %d", chat_id)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="leaderboard auto-reset. everyone starts fresh 🫡",
            )
        except Exception as exc:
            log.warning("failed to notify chat %d of reset: %s", chat_id, exc)


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