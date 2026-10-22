import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.watchdog import NetworkWatchdog


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_healthy_by_default():
    dog = NetworkWatchdog(300, clock=FakeClock())
    assert not dog.is_failing
    assert dog.failing_for == 0.0


def test_trips_only_after_threshold_of_unbroken_failures():
    clock = FakeClock()
    dog = NetworkWatchdog(300, clock=clock)
    assert dog.record_failure() is False  # first failure starts the clock
    clock.now += 299
    assert dog.record_failure() is False
    clock.now += 1
    assert dog.record_failure() is True
    assert dog.failing_for == 300


def test_success_resets_the_failure_run():
    clock = FakeClock()
    dog = NetworkWatchdog(300, clock=clock)
    dog.record_failure()
    clock.now += 250
    dog.record_success()
    assert not dog.is_failing
    clock.now += 100
    # A new failure starts a fresh run — the earlier 250s don't count.
    assert dog.record_failure() is False
    clock.now += 299
    assert dog.record_failure() is False
