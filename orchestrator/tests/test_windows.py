"""Window occurrence math: recurring, absolute, freezes, blast ceilings."""

from __future__ import annotations

import datetime

from autonetops_orchestrator.windows import ChangeWindow, active_freezes, next_slot

UTC = datetime.timezone.utc


def dt(spec: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(spec).replace(tzinfo=UTC)


TUESDAY_NIGHT = ChangeWindow(
    name="emea-standard-maintenance",
    days=("tuesday", "thursday"),
    start_utc="21:00",
    duration_minutes=240,
    max_blast_radius="high",
    devices=frozenset({"pe-emea-01", "pe-emea-02", "core-rr-01"}),
)

ALWAYS_OPEN = ChangeWindow(
    name="lab-continuous",
    days=tuple(
        ["monday", "tuesday", "wednesday", "thursday", "friday",
         "saturday", "sunday"]),
    start_utc="00:00",
    duration_minutes=1440,
    max_blast_radius="moderate",
)

CORE_FREEZE = ChangeWindow(
    name="q3-core-audit-freeze",
    window_type="freeze",
    starts_at=dt("2026-07-20T00:00:00"),
    ends_at=dt("2026-07-27T00:00:00"),
    devices=frozenset({"core-rr-01"}),
)


def test_recurring_occurrence_and_midnight_span():
    # Tuesday 2026-07-14; window runs 21:00 -> 01:00 Wednesday
    occurrence = next(iter(TUESDAY_NIGHT.occurrences(dt("2026-07-13T09:00:00"))))
    assert occurrence == (dt("2026-07-14T21:00:00"), dt("2026-07-15T01:00:00"))
    # at 23:30 Tuesday the window is still active (started earlier that day)
    assert TUESDAY_NIGHT.active_at(dt("2026-07-14T23:30:00"))
    # ...and just past midnight it still is: the -1 day lookback
    assert TUESDAY_NIGHT.active_at(dt("2026-07-15T00:30:00"))
    assert not TUESDAY_NIGHT.active_at(dt("2026-07-15T02:00:00"))


def test_scope_and_blast_ceiling():
    assert TUESDAY_NIGHT.applies_to({"pe-emea-01"})
    assert not TUESDAY_NIGHT.applies_to({"ce-custc-01"})
    assert ALWAYS_OPEN.applies_to({"anything"})  # empty scope = all
    assert ALWAYS_OPEN.allows_blast("moderate")
    assert not ALWAYS_OPEN.allows_blast("high")


def test_next_slot_prefers_earliest_eligible():
    windows = [TUESDAY_NIGHT, ALWAYS_OPEN]
    now = dt("2026-07-13T09:00:00")
    slot = next_slot(windows, {"pe-emea-01"}, "moderate", now)
    assert slot is not None
    window, start, _end = slot
    assert window.name == "lab-continuous"  # open right now
    assert start == now
    # a high blast radius cannot ride lab-continuous; it waits for Tuesday
    window, start, _end = next_slot(windows, {"pe-emea-01"}, "high", now)
    assert window.name == "emea-standard-maintenance"
    assert start == dt("2026-07-14T21:00:00")


def test_freeze_defers_slot():
    always = ChangeWindow(
        name="always", days=ALWAYS_OPEN.days, start_utc="00:00",
        duration_minutes=1440, max_blast_radius="high",
    )
    now = dt("2026-07-21T12:00:00")  # inside the freeze
    assert active_freezes([CORE_FREEZE], {"core-rr-01"}, now)
    slot = next_slot([always, CORE_FREEZE], {"core-rr-01"}, "low", now)
    assert slot is not None
    _window, start, _end = slot
    assert start >= dt("2026-07-27T00:00:00")  # pushed past the freeze
    # devices outside the freeze scope are untouched by it
    _window, start, _end = next_slot([always, CORE_FREEZE], {"pe-emea-01"}, "low", now)
    assert start == now


def test_freeze_truncates_slot_end():
    always = ChangeWindow(
        name="always", days=ALWAYS_OPEN.days, start_utc="00:00",
        duration_minutes=1440, max_blast_radius="high",
    )
    now = dt("2026-07-19T12:00:00")  # freeze starts at 2026-07-20T00:00
    _window, start, end = next_slot([always, CORE_FREEZE], {"core-rr-01"}, "low", now)
    assert start == now
    assert end == dt("2026-07-20T00:00:00")


def test_need_minutes_skips_too_short_slots():
    short = ChangeWindow(
        name="short", days=("monday",), start_utc="10:00", duration_minutes=10,
        max_blast_radius="high",
    )
    long = ChangeWindow(
        name="long", days=("wednesday",), start_utc="10:00", duration_minutes=240,
        max_blast_radius="high",
    )
    now = dt("2026-07-13T09:00:00")  # Monday morning
    window, _start, _end = next_slot([short, long], {"x"}, "low", now, need_minutes=30)
    assert window.name == "long"


def test_next_slot_finds_gap_after_mid_window_freeze():
    """A freeze in the middle of a window must not kill the time after it."""
    import datetime

    UTC = datetime.timezone.utc
    window = ChangeWindow(
        name="nightly", days=("tuesday",), start_utc="01:00",
        duration_minutes=240, max_blast_radius="high",  # 01:00-05:00
    )
    freeze = ChangeWindow(
        name="mid-freeze", window_type="freeze",
        starts_at=datetime.datetime(2026, 7, 14, 1, 30, tzinfo=UTC),
        ends_at=datetime.datetime(2026, 7, 14, 2, 30, tzinfo=UTC),
    )
    after = datetime.datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    # 90 min does not fit before the freeze (only 30) but fits after it
    slot = next_slot([window, freeze], set(), "low", after, need_minutes=90)
    assert slot is not None
    _, start, end = slot
    assert start == datetime.datetime(2026, 7, 14, 2, 30, tzinfo=UTC)
    assert end - start >= datetime.timedelta(minutes=90)


def test_next_slot_overlapping_freezes_any_order():
    """Overlapping freezes must be walked in time order, not list order."""
    import datetime

    UTC = datetime.timezone.utc
    window = ChangeWindow(
        name="nightly", days=("tuesday",), start_utc="01:00",
        duration_minutes=240, max_blast_radius="high",
    )
    f1 = ChangeWindow(
        name="f1", window_type="freeze",
        starts_at=datetime.datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
        ends_at=datetime.datetime(2026, 7, 14, 1, 30, tzinfo=UTC),
    )
    f2 = ChangeWindow(
        name="f2", window_type="freeze",
        starts_at=datetime.datetime(2026, 7, 14, 1, 20, tzinfo=UTC),
        ends_at=datetime.datetime(2026, 7, 14, 1, 50, tzinfo=UTC),
    )
    after = datetime.datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    for freezes in ([f1, f2], [f2, f1]):  # order must not matter
        slot = next_slot([window, *freezes], set(), "low", after, need_minutes=30)
        assert slot is not None
        _, start, _end = slot
        assert start == datetime.datetime(2026, 7, 14, 1, 50, tzinfo=UTC)
