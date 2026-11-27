#!/usr/bin/env python3
"""Hand azure-to-aws's AI track to the sibling bedrock-migration-assessment skill: probe it, route, convert, pass host answers, accept its artifacts."""
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
HOST_SKILL = "azure-to-aws"
INITIATED_BY = "AZURE_TO_AWS"
INSTALL_HINT = ("Install the bedrock-migration-assessment skill from the same plugin as azure-to-aws, "
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
)
# Fixed probe inputs: a minimal neutral profile the validator must accept and an Azure-shaped one it must reject.
GOOD_PROFILE = {"schema_version": "1.0", "gateways": [], "ai_sources": [{
    "provider": "openai", "source_service": "azure_openai", "model_families": ["gpt"], "model_evidence": "observed",
    "models": ["gpt-4o"], "model_observations": [{"normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
                                                  "evidence": [{"provenance": "iac", "confidence": "medium"}]}]}]}
LEGACY_PROFILE = {"metadata": {"profile_source": "iac_cognitive"}, "summary": {"ai_source": "azure_openai"}, "infrastructure": [],
                  "models": [{"model_id": "gpt-4o", "service": "azure_openai", "detected_via": ["terraform"]}]}
NEUTRAL_PROFILE = "ai-workload-profile.neutral.json"
PHASE_ORDER = ("clarify", "design", "estimate")
THROUGH_FILES = {"clarify": ("preferences.json",), "design": ("preferences.json", "aws-design-ai.json"),
                 "estimate": ("preferences.json", "aws-design-ai.json", "estimation-ai.json")}
# Azure-only rows of schema-discover-ai.md: ai_source "other" and these services stay on design-refs/ai.md.
TRADITIONAL_ML_SOURCE = "other"
AZURE_OPENAI_SERVICES = ("azure_openai", "azure_openai_embeddings")
AI_TYPE_PREFIXES = ("microsoft.cognitiveservices/", "microsoft.machinelearningservices/")
DEPLOYMENT_TYPES = ("azurerm_cognitive_deployment", "microsoft.cognitiveservices/accounts/deployments")
# bedrock-migration-assessment discover-app-code.md Step 4 patterns, plus Azure's bare whisper and tts model names.
OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4", "text-embedding-", "dall-e-", "whisper-", "tts-")
OPENAI_NAMES = ("whisper", "tts")
NORMALIZED_MODEL = re.compile(r"^(?!(?:both|unknown)$)[a-z0-9][a-z0-9._:/-]*$")
# Evidence kinds that prove a deployment without reading code, in state precedence order (schema-discover-ai.md Reconciliation).
PROOF = {"live": ("live_api", "high", "azure-to-aws live az deployment capture"),
         "rdfa": ("live_api", "medium", "azure-to-aws RDfA report deployment"),
         "terraform": ("iac", "medium", "azure-to-aws Terraform Cognitive Services deployment")}
PROOF_ALIASES = {"terraform": "terraform", "iac": "terraform", "live": "live", "live_az": "live", "rdfa": "rdfa", "rdfa_report": "rdfa"}
EVIDENCE_ORDER = ("terraform", "live", "rdfa")
PREFS_OBJECTS = ("global", "design_constraints", "metadata", "startup_constraints", "ai_constraints")
# Azure Clarify disposition to the assessment's chosen_by; PROPOSED is resolved per row.
CHOSEN_BY = {"DETECTED": "extracted", "ESSENTIAL": "user"}
# bedrock-migration-assessment schema-preferences.md constraint catalog: question text and design_consequence per host answer.
HOST_QUESTIONS = {"target_region": "Which AWS Region should this migration target?",
                  "compliance": "Do you have any compliance or regulatory requirements?"}
HOST_CONSEQUENCES = {"target_region": "Bedrock resources deploy in {}; model availability is checked for this region",
                     "compliance": "{} gates Bedrock models, regions, and logging"}
FIXES = {"inventory_unreadable": "; run azure-to-aws Discover again", "legacy_unreadable": "; run azure-to-aws Discover again",
         "preferences_unreadable": "; run azure-to-aws Clarify again", "handoff_unreadable": "; run route and convert again",
         "host_answers_unreadable": "; run host-answers again", "scan_unreadable": "; scan the code with bedrock-migration-assessment again"}
RECORDED_COPIES = ("artifacts", "pending_artifacts")  # pending_artifacts lists copies an accept is still writing
UNREADABLE = object()  # an ai-handoff.json that cannot be parsed; withdrawn like a non-object record


class HandoffError(Exception):
    def __init__(self, error: str, detail: str, **extra: Any) -> None:
        super().__init__(f"{error}: {detail}")
        self.error, self.detail, self.extra = error, detail, extra


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, error: str) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HandoffError(error, f"{path.name}: {exc}{FIXES.get(error, '')}")


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _check_destinations(*paths: Path) -> None:
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise HandoffError("unsafe_destination", f"{path.name} is a symbolic link or not a regular file; remove it and run the command again")


def _write_bytes(path: Path, data: bytes) -> None:
    _check_destinations(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_json(path: Path, doc: Any) -> None:
    _write_bytes(path, (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _run(script: str, *args: str) -> tuple[int, Any]:
    try:
        proc = subprocess.run([sys.executable, str(BMA_BASE / "scripts" / script), *args], capture_output=True, timeout=120)
        return proc.returncode, json.loads(proc.stdout.decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
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
            raise HandoffError("bma_tampered", "validate-ai-profile.py did not reject an Azure-shaped azure-to-aws profile")
        code, out = _run("readiness.py", str(Path(tmp) / "no-run"), "--through", "discover")
        if code == 0 or not isinstance(out, dict) or out.get("reason") != "run_not_found":
            raise HandoffError("bma_tampered", "readiness.py did not report run_not_found for a missing run")


def _require_present() -> None:
    result = probe()
    if result["status"] != "present":
        raise HandoffError("bma_tampered" if result["status"] == "tampered" else "bma_absent", result["detail"])


def _is_ai(item: Any) -> bool:
    kind = item.get("azure_type") if isinstance(item, dict) else None
    return isinstance(kind, str) and kind.lower().startswith(AI_TYPE_PREFIXES)


def _has_infrastructure(azure_dir: Path) -> bool:
    path = azure_dir / "azure-resource-inventory.json"
    doc = _read_json(path, "inventory_unreadable") if path.exists() else None
    resources = doc.get("resources", []) if isinstance(doc, dict) else []
    if not isinstance(resources, list):
        raise HandoffError("inventory_unreadable", f"{path.name} has a resources field that is not an array{FIXES['inventory_unreadable']}")
    return any(not _is_ai(item) for item in resources)


def _profile_digest(azure_dir: Path) -> str:
    try:
        return "sha256:" + _sha((azure_dir / "ai-workload-profile.json").read_bytes())
    except OSError as exc:
        raise HandoffError("legacy_unreadable", f"ai-workload-profile.json: {exc}{FIXES['legacy_unreadable']}")


def _ai_source(azure_dir: Path) -> Any:
    legacy = _read_json(azure_dir / "ai-workload-profile.json", "legacy_unreadable")
    summary = legacy.get("summary") if isinstance(legacy, dict) else None
    return summary.get("ai_source") if isinstance(summary, dict) else None


def _remove_copies(azure_dir: Path, copied: dict) -> None:
    for name in THROUGH_FILES["estimate"][1:]:
        path = azure_dir / name
        if path.is_file() and not path.is_symlink() and copied.get(name) == _sha(path.read_bytes()):
            path.unlink()


def _held_record(path: Path) -> Any:
    try:
        return _read_json(path, "handoff_unreadable") if path.exists() else None
    except HandoffError:
        return UNREADABLE


def _azure_prefs(path: Path) -> dict:
    prefs = _read_json(path, "preferences_unreadable")
    ok = isinstance(prefs, dict) and all(k not in prefs or isinstance(prefs[k], dict) for k in PREFS_OBJECTS)
    source = (prefs.get("metadata") or {}).get("ai_preferences_source") if ok else None
    if source is not None:
        keys = source.get("startup_keys", []) if isinstance(source, dict) else None
        ok = isinstance(keys, list) and all(isinstance(k, str) for k in keys) and isinstance(source.get("startup_before", {}), dict)
    if not ok:
        raise HandoffError("preferences_unreadable", f"{path.name} has a field of the wrong type; run azure-to-aws Clarify again")
    return prefs


def _withdraw(azure_dir: Path) -> None:
    record_path = azure_dir / "ai-handoff.json"
    record = _held_record(record_path)
    for field in RECORDED_COPIES:
        copied = record.get(field) if isinstance(record, dict) else None
        _remove_copies(azure_dir, copied if isinstance(copied, dict) else {})
    (azure_dir / NEUTRAL_PROFILE).unlink(missing_ok=True)
    _restore_preferences(azure_dir)
    record_path.unlink(missing_ok=True)


def _restore_preferences(azure_dir: Path) -> None:
    prefs_path = azure_dir / "preferences.json"
    prefs = _azure_prefs(prefs_path) if prefs_path.exists() else None
    if isinstance(prefs, dict) and "ai_preferences_source" in (prefs.get("metadata") or {}):
        if prefs["metadata"].get("migration_type") == "ai-only":
            before = prefs["metadata"]["ai_preferences_source"].get("preferences_before")
            if isinstance(before, dict):
                _write_json(prefs_path, before)
            else:
                prefs_path.unlink()
        else:
            source = prefs["metadata"].pop("ai_preferences_source")
            prefs.pop("ai_constraints", None)
            if isinstance(source, dict) and "ai_constraints_before" in source:
                prefs["ai_constraints"] = source["ai_constraints_before"]
            source = source if isinstance(source, dict) else {}
            startup = dict(prefs.get("startup_constraints") or {})
            for key in source.get("startup_keys", []):
                startup.pop(key, None)
            startup.update(source.get("startup_before", {}))
            prefs["startup_constraints"] = startup
            if source.get("startup_absent") and not startup:
                prefs.pop("startup_constraints")
            _write_json(prefs_path, prefs)


def _withdraw_if_stale(azure_dir: Path, infra: bool) -> None:
    held = _held_record(azure_dir / "ai-handoff.json")
    if held is not None and (not isinstance(held, dict) or held.get("status") == "deferred"
                             or held.get("profile_digest") != _profile_digest(azure_dir)
                             or held.get("infrastructure_moves") != infra):
        _withdraw(azure_dir)


def route(azure_dir: Path, infra_only: bool) -> tuple[int, dict]:
    record = azure_dir / "ai-handoff.json"
    if not (azure_dir / "ai-workload-profile.json").exists():
        _withdraw(azure_dir)
        return 0, {"route": "no_ai", "message": "No AI workload was discovered; nothing to hand off."}
    if _ai_source(azure_dir) == TRADITIONAL_ML_SOURCE:
        _withdraw(azure_dir)
        return 0, {"route": "traditional_ml", "message": (
            "The AI resources are Azure AI services or non-OpenAI models, which azure-to-aws designs with its own "
            "design-refs/ai.md rubric; nothing is handed to bedrock-migration-assessment.")}
    status = probe()["status"]
    infra = _has_infrastructure(azure_dir)
    if status == "present" and infra and infra_only:
        _withdraw(azure_dir)
        _write_json(record, {"profile_digest": _profile_digest(azure_dir), "status": "deferred", "reason": "user_chose_infra_only"})
        return 0, {"route": "defer", "reason": "user_chose_infra_only",
                   "message": "The AI workloads are deferred at your request; the infrastructure migration continues."}
    if status == "present":
        _withdraw_if_stale(azure_dir, infra)
        return 0, {"route": "delegate", "message": "AI Clarify, Design, and Estimate run in bedrock-migration-assessment."}
    reason = "bma_absent" if status == "absent" else "bma_tampered"
    if infra and (status == "absent" or infra_only):
        _withdraw(azure_dir)
        _write_json(record, {"profile_digest": _profile_digest(azure_dir), "status": "deferred", "reason": reason})
        return 0, {"route": "defer", "reason": reason, "message": (
            "The AI workloads in this subscription are deferred: bedrock-migration-assessment is "
            + ("not installed. " if status == "absent" else "installed but failed its checks. ")
            + "The azure-to-aws infrastructure migration continues without a Bedrock design. " + INSTALL_HINT)}
    _withdraw_if_stale(azure_dir, infra)
    if status == "absent":
        return 1, {"route": "stop", "reason": "bma_required", "message": (
            "This migration has only AI workloads, and bedrock-migration-assessment, which designs and prices them, "
            "is not installed. " + INSTALL_HINT)}
    return 1, {"route": "stop", "reason": "bma_tampered", "message": (
        "bedrock-migration-assessment is installed but failed its checks, so its results cannot be trusted. "
        "Reinstall it" + (", or continue with the infrastructure only and defer the AI workloads." if infra else "."))}


def _family(model: str) -> str:
    base = model.split(":")[1] if model.startswith("ft:") and ":" in model[3:] else model
    for prefix, family in (("gpt-", "gpt"), ("o1", "o_series"), ("o3", "o_series"), ("o4", "o_series"), ("text-embedding-", "embedding")):
        if base.startswith(prefix):
            return family
    match = re.match(r"[a-z][a-z0-9]*", base)
    return match.group(0) if match else "other"


def _model_reason(raw: Any, model_format: Any) -> str | None:
    if not isinstance(raw, str) or not NORMALIZED_MODEL.match(raw.lower()):
        return "invalid_model_id"
    if isinstance(model_format, str):
        return None if model_format.lower() == "openai" else "non_openai_model"
    return None if raw.lower().startswith(OPENAI_PREFIXES) or raw.lower() in OPENAI_NAMES else "non_openai_model"


def _row_sources(model: dict) -> set:
    sources = {e["source"] for e in _list(model.get("evidence")) if isinstance(e, dict) and isinstance(e.get("source"), str)}
    return sources | {s for s in _list(model.get("detected_via")) if isinstance(s, str)}


def _row_kinds(model: dict, raw: str, index: dict) -> tuple[set[str], bool]:
    kept, replaced = set(), set()
    for item in (e for e in _list(model.get("evidence")) if isinstance(e, dict)):
        kind = PROOF_ALIASES.get(item["source"]) if isinstance(item.get("source"), str) else None
        if kind is None:
            continue
        address, azure_id = (item.get(k) if isinstance(item.get(k), str) else None for k in ("address", "azure_id"))
        deployment = index.get(("address", address)) or index.get(("azure_id", azure_id and azure_id.lower()))
        if deployment is not None and kind == "terraform":
            deployment["declared"].add(raw.lower())
        state = _state_model(deployment) if deployment is not None else None
        (replaced if state is not None and state != raw.lower() else kept).add(kind)
    listed = {PROOF_ALIASES[s] for s in _list(model.get("detected_via")) if isinstance(s, str) and s in PROOF_ALIASES}
    return kept | (listed - replaced), bool(replaced)


def _entry_kinds(entry: dict) -> set[str]:
    named = [entry.get("source"), *_list(entry.get("sources"))]
    kinds = {PROOF_ALIASES[s] for s in named if isinstance(s, str) and s in PROOF_ALIASES}
    return kinds | ({"terraform"} if entry.get("address") else set())


def _deployment_model(entry: dict) -> tuple[Any, Any]:
    config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
    model = config.get("model")
    if isinstance(model, dict):
        return model.get("name"), model.get("format")
    return model, config.get("model_format")


def _is_deployment(entry: Any) -> bool:
    return isinstance(entry, dict) and (entry.get("role") == "deployment" or str(entry.get("type", "")).lower() in DEPLOYMENT_TYPES)


def _evidence(kinds: set[str]) -> list[dict]:
    return [{"provenance": p, "confidence": c, "detail": d} for kind in EVIDENCE_ORDER if kind in kinds for p, c, d in [PROOF[kind]]]


def _observe(observations: dict, raw: str, kinds: set[str]) -> None:
    name = raw.lower()
    entry = observations.setdefault(name, {"normalized_model": name, "raw_model": raw, "model_family": _family(name), "evidence": []})
    entry["evidence"] += [e for e in _evidence(kinds) if e not in entry["evidence"]]
    entry["evidence"].sort(key=lambda e: [PROOF[k][:2] for k in EVIDENCE_ORDER].index((e["provenance"], e["confidence"])))


def _from_models(models: list, deployments: list[dict], observations: dict, not_converted: list) -> None:
    index = {(key, value): d for d in deployments for key in ("address", "azure_id") for value in d[key]}
    for model in models:
        raw = model.get("model_id") if isinstance(model, dict) else None
        if not isinstance(raw, str) or not raw:
            not_converted.append({"model": raw if isinstance(raw, str) else None, "reason": "invalid_model_id"})
            continue
        service = str(model.get("service", ""))
        kinds, replaced = _row_kinds(model, raw, index)
        if service.startswith("cognitive_") or service == "azure_ml":
            reason = "traditional_ml"
        elif service not in AZURE_OPENAI_SERVICES:
            reason = "code_evidence_only"
        elif not kinds:
            reason = "drifted_deployment_model" if replaced else "code_evidence_only" if "code" in _row_sources(model) else "no_provenance"
        else:
            reason = _model_reason(raw, None)
        if reason:
            not_converted.append({"model": raw, "reason": reason})
        else:
            _observe(observations, raw, kinds)


def _deployments(infrastructure: list) -> list[dict]:
    groups: dict[Any, list[dict]] = {}
    for index, entry in enumerate(e for e in infrastructure if _is_deployment(e)):
        azure_id = entry.get("azure_id")
        groups.setdefault(azure_id.lower() if isinstance(azure_id, str) and azure_id else index, []).append(entry)
    return [{"entries": entries, "declared": set(),
             "named": sorted(((min((list(PROOF).index(k) for k in _entry_kinds(e)), default=len(PROOF)), *_deployment_model(e))
                              for e in entries if _deployment_model(e)[0] is not None), key=lambda n: n[0]),
             "address": {e["address"] for e in entries if isinstance(e.get("address"), str) and e["address"]},
             "azure_id": {e["azure_id"].lower() for e in entries if isinstance(e.get("azure_id"), str) and e["azure_id"]}}
            for entries in groups.values()]


def _state_model(deployment: dict) -> str | None:
    named = deployment["named"]
    return named[0][1].lower() if named and isinstance(named[0][1], str) else None


def _from_infrastructure(deployments: list[dict], observations: dict, not_converted: list) -> None:
    for deployment in deployments:
        entries, named = deployment["entries"], deployment["named"]
        if not named:
            label = next((e.get(k) for e in entries for k in ("address", "azure_id") if isinstance(e.get(k), str)), None)
            not_converted.append({"model": None, "reason": "deployment_without_model", "deployment": label})
            continue
        _, raw, model_format = named[0]
        kinds = set()
        for entry in (e for e in entries if str(_deployment_model(e)[0]).lower() == str(raw).lower()):
            entry_kinds = _entry_kinds(entry)
            # A merged entry's config follows state, so its address proves the model only when a Terraform row declares it.
            if entry_kinds - {"terraform"} and str(raw).lower() not in deployment["declared"]:
                entry_kinds.discard("terraform")
            kinds |= entry_kinds
        reason = _model_reason(raw, model_format)
        if reason:
            not_converted.append({"model": raw if isinstance(raw, str) else None, "reason": reason})
        elif kinds:
            _observe(observations, raw, kinds)
        else:
            not_converted.append({"model": raw, "reason": "no_provenance"})
        not_converted += [{"model": other, "reason": "drifted_deployment_model"} for _, other, _ in named[1:]
                          if isinstance(other, str) and other.lower() != str(raw).lower()]


def convert(azure_dir: Path, scan_path: Path | None) -> dict:
    _require_present()
    out_path, record_path = azure_dir / NEUTRAL_PROFILE, azure_dir / "ai-handoff.json"
    _check_destinations(out_path, record_path)
    legacy = _read_json(azure_dir / "ai-workload-profile.json", "legacy_unreadable")
    if not isinstance(legacy, dict) or not isinstance(legacy.get("models"), list) \
            or not isinstance(legacy.get("infrastructure", []), list):
        raise HandoffError("legacy_invalid", "the azure-to-aws profile has no models[] array or a non-array infrastructure field")
    profile: dict = {"schema_version": "1.0", "ai_sources": [], "gateways": []}
    if scan_path is not None:
        profile = _read_json(scan_path, "scan_unreadable")
        if _run("validate-ai-profile.py", str(scan_path))[0] != 0:
            raise HandoffError("scan_invalid", "bedrock-migration-assessment's validator rejected the scanned profile")
    observations: dict[str, dict] = {}
    not_converted: list[dict] = []
    deployments = _deployments(legacy.get("infrastructure", []))
    _from_models(legacy["models"], deployments, observations, not_converted)
    _from_infrastructure(deployments, observations, not_converted)
    if observations:
        _merge_azure_openai(profile, list(observations.values()))
    if not profile["ai_sources"] and not profile["gateways"]:
        raise HandoffError("no_ai_sources", "nothing in the profile proves an AI source without code, and no scan was given",
                           not_converted=not_converted)
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "profile.json"
        candidate.write_text(json.dumps(profile, indent=2))
        code, out = _run("validate-ai-profile.py", str(candidate))
    if code != 0:
        raise HandoffError("convert_invalid", f"the converted profile was rejected: {(out or {}).get('error')}")
    _withdraw(azure_dir)
    _write_json(out_path, profile)
    _write_json(record_path, {"profile_digest": _profile_digest(azure_dir), "status": "converted",
                              "assessment_profile_digest": "sha256:" + _sha(out_path.read_bytes()), "artifacts": {},
                              "infrastructure_moves": _has_infrastructure(azure_dir)})
    kept = set(next((s["models"] for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("openai", "azure_openai")), []))
    not_converted = [n for i, n in enumerate(not_converted) if not (isinstance(n["model"], str) and n["model"].lower() in kept)
                     and not (n["reason"] == "drifted_deployment_model" and n in not_converted[:i])]
    return {"ok": True, "out": str(out_path), "converted": sorted(observations), "not_converted": not_converted}


def _merge_azure_openai(profile: dict, observations: list[dict]) -> None:
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "openai" and upstream.get("source_service", "azure_openai") == "azure_openai":
                raise HandoffError("convert_conflict", f"{gateway['product']} already routes to OpenAI or Azure OpenAI; "
                                   "run the assessment on its own scan")
    source = next((s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("openai", "azure_openai")), None)
    if source is None:
        source = {"provider": "openai", "source_service": "azure_openai", "model_families": [], "model_evidence": "observed",
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


def _host_answer(field: str, row: Any) -> dict | None:
    value = row.get("value") if isinstance(row, dict) else None
    if field == "target_region" and not (isinstance(value, str) and value):
        return None
    if field == "compliance":
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            return None
        value = value or ["none"]
    disposition = row.get("disposition")
    chosen_by = CHOSEN_BY.get(disposition) or (("default" if row.get("value") == row.get("default") else "user")
                                                if disposition == "PROPOSED" else None)
    if chosen_by is None:
        return None
    shown = value if isinstance(value, str) else ", ".join(value)
    detail = row.get("source") if isinstance(row.get("source"), str) and row["source"].strip() else None
    prompt = {"extracted": f"Detected by {HOST_SKILL}: {shown}" + (f" ({detail})" if detail else ""),
              "user": f"{HOST_QUESTIONS[field]} (answered in {HOST_SKILL} Clarify)",
              "default": f"{HOST_QUESTIONS[field]} (default applied)"}[chosen_by]
    return {"value": value, "chosen_by": chosen_by, "prompt": prompt, "design_consequence": HOST_CONSEQUENCES[field].format(shown),
            "source": f"host:{HOST_SKILL}"}


def _host_constraints(azure_dir: Path) -> dict:
    prefs_path = azure_dir / "preferences.json"
    if not _has_infrastructure(azure_dir):
        return {}
    if not prefs_path.exists():
        raise HandoffError("preferences_missing", "this run moves infrastructure but has no preferences.json; run azure-to-aws Clarify first")
    prefs = _azure_prefs(prefs_path)
    out = {}
    for field, section in (("target_region", "global"), ("compliance", "design_constraints")):
        answer = _host_answer(field, (prefs.get(section) or {}).get(field))
        if answer is not None:
            out[field] = answer
    return out


def _open_record(azure_dir: Path, bma_dir: Path) -> dict:
    record_path = azure_dir / "ai-handoff.json"
    record = _read_json(record_path, "handoff_unreadable") if record_path.exists() else None
    if not isinstance(record, dict) or record.get("status") not in ("converted", "in_progress", "assessment_completed"):
        raise HandoffError("handoff_not_open", "no open AI handoff; run convert first")
    if not all(isinstance(record.get(f, {}), dict) for f in RECORDED_COPIES) or record.get("through", "clarify") not in PHASE_ORDER:
        raise HandoffError("handoff_unreadable", "ai-handoff.json has a malformed artifacts or through field; run convert again")
    if record.get("profile_digest") != _profile_digest(azure_dir):
        raise HandoffError("profile_changed", "ai-workload-profile.json changed after convert; run convert again and start a new assessment run")
    if record.get("infrastructure_moves") != _has_infrastructure(azure_dir):
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


def host_answers(azure_dir: Path, bma_dir: Path, stop_after: str) -> dict:
    _require_present()
    record_path, held_path = azure_dir / "ai-handoff.json", bma_dir / "host-answers.json"
    _check_destinations(record_path, held_path)
    record = _open_record(azure_dir, bma_dir)
    data = _verified(bma_dir, _ready(bma_dir, "discover"), "discover")
    if "sha256:" + _sha(data["ai-workload-profile.json"]) != record.get("assessment_profile_digest"):
        raise HandoffError("assessment_profile_mismatch", f"{bma_dir.name} did not assess the profile convert wrote")
    if record["status"] == "converted":
        record.update(assessment_dir=bma_dir.name, status="in_progress")
    constraints = _host_constraints(azure_dir)
    held = _held_record(held_path)
    if "through" in record and (not isinstance(held, dict) or held.get("design_constraints") != constraints):
        for field in RECORDED_COPIES:
            _remove_copies(azure_dir, record.pop(field, {}))
        _restore_preferences(azure_dir)
        record.pop("through")
        record.update(status="in_progress", artifacts={})
    _write_json(record_path, record)
    _write_json(held_path, {"host_skill": HOST_SKILL, "infrastructure_moves": _has_infrastructure(azure_dir),
                            "stop_after": stop_after, "design_constraints": constraints})
    return {"ok": True, "assessment_dir": bma_dir.name, "stop_after": stop_after, "host_answers": sorted(constraints)}


def accept(azure_dir: Path, bma_dir: Path, through: str) -> dict:
    _require_present()
    record_path = azure_dir / "ai-handoff.json"
    _check_destinations(record_path, *(azure_dir / name for name in THROUGH_FILES["estimate"]))
    record = _open_record(azure_dir, bma_dir)
    if record["status"] == "converted" or not (bma_dir / "host-answers.json").exists():
        raise HandoffError("handoff_not_open", "no open AI handoff; start it with host-answers")
    if PHASE_ORDER.index(through) < PHASE_ORDER.index(record.get("through", "clarify")):
        raise HandoffError("accept_regressed", f"this handoff already accepted {record['through']}; accept {record['through']} or later")
    host = _read_json(bma_dir / "host-answers.json", "host_answers_unreadable")
    if not isinstance(host, dict) or host.get("design_constraints") != _host_constraints(azure_dir):
        raise HandoffError("host_answers_stale", "azure-to-aws region or compliance changed after the handoff; run host-answers again, "
                           "then resume AI Clarify")
    data = _verified(bma_dir, _ready(bma_dir, through), through)
    if "sha256:" + _sha(data["ai-workload-profile.json"]) != record.get("assessment_profile_digest"):
        raise HandoffError("assessment_profile_mismatch", f"{bma_dir.name} no longer holds the profile this run handed over")
    _remove_copies(azure_dir, {k: v for k, v in record.get("pending_artifacts", {}).items() if k not in THROUGH_FILES[through]})
    _write_json(record_path, record | {"pending_artifacts": {name: _sha(data[name]) for name in THROUGH_FILES[through][1:]}})
    _merge_preferences(azure_dir, bma_dir, data["preferences.json"])
    for name in THROUGH_FILES[through][1:]:
        _write_bytes(azure_dir / name, data[name])
    record.pop("pending_artifacts", None)
    record.update(status="assessment_completed" if through == "estimate" else "in_progress", through=through,
                  artifacts={name: _sha(data[name]) for name in THROUGH_FILES[through]})
    _write_json(record_path, record)
    return {"ok": True, "through": through, "copied": list(THROUGH_FILES[through][1:]), "artifacts": record["artifacts"]}


def _verified(bma_dir: Path, ready: dict, through: str) -> dict[str, bytes]:
    reported = ready.get("artifacts") or {}
    data = {}
    for name in ("ai-workload-profile.json", *THROUGH_FILES.get(through, ())):
        try:
            raw = (bma_dir / name).read_bytes()
        except OSError as exc:
            raise HandoffError("bma_tampered", f"{name} became unreadable after readiness.py checked it: {exc}")
        if not isinstance(reported.get(name), dict) or reported[name].get("sha256") != _sha(raw):
            raise HandoffError("bma_tampered", f"readiness.py reported a SHA-256 for {name} that does not match the file")
        data[name] = raw
    return data


def _merge_preferences(azure_dir: Path, bma_dir: Path, raw: bytes) -> None:
    assessment = json.loads(raw.decode("utf-8"))
    source = {"assessment_dir": bma_dir.name, "sha256": _sha(raw)}
    path = azure_dir / "preferences.json"
    if not _has_infrastructure(azure_dir):
        held = _read_json(path, "preferences_unreadable") if path.exists() else None
        metadata = held.get("metadata") if isinstance(held, dict) else None
        earlier = metadata.get("ai_preferences_source") if isinstance(metadata, dict) else None
        if isinstance(earlier, dict) and isinstance(earlier.get("preferences_before"), dict):
            source["preferences_before"] = earlier["preferences_before"]
        elif earlier is None and isinstance(held, dict):
            source["preferences_before"] = held
        elif earlier is None and held is not None:
            raise HandoffError("preferences_unreadable", "preferences.json is not a JSON object; move it aside, then accept again")
        assessment.setdefault("metadata", {})["ai_preferences_source"] = source
        _write_json(path, assessment)
        return
    prefs = _azure_prefs(path)
    earlier = (prefs.get("metadata") or {}).get("ai_preferences_source")
    if earlier.get("startup_absent") if earlier is not None else "startup_constraints" not in prefs:
        source["startup_absent"] = True
    earlier = earlier or {}
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
    p.add_argument("azure_dir", type=Path)
    p.add_argument("--infra-only", action="store_true", help="the user chose to continue without the AI track")
    p = sub.add_parser("convert", help=f"write {NEUTRAL_PROFILE}, the neutral profile the assessment reads, and open the handoff")
    p.add_argument("azure_dir", type=Path)
    p.add_argument("--scan", type=Path, help="a profile from the assessment's own application-code scan")
    p = sub.add_parser("host-answers", help="open the handoff and pass this run's region and compliance")
    p.add_argument("azure_dir", type=Path)
    p.add_argument("bma_dir", type=Path)
    p.add_argument("--stop-after", choices=tuple(THROUGH_FILES), required=True)
    p = sub.add_parser("accept", help="check the assessment run and copy its artifacts into this run")
    p.add_argument("azure_dir", type=Path)
    p.add_argument("bma_dir", type=Path)
    p.add_argument("--through", choices=tuple(THROUGH_FILES), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            result = probe()
            code = 0 if result["status"] == "present" else 1
        elif args.command == "route":
            code, result = route(args.azure_dir, args.infra_only)
        else:
            if args.command == "convert":
                result = convert(args.azure_dir, args.scan)
            elif args.command == "host-answers":
                result = host_answers(args.azure_dir, args.bma_dir, args.stop_after)
            else:
                result = accept(args.azure_dir, args.bma_dir, args.through)
            code = 0
    except HandoffError as exc:
        result, code = {"ok": False, "error": exc.error, "detail": exc.detail, **exc.extra}, 1
    except OSError as exc:
        name = Path(exc.filename).name if exc.filename else "a file"
        result, code = {"ok": False, "error": "filesystem_error", "detail": f"{name}: {exc.strerror or exc}; fix the file system "
                        "problem and run the command again"}, 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
