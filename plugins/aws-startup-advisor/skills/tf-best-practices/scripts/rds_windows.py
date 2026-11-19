#!/usr/bin/env python3
"""Resolve RDS backup and maintenance windows without overlapping UTC ranges.

AWS requires a daily ``hh:mm-hh:mm`` backup window and a weekly
``ddd:hh:mm-ddd:hh:mm`` maintenance window, each at least 30 minutes long.
Ranges are half-open: one window can start exactly when the other ends.

Explicit windows are never moved; day names are normalized to lowercase.
Absent preferences use Sunday 04:00-04:30 UTC for maintenance and prefer
03:00-03:30 UTC for backup. These are deterministic defaults, not a claim
about the customer's off-peak hours. If necessary, an unspecified window
is moved to the first available 30-minute range. If no such range exists,
resolution fails instead of shortening or overlapping a window.

The CLI can read the skill's preferences.json. Its existing broad day
choices select the first permitted day (Tuesday for Tuesday-Thursday and
Saturday for Saturday-Sunday) and a 30-minute window at hour_utc.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Sequence


MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
MINIMUM_WINDOW_MINUTES = 30
DEFAULT_MAINTENANCE_WINDOW = "sun:04:00-sun:04:30"
DEFAULT_BACKUP_WINDOW = "03:00-03:30"

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CLOCK = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
_BACKUP_PATTERN = re.compile(rf"(?P<start>{_CLOCK})-(?P<end>{_CLOCK})")
_MAINTENANCE_PATTERN = re.compile(
    rf"(?P<start_day>mon|tue|wed|thu|fri|sat|sun):(?P<start>{_CLOCK})"
    rf"-(?P<end_day>mon|tue|wed|thu|fri|sat|sun):(?P<end>{_CLOCK})",
    re.IGNORECASE,
)
_PREFERENCE_DAYS = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
    "tuesday-thursday": "tue",
    "saturday-sunday": "sat",
    **{day: day for day in _DAYS},
}


def _clock_minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def _clock_text(minutes: int) -> str:
    hour, minute = divmod(minutes % MINUTES_PER_DAY, 60)
    return f"{hour:02d}:{minute:02d}"


def _parse_backup(window: str) -> tuple[str, int, int]:
    if not isinstance(window, str) or not (
        match := _BACKUP_PATTERN.fullmatch(window)
    ):
        raise ValueError(
            "backup_window must be a UTC range in hh:mm-hh:mm format"
        )
    start = _clock_minutes(match["start"])
    end = _clock_minutes(match["end"])
    duration = (end - start) % MINUTES_PER_DAY
    if duration < MINIMUM_WINDOW_MINUTES:
        raise ValueError("backup_window must last at least 30 minutes")
    return window, start, duration


def _parse_maintenance(window: str) -> tuple[str, int, int]:
    if not isinstance(window, str) or not (
        match := _MAINTENANCE_PATTERN.fullmatch(window)
    ):
        raise ValueError(
            "maintenance_window must be a UTC range in "
            "ddd:hh:mm-ddd:hh:mm format"
        )
    start_day = match["start_day"].lower()
    end_day = match["end_day"].lower()
    start = _DAYS.index(start_day) * MINUTES_PER_DAY + _clock_minutes(
        match["start"]
    )
    end = _DAYS.index(end_day) * MINUTES_PER_DAY + _clock_minutes(match["end"])
    duration = (end - start) % MINUTES_PER_WEEK
    if duration < MINIMUM_WINDOW_MINUTES:
        raise ValueError("maintenance_window must last at least 30 minutes")
    return window.lower(), start, duration


def _overlap(
    backup_start: int,
    backup_duration: int,
    maintenance_start: int,
    maintenance_duration: int,
) -> bool:
    maintenance_end = maintenance_start + maintenance_duration
    # Include the previous day's backup because it can cross midnight into
    # maintenance. Unrolling the maintenance week also handles Sunday wrap.
    first_day = maintenance_start // MINUTES_PER_DAY - 1
    last_day = (maintenance_end - 1) // MINUTES_PER_DAY
    for day in range(first_day, last_day + 1):
        start = day * MINUTES_PER_DAY + backup_start
        if start < maintenance_end and start + backup_duration > maintenance_start:
            return True
    return False


def windows_overlap(backup_window: str, maintenance_window: str) -> bool:
    """Return whether recurring daily backup and weekly maintenance overlap.

    Invalid windows raise ValueError; they are never interpreted as a pass.
    """
    _, backup_start, backup_duration = _parse_backup(backup_window)
    _, maintenance_start, maintenance_duration = _parse_maintenance(
        maintenance_window
    )
    return _overlap(
        backup_start, backup_duration, maintenance_start, maintenance_duration
    )


def resolve_windows(
    maintenance_window: str | None = None,
    backup_window: str | None = None,
) -> dict[str, str]:
    """Validate explicit windows and fill absent windows deterministically.

    Two explicit overlapping windows raise ValueError. An absent window can
    move, but every explicitly supplied window keeps the requested timing.
    """
    maintenance_explicit = maintenance_window is not None
    backup_explicit = backup_window is not None
    maintenance, maintenance_start, maintenance_duration = _parse_maintenance(
        DEFAULT_MAINTENANCE_WINDOW
        if maintenance_window is None
        else maintenance_window
    )
    backup, backup_start, backup_duration = _parse_backup(
        DEFAULT_BACKUP_WINDOW if backup_window is None else backup_window
    )

    if not _overlap(
        backup_start, backup_duration, maintenance_start, maintenance_duration
    ):
        return {"backup_window": backup, "maintenance_window": maintenance}

    if maintenance_explicit and backup_explicit:
        raise ValueError("explicit backup_window and maintenance_window overlap")

    if not backup_explicit:
        for offset in range(1, MINUTES_PER_DAY):
            candidate = (backup_start + offset) % MINUTES_PER_DAY
            if not _overlap(
                candidate,
                MINIMUM_WINDOW_MINUTES,
                maintenance_start,
                maintenance_duration,
            ):
                backup = (
                    f"{_clock_text(candidate)}-"
                    f"{_clock_text(candidate + MINIMUM_WINDOW_MINUTES)}"
                )
                return {
                    "backup_window": backup,
                    "maintenance_window": maintenance,
                }
        raise ValueError(
            "maintenance_window leaves no non-overlapping daily "
            "30-minute backup window"
        )

    # Only maintenance is absent. Keep its preferred day and move the
    # default's start around that day without changing the explicit backup.
    day_start = maintenance_start // MINUTES_PER_DAY * MINUTES_PER_DAY
    preferred_start = maintenance_start % MINUTES_PER_DAY
    for offset in range(1, MINUTES_PER_DAY):
        candidate = day_start + (preferred_start + offset) % MINUTES_PER_DAY
        if not _overlap(
            backup_start, backup_duration, candidate, MINIMUM_WINDOW_MINUTES
        ):
            end = (candidate + MINIMUM_WINDOW_MINUTES) % MINUTES_PER_WEEK
            maintenance = (
                f"{_DAYS[candidate // MINUTES_PER_DAY]}:{_clock_text(candidate)}-"
                f"{_DAYS[end // MINUTES_PER_DAY]}:{_clock_text(end)}"
            )
            return {"backup_window": backup, "maintenance_window": maintenance}
    raise ValueError(
        "backup_window leaves no non-overlapping weekly "
        "30-minute maintenance window"
    )


def _maintenance_preference(value: Any) -> str | None:
    if value is None or value == "flexible":
        return None
    if isinstance(value, str):
        return _parse_maintenance(value)[0]
    if not isinstance(value, dict) or set(value) != {"day", "hour_utc"}:
        raise ValueError(
            "global.maintenance_window must be 'flexible', an AWS weekly "
            "range, or an object containing day and hour_utc"
        )
    day = value["day"]
    hour = value["hour_utc"]
    if not isinstance(day, str) or day.lower() not in _PREFERENCE_DAYS:
        raise ValueError("global.maintenance_window.day is not supported")
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError(
            "global.maintenance_window.hour_utc must be an integer from 0 to 23"
        )
    selected_day = _PREFERENCE_DAYS[day.lower()]
    return f"{selected_day}:{hour:02d}:00-{selected_day}:{hour:02d}:30"


def _load_preferences(path: Path) -> tuple[str | None, str | None]:
    preferences = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(preferences, dict):
        raise ValueError("preferences.json must contain a JSON object")
    global_preferences = preferences.get("global", {})
    if not isinstance(global_preferences, dict):
        raise ValueError("preferences.json.global must contain a JSON object")
    return (
        _maintenance_preference(global_preferences.get("maintenance_window")),
        global_preferences.get("backup_window"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preferences",
        type=Path,
        help="read global maintenance_window and optional backup_window from JSON",
    )
    parser.add_argument(
        "--maintenance-window",
        help="explicit weekly UTC range, e.g. sun:04:00-sun:04:30",
    )
    parser.add_argument(
        "--backup-window",
        help="explicit daily UTC range, e.g. 03:00-03:30",
    )
    args = parser.parse_args(argv)
    if args.preferences is not None and (
        args.maintenance_window is not None or args.backup_window is not None
    ):
        parser.error("--preferences cannot be combined with explicit window flags")
    try:
        maintenance, backup = (
            _load_preferences(args.preferences)
            if args.preferences is not None
            else (args.maintenance_window, args.backup_window)
        )
        result = resolve_windows(maintenance, backup)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
