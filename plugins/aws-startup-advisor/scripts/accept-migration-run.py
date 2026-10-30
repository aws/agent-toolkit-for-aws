#!/usr/bin/env python3
"""Independently audit a completed GCP or Heroku infrastructure migration run.

Python 3.10+. This is a local acceptance check, not an ATX status update or a deployment test.
It re-runs the repository validators instead of trusting worker-written PASS
reports. Inputs are read-only; the JSON report must be outside the run.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / "scripts"
TF_SCRIPTS = PLUGIN / "skills/tf-best-practices/scripts"
PHASES = ("discover", "clarify", "design", "estimate")
SKILLS = ("gcp-to-aws", "heroku-to-aws")
IAC_COMPUTE_TYPES = {
    "google_compute_instance", "google_cloud_run_service", "google_cloud_run_v2_service",
    "google_container_cluster", "google_app_engine_application",
}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load validator: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def file_hashes(root: Path) -> dict[str, str]:
    """Reject links/special files before any checker traverses the run."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink is not supported: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Special file is not supported: {path.relative_to(root)}")
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def check(name: str, status: str, detail: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def required_files(root: Path, names: list[str]) -> list[str]:
    return [name for name in names if not (root / name).is_file()
            or (root / name).stat().st_size == 0]


def required_json(root: Path, names: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Presence and contract lookup do not imply that an uncovered file parses."""
    values = {}
    errors = []
    for name in names:
        if not name.endswith(".json") or not (root / name).is_file():
            continue
        try:
            values[name] = read_object(root / name)
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    return values, errors


def requires_eb_workflow(design: dict[str, Any], preferences: dict[str, Any], report_tools: Any) -> bool:
    has_eb = any("beanstalk" in service.casefold()
                 for service in report_tools._iter_aws_services(design))
    constraints = preferences.get("design_constraints") or {}
    row = constraints.get("eb_deploy_method") if isinstance(constraints, dict) else None
    method = row.get("value") if isinstance(row, dict) else None
    return has_eb and method not in ("manual", "codepipeline")


def requires_postgres_script(design: dict[str, Any], report_tools: Any) -> bool:
    # Keep the named-service predicate and engine-qualified RDS/Aurora designs.
    if any("rds postgresql" in service.casefold() or "aurora postgresql" in service.casefold()
           for service in report_tools._iter_aws_services(design)):
        return True
    services = design.get("services") or []
    for service in services if isinstance(services, list) else []:
        if not isinstance(service, dict):
            continue
        label = service.get("aws_service")
        config = service.get("aws_config") or {}
        engine = config.get("engine") if isinstance(config, dict) else None
        if isinstance(label, str) and isinstance(engine, str) and (
            "rds" in label.casefold() or "aurora" in label.casefold()
        ) and engine.casefold() in {"postgres", "postgresql", "aurora-postgresql"}:
            return True
    return False


def heroku_conditional_outputs(
    root: Path, design: dict[str, Any], preferences: dict[str, Any],
    report_tools: Any, policy: Any,
) -> dict[str, Any]:
    """Enforce Generate's selected output floor, not deployment correctness."""
    services = {service.casefold() for service in report_tools._iter_aws_services(design)}
    names = []
    errors = []
    limitations = []
    if "elasticache redis" in services:
        names.append("scripts/migrate-redis.sh")
    if any("beanstalk" in service for service in services):
        names.append("terraform/beanstalk.tf")
        constraints = preferences.get("design_constraints") or {}
        row = constraints.get("eb_deploy_method") if isinstance(constraints, dict) else None
        method = row.get("value") if isinstance(row, dict) else None
        if method in (None, "github_actions"):
            names.append(".github/workflows/deploy-eb.yml")
        elif method == "codepipeline":
            names.append("terraform/pipeline.tf")
        elif method != "manual":
            limitations.append("Unknown Elastic Beanstalk deployment method")
    if "eks" in services or "eks_cluster" in design:
        names.extend(["terraform/eks.tf", "kubernetes/namespace.yaml"])
        deployments = [path for path in (root / "kubernetes").glob("*-deployment.yaml")
                       if path.is_file() and path.stat().st_size]
        if not deployments:
            errors.append("kubernetes/*-deployment.yaml: no nonempty deployment manifest")
        eks_file = root / "terraform/eks.tf"
        if eks_file.is_file():
            text = eks_file.read_text(encoding="utf-8")
            types = {
                resource_type for resource_type in (
                    "aws_eks_cluster", "aws_eks_node_group", "aws_launch_template",
                    "aws_autoscaling_group", "aws_security_group",
                ) if policy._extract_blocks(text, resource_type)
            }
            if "aws_eks_cluster" not in types:
                errors.append("terraform/eks.tf: missing aws_eks_cluster resource")
            cluster = design.get("eks_cluster")
            node_type = cluster.get("node_group_type") if isinstance(cluster, dict) else None
            if node_type == "managed":
                if "aws_eks_node_group" not in types:
                    errors.append("terraform/eks.tf: missing managed aws_eks_node_group resource")
            elif node_type == "self-managed":
                missing = {"aws_launch_template", "aws_autoscaling_group",
                           "aws_security_group"} - types
                if missing:
                    errors.append("terraform/eks.tf: missing self-managed resources: " +
                                  ", ".join(sorted(missing)))
            elif not ({"aws_eks_node_group"} <= types or {
                "aws_launch_template", "aws_autoscaling_group", "aws_security_group",
            } <= types):
                errors.append("terraform/eks.tf: missing node group resources")
        # File/resource presence cannot establish manifest kinds, per-formation
        # coverage or node-group wiring. Do not turn that limited check into PASS.
        limitations.append(
            "EKS Kubernetes manifests and node-group wiring require separate review; "
            "only the documented file and resource presence was checked."
        )
    missing = required_files(root, names)
    return check("conditional_outputs", "FAIL" if missing or errors else
                 "UNVERIFIED" if limitations else "PASS", {
                     "missing": missing, "errors": errors, "limitations": limitations,
                 })


def discovery_facts(inventory: dict[str, Any], skill: str) -> dict[str, Any]:
    """Check narrow producer obligations not encoded as required shape keys."""
    if skill == "heroku-to-aws":
        missing = []
        apps = inventory.get("apps", [])
        if not isinstance(apps, list):
            return check("discovery_facts", "FAIL", "apps must be an array")
        for index, app in enumerate(apps):
            if isinstance(app, dict):
                missing.extend(f"apps[{index}].{field}" for field in ("region", "stack")
                               if field not in app)
        return check("discovery_facts", "UNVERIFIED" if missing else "PASS", {
            "missing": missing,
            "note": "Legacy inventories may omit region/stack; explicit null is valid unknown data.",
        })
    metadata = inventory.get("metadata") or {}
    sources = metadata.get("discovery_sources") if isinstance(metadata, dict) else None
    non_iac_only = isinstance(sources, list) and bool(sources) and all(
        source in ("live", "billing") for source in sources
    )
    profiles = inventory.get("graviton_profile")
    profile_fields = {"service_name", "tier", "target_architecture", "signals", "caveats", "source"}
    profile_names = {
        item["service_name"] for item in profiles
        if isinstance(item, dict) and profile_fields.issubset(item)
        and isinstance(item.get("service_name"), str)
    } if isinstance(profiles, list) else set()
    missing = []
    resources = inventory.get("resources", [])
    if not isinstance(resources, list):
        return check("discovery_facts", "FAIL", "resources must be an array")
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("type"), str):
            continue
        if resource["type"] not in IAC_COMPUTE_TYPES:
            continue
        source = resource.get("source")
        if source in ("live", "billing") or (source is None and non_iac_only):
            continue
        config = resource.get("config") or {}
        names = {name for name in (resource.get("name"), resource.get("address"),
                                  config.get("name") if isinstance(config, dict) else None)
                 if isinstance(name, str) and name}
        if not names.intersection(profile_names):
            missing.append(resource.get("address") or resource.get("name") or resource["type"])
    return check("discovery_facts", "FAIL" if missing else "PASS", {
        "compute_missing_graviton_profile": missing,
        "note": "Matches IaC compute by name, address or config.name; live-only/billing-only profiles are not required.",
    })


def lifecycle(state: dict[str, Any]) -> tuple[str, list[str]]:
    """The documented decision-only terminal is complete with Generate pending."""
    errors = []
    phases = state.get("phases")
    if not isinstance(phases, dict):
        return "unknown", ["phases must be an object"]
    if any(phases.get(phase) != "completed" for phase in PHASES):
        errors.append("Discover, Clarify, Design and Estimate must be completed")
    if phases.get("workshop") != "completed":
        errors.append("The Decision gate/workshop must be resolved")
    if "current_phase" not in state:
        errors.append("UNVERIFIED: legacy state has no current_phase")
    elif state["current_phase"] != "complete":
        errors.append("current_phase must be complete")
    mode = state.get("run_mode")
    if mode == "decide" and phases.get("generate") == "pending":
        route = "decision"
    elif mode == "decide_and_execute" and phases.get("generate") == "completed":
        route = "execution"
    else:
        route = "unknown"
        errors.append("UNVERIFIED: legacy state has no run_mode" if "run_mode" not in state else
                      "run_mode and Generate status do not describe a completed supported run")
    if "current_phase" not in state:
        route = "unknown"
    if state.get("dirty_state") is not None:
        errors.append("The run retains dirty_state")
    return route, errors


def validation_report_errors(value: dict[str, Any]) -> list[str]:
    """Check the existing runtime v2 envelope, without trusting its verdict."""
    errors = []
    if value.get("$schema") != "validation-report/v2":
        errors.append("$schema must be validation-report/v2")
    status = value.get("status")
    if not isinstance(status, str) or status not in {
        "passed", "passed_degraded_offline", "skipped_user_continue",
        "skipped_user_abort", "policy_failed",
    }:
        errors.append("status is outside the runtime contract")
    if value.get("policy_status") != "POLICY_OK":
        errors.append("Completed infrastructure requires policy_status POLICY_OK")
    if not isinstance(status, str) or status not in {"passed", "passed_degraded_offline", "skipped_user_continue"}:
        errors.append("status does not permit infrastructure completion")
    if type(value.get("attempts")) is not int or value["attempts"] < 0:
        errors.append("attempts must be a nonnegative integer")
    for name in ("errors_found", "errors_fixed", "policy_violations"):
        if not isinstance(value.get(name), list):
            errors.append(f"{name} must be an array")
            continue
        for index, item in enumerate(value[name]):
            prefix = f"{name}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("file", "summary"):
                if not isinstance(item.get(field), str):
                    errors.append(f"{prefix}.{field} must be a string")
            if type(item.get("line")) is not int or item["line"] < 0:
                errors.append(f"{prefix}.line must be a nonnegative integer")
            if item.get("severity") not in ("error", "warning"):
                errors.append(f"{prefix}.severity must be error or warning")
            if name == "errors_found" and isinstance(item.get("summary"), str) and len(item["summary"]) > 200:
                errors.append(f"{prefix}.summary exceeds 200 characters")
            if name == "errors_fixed" and (type(item.get("attempt")) is not int or item["attempt"] < 1):
                errors.append(f"{prefix}.attempt must be a positive integer")
    if value.get("policy_violations") != []:
        errors.append("POLICY_OK requires empty policy_violations")
    if type(value.get("offline_fallback_used")) is not bool or (
        value["offline_fallback_used"] != (status == "passed_degraded_offline")
    ):
        errors.append("offline_fallback_used must match passed_degraded_offline")
    if not isinstance(value.get("terraform_version"), str):
        errors.append("terraform_version must be a string")
    try:
        stamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("not UTC")
    except (KeyError, TypeError, AttributeError, ValueError):
        errors.append("timestamp must be an ISO 8601 UTC timestamp")
    return errors


def command(args: list[str], cwd: Path, env: dict[str, str], timeout: int = 180) -> dict[str, Any]:
    """Only called with committed checkers, Bash syntax checking or chosen Terraform."""
    try:
        result = subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": args, "returncode": None, "error": str(exc)}
    return {"argv": args, "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def clean_environment(home: Path) -> dict[str, str]:
    # Do not inherit credentials, BASH_ENV, TF_CLI_ARGS, TF_VAR_* or plugin paths.
    return {"PATH": os.defpath, "HOME": str(home), "LANG": "C.UTF-8",
            "CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}


def terraform_support(terraform: Path, policy: Any) -> list[str]:
    """Conservative allowlist for opt-in provider execution, using the policy lexer.

    All modules and JSON configurations require separate review. Only an explicit
    registry HashiCorp AWS provider and aws_* resources/data are supported here.
    """
    issues = []
    tf_files = sorted(terraform.glob("*.tf"))
    if not tf_files:
        return ["No root Terraform files"]
    if list(terraform.rglob("*.tf.json")):
        issues.append("JSON Terraform configuration requires separate review")
    if any(path.parent != terraform for path in terraform.rglob("*.tf")
           if ".terraform" not in path.relative_to(terraform).parts):
        issues.append("Nested Terraform directories require separate review")
    required_aws = False
    for path in tf_files:
        text = policy._strip_hcl_comments(path.read_text(encoding="utf-8"))
        # Validation may evaluate these functions. The clean environment is not
        # a filesystem sandbox, so do not allow reads from paths in generated HCL.
        if re.search(r"\b(?:file\w*|templatefile)\s*\(", text):
            issues.append(f"{path.name}: filesystem-reading functions require separate review")
        depths, codes, _ = policy._lex_hcl(text)
        # Read complete top-level blocks, ignoring comments, strings and heredocs.
        header = re.compile(r'([A-Za-z_]\w*)((?:\s+"[^"\n]*"){0,2})\s*\{')
        for match in header.finditer(text):
            if not codes[match.start()] or depths[match.start()] != 0:
                continue
            kind = match.group(1)
            labels = re.findall(r'"([^"]*)"', match.group(2))
            if kind not in {"terraform", "provider", "resource", "data", "variable", "locals", "output"}:
                issues.append(f"{path.name}: unsupported {kind} block")
            if kind == "provider" and labels != ["aws"]:
                issues.append(f"{path.name}: only the aws provider is supported")
            if kind in {"resource", "data"} and (not labels or not labels[0].startswith("aws_")):
                issues.append(f"{path.name}: only aws_* resources and data are supported")
            if kind == "terraform":
                body, _ = policy._extract_braced_block(text, match.end() - 1)
                if policy._own_blocks(body, "cloud"):
                    issues.append(f"{path.name}: Terraform Cloud requires separate review")
                for providers in policy._own_blocks(body, "required_providers"):
                    p_depths, p_codes, _ = policy._lex_hcl(providers)
                    for provider in re.finditer(r'("[^"]+"|[A-Za-z_]\w*)\s*=\s*\{', providers):
                        if not p_codes[provider.end() - 1] or p_depths[provider.end() - 1] != 1:
                            continue
                        config, _ = policy._extract_braced_block(providers, provider.end() - 1)
                        source = policy._attr_string(config, "source")
                        if provider.group(1).strip('"') != "aws" or source not in {
                            "hashicorp/aws", "registry.terraform.io/hashicorp/aws",
                        }:
                            issues.append(f"{path.name}: provider source requires separate review")
                        else:
                            required_aws = True
                    # Legacy string declarations do not make the allowlist.
                    for provider in re.finditer(r'("[^"]+"|[A-Za-z_]\w*)\s*=\s*"', providers):
                        equals = providers.index("=", provider.start(), provider.end())
                        if p_codes[equals] and p_depths[equals] == 1:
                            issues.append(f"{path.name}: legacy provider declaration requires review")
    if not required_aws:
        issues.append("An explicit hashicorp/aws required_providers declaration is required")
    return sorted(set(issues))


def terraform_checks(root: Path, binary: Path | None, policy: Any) -> dict[str, Any]:
    if binary is None:
        return check("terraform", "UNVERIFIED", "Pass --terraform /absolute/path/to/terraform to opt in")
    issues = terraform_support(root / "terraform", policy)
    if issues:
        return check("terraform", "UNVERIFIED", issues)
    with tempfile.TemporaryDirectory(prefix="migration-acceptance-") as temp:
        scratch = Path(temp)
        work = scratch / "terraform"
        # Ignore downloaded plugins, state, plans, credentials and arbitrary CLI config.
        work.mkdir()
        for path in (root / "terraform").glob("*.tf"):
            shutil.copyfile(path, work / path.name)
        lock = root / "terraform/.terraform.lock.hcl"
        if lock.is_file():
            shutil.copyfile(lock, work / lock.name)
        env = clean_environment(scratch)
        config = scratch / "terraform.rc"
        config.write_text('provider_installation { direct { include = ["registry.terraform.io/hashicorp/aws"] } }\n')
        env["TF_CLI_CONFIG_FILE"] = str(config)
        invocations = []
        for args in (
            [str(binary), "version", "-json"],
            [str(binary), "fmt", "-check", "-recursive"],
            [str(binary), "init", "-backend=false", "-get=false", "-input=false", "-no-color"],
            [str(binary), "validate", "-json", "-no-color"],
        ):
            invocation = command(args, work, env)
            invocations.append(invocation)
            if invocation.get("returncode") != 0:
                status = "UNVERIFIED" if invocation.get("returncode") is None or args[1] in {"version", "init"} else "FAIL"
                return check("terraform", status, invocations)
            if args[1] in {"version", "validate"}:
                try:
                    payload = json.loads(invocation["stdout"])
                    valid = isinstance(payload, dict)
                    if valid and args[1] == "version":
                        valid = isinstance(payload.get("terraform_version"), str) and bool(payload["terraform_version"])
                    elif valid:
                        valid = payload.get("valid") is True and payload.get("error_count") == 0
                except (KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    return check("terraform", "UNVERIFIED", invocations)
        return check("terraform", "PASS", invocations)


def accept(root: Path, skill: str, terraform: Path | None = None) -> dict[str, Any]:
    before = file_hashes(root)
    contracts = load_module("_accept_contracts", SCRIPTS / "validate-artifacts.py")
    policy = load_module("_accept_policy", TF_SCRIPTS / "validate-terraform-policy.py")
    artifacts = load_module("_accept_artifacts", TF_SCRIPTS / "validate-migration-artifacts.py")
    checks: list[dict[str, Any]] = []
    route = "unknown"
    try:
        state = read_object(root / ".phase-status.json")
    except (OSError, ValueError):
        state = {}
    route, errors = lifecycle(state)
    lifecycle_status = ("FAIL" if any(not item.startswith("UNVERIFIED:") for item in errors) else
                        "UNVERIFIED" if errors else "PASS")
    checks.append(check("lifecycle", lifecycle_status, errors))
    owner = state.get("owning_skill")
    expected_owner = skill.upper().replace("-", "_")
    checks.append(check(
        "owning_skill",
        "UNVERIFIED" if "owning_skill" not in state else "PASS" if owner == expected_owner else "FAIL",
        {"expected": expected_owner, "actual": owner,
         "note": "An absent legacy owner cannot establish the requested skill scope."},
    ))
    manifest = contracts.load_manifest(contracts.DEFAULT_MANIFEST)
    findings: list[Any] = []
    count = contracts.validate_run_dir(root, skill, manifest, findings)
    errors = [finding.as_dict() for finding in findings if finding.severity == "error"]
    checks.append(check("artifact_contracts", "FAIL" if errors else "PASS",
                        {"checked_artifacts": count, "errors": errors,
                         "coverage_limitations": [finding.as_dict() for finding in findings
                                                  if finding.code == "NO_CONTRACT"]}))
    inventory = "gcp-resource-inventory.json" if skill == "gcp-to-aws" else "heroku-resource-inventory.json"
    names = [".phase-status.json", inventory, "preferences.json", "aws-design.json", "estimation-infra.json"]
    if skill == "gcp-to-aws":
        names.append("gcp-resource-clusters.json")
    if route == "decision":
        names.extend(["DECISION.md", "decision-report.html"])
    elif route == "execution":
        names.extend(["MIGRATION_GUIDE.md", "README.md",
                      "validation-report.json", "artifact-validation-status.json"])
        if skill == "gcp-to-aws":
            names.append("generation-infra.json")
        else:
            names.extend(["migration-report.html", "report-validation-status.json", "generation-warnings.json",
                          "terraform/main.tf", "terraform/baseline.tf", "terraform/variables.tf",
                          "terraform/outputs.tf", "terraform/security.tf", "terraform/.gitignore",
                          "terraform/terraform.tfvars.example"])
    missing = required_files(root, names)
    if route == "execution":
        for directory in ("terraform", "scripts") if skill == "gcp-to-aws" else ("terraform",):
            if not (root / directory).is_dir() or not any((root / directory).iterdir()):
                missing.append(directory + "/")
    checks.append(check("required_outputs", "FAIL" if missing else "PASS", missing))
    documents, errors = required_json(root, names)
    checks.append(check("required_json_objects", "FAIL" if errors else "PASS", errors))
    if inventory in documents:
        checks.append(discovery_facts(documents[inventory], skill))
    other_routes = [name for name in ("aws-design-ai.json", "aws-design-billing.json",
                                     "estimation-ai.json", "estimation-billing.json") if (root / name).exists()]
    if other_routes:
        checks.append(check("route_coverage", "UNVERIFIED",
                            {"unsupported_routes": other_routes, "supported": "infrastructure only"}))
    report_name = "decision-report.html" if route == "decision" else "migration-report.html"
    if (root / report_name).is_file():
        validator = (SCRIPTS / "validate-migration-report.py" if skill == "gcp-to-aws" else
                     PLUGIN / "skills/heroku-to-aws/scripts/validate-heroku-migration-report.py")
        args = [sys.executable, str(validator), str(root / report_name),
                "--migration-dir", str(root), "--mode", "decision" if route == "decision" else "full"]
        if skill == "gcp-to-aws":
            args.extend(["--estimation-infra", str(root / "estimation-infra.json"),
                         "--aws-design", str(root / "aws-design.json")])
        with tempfile.TemporaryDirectory(prefix="migration-report-") as temp:
            result = command(args, root, clean_environment(Path(temp)))
        checks.append(check("rendered_report", "PASS" if result.get("returncode") == 0 else "FAIL", result))
    if route == "execution":
        try:
            errors = validation_report_errors(read_object(root / "validation-report.json"))
        except (OSError, ValueError) as exc:
            errors = [str(exc)]
        checks.append(check("runtime_report_contract", "FAIL" if errors else "PASS", errors))
        stamp_errors = []
        for filename, key, expected in (
            ("artifact-validation-status.json", "artifact_status", "ARTIFACTS_OK"),
            *([("report-validation-status.json", "report_status", "REPORT_OK")]
              if skill == "heroku-to-aws" else []),
        ):
            try:
                if read_object(root / filename).get(key) != expected:
                    stamp_errors.append(f"{filename} must record {key}={expected}")
            except (OSError, ValueError) as exc:
                stamp_errors.append(str(exc))
        checks.append(check("reported_check_contracts", "FAIL" if stamp_errors else "PASS", stamp_errors))
        if (root / "terraform").is_dir():
            passed, violations = policy.validate(root / "terraform")
            checks.append(check("terraform_policy", "PASS" if passed else "FAIL",
                                [asdict(item) for item in violations]))
            checks.append(terraform_checks(root, terraform, policy))
        require_workflow = False
        require_postgres = False
        if skill == "heroku-to-aws":
            report_tools = load_module("_accept_report_tools", SCRIPTS / "validate-migration-report.py")
            checks.append(heroku_conditional_outputs(
                root, documents.get("aws-design.json", {}), documents.get("preferences.json", {}),
                report_tools, policy,
            ))
            require_postgres = requires_postgres_script(documents.get("aws-design.json", {}), report_tools)
            require_workflow = requires_eb_workflow(
                documents.get("aws-design.json", {}), documents.get("preferences.json", {}), report_tools,
            )
        artifact_result = artifacts.validate(
            root, require_postgres_script=require_postgres,
            require_eb_workflow=require_workflow,
        )
        checks.append(check("generated_artifacts",
                            "PASS" if artifact_result["artifact_status"] == "ARTIFACTS_OK" else "FAIL",
                            artifact_result))
        with tempfile.TemporaryDirectory(prefix="migration-shell-") as temp:
            shell_results = [
                command(["/bin/bash", "--noprofile", "--norc", "-n", str(path)],
                        root, clean_environment(Path(temp)))
                for path in sorted((root / "scripts").rglob("*.sh"))
            ]
        checks.append(check("shell_syntax", "FAIL" if any(
            item.get("returncode") != 0 for item in shell_results) else "PASS", shell_results))
    after = file_hashes(root)
    checks.append(check("inputs_unchanged", "PASS" if before == after else "FAIL",
                        "SHA-256 comparison before and after validation"))
    source_paths = {
        SCRIPTS / "accept-migration-run.py", SCRIPTS / "validate-artifacts.py",
        SCRIPTS / "artifact-contracts.json", SCRIPTS / "validate-migration-report.py",
        PLUGIN / "skills/heroku-to-aws/scripts/validate-heroku-migration-report.py",
        TF_SCRIPTS / "validate-terraform-policy.py", TF_SCRIPTS / "validate-migration-artifacts.py",
        TF_SCRIPTS / "rds_windows.py",
        *(PLUGIN / "skills").rglob("schema-*.md"),
        *(PLUGIN / "skills/shared").rglob("*.schema.json"),
        *(SCRIPTS / "contracts").glob("*.json"),
    }
    source_hashes = {str(path.relative_to(PLUGIN)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(source_paths)}
    statuses = {item["status"] for item in checks}
    verdict = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
    return {"schema_version": 1, "producer": "accept-migration-run", "verdict": verdict,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "skill": skill, "scope": route, "input_sha256": before, "checker_sha256": source_hashes,
            "checks": checks, "limitations": [
                "Local acceptance does not change ATX job status or prove deployment success.",
                "Only infrastructure decision and execution runs are supported.",
                "Static checkers cover their documented rules, not arbitrary migration semantics.",
                "Files without published contracts are listed under artifact_contracts.coverage_limitations.",
                "Worker-written PASS reports are contract-checked but never used as execution evidence.",
            ]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--skill", choices=SKILLS, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file outside the run")
    parser.add_argument("--terraform", type=Path, help="Trusted absolute Terraform binary; permits official AWS provider installation in a copy")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    root, output = args.run_dir.resolve(), args.output.resolve()
    if not root.is_dir():
        parser.error("--run-dir must be a directory")
    if args.run_dir.is_symlink():
        parser.error("--run-dir must not be a symlink")
    if output == root or root in output.parents or args.output.is_symlink():
        parser.error("--output must be outside the run and must not be a symlink")
    if output.exists():
        parser.error("--output must be a new file")
    if args.terraform is not None and (not args.terraform.is_absolute() or not args.terraform.is_file()
                                       or not os.access(args.terraform, os.X_OK)):
        parser.error("--terraform must name a trusted, executable absolute path")
    try:
        report = accept(root, args.skill, args.terraform)
    except Exception as exc:
        # A failed checker is not evidence that generated artifacts are valid.
        report = {"schema_version": 1, "producer": "accept-migration-run",
                  "verdict": "UNVERIFIED", "error_type": type(exc).__name__, "error": str(exc)}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"{report['verdict']} | report={output}")
    return {"PASS": 0, "FAIL": 1, "UNVERIFIED": 2}[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
