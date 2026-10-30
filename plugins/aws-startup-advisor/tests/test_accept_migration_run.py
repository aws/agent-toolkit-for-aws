"""Regression tests for independent local migration acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/accept-migration-run.py"
PLUGIN = SCRIPT.parent.parent
spec = importlib.util.spec_from_file_location("accept_migration_run", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(acceptance)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def decision_run(parent: Path) -> Path:
    """A sanitized storage-only decision pack, using the checked-in report golden."""
    root = parent / "0723-1900"
    shutil.copytree(PLUGIN / "fixtures/gcp-decision-gate/after-decide-complete", root)
    write_json(root / "gcp-resource-inventory.json", {
        "metadata": {"report_date": "2026-07-23", "project_directory": "example",
                     "terraform_version": "1.9.5"},
        "summary": {"total_resources": 1, "primary_resources": 1, "secondary_resources": 0,
                    "total_clusters": 1, "classification_coverage": "100%"},
        "resources": [{"address": "google_storage_bucket.assets", "type": "google_storage_bucket",
                       "name": "assets", "classification": "PRIMARY", "tier": "storage",
                       "confidence": 1, "config": {"location": "US"},
                       "depth": 0, "cluster_id": "storage_1"}],
        "graviton_profile": [],
        "ai_detection": {"has_ai_workload": False, "confidence": 0, "confidence_level": "none",
                         "signals_found": [], "ai_services": []},
    })
    write_json(root / "gcp-resource-clusters.json", {"clusters": []})
    write_json(root / "preferences.json", {"design_constraints": {
        "target_region": {"value": "us-east-1", "chosen_by": "user",
                          "prompt": "Target AWS region?", "design_consequence": "Use us-east-1"},
    }})
    write_json(root / "aws-design.json", {"phase": "design", "services": [
        {"aws_service": "S3", "source_resource_id": "google_storage_bucket.assets"},
    ]})
    return root


def execution_run(parent: Path) -> Path:
    root = decision_run(parent)
    state = json.loads((root / ".phase-status.json").read_text())
    state["run_mode"] = "decide_and_execute"
    state["phases"]["generate"] = "completed"
    write_json(root / ".phase-status.json", state)
    write_json(root / "generation-infra.json", {"phase": "generate"})
    write_json(root / "validation-report.json", {
        "$schema": "validation-report/v2", "status": "passed", "policy_status": "POLICY_OK",
        "attempts": 0, "errors_found": [], "errors_fixed": [], "policy_violations": [],
        "offline_fallback_used": False, "timestamp": "2026-07-23T20:00:00Z",
        "terraform_version": "1.9.5",
    })
    write_json(root / "artifact-validation-status.json", {"artifact_status": "ARTIFACTS_OK"})
    (root / "MIGRATION_GUIDE.md").write_text("# Migration guide\n")
    (root / "README.md").write_text("# Artifact catalog\n")
    terraform = root / "terraform"
    terraform.mkdir()
    (terraform / "main.tf").write_text('''terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
provider "aws" {
  region = "us-east-1"
}
resource "aws_s3_bucket" "assets" {
  bucket = "example-migration-bucket"
}
''')
    (root / "scripts").mkdir()
    (root / "scripts/verify.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n")
    return root


def heroku_decision_run(parent: Path) -> Path:
    root = parent / "0818-1400"
    shutil.copytree(PLUGIN / "fixtures/heroku-decision-gate/after-decide-complete", root)
    for name in ("preferences.json", "aws-design.json"):
        shutil.copyfile(PLUGIN / "fixtures/heroku-workshop/seed" / name, root / name)
    write_json(root / "heroku-resource-inventory.json", {
        "metadata": {"discovery_timestamp": "2026-08-18T14:00:00Z", "total_apps_discovered": 1,
                     "discovery_sources": ["terraform"], "confidence": "full"},
        "apps": [{"app_name": "example", "app_id": "01234567-89ab-cdef-0123-456789abcdef",
                  "region": "us", "stack": "heroku-22", "heroku_generation": "cedar",
                  "generation_action": "detect_only", "generation_diagnostics": [],
                  "space": None, "discovery_status": "success", "failure_reason": None,
                  "procfile_parse_warning": None, "app_json_parse_warning": None}],
        "resources": [{"resource_id": "formation:example:web", "resource_type": "formation",
                       "heroku_app": "example", "config": {"dyno_type": "standard-1x",
                       "quantity": 1, "process_type": "web"}, "source": "terraform"}],
    })
    return root


def by_name(report: dict, name: str) -> dict:
    return next(item for item in report["checks"] if item["name"] == name)


class AcceptanceTests(unittest.TestCase):
    def test_heroku_decision_pack_passes_real_validators(self):
        with tempfile.TemporaryDirectory() as temp:
            report = acceptance.accept(heroku_decision_run(Path(temp)), "heroku-to-aws")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertEqual("decision", report["scope"])

    def test_heroku_design_must_parse_even_without_a_published_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = heroku_decision_run(Path(temp))
            (root / "aws-design.json").write_text("{ malformed")
            report = acceptance.accept(root, "heroku-to-aws")
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual("FAIL", by_name(report, "required_json_objects")["status"])
            coverage = by_name(report, "artifact_contracts")["detail"]["coverage_limitations"]
            self.assertTrue(any("aws-design.json" in item["artifact"] for item in coverage))

    def test_heroku_missing_metadata_is_unverified_but_explicit_null_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = heroku_decision_run(Path(temp))
            inventory = json.loads((root / "heroku-resource-inventory.json").read_text())
            del inventory["apps"][0]["region"]
            del inventory["apps"][0]["stack"]
            write_json(root / "heroku-resource-inventory.json", inventory)
            report = acceptance.accept(root, "heroku-to-aws")
            self.assertEqual("UNVERIFIED", report["verdict"], report["checks"])
            inventory["apps"][0].update(region=None, stack=None)
            write_json(root / "heroku-resource-inventory.json", inventory)
            report = acceptance.accept(root, "heroku-to-aws")
            self.assertEqual("PASS", report["verdict"], report["checks"])

    def test_iac_compute_requires_a_matching_profile_without_overwriting_app_code(self):
        for resource_type in acceptance.IAC_COMPUTE_TYPES:
            with self.subTest(resource_type=resource_type):
                resource = {"type": resource_type, "name": "logical",
                            "address": f"{resource_type}.logical", "config": {"name": "service"}}
                inventory = {"resources": [resource]}
                self.assertEqual("FAIL", acceptance.discovery_facts(inventory, "gcp-to-aws")["status"])
                inventory["graviton_profile"] = [{"service_name": "logical"}]
                self.assertEqual("FAIL", acceptance.discovery_facts(inventory, "gcp-to-aws")["status"])
                for name in ("logical", resource["address"], "service"):
                    profile = {"service_name": name, "source": "app_code", "tier": "conditional",
                               "target_architecture": "arm64", "signals": [], "caveats": []}
                    inventory["graviton_profile"] = [profile]
                    before = json.dumps(inventory, sort_keys=True)
                    self.assertEqual("PASS", acceptance.discovery_facts(inventory, "gcp-to-aws")["status"])
                    self.assertEqual(before, json.dumps(inventory, sort_keys=True))

    def test_non_compute_and_billing_only_do_not_require_iac_profiles(self):
        for inventory in (
            {"resources": [{"type": "google_storage_bucket", "name": "assets"}]},
            {"metadata": {"discovery_sources": ["billing"]},
             "resources": [{"type": "google_compute_instance", "name": "vm"}]},
            {"resources": [{"type": "google_compute_instance", "name": "vm", "source": "billing"}]},
        ):
            with self.subTest(inventory=inventory):
                self.assertEqual("PASS", acceptance.discovery_facts(inventory, "gcp-to-aws")["status"])

    def test_heroku_eb_requires_workflow_only_for_selected_or_default_github(self):
        for method in (None, "github_actions", "manual", "codepipeline"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temp:
                root = execution_run(Path(temp))
                write_json(root / "aws-design.json", {
                    "services": [{"aws_service": "Elastic Beanstalk"}],
                })
                preferences = {"design_constraints": {}}
                if method is not None:
                    preferences["design_constraints"]["eb_deploy_method"] = {"value": method}
                write_json(root / "preferences.json", preferences)
                report = acceptance.accept(root, "heroku-to-aws")
                check = by_name(report, "generated_artifacts")
                rules = [item["rule"] for item in check["detail"]["findings"]]
                self.assertEqual(method in (None, "github_actions"), "eb_deploy_missing" in rules)

    def test_supported_decision_pack_passes_real_validators_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            before = acceptance.file_hashes(root)
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertEqual("decision", report["scope"])
            self.assertEqual(before, acceptance.file_hashes(root))
            self.assertEqual("PASS", by_name(report, "rendered_report")["status"])

    def test_retained_execution_outputs_do_not_change_decision_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            (root / "terraform").mkdir()
            (root / "terraform/old.tf").write_text('module "legacy" { source = "./legacy" }\n')
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertNotIn("terraform", [item["name"] for item in report["checks"]])

    def test_completed_label_does_not_hide_missing_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            (root / "validation-report.json").unlink()
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("FAIL", report["verdict"])
            self.assertIn("validation-report.json", by_name(report, "required_outputs")["detail"])
            self.assertEqual("FAIL", by_name(report, "runtime_report_contract")["status"])

    def test_fake_pass_report_does_not_hide_current_policy_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            with (root / "terraform/main.tf").open("a") as stream:
                stream.write('resource "aws_db_instance" "database" { publicly_accessible = true }\n')
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual("PASS", by_name(report, "runtime_report_contract")["status"])
            self.assertEqual("FAIL", by_name(report, "terraform_policy")["status"])

    def test_valid_static_execution_never_claims_terraform_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("UNVERIFIED", report["verdict"], report["checks"])
            self.assertEqual("UNVERIFIED", by_name(report, "terraform")["status"])

    def test_bad_downloaded_estimate_shape_fails_current_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            estimate = json.loads((root / "estimation-infra.json").read_text())
            estimate["projected_costs"]["breakdown"] = [{"service": "S3", "monthly_cost": 1}]
            write_json(root / "estimation-infra.json", estimate)
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("FAIL", by_name(report, "artifact_contracts")["status"])

    def test_fabricated_or_malformed_check_stamps_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            write_json(root / "artifact-validation-status.json", {"artifact_status": "done"})
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("FAIL", by_name(report, "reported_check_contracts")["status"])

    def test_unresolved_workshop_is_not_a_completed_decision(self):
        route, errors = acceptance.lifecycle({
            "current_phase": "complete", "run_mode": "decide",
            "phases": {**{phase: "completed" for phase in acceptance.PHASES},
                       "workshop": "pending", "generate": "pending"},
        })
        self.assertEqual("decision", route)
        self.assertTrue(errors)

    def test_declined_feedback_is_not_a_blocker_and_legacy_state_is_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            state = json.loads((root / ".phase-status.json").read_text())
            state["phases"]["feedback"] = "pending"
            write_json(root / ".phase-status.json", state)
            self.assertEqual("PASS", acceptance.accept(root, "gcp-to-aws")["verdict"])
            del state["run_mode"]
            write_json(root / ".phase-status.json", state)
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("UNVERIFIED", by_name(report, "lifecycle")["status"])
            state["run_mode"] = "decide"
            del state["current_phase"]
            write_json(root / ".phase-status.json", state)
            report = acceptance.accept(root, "gcp-to-aws")
            self.assertEqual("UNVERIFIED", by_name(report, "lifecycle")["status"])

    def test_symlinks_are_rejected_before_validators(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            (root / "outside").symlink_to(Path(temp))
            with self.assertRaisesRegex(ValueError, "Symlink"):
                acceptance.accept(root, "gcp-to-aws")

    def test_cli_rejects_outputs_inside_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            with self.assertRaises(SystemExit) as caught:
                acceptance.main(["--run-dir", str(root), "--skill", "gcp-to-aws",
                                 "--output", str(root / "acceptance.json")])
            self.assertEqual(2, caught.exception.code)
            self.assertFalse((root / "acceptance.json").exists())

    def test_output_is_exclusive_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            output = Path(temp) / "acceptance.json"
            self.assertEqual(0, acceptance.main([
                "--run-dir", str(root), "--skill", "gcp-to-aws", "--output", str(output),
            ]))
            self.assertEqual("PASS", json.loads(output.read_text())["verdict"])
            with self.assertRaises(SystemExit):
                acceptance.main(["--run-dir", str(root), "--skill", "gcp-to-aws", "--output", str(output)])

    def test_terraform_safety_allowlist_blocks_untrusted_providers_and_modules(self):
        policy = acceptance.load_module("_test_accept_policy", acceptance.TF_SCRIPTS / "validate-terraform-policy.py")
        for extra in (
            'module "remote" { source = "git::https://example.invalid/module" }',
            'data "external" "run" { program = ["bash", "evil.sh"] }',
            'terraform { required_providers { "evil" = { source = "example/evil" } } }',
            'terraform { required_providers { evil = "example/evil" } }',
            'terraform { required_providers /* comment */ { evil = { source = "example/evil" } } }',
            'module /* comment */ "local" { source = "/tmp/untrusted" }',
            'locals { token = file("/private/credential") }',
            'locals { token = file /* comment */ ("/private/credential") }',
        ):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                root = execution_run(Path(temp))
                with (root / "terraform/main.tf").open("a") as stream:
                    stream.write(extra + "\n")
                with patch.object(acceptance, "command") as run:
                    result = acceptance.terraform_checks(root, Path("/trusted/terraform"), policy)
                self.assertEqual("UNVERIFIED", result["status"])
                run.assert_not_called()

    def test_terraform_runs_only_bounded_commands_in_copy_with_clean_environment(self):
        policy = acceptance.load_module("_test_accept_policy_copy", acceptance.TF_SCRIPTS / "validate-terraform-policy.py")
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            before = acceptance.file_hashes(root)
            seen = []

            def run(args, cwd, env, timeout=180):
                seen.append(args[1])
                self.assertNotEqual(root / "terraform", cwd)
                self.assertEqual(before["terraform/main.tf"],
                                 acceptance.hashlib.sha256((cwd / "main.tf").read_bytes()).hexdigest())
                self.assertNotIn("AWS_ACCESS_KEY_ID", env)
                self.assertNotIn("TF_CLI_ARGS", env)
                self.assertNotIn("BASH_ENV", env)
                payload = {"terraform_version": "1.13.5"} if args[1] == "version" else {
                    "valid": True, "error_count": 0,
                }
                return {"argv": args, "returncode": 0, "stdout": json.dumps(payload), "stderr": ""}

            with patch.object(acceptance, "command", side_effect=run):
                result = acceptance.terraform_checks(root, Path("/trusted/terraform"), policy)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(["version", "fmt", "init", "validate"], seen)
            self.assertEqual(before, acceptance.file_hashes(root))

    def test_wrong_executable_cannot_claim_terraform_pass(self):
        policy = acceptance.load_module("_test_wrong_binary", acceptance.TF_SCRIPTS / "validate-terraform-policy.py")
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            with patch.object(acceptance, "command", return_value={
                "returncode": 0, "stdout": "", "stderr": "",
            }):
                report = acceptance.terraform_checks(root, Path("/bin/true"), policy)
            self.assertEqual("UNVERIFIED", report["status"])

    def test_runtime_report_rejects_noncanonical_or_wrong_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            report = json.loads((root / "validation-report.json").read_text())
            report["status"] = {"claimed": "passed"}
            report["attempts"] = True
            self.assertTrue(acceptance.validation_report_errors(report))

    def test_runtime_report_rejects_unstructured_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = execution_run(Path(temp))
            report = json.loads((root / "validation-report.json").read_text())
            report["errors_found"] = ["all good"]
            self.assertIn("errors_found[0] must be an object",
                          acceptance.validation_report_errors(report))

    def test_checker_failure_is_an_unverified_json_verdict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = decision_run(Path(temp))
            output = Path(temp) / "acceptance.json"
            with patch.object(acceptance, "accept", side_effect=RuntimeError("checker did not run")):
                code = acceptance.main(["--run-dir", str(root), "--skill", "gcp-to-aws",
                                        "--output", str(output)])
            self.assertEqual(2, code)
            self.assertEqual("UNVERIFIED", json.loads(output.read_text())["verdict"])


if __name__ == "__main__":
    unittest.main()
