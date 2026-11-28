#!/usr/bin/env python3
"""Hand gcp-to-aws's AI track to the sibling bedrock-migration-assessment skill: probe it, route, convert, pass host answers, accept its artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BMA_BASE = HERE.parent.parent / "bedrock-migration-assessment"
HOST_SKILL = "gcp-to-aws"
INITIATED_BY = "GCP_TO_AWS"
INSTALL_HINT = ("Install the bedrock-migration-assessment skill from the same plugin as gcp-to-aws, "
                "then resume this migration.")
REQUIRED_FILES = (
    "SKILL.md",
    "scripts/validate-ai-profile.py",
    "scripts/readiness.py",
    "references/phases/discover/discover.md",
    "references/phases/discover/discover-app-code.md",
    "references/phases/clarify/clarify-ai-only.md",
    "references/phases/design/design-ai.md",
    "references/phases/estimate/estimate-ai.md",
    "references/phases/generate/generate-ai.md",
    "scripts/generate-ai.py",
)
# Fixed probe inputs: a minimal neutral profile the validator must accept and a legacy one it must reject.
GOOD_PROFILE = {"schema_version": "1.0", "gateways": [], "ai_sources": [{
    "provider": "openai", "source_service": "openai_api", "model_families": ["gpt"], "model_evidence": "observed",
    "models": ["gpt-4o"], "model_observations": [{"normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
                                                  "evidence": [{"provenance": "code", "confidence": "high"}]}]}]}
LEGACY_PROFILE = {"metadata": {}, "summary": {"ai_source": "openai"}, "models": []}
HOST_FIELDS = ("target_region", "compliance")
AI_TYPE_PREFIX = "google_vertex_ai"
NEUTRAL_PROFILE = "ai-workload-profile.neutral.json"
PHASE_ORDER = ("clarify", "design", "estimate", "generate")
THROUGH_FILES = {"clarify": ("preferences.json",), "design": ("preferences.json", "aws-design-ai.json"),
                 "estimate": ("preferences.json", "aws-design-ai.json", "estimation-ai.json"),
                 "generate": ("preferences.json", "aws-design-ai.json", "estimation-ai.json", "generation-ai.json")}
AI_MIGRATION = "ai-migration"
USAGE_PROFILES = ("openai-usage-profile.json", "anthropic-usage-profile.json", "openrouter-usage-profile.json")
VERTEX_SERVICES = ("vertex_ai_generative", "vertex_ai_embeddings")
# Legacy evidence sources that prove Vertex AI without reading code, and their #415 provenance and confidence.
PROOF = {"monitoring": ("live_api", "high", "gcp-to-aws Cloud Monitoring publisher tokens"),
         "terraform": ("iac", "medium", "gcp-to-aws Terraform Vertex AI resource")}
PREFS_OBJECTS = ("design_constraints", "metadata", "startup_constraints", "ai_constraints")
UNREADABLE = object()  # an ai-handoff.json that cannot be parsed; withdrawn like a non-object record
GEMINI_VERSION_SUFFIX = re.compile(r"(-latest|-preview(-[0-9-]+)?|-exp(-[0-9-]+)?|-[0-9]+)$")


class HandoffError(Exception):
    def __init__(self, error: str, detail: str, **extra: Any) -> None:
        super().__init__(f"{error}: {detail}")
        self.error, self.detail, self.extra = error, detail, extra


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, error: str) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(error, f"{path.name}: {exc}")


def _write_bytes(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _write_json(path: Path, doc: Any) -> None:
    _write_bytes(path, (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _run(script: str, *args: str) -> tuple[int, Any]:
    try:
        proc = subprocess.run([sys.executable, str(BMA_BASE / "scripts" / script), *args], capture_output=True, timeout=120)
        return proc.returncode, json.loads(proc.stdout.decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, json.JSONDecodeError):
        return 1, None


def probe() -> dict:
    if not BMA_BASE.is_dir():
        return {"status": "absent", "bma_base": str(BMA_BASE), "detail": "bedrock-migration-assessment is not installed"}
    try:
        _check_sibling()
    except HandoffError as exc:
        return {"status": "tampered", "bma_base": str(BMA_BASE), "detail": exc.detail}
    return {"status": "present", "bma_base": str(BMA_BASE), "detail": "checks passed"}


def _check_sibling() -> None:
    missing = [f for f in REQUIRED_FILES if not (BMA_BASE / f).is_file()]
    if missing:
        raise HandoffError("bma_tampered", f"missing {', '.join(missing)}")
    try:
        front = (BMA_BASE / "SKILL.md").read_text(encoding="utf-8").split("---", 2)
    except (OSError, UnicodeDecodeError) as exc:
        raise HandoffError("bma_tampered", f"SKILL.md is unreadable: {exc}")
    if len(front) < 3 or not re.search(r"^name: bedrock-migration-assessment\s*$", front[1], re.M):
        raise HandoffError("bma_tampered", "SKILL.md does not name bedrock-migration-assessment")
    with tempfile.TemporaryDirectory() as tmp:
        good, legacy = Path(tmp) / "good.json", Path(tmp) / "legacy.json"
        good.write_text(json.dumps(GOOD_PROFILE))
        legacy.write_text(json.dumps(LEGACY_PROFILE))
        code, out = _run("validate-ai-profile.py", str(good))
        if code != 0 or not isinstance(out, dict) or out.get("ok") is not True or out.get("schema_version") != "1.0":
            raise HandoffError("bma_tampered", "validate-ai-profile.py rejected a valid neutral profile")
        code, out = _run("validate-ai-profile.py", str(legacy))
        if code == 0 or not isinstance(out, dict) or out.get("error") != "legacy_profile_rejected":
            raise HandoffError("bma_tampered", "validate-ai-profile.py did not reject a legacy GCP profile")
        code, out = _run("readiness.py", str(Path(tmp) / "no-run"), "--through", "discover")
        if code == 0 or not isinstance(out, dict) or out.get("reason") != "run_not_found":
            raise HandoffError("bma_tampered", "readiness.py did not report run_not_found for a missing run")


def _require_present() -> None:
    result = probe()
    if result["status"] != "present":
        raise HandoffError("bma_tampered" if result["status"] == "tampered" else "bma_absent", result["detail"])


def _is_ai(item: Any, type_key: str) -> bool:
    if not isinstance(item, dict):
        return False
    kind = item.get(type_key)
    return str(kind).startswith(AI_TYPE_PREFIX) if kind else bool(item.get("ai_signals"))


def _has_infrastructure(gcp_dir: Path) -> bool:
    for name, key, type_key, error in (("gcp-resource-inventory.json", "resources", "type", "inventory_unreadable"),
                                       ("billing-profile.json", "services", "gcp_service_type", "billing_unreadable")):
        path = gcp_dir / name
        doc = _read_json(path, error) if path.exists() else None
        if isinstance(doc, dict) and any(not _is_ai(item, type_key) for item in doc.get(key) or []):
            return True
    return False


def _profile_digest(gcp_dir: Path) -> str:
    return "sha256:" + _sha((gcp_dir / "ai-workload-profile.json").read_bytes())


def _generated_file(rel: Any) -> bool:
    parts = rel.split("/") if isinstance(rel, str) else []
    return len(parts) > 1 and parts[0] == AI_MIGRATION and all(p not in ("", ".", "..") for p in parts)


def _inside(gcp_dir: Path, rel: str) -> bool:
    path = gcp_dir
    for part in rel.split("/"):
        path = path / part
        if path.is_symlink():
            return False
    return True


def _remove_copies(gcp_dir: Path, copied: dict) -> None:
    for rel, sha in copied.items():
        if rel not in (*THROUGH_FILES["generate"][1:], *USAGE_PROFILES) and not _generated_file(rel):
            continue
        path = gcp_dir / rel
        if _inside(gcp_dir, rel) and path.is_file() and sha == _sha(path.read_bytes()):
            path.unlink()
    root = gcp_dir / AI_MIGRATION
    if root.is_dir() and not root.is_symlink():
        for folder in sorted((d for d in root.rglob("*") if d.is_dir() and not d.is_symlink()), key=lambda d: len(d.parts), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
        if not any(root.iterdir()):
            root.rmdir()


def _held_record(path: Path) -> Any:
    try:
        return _read_json(path, "handoff_unreadable") if path.exists() else None
    except HandoffError:
        return UNREADABLE


def _gcp_prefs(path: Path) -> dict:
    prefs = _read_json(path, "preferences_unreadable")
    ok = isinstance(prefs, dict) and all(isinstance(prefs.get(k) or {}, dict) for k in PREFS_OBJECTS)
    source = (prefs.get("metadata") or {}).get("ai_preferences_source") if ok else None
    if source is not None:
        keys = source.get("startup_keys", []) if isinstance(source, dict) else None
        ok = isinstance(keys, list) and all(isinstance(k, str) for k in keys) and isinstance(source.get("startup_before", {}), dict)
    if not ok:
        raise HandoffError("preferences_unreadable", f"{path.name} has a field of the wrong type; run gcp-to-aws Clarify again")
    return prefs


def _withdraw(gcp_dir: Path) -> None:
    record_path = gcp_dir / "ai-handoff.json"
    record = _held_record(record_path)
    for field in ("artifacts", "usage_copies"):
        copied = record.get(field) if isinstance(record, dict) else None
        _remove_copies(gcp_dir, copied if isinstance(copied, dict) else {})
    (gcp_dir / NEUTRAL_PROFILE).unlink(missing_ok=True)
    prefs_path = gcp_dir / "preferences.json"
    prefs = _gcp_prefs(prefs_path) if prefs_path.exists() else None
    if isinstance(prefs, dict) and "ai_preferences_source" in (prefs.get("metadata") or {}):
        if prefs["metadata"].get("migration_type") == "ai-only":
            prefs_path.unlink()
        else:
            source = prefs["metadata"].pop("ai_preferences_source")
            prefs.pop("ai_constraints", None)
            if isinstance(source, dict) and "ai_constraints_before" in source:
                prefs["ai_constraints"] = source["ai_constraints_before"]
            startup = prefs.get("startup_constraints") or {}
            for key in source.get("startup_keys", []) if isinstance(source, dict) else []:
                startup.pop(key, None)
            startup.update(source.get("startup_before", {}) if isinstance(source, dict) else {})
            _write_json(prefs_path, prefs)
    record_path.unlink(missing_ok=True)


def route(gcp_dir: Path, infra_only: bool) -> tuple[int, dict]:
    record = gcp_dir / "ai-handoff.json"
    if not (gcp_dir / "ai-workload-profile.json").exists():
        _withdraw(gcp_dir)
        return 0, {"route": "no_ai", "message": "No AI workload was discovered; nothing to hand off."}
    status = probe()["status"]
    infra = _has_infrastructure(gcp_dir)
    if status == "present" and infra and infra_only:
        _withdraw(gcp_dir)
        _write_json(record, {"profile_digest": _profile_digest(gcp_dir), "status": "deferred", "reason": "user_chose_infra_only"})
        return 0, {"route": "defer", "reason": "user_chose_infra_only",
                   "message": "The AI workloads are deferred at your request; the infrastructure migration continues."}
    if status == "present":
        held = _held_record(record)
        if held is not None and (not isinstance(held, dict) or held.get("status") == "deferred"
                                 or held.get("profile_digest") != _profile_digest(gcp_dir)
                                 or held.get("infrastructure_moves") != infra):
            _withdraw(gcp_dir)
        return 0, {"route": "delegate", "message": "AI Clarify, Design, Estimate, and Generate run in bedrock-migration-assessment."}
    reason = "bma_absent" if status == "absent" else "bma_tampered"
    if infra and (status == "absent" or infra_only):
        _withdraw(gcp_dir)
        _write_json(record, {"profile_digest": _profile_digest(gcp_dir), "status": "deferred", "reason": reason})
        return 0, {"route": "defer", "reason": reason, "message": (
            "The AI workloads in this project are deferred: bedrock-migration-assessment is "
            + ("not installed. " if status == "absent" else "installed but failed its checks. ")
            + "The infrastructure migration continues without a Bedrock design. " + INSTALL_HINT)}
    if status == "absent":
        return 1, {"route": "stop", "reason": "bma_required", "message": (
            "This migration has only AI workloads, and bedrock-migration-assessment, which designs and prices them, "
            "is not installed. " + INSTALL_HINT)}
    return 1, {"route": "stop", "reason": "bma_tampered", "message": (
        "bedrock-migration-assessment is installed but failed its checks, so its results cannot be trusted. "
        "Reinstall it" + (", or continue with the infrastructure only and defer the AI workloads." if infra else "."))}


def _normalize(raw: str) -> str:
    model = raw.lower()
    model = re.sub(r"^(projects/[^/]+/locations/[^/]+/)?publishers/[a-z0-9_-]+/models/", "", model)
    if model.startswith("gemini-"):
        stripped = GEMINI_VERSION_SUFFIX.sub("", model)
        model = stripped if stripped != "gemini" else model
    return model


def _family(model: str) -> str:
    for prefix, family in (("gemini-", "gemini"), ("text-embedding-", "embedding")):
        if model.startswith(prefix):
            return family
    return re.split(r"[-.:/_]", model, maxsplit=1)[0]


def _evidence(model: dict) -> list[dict]:
    sources = {e.get("source") for e in model.get("evidence") or [] if isinstance(e, dict)}
    sources |= set(model.get("detected_via") or [])
    return [{"provenance": p, "confidence": c, "detail": d} for key, (p, c, d) in PROOF.items() if key in sources]


def convert(gcp_dir: Path, scan_path: Path | None) -> dict:
    _require_present()
    out_path = gcp_dir / NEUTRAL_PROFILE
    legacy = _read_json(gcp_dir / "ai-workload-profile.json", "legacy_unreadable")
    if not isinstance(legacy, dict) or not isinstance(legacy.get("models"), list):
        raise HandoffError("legacy_invalid", "the gcp-to-aws profile has no models[] array")
    profile: dict = {"schema_version": "1.0", "ai_sources": [], "gateways": []}
    if scan_path is not None:
        profile = _read_json(scan_path, "scan_unreadable")
        if _run("validate-ai-profile.py", str(scan_path))[0] != 0:
            raise HandoffError("scan_invalid", "bedrock-migration-assessment's validator rejected the scanned profile")
    observations: dict[str, dict] = {}
    not_converted = []
    for model in legacy["models"]:
        raw = model.get("model_id") if isinstance(model, dict) else None
        if not isinstance(raw, str) or not raw:
            not_converted.append({"model": raw if isinstance(raw, str) else None, "reason": "invalid_model_id"})
            continue
        if model.get("service") not in VERTEX_SERVICES:
            reason = "unsupported_service" if str(model.get("service", "")).startswith("vertex_") else "code_evidence_only"
            not_converted.append({"model": raw, "reason": reason})
            continue
        evidence = _evidence(model)
        if not evidence:
            not_converted.append({"model": raw, "reason": "code_evidence_only"})
            continue
        name = _normalize(raw)
        entry = observations.setdefault(name, {"normalized_model": name, "raw_model": raw, "model_family": _family(name), "evidence": []})
        entry["evidence"] += [e for e in evidence if e not in entry["evidence"]]
    if observations:
        _merge_vertex(profile, list(observations.values()))
    if not profile["ai_sources"] and not profile["gateways"]:
        raise HandoffError("no_ai_sources", "nothing in the profile proves an AI source without code, and no scan was given",
                           not_converted=not_converted)
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "profile.json"
        candidate.write_text(json.dumps(profile, indent=2))
        code, out = _run("validate-ai-profile.py", str(candidate))
    if code != 0:
        raise HandoffError("convert_invalid", f"the converted profile was rejected: {(out or {}).get('error')}")
    _withdraw(gcp_dir)
    _write_json(out_path, profile)
    _write_json(gcp_dir / "ai-handoff.json", {"profile_digest": _profile_digest(gcp_dir), "status": "converted",
                                               "assessment_profile_digest": "sha256:" + _sha(out_path.read_bytes()), "artifacts": {},
                                               "infrastructure_moves": _has_infrastructure(gcp_dir)})
    return {"ok": True, "out": str(out_path), "converted": sorted(observations), "not_converted": not_converted}


def _merge_vertex(profile: dict, observations: list[dict]) -> None:
    source = next((s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("google", "vertex_ai")), None)
    if source is None:
        source = {"provider": "google", "source_service": "vertex_ai", "model_families": [], "model_evidence": "observed",
                  "models": [], "model_observations": []}
        profile["ai_sources"].append(source)
    existing = {o["normalized_model"]: o for o in source["model_observations"]}
    for item in observations:
        if item["normalized_model"] in existing:
            target = existing[item["normalized_model"]]
            target["evidence"] += [e for e in item["evidence"] if e not in target["evidence"]]
        else:
            source["model_observations"].append(item)
    source["model_evidence"] = "observed"
    source["model_observations"].sort(key=lambda o: o["normalized_model"])
    source["models"] = [o["normalized_model"] for o in source["model_observations"]]
    source["model_families"] = sorted({o["model_family"] for o in source["model_observations"]} | set(source["model_families"]))
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "google" and upstream.get("source_service", "vertex_ai") == "vertex_ai":
                raise HandoffError("convert_conflict", f"{gateway['product']} already routes to Vertex AI; run the assessment on its own scan")


def _host_constraints(gcp_dir: Path) -> dict:
    prefs_path = gcp_dir / "preferences.json"
    if not _has_infrastructure(gcp_dir):
        return {}
    if not prefs_path.exists():
        raise HandoffError("preferences_missing", "this run moves infrastructure but has no preferences.json; run gcp-to-aws Clarify first")
    prefs = _gcp_prefs(prefs_path)
    given = prefs.get("design_constraints") or {}
    out = {}
    for field in HOST_FIELDS:
        wrapper = given.get(field)
        if isinstance(wrapper, dict) and "value" in wrapper:
            out[field] = {k: v for k, v in wrapper.items() if k not in ("question_id", "source")} | {"source": f"host:{HOST_SKILL}"}
    return out


def _open_record(gcp_dir: Path, bma_dir: Path) -> dict:
    record_path = gcp_dir / "ai-handoff.json"
    record = _read_json(record_path, "handoff_unreadable") if record_path.exists() else None
    if not isinstance(record, dict) or record.get("status") not in ("converted", "in_progress", "assessment_completed"):
        raise HandoffError("handoff_not_open", "no open AI handoff; run convert first")
    if not isinstance(record.get("artifacts", {}), dict) or not isinstance(record.get("usage_copies", {}), dict) \
            or record.get("through", "clarify") not in PHASE_ORDER:
        raise HandoffError("handoff_unreadable", "ai-handoff.json has a malformed artifacts, usage_copies or through field; run convert again")
    if record.get("profile_digest") != _profile_digest(gcp_dir):
        raise HandoffError("profile_changed", "ai-workload-profile.json changed after convert; run convert again and start a new assessment run")
    if record.get("infrastructure_moves") != _has_infrastructure(gcp_dir):
        raise HandoffError("infrastructure_changed", "whether infrastructure moves changed after convert; run route and convert again "
                           "and start a new assessment run")
    if record.get("assessment_dir") not in (None, bma_dir.name):
        raise HandoffError("handoff_mismatch", f"the open handoff names {record.get('assessment_dir')!r}, not {bma_dir.name!r}")
    return record


def _ready(bma_dir: Path, through: str) -> dict:
    code, ready = _run("readiness.py", str(bma_dir), "--through", through)
    if code != 0 or not isinstance(ready, dict) or ready.get("ready") is not True:
        if isinstance(ready, dict) and ready.get("ready") is False:
            raise HandoffError("assessment_not_ready", ready.get("detail", ""), reason=ready.get("reason"))
        raise HandoffError("bma_tampered", "readiness.py did not return a readiness answer")
    if ready.get("initiated_by") != INITIATED_BY:
        raise HandoffError("handoff_mismatch", f"{bma_dir.name} was not started by {HOST_SKILL}")
    return ready


def host_answers(gcp_dir: Path, bma_dir: Path, stop_after: str) -> dict:
    _require_present()
    record = _open_record(gcp_dir, bma_dir)
    data = _verified(bma_dir, _ready(bma_dir, "discover"), "discover")
    if "sha256:" + _sha(data["ai-workload-profile.json"]) != record.get("assessment_profile_digest"):
        raise HandoffError("assessment_profile_mismatch", f"{bma_dir.name} did not assess the profile convert wrote")
    record_path = gcp_dir / "ai-handoff.json"
    if record["status"] == "converted":
        record.update(assessment_dir=bma_dir.name, status="in_progress")
    constraints = _host_constraints(gcp_dir)
    held_path = bma_dir / "host-answers.json"
    held = _read_json(held_path, "host_answers_unreadable") if held_path.exists() else None
    if "through" in record and (not isinstance(held, dict) or held.get("design_constraints") != constraints):
        _remove_copies(gcp_dir, record.get("artifacts") or {})
        record.pop("through")
        record.update(status="in_progress", artifacts={})
    _write_json(held_path, {"host_skill": HOST_SKILL, "infrastructure_moves": _has_infrastructure(gcp_dir),
                            "stop_after": stop_after, "design_constraints": constraints})
    _write_json(record_path, record)
    return {"ok": True, "assessment_dir": bma_dir.name, "stop_after": stop_after}


def accept(gcp_dir: Path, bma_dir: Path, through: str) -> dict:
    _require_present()
    record_path = gcp_dir / "ai-handoff.json"
    record = _open_record(gcp_dir, bma_dir)
    if record["status"] == "converted" or not (bma_dir / "host-answers.json").exists():
        raise HandoffError("handoff_not_open", "no open AI handoff; start it with host-answers")
    if PHASE_ORDER.index(through) < PHASE_ORDER.index(record.get("through", "clarify")):
        raise HandoffError("accept_regressed", f"this handoff already accepted {record['through']}; accept {record['through']} or later")
    host = _read_json(bma_dir / "host-answers.json", "host_answers_unreadable")
    if not isinstance(host, dict) or host.get("design_constraints") != _host_constraints(gcp_dir):
        raise HandoffError("host_answers_stale", "gcp-to-aws region or compliance changed after the handoff; run host-answers again, then resume AI Clarify")
    data = _verified(bma_dir, _ready(bma_dir, through), through)
    if "sha256:" + _sha(data["ai-workload-profile.json"]) != record.get("assessment_profile_digest"):
        raise HandoffError("assessment_profile_mismatch", f"{bma_dir.name} no longer holds the profile this run handed over")
    copies = [name for name in data if name not in ("ai-workload-profile.json", "preferences.json")]
    unsafe = [rel for rel in copies if not _inside(gcp_dir, rel)]
    if unsafe:
        raise HandoffError("unsafe_destination", f"{unsafe[0]} passes through a symbolic link in this run directory; remove the link and accept again")
    earlier = record.get("artifacts") or {}
    edited = [rel for rel in copies if _generated_file(rel) and (gcp_dir / rel).is_file()
              and _sha((gcp_dir / rel).read_bytes()) not in (_sha(data[rel]), earlier.get(rel))]
    if edited:
        raise HandoffError("destination_changed", f"{edited[0]} was changed after the last accept; copy it elsewhere, remove it, and accept again")
    _merge_preferences(gcp_dir, bma_dir, data["preferences.json"])
    _remove_copies(gcp_dir, {rel: sha for rel, sha in (record.get("artifacts") or {}).items() if _generated_file(rel) and rel not in data})
    for rel in copies:
        (gcp_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        _write_bytes(gcp_dir / rel, data[rel])
    usage = _copy_usage(gcp_dir, bma_dir, record.get("usage_copies") or {})
    record.update(status="in_progress" if through in ("clarify", "design") else "assessment_completed", through=through,
                  artifacts={rel: _sha(data[rel]) for rel in data if rel != "ai-workload-profile.json"}, usage_copies=usage)
    _write_json(record_path, record)
    return {"ok": True, "through": through, "copied": copies, "artifacts": record["artifacts"], "usage_profiles": sorted(usage)}


def _copy_usage(gcp_dir: Path, bma_dir: Path, earlier: dict) -> dict:
    copied = {}
    for name in USAGE_PROFILES:
        source, target = bma_dir / name, gcp_dir / name
        ours = target.is_file() and not target.is_symlink() and earlier.get(name) == _sha(target.read_bytes())
        if target.exists() and not ours or target.is_symlink():
            continue
        if not source.is_file():
            if ours:
                target.unlink()
            continue
        try:
            raw = source.read_bytes()
        except OSError as exc:
            raise HandoffError("bma_tampered", f"{name} in the assessment run is unreadable: {exc}")
        _write_bytes(target, raw)
        copied[name] = _sha(raw)
    return copied


def _verified(bma_dir: Path, ready: dict, through: str) -> dict[str, bytes]:
    reported = ready.get("artifacts") or {}
    expected = ("ai-workload-profile.json", *THROUGH_FILES.get(through, ()))
    generated = [rel for rel in reported if rel not in expected] if through == "generate" else []
    outside = [rel for rel in generated if not _generated_file(rel)]
    if outside:
        raise HandoffError("bma_tampered", f"readiness.py reported {outside[0]!r}, which is not a file under {AI_MIGRATION}/")
    data = {}
    for name in (*expected, *sorted(generated)):
        try:
            raw = (bma_dir / name).read_bytes()
        except OSError as exc:
            raise HandoffError("bma_tampered", f"{name} became unreadable after readiness.py checked it: {exc}")
        if not isinstance(reported.get(name), dict) or reported[name].get("sha256") != _sha(raw):
            raise HandoffError("bma_tampered", f"readiness.py reported a SHA-256 for {name} that does not match the file")
        data[name] = raw
    return data


def _merge_preferences(gcp_dir: Path, bma_dir: Path, raw: bytes) -> None:
    assessment = json.loads(raw.decode("utf-8"))
    source = {"assessment_dir": bma_dir.name, "sha256": _sha(raw)}
    path = gcp_dir / "preferences.json"
    if not _has_infrastructure(gcp_dir):
        assessment.setdefault("metadata", {})["ai_preferences_source"] = source
        _write_json(path, assessment)
        return
    prefs = _gcp_prefs(path)
    earlier = (prefs.get("metadata") or {}).get("ai_preferences_source") or {}
    current = prefs.setdefault("startup_constraints", {})
    owned = set(earlier.get("startup_keys", []))
    host = {k: v for k, v in current.items() if k not in owned} | earlier.get("startup_before", {})
    startup = assessment.get("startup_constraints", {})
    prefs["startup_constraints"] = host | startup
    if "ai_preferences_source" in (prefs.get("metadata") or {}):
        if "ai_constraints_before" in earlier:
            source["ai_constraints_before"] = earlier["ai_constraints_before"]
    elif "ai_constraints" in prefs:
        source["ai_constraints_before"] = prefs["ai_constraints"]
    prefs["ai_constraints"] = assessment.get("ai_constraints", {})
    prefs.setdefault("metadata", {})["ai_preferences_source"] = source | {
        "startup_keys": sorted(startup), "startup_before": {k: host[k] for k in startup if k in host}}
    _write_json(path, prefs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="check that the sibling skill is installed and behaves as expected")
    p = sub.add_parser("route", help="decide how this run's AI track proceeds")
    p.add_argument("gcp_dir", type=Path)
    p.add_argument("--infra-only", action="store_true", help="the user chose to continue without the AI track")
    p = sub.add_parser("convert", help=f"write {NEUTRAL_PROFILE}, the neutral profile the assessment reads, and open the handoff")
    p.add_argument("gcp_dir", type=Path)
    p.add_argument("--scan", type=Path, help="a profile from the assessment's own application-code scan")
    p = sub.add_parser("host-answers", help="open the handoff and pass this run's region and compliance")
    p.add_argument("gcp_dir", type=Path)
    p.add_argument("bma_dir", type=Path)
    p.add_argument("--stop-after", choices=tuple(THROUGH_FILES), required=True)
    p = sub.add_parser("accept", help="check the assessment run and copy its artifacts into this run")
    p.add_argument("gcp_dir", type=Path)
    p.add_argument("bma_dir", type=Path)
    p.add_argument("--through", choices=tuple(THROUGH_FILES), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            result = probe()
            code = 0 if result["status"] == "present" else 1
        elif args.command == "route":
            code, result = route(args.gcp_dir, args.infra_only)
        else:
            if args.command == "convert":
                result = convert(args.gcp_dir, args.scan)
            elif args.command == "host-answers":
                result = host_answers(args.gcp_dir, args.bma_dir, args.stop_after)
            else:
                result = accept(args.gcp_dir, args.bma_dir, args.through)
            code = 0
    except HandoffError as exc:
        result, code = {"ok": False, "error": exc.error, "detail": exc.detail, **exc.extra}, 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
