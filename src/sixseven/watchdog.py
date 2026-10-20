"""Decide when Telegram has been unreachable long enough to give up and restart.

PTB's polling loop retries network errors forever, so when the network breaks
the bot stays "Up" while missing every message (2026-10-02: 45 silent minutes of
DNS failures). The bot probes the network on a timer, feeds the results in
here, and exits once failures have run unbroken past the threshold — a restart
loop is far easier to notice than a quietly deaf bot.
"""

from __future__ import annotations

import time
from typing import Callable


class NetworkWatchdog:
    def __init__(self, threshold: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._threshold = threshold
        self._clock = clock
        self._failing_since: float | None = None

    @property
    def is_failing(self) -> bool:
        return self._failing_since is not None

    @property
    def failing_for(self) -> float:
        """Seconds since the current run of failures began (0 when healthy)."""
        if self._failing_since is None:
            return 0.0
        return self._clock() - self._failing_since

    def record_success(self) -> None:
        self._failing_since = None

    def record_failure(self) -> bool:
        """Note a failed probe. Returns True once failures have lasted >= threshold."""
        if self._failing_since is None:
            self._failing_since = self._clock()
        return self.failing_for >= self._threshold
