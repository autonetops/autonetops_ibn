"""Change windows: WHEN a plan may touch the network.

Windows live in the SoT (OpsChangeWindow in Infrahub) - data under review,
exactly like the intent. Two shapes share one kind: recurring weekly
(days + start_utc + duration_minutes) and absolute one-off
(starts_at + ends_at, used mainly by freezes). All math is UTC.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Iterator

WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
]

BLAST_ORDER = {"low": 0, "moderate": 1, "high": 2}

WINDOWS_QUERY = """
query ChangeWindows {
  OpsChangeWindow {
    edges {
      node {
        name { value }
        window_type { value }
        days { value }
        start_utc { value }
        duration_minutes { value }
        starts_at { value }
        ends_at { value }
        max_blast_radius { value }
        devices { edges { node { display_label } } }
      }
    }
  }
}
"""


def _parse_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


@dataclass(frozen=True)
class ChangeWindow:
    name: str
    window_type: str = "maintenance"  # maintenance | freeze
    days: tuple[str, ...] = ()
    start_utc: str | None = None  # "HH:MM"
    duration_minutes: int | None = None
    starts_at: datetime.datetime | None = None
    ends_at: datetime.datetime | None = None
    max_blast_radius: str = "moderate"
    devices: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_absolute(self) -> bool:
        return self.starts_at is not None and self.ends_at is not None

    def applies_to(self, devices: set[str]) -> bool:
        """Empty scope means every device."""
        return not self.devices or bool(self.devices & devices)

    def allows_blast(self, classification: str) -> bool:
        return BLAST_ORDER.get(classification, 2) <= BLAST_ORDER.get(
            self.max_blast_radius, 1
        )

    def occurrences(
        self, after: datetime.datetime, horizon_days: int = 14
    ) -> Iterator[tuple[datetime.datetime, datetime.datetime]]:
        """(start, end) pairs whose end lies after ``after``, in order."""
        if self.is_absolute:
            assert self.starts_at and self.ends_at
            if self.ends_at > after:
                yield self.starts_at, self.ends_at
            return
        if not self.days or not self.start_utc or not self.duration_minutes:
            return
        hour, minute = (int(part) for part in self.start_utc.split(":"))
        duration = datetime.timedelta(minutes=self.duration_minutes)
        for offset in range(-1, horizon_days + 1):  # -1: window may span midnight
            day = (after + datetime.timedelta(days=offset)).date()
            if WEEKDAYS[day.weekday()] not in self.days:
                continue
            start = datetime.datetime(
                day.year, day.month, day.day, hour, minute,
                tzinfo=datetime.timezone.utc,
            )
            if start + duration > after:
                yield start, start + duration

    def active_at(self, at: datetime.datetime) -> bool:
        return any(start <= at < end for start, end in self.occurrences(at))


def load_windows(client, branch: str = "main") -> list[ChangeWindow]:
    """Read every OpsChangeWindow from the SoT."""
    result = client.execute_graphql(query=WINDOWS_QUERY, branch_name=branch)
    windows: list[ChangeWindow] = []
    for edge in result["OpsChangeWindow"]["edges"]:
        node = edge["node"]

        def value(attr: str):
            return (node.get(attr) or {}).get("value")

        windows.append(ChangeWindow(
            name=value("name"),
            window_type=value("window_type") or "maintenance",
            days=tuple(value("days") or ()),
            start_utc=value("start_utc"),
            duration_minutes=value("duration_minutes"),
            starts_at=_parse_dt(value("starts_at")),
            ends_at=_parse_dt(value("ends_at")),
            max_blast_radius=value("max_blast_radius") or "moderate",
            devices=frozenset(
                e["node"]["display_label"]
                for e in (node.get("devices") or {}).get("edges", [])
            ),
        ))
    return windows


def active_freezes(
    windows: list[ChangeWindow], devices: set[str], at: datetime.datetime
) -> list[ChangeWindow]:
    return [
        w for w in windows
        if w.window_type == "freeze" and w.applies_to(devices) and w.active_at(at)
    ]


def next_slot(
    windows: list[ChangeWindow],
    devices: set[str],
    blast: str,
    after: datetime.datetime,
    need_minutes: int = 0,
    horizon_days: int = 14,
) -> tuple[ChangeWindow, datetime.datetime, datetime.datetime] | None:
    """Earliest usable (window, start, end) with at least ``need_minutes``
    inside a maintenance window, outside every applicable freeze.

    A freeze truncates or defers a slot; it never silently shrinks the plan.
    """
    eligible = [
        w for w in windows
        if w.window_type == "maintenance"
        and w.applies_to(devices)
        and w.allows_blast(blast)
    ]
    freezes = [
        w for w in windows if w.window_type == "freeze" and w.applies_to(devices)
    ]
    need = datetime.timedelta(minutes=need_minutes)

    slots: list[tuple[datetime.datetime, datetime.datetime, ChangeWindow]] = []
    for window in eligible:
        for start, end in window.occurrences(after, horizon_days):
            slots.append((max(start, after), end, window))
    slots.sort()

    for start, end, window in slots:
        cursor = start
        for freeze in freezes:
            for f_start, f_end in freeze.occurrences(cursor, horizon_days):
                if f_start <= cursor < f_end:  # slot begins inside a freeze
                    cursor = f_end
                elif cursor < f_start < end:  # freeze cuts the slot short
                    end = f_start
        if cursor < end and end - cursor >= need:
            return window, cursor, end
    return None
