"""Exercise RDS window resolution, recurring overlap, and the packaged CLI."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills/tf-best-practices/scripts/rds_windows.py"
TEMPLATE = (
    PLUGIN_ROOT
    / "skills/heroku-to-aws/references/phases/generate/generate-terraform.md"
)
SPEC = importlib.util.spec_from_file_location("rds_windows", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
rds_windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rds_windows)


@pytest.mark.parametrize(
    ("backup", "maintenance", "overlap"),
    [
        ("03:00-03:30", "sun:04:00-sun:04:30", False),
        ("03:00-03:30", "wed:03:00-wed:03:30", True),
        ("03:00-03:30", "mon:03:15-mon:03:45", True),
        ("03:00-03:30", "thu:02:45-thu:03:15", True),
        ("03:00-03:30", "sun:03:30-sun:04:00", False),
        ("03:00-03:30", "sun:02:30-sun:03:00", False),
        ("23:45-00:15", "tue:00:00-tue:00:30", True),
        ("23:45-00:15", "tue:00:15-tue:00:45", False),
        ("23:45-00:15", "mon:23:15-mon:23:45", False),
        ("00:00-00:30", "sun:23:45-mon:00:15", True),
        ("00:15-00:45", "sun:23:45-mon:00:15", False),
        ("23:30-00:00", "sun:23:45-mon:00:15", True),
        ("23:15-23:45", "sun:23:45-mon:00:15", False),
        ("03:00-03:30", "sat:05:00-mon:02:00", True),
        ("03:00-03:30", "mon:04:00-tue:03:00", False),
        ("03:00-03:30", "mon:03:30-tue:03:00", False),
    ],
)
def test_recurring_overlap(backup: str, maintenance: str, overlap: bool) -> None:
    assert rds_windows.windows_overlap(backup, maintenance) is overlap


@pytest.mark.parametrize(
    "backup",
    [
        "",
        "3:00-03:30",
        "24:00-00:30",
        "00:60-01:30",
        "00:00-00:29",
        "23:50-00:10",
        "00:00-00:00",
        " 03:00-03:30",
        "03:00-03:30 UTC",
        "sun:03:00-sun:03:30",
        300,
        {},
    ],
)
def test_reject_invalid_backup(backup: object) -> None:
    with pytest.raises(ValueError, match="backup_window"):
        rds_windows.resolve_windows(backup_window=backup)
    with pytest.raises(ValueError, match="backup_window"):
        rds_windows.windows_overlap(backup, "sun:04:00-sun:04:30")


@pytest.mark.parametrize(
    "maintenance",
    [
        "",
        "sunday:04:00-sunday:04:30",
        "sun:4:00-sun:04:30",
        "sun:24:00-mon:00:30",
        "sun:04:60-sun:05:30",
        "sun:04:00-sun:04:29",
        "sun:23:50-mon:00:10",
        "sun:04:00-sun:04:00",
        " sun:04:00-sun:04:30",
        "sun:04:00-sun:04:30 UTC",
        "03:00-03:30",
        400,
        {},
    ],
)
def test_reject_invalid_maintenance(maintenance: object) -> None:
    with pytest.raises(ValueError, match="maintenance_window"):
        rds_windows.resolve_windows(maintenance_window=maintenance)
    with pytest.raises(ValueError, match="maintenance_window"):
        rds_windows.windows_overlap("03:00-03:30", maintenance)


def test_default_windows() -> None:
    assert rds_windows.resolve_windows() == {
        "backup_window": "03:00-03:30",
        "maintenance_window": "sun:04:00-sun:04:30",
    }


def test_explicit_windows_keep_requested_times() -> None:
    assert rds_windows.resolve_windows(
        "MON:00:30-MON:01:00", "23:30-00:30"
    ) == {
        "backup_window": "23:30-00:30",
        "maintenance_window": "mon:00:30-mon:01:00",
    }


def test_explicit_overlap_rejected_instead_of_moved() -> None:
    with pytest.raises(ValueError, match="explicit.*overlap"):
        rds_windows.resolve_windows("sun:03:00-sun:04:00", "03:00-03:30")


def test_explicit_week_wrap_overlap_rejected() -> None:
    with pytest.raises(ValueError, match="explicit.*overlap"):
        rds_windows.resolve_windows("sun:23:45-mon:00:15", "00:00-00:30")


def test_missing_backup_moves_but_preserves_maintenance() -> None:
    result = rds_windows.resolve_windows("tue:03:00-tue:04:00")
    assert result == {
        "backup_window": "04:00-04:30",
        "maintenance_window": "tue:03:00-tue:04:00",
    }


def test_missing_maintenance_moves_but_preserves_backup() -> None:
    result = rds_windows.resolve_windows(backup_window="03:45-04:15")
    assert result == {
        "backup_window": "03:45-04:15",
        "maintenance_window": "sun:04:15-sun:04:45",
    }


@pytest.mark.parametrize(
    "maintenance",
    [
        "sun:00:00-sun:23:31",
        "mon:00:00-tue:00:00",
        "sat:12:00-mon:00:00",
        "mon:00:01-mon:00:00",
    ],
)
def test_no_daily_backup_can_fit(maintenance: str) -> None:
    with pytest.raises(ValueError, match="no non-overlapping daily"):
        rds_windows.resolve_windows(maintenance)


def test_only_half_hour_daily_gap_is_used() -> None:
    assert rds_windows.resolve_windows("sun:00:00-sun:23:30") == {
        "backup_window": "23:30-00:00",
        "maintenance_window": "sun:00:00-sun:23:30",
    }


def test_only_half_hour_maintenance_gap_is_used_across_midnight() -> None:
    assert rds_windows.resolve_windows(backup_window="00:15-23:45") == {
        "backup_window": "00:15-23:45",
        "maintenance_window": "sun:23:45-mon:00:15",
    }


def test_no_maintenance_window_can_fit() -> None:
    with pytest.raises(ValueError, match="no non-overlapping weekly"):
        rds_windows.resolve_windows(backup_window="00:00-23:31")


def _clock(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _weekly_clock(minutes: int) -> str:
    minutes %= 10080
    return f"{('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[minutes // 1440]}:{_clock(minutes)}"


def test_overlap_matches_independent_minute_by_minute_oracle() -> None:
    rng = random.Random(76409)
    for case in range(400):
        backup_start = rng.randrange(1440)
        maintenance_start = rng.randrange(10080)
        backup_duration = rng.randrange(30, 1440 if case % 8 == 0 else 180)
        maintenance_duration = rng.randrange(
            30, 10080 if case % 8 == 0 else 180
        )
        backup = (
            f"{_clock(backup_start)}-{_clock(backup_start + backup_duration)}"
        )
        maintenance = (
            f"{_weekly_clock(maintenance_start)}-"
            f"{_weekly_clock(maintenance_start + maintenance_duration)}"
        )
        # Independently examine individual minutes in the weekly window.
        # This exercises all boundaries without reproducing the interval logic.
        expected = any(
            (minute - backup_start) % 1440 < backup_duration
            for minute in range(
                maintenance_start, maintenance_start + maintenance_duration
            )
        )
        assert rds_windows.windows_overlap(backup, maintenance) is expected, (
            backup,
            maintenance,
        )


def test_resolver_finds_daily_gap_when_one_exists() -> None:
    rng = random.Random(7919)
    for _ in range(200):
        start = rng.randrange(10080)
        duration = rng.randrange(30, 1411)
        maintenance = f"{_weekly_clock(start)}-{_weekly_clock(start + duration)}"
        windows = rds_windows.resolve_windows(maintenance)
        assert windows["maintenance_window"] == maintenance
        assert not rds_windows.windows_overlap(
            windows["backup_window"], windows["maintenance_window"]
        )


def test_resolver_finds_maintenance_gap_when_one_exists() -> None:
    rng = random.Random(8675309)
    for _ in range(200):
        start = rng.randrange(1440)
        duration = rng.randrange(30, 1411)
        backup = f"{_clock(start)}-{_clock(start + duration)}"
        windows = rds_windows.resolve_windows(backup_window=backup)
        assert windows["backup_window"] == backup
        assert not rds_windows.windows_overlap(
            windows["backup_window"], windows["maintenance_window"]
        )


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_direct_input_returns_json() -> None:
    result = _cli("--maintenance-window", "sun:03:00-sun:04:00")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "backup_window": "04:00-04:30",
        "maintenance_window": "sun:03:00-sun:04:00",
    }
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("preference", "expected"),
    [
        ("flexible", "sun:04:00-sun:04:30"),
        (None, "sun:04:00-sun:04:30"),
        ({"day": "tuesday-thursday", "hour_utc": 3}, "tue:03:00-tue:03:30"),
        ({"day": "saturday-sunday", "hour_utc": 3}, "sat:03:00-sat:03:30"),
        ({"day": "sunday", "hour_utc": 4}, "sun:04:00-sun:04:30"),
        ("FRI:23:45-SAT:00:15", "fri:23:45-sat:00:15"),
    ],
)
def test_cli_existing_preference_choices(
    tmp_path: Path, preference: object, expected: str
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"global": {"maintenance_window": preference}}))
    result = _cli("--preferences", str(path))
    assert result.returncode == 0, result.stderr
    windows = json.loads(result.stdout)
    assert windows["maintenance_window"] == expected
    assert not rds_windows.windows_overlap(
        windows["backup_window"], windows["maintenance_window"]
    )


def test_cli_explicit_preference_overlap_fails_with_no_json(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps(
            {
                "global": {
                    "maintenance_window": "fri:23:45-sat:00:15",
                    "backup_window": "00:00-00:30",
                }
            }
        )
    )
    result = _cli("--preferences", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "explicit backup_window and maintenance_window overlap" in result.stderr


@pytest.mark.parametrize(
    "preferences",
    [
        [],
        {"global": []},
        {"global": {"maintenance_window": "whenever"}},
        {"global": {"maintenance_window": {}}},
        {"global": {"maintenance_window": {"day": "holiday", "hour_utc": 3}}},
        {"global": {"maintenance_window": {"day": "sunday", "hour_utc": 24}}},
        {"global": {"maintenance_window": {"day": "sunday", "hour_utc": True}}},
        {
            "global": {
                "maintenance_window": {
                    "day": "sunday",
                    "hour_utc": 4,
                    "duration": 120,
                }
            }
        },
        {"global": {"backup_window": "bad"}},
    ],
)
def test_cli_rejects_unknown_preferences(
    tmp_path: Path, preferences: object
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps(preferences))
    result = _cli("--preferences", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("contents", ["{", "null", '"text"', "\ud800"])
def test_cli_rejects_unreadable_json(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "preferences.json"
    path.write_bytes(contents.encode("utf-8", errors="surrogatepass"))
    result = _cli("--preferences", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_missing_file(tmp_path: Path) -> None:
    result = _cli("--preferences", str(tmp_path / "missing.json"))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr


def test_cli_rejects_conflicting_input_sources(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text("{}")
    result = _cli(
        "--preferences", str(path), "--backup-window", "01:00-01:30"
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "cannot be combined" in result.stderr


def test_templates_use_distinct_validated_window_fields() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    database_section = text.split("## Step 7: Generate `database.tf`", 1)[1].split(
        "## Step 8:", 1
    )[0]
    assert "<preferences.json.global.maintenance_window formatted>" not in (
        database_section
    )
    assert 'backup_window           = "<rds-windows.json.backup_window>"' in text
    assert 'maintenance_window      = "<rds-windows.json.maintenance_window>"' in (
        text
    )
    assert 'preferred_backup_window      = "<rds-windows.json.backup_window>"' in (
        text
    )
    assert (
        'preferred_maintenance_window = "<rds-windows.json.maintenance_window>"'
        in text
    )
    assert "rds_windows.py" in database_section
    assert "MUST stop database generation" in database_section
    assert 'python3 "$PLUGIN_ROOT/skills/tf-best-practices/scripts/rds_windows.py"' not in database_section


def test_window_preparation_stays_before_worker_dispatch() -> None:
    root = TEMPLATE.parent.parent
    decision = (root / "estimate" / "estimate-assemble.md").read_text(
        encoding="utf-8"
    )
    assert "Prepare database windows in the main window" in decision
    assert 'python3 "$PLUGIN_ROOT/skills/tf-best-practices/scripts/rds_windows.py"' in decision
    assert "including database-window preparation even if no questions remain" in decision
