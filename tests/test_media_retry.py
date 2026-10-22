"""Download-retry queue and network watchdog jobs, driven with fake Telegram objects."""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from telegram.error import BadRequest, NetworkError, TimedOut

from sixseven import bot as botmod
from sixseven.config import Config
from sixseven.storage import Storage
from sixseven.watchdog import NetworkWatchdog


class FakeFile:
    async def download_to_drive(self, path):
        with open(path, "wb") as f:
            f.write(b"img")


class FakeBot:
    def __init__(self, get_file_error=None):
        self.get_file_error = get_file_error
        self.sent = []

    async def get_file(self, file_id):
        if self.get_file_error is not None:
            raise self.get_file_error
        return FakeFile()

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=500 + len(self.sent))


class FakeDetector:
    def __init__(self, kinds=("67",)):
        self.kinds = list(kinds)

    def detect(self, path, kind):
        return SimpleNamespace(matched=bool(self.kinds), kinds=self.kinds)


class FakeApplication:
    def __init__(self):
        self.stopped = False

    def stop_running(self):
        self.stopped = True


@pytest.fixture
def ctx(tmp_path):
    executor = ThreadPoolExecutor(max_workers=1)
    context = SimpleNamespace(
        bot=FakeBot(),
        application=FakeApplication(),
        bot_data={
            "config": Config(telegram_bot_token="x"),
            "storage": Storage(str(tmp_path / "t.db")),
            "detector": FakeDetector(),
            "detect_executor": executor,
            "watchdog": NetworkWatchdog(300),
            "startup_time": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
    )
    yield context
    executor.shutdown()


def _queue(storage, message_id=10, quote=True, thread_id=None):
    storage.queue_pending_media(
        -100, message_id, thread_id, quote, 42, "Alice", "alice", "FILE", "image", "dns down"
    )


def _media_update(message_id=10):
    msg = SimpleNamespace(
        chat_id=-100,
        message_id=message_id,
        message_thread_id=None,
        is_topic_message=False,
        chat=SimpleNamespace(type="supergroup"),
        date=datetime.now(timezone.utc),
        photo=[SimpleNamespace(file_id="FILE", file_size=1000)],
        video=None,
        video_note=None,
        animation=None,
    )
    return SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=42, full_name="Alice", username="alice"),
        effective_chat=SimpleNamespace(id=-100),
    )


def test_retryable_errors():
    assert botmod._is_retryable(NetworkError("httpx.ConnectError: name resolution"))
    assert botmod._is_retryable(TimedOut())
    assert not botmod._is_retryable(BadRequest("File is too big"))
    assert not botmod._is_retryable(ValueError("corrupt"))


def test_media_ref_quotes_in_groups_only():
    group = botmod._MediaRef(-100, 10, 7, quote=True).reply_kwargs()
    assert group["chat_id"] == -100 and group["message_thread_id"] == 7
    assert group["reply_parameters"].message_id == 10
    assert group["reply_parameters"].allow_sending_without_reply

    private = botmod._MediaRef(42, 10, None, quote=False).reply_kwargs()
    assert "reply_parameters" not in private


def test_on_media_queues_download_network_failure(ctx):
    ctx.bot.get_file_error = NetworkError("httpx.ConnectError: name resolution")
    asyncio.run(botmod.on_media(_media_update(), ctx))

    rows = ctx.bot_data["storage"].pending_media()
    assert len(rows) == 1
    row = rows[0]
    assert (row["chat_id"], row["message_id"], row["user_id"]) == (-100, 10, 42)
    assert (row["display_name"], row["file_id"], row["quote"]) == ("Alice", "FILE", 1)
    assert ctx.bot.sent == []


def test_on_media_does_not_queue_bad_request(ctx):
    ctx.bot.get_file_error = BadRequest("File is too big")
    asyncio.run(botmod.on_media(_media_update(), ctx))
    assert ctx.bot_data["storage"].pending_media() == []


def test_retry_awards_point_and_replies_to_original(ctx):
    storage = ctx.bot_data["storage"]
    _queue(storage, message_id=10)
    asyncio.run(botmod.retry_pending_media(ctx))

    assert storage.pending_media() == []
    assert storage.user_count(-100, 42) == 1
    [award] = ctx.bot.sent
    assert award["chat_id"] == -100
    assert award["reply_parameters"].message_id == 10
    log_row = storage.points_log_by_id(1)
    assert log_row["media_message_id"] == 10
    assert log_row["award_message_id"] == 501


def test_retry_without_match_just_dequeues(ctx):
    ctx.bot_data["detector"] = FakeDetector(kinds=())
    storage = ctx.bot_data["storage"]
    _queue(storage)
    asyncio.run(botmod.retry_pending_media(ctx))
    assert storage.pending_media() == []
    assert storage.user_count(-100, 42) == 0
    assert ctx.bot.sent == []


def test_retry_keeps_item_on_network_failure_then_gives_up(ctx):
    ctx.bot.get_file_error = NetworkError("still down")
    storage = ctx.bot_data["storage"]
    _queue(storage)

    asyncio.run(botmod.retry_pending_media(ctx))
    [row] = storage.pending_media()
    assert row["attempts"] == 2 and row["last_error"] == "still down"

    for _ in range(botmod._PENDING_MAX_ATTEMPTS - 2):
        asyncio.run(botmod.retry_pending_media(ctx))
    assert storage.pending_media() == []


def test_retry_drops_non_retryable_failure(ctx):
    ctx.bot.get_file_error = BadRequest("wrong file_id")
    storage = ctx.bot_data["storage"]
    _queue(storage)
    asyncio.run(botmod.retry_pending_media(ctx))
    assert storage.pending_media() == []


def test_retry_waits_while_network_is_down(ctx):
    storage = ctx.bot_data["storage"]
    _queue(storage)
    ctx.bot_data["watchdog"].record_failure()
    asyncio.run(botmod.retry_pending_media(ctx))
    [row] = storage.pending_media()
    assert row["attempts"] == 1  # untouched
    assert ctx.bot.sent == []


def test_network_probe_stops_app_only_after_threshold(ctx, monkeypatch):
    async def failing_probe(bot):
        raise NetworkError("name resolution")

    monkeypatch.setattr(botmod, "_probe_telegram", failing_probe)
    clock = {"now": 0.0}
    ctx.bot_data["watchdog"] = NetworkWatchdog(300, clock=lambda: clock["now"])

    asyncio.run(botmod.network_probe(ctx))
    clock["now"] = 240
    asyncio.run(botmod.network_probe(ctx))
    assert not ctx.application.stopped

    clock["now"] = 300
    asyncio.run(botmod.network_probe(ctx))
    assert ctx.application.stopped
    assert ctx.bot_data["network_down_exit"] is True


def test_network_probe_success_resets_watchdog(ctx, monkeypatch):
    async def ok_probe(bot):
        return None

    monkeypatch.setattr(botmod, "_probe_telegram", ok_probe)
    ctx.bot_data["watchdog"].record_failure()
    asyncio.run(botmod.network_probe(ctx))
    assert not ctx.bot_data["watchdog"].is_failing
    assert not ctx.application.stopped
