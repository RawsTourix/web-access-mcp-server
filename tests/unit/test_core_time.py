from datetime import UTC, datetime

import pytest

from web_access.core.time import Deadline, FakeClock, SystemClock


def test_system_clock_is_utc_aware() -> None:
    now = SystemClock().utc_now()
    assert now.tzinfo is UTC


def test_fake_clock_and_deadline_are_deterministic() -> None:
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC), monotonic_time=10.0)
    deadline = Deadline.after(clock, 5.0)
    clock.advance(2.0)
    assert deadline.remaining(clock) == 3.0
    assert clock.utc_now() == datetime(2025, 1, 1, 0, 0, 2, tzinfo=UTC)
    assert not deadline.expired(clock)
    clock.advance(3.0)
    assert deadline.expired(clock)


def test_child_deadline_cannot_exceed_parent() -> None:
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC))
    parent = Deadline.after(clock, 3)
    assert parent.child(clock, 10).expires_at == parent.expires_at


def test_clock_and_deadline_reject_backwards_time() -> None:
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        Deadline.after(clock, -1)
