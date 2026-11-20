#!/usr/bin/env python3
"""Tell another skill whether a bedrock-migration-assessment run is complete and valid through a phase, re-checking every artifact."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


design_ai = _load("bma_readiness_design", "design-ai.py")
estimate_ai = _load("bma_readiness_estimate", "estimate-ai.py")
validator = design_ai.validator

STATUS_SCHEMA = HERE.parent / "references" / "vendored" / "state" / "phase-status.schema.json"
# Phases in run order, each with the artifacts that phase leaves behind.
PHASES = (("discover", ("ai-workload-profile.json",)), ("clarify", ("preferences.json",)),
          ("design", ("aws-design-ai.json",)), ("estimate", ("estimation-ai.json",)))
THROUGH = tuple(name for name, _ in PHASES if name in ("design", "estimate"))


class NotReady(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _json(path: Path, missing: str, unreadable: str, read: dict[str, bytes] | None = None) -> Any:
    try:
        raw = path.read_bytes()
        if read is not None:
            read[path.name] = raw
        return json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        raise NotReady(missing, f"{path.name} is not in the run directory")
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise NotReady(unreadable, f"{path.name}: {exc}")


def _status(run_dir: Path) -> dict:
    if not run_dir.is_dir():
        raise NotReady("run_not_found", f"{run_dir} is not a directory")
    status = _json(run_dir / ".phase-status.json", "status_not_found", "status_unreadable")
    schema = json.loads(STATUS_SCHEMA.read_text(encoding="utf-8"))
    errors = validator._schema_errors(schema, status, schema) if isinstance(status, dict) else ["not an object"]
    if not errors:
        allowed = schema["properties"]["phases"]["additionalProperties"]["enum"]
        errors = [f"$.phases.{k}: {v!r} not in {allowed}" for k, v in status["phases"].items() if v not in allowed]
        errors += [] if status["phases"] else ["$.phases: no phases"]
    if errors:
        raise NotReady("status_invalid", "; ".join(errors[:3]))
    if not status["migration_id"].startswith("bma-") or "owning_skill" in status:
        raise NotReady("not_this_skill", f"run {status['migration_id']!r} was not created by bedrock-migration-assessment")
    return status


def check(run_dir: Path, through: str) -> dict:
    status = _status(run_dir)
    read: dict[str, bytes] = {}
    needed = PHASES[: [name for name, _ in PHASES].index(through) + 1]
    for name, _ in needed:
        state = status["phases"].get(name)
        if state != "completed":
            raise NotReady("phase_incomplete", f"phases.{name} is {state!r}; resume the run with bedrock-migration-assessment")
    profile = _json(run_dir / "ai-workload-profile.json", "artifact_missing", "artifact_unreadable", read)
    try:
        validator.validate_profile(profile)
    except validator.ProfileRejected as exc:
        raise NotReady("profile_invalid", f"{exc.code}: {exc.detail}")
    prefs = _json(run_dir / "preferences.json", "artifact_missing", "artifact_unreadable", read)
    try:
        if not isinstance(prefs, dict):
            raise design_ai.DesignInputError("preferences_invalid", "preferences.json must be a JSON object")
        design_ai.build_plan(profile, prefs)
    except design_ai.DesignInputError as exc:
        raise NotReady("preferences_invalid", f"{exc.code}: {exc.detail}")
    design = _json(run_dir / "aws-design-ai.json", "artifact_missing", "artifact_unreadable", read)
    result = design_ai.check_design(design, profile, prefs)
    if not result["ok"]:
        raise NotReady("design_invalid", "; ".join(e["code"] for e in result["errors"][:5]))
    if through == "estimate":
        estimate = _json(run_dir / "estimation-ai.json", "artifact_missing", "artifact_unreadable", read)
        try:
            result = estimate_ai.check_estimate(estimate, estimate_ai.figures_for(run_dir))
        except (estimate_ai.EstimateInputError, design_ai.DesignInputError) as exc:
            raise NotReady("estimate_invalid", f"{exc.code}: {exc.detail}")
        if not result["ok"]:
            raise NotReady("estimate_invalid", "; ".join(e["code"] for e in result["errors"][:5]))
    artifacts = {f: {"path": str(run_dir / f), "sha256": hashlib.sha256(read[f]).hexdigest()} for _, files in needed for f in files}
    return {"ready": True, "through": through, "migration_id": status["migration_id"], "run_id": status.get("run_id"), "artifacts": artifacts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="the bedrock-migration-assessment $MIGRATION_DIR")
    parser.add_argument("--through", choices=THROUGH, required=True, help="the last phase the caller needs")
    args = parser.parse_args(argv)
    try:
        result = check(args.run_dir, args.through)
    except NotReady as exc:
        result = {"ready": False, "through": args.through, "reason": exc.reason, "detail": exc.detail}
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
