"""Regression cases for the source/contract mismatches found in the gamma audit."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = PLUGIN_ROOT / "skills"
SPEC = importlib.util.spec_from_file_location(
    "research_contract_validator", PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def validate(tmp_path, skill, files):
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    findings = []
    manifest = VALIDATOR.load_manifest(PLUGIN_ROOT / "scripts" / "artifact-contracts.json")
    checked = VALIDATOR.validate_run_dir(tmp_path, skill, manifest, findings)
    errors = [finding for finding in findings if finding.severity == "error"]
    return checked, errors


def heroku_inventory():
    """One app and all five authored Terraform resource blocks, including release=0."""
    return {
        "metadata": {
            "discovery_timestamp": "2026-10-30T21:32:00Z",
            "total_apps_discovered": 1,
            "discovery_sources": ["terraform"],
            "confidence": "full",
        },
        "apps": [{
            "app_name": "acme-web", "app_id": None,
            "region": "us", "stack": "heroku-22",
            "heroku_generation": "cedar", "generation_action": "detect_only",
            "generation_diagnostics": [], "space": None,
            "discovery_status": "success", "failure_reason": None,
            "procfile_parse_warning": None, "app_json_parse_warning": None,
        }],
        "resources": [
            {
                "resource_id": "app:acme-web", "resource_type": "app",
                "heroku_app": "acme-web",
                "config": {"app_name": "acme-web", "region": "us", "stack": "heroku-22"},
                "source": "terraform", "tf_file": "heroku.tf", "tf_resource_name": "web",
            },
            *[
                {
                    "resource_id": f"formation:acme-web:{process}",
                    "resource_type": "formation", "heroku_app": "acme-web",
                    "config": {
                        "process_type": process, "command": None,
                        "dyno_type": "standard-1x", "quantity": quantity,
                    },
                    "source": "terraform", "tf_file": "heroku.tf",
                    "tf_resource_name": process,
                }
                for process, quantity in (("web", 1), ("release", 0))
            ],
            *[
                {
                    "resource_id": f"addon:acme-web:{service}:{plan}:{name}",
                    "resource_type": "addon", "heroku_app": "acme-web",
                    "config": {
                        "addon_service": service, "plan": plan, "provider": "heroku",
                        "addon_name": name, "addon_name_source": "tf_resource_name_fallback",
                    },
                    "source": "terraform", "tf_file": "heroku.tf", "tf_resource_name": name,
                }
                for service, plan, name in (
                    ("heroku-postgresql", "standard-0", "postgres"),
                    ("scheduler", "standard", "scheduler"),
                )
            ],
        ],
        "terraform_metadata": {
            "found": True, "tf_files_scanned": 1,
            "resource_types_extracted": ["heroku_app", "heroku_formation", "heroku_addon"],
            "parse_warnings": [],
        },
    }


def estimate():
    """Documented calculations and provenance, without arbitrary extension fields."""
    return {
        "phase": "estimate", "design_source": "infrastructure",
        "complexity_tier": "small", "pricing_source": {"status": "cached"},
        "projected_costs": {
            "aws_monthly_premium": 200, "aws_monthly_balanced": 180,
            "aws_monthly_optimized": 160,
            "aws_annual_premium": 2400, "aws_annual_balanced": 2160,
            "aws_annual_optimized": 1920,
            "scenario_deltas": {"premium": ["Larger database +$20"], "optimized": ["Commitment -$20"]},
            "breakdown": {
                category: {
                    "service": service, "monthly": 10,
                    "calculation": "quantity × rate", "pricing_source": source,
                }
                for category, service, source in (
                    ("compute", "Fargate", "cached"),
                    ("database", "RDS PostgreSQL", "estimated"),
                    ("storage", "S3", "cached"),
                    ("messaging", "SQS", "cached"),
                )
            },
        },
        "cost_comparison": {
            "gcp_monthly_baseline": 9.37,
            "gcp_baseline_quality": "Estimated standing charges only",
            "not_comparable_warning": "Incomplete source baseline",
        },
        "migration_cost_considerations": {
            "billing_data_available": False, "baseline_available": False,
            "categories": [], "note": "No authored source disk size",
        },
        "financial_summary": {
            "current_gcp_monthly": 9.37, "current_gcp_note": "Estimate, not a bill",
            "monthly_comparison_note": "Incomplete source baseline",
            "recommendation": "Conditional on missing workload evidence",
        },
        "recommendation": {"path": "migrate_optimized"},
    }


def scenario_index():
    return {
        "baseline_scenario_id": "scenario-001", "active_scenario_id": "scenario-001",
        "max_scenarios": 5, "inventory_fingerprint": "a" * 64,
        "scenarios": [{
            "scenario_id": "scenario-001", "label": "baseline",
            "created_at": "2026-10-30T21:32:00Z", "source": "baseline",
            "manifest": "scenarios/scenario-001.json",
        }],
    }


def test_heroku_authored_resource_and_provenance_fields_pass(tmp_path):
    checked, errors = validate(
        tmp_path, "heroku-to-aws", {"heroku-resource-inventory.json": heroku_inventory()}
    )
    assert checked == 1
    assert errors == []


def test_heroku_schema_still_rejects_unrecognized_metadata(tmp_path):
    inventory = heroku_inventory()
    inventory["resources"][0]["config"]["invented_network"] = True
    _, errors = validate(
        tmp_path, "heroku-to-aws", {"heroku-resource-inventory.json": inventory}
    )
    assert any(error.code == "UNKNOWN_KEY" and error.path.endswith(".invented_network")
               for error in errors)


def test_estimate_calculation_and_provenance_fields_pass(tmp_path):
    data = estimate()
    data["projected_costs"]["breakdown"].update({
        "networking": {
            "service": "ALB + NAT Gateway", "monthly": 53.01, "pricing_source": "cached",
            "components": {
                "alb": {"monthly": 17.01, "calculation": "hourly + LCU"},
                "nat_gateway": {"monthly": 35.1, "calculation": "hourly + data"},
                "route_53": {"monthly": 0.9, "calculation": "zone + queries"},
            },
        },
        "supporting": {"ecr": {"monthly": 0.05, "calculation": "0.5 GB × $0.10/GB"}},
        "observability": {
            "service": "CloudWatch", "low": 2, "mid": 3.53, "high": 5,
            "accuracy": "±30%", "pricing_source": "cached",
            "components": {"log_ingestion": 0.5, "log_storage": 0.03,
                           "custom_metrics": 3, "alarms": 0, "tracing": 0},
            "volume_source": "heuristic",
            "volume_detail": {
                "total_log_gb": 6, "sources": "Fargate + RDS + ALB",
                "billable_log_gb": 1, "custom_metrics_count": 20,
                "billable_metrics": 10, "alarm_count": 5,
                "alarm_count_source": "default", "tracing_detected": False,
            },
        },
    })
    checked, errors = validate(tmp_path, "gcp-to-aws", {"estimation-infra.json": data})
    assert checked == 1
    assert errors == []


@pytest.mark.parametrize("key", ["recommendation_summary", "invented_roi"])
def test_estimate_rejects_undocumented_verdict_aliases(tmp_path, key):
    data = estimate()
    data["financial_summary"][key] = "Independent verdict"
    _, errors = validate(tmp_path, "gcp-to-aws", {"estimation-infra.json": data})
    assert any(error.code == "UNKNOWN_KEY" and error.path == f"financial_summary.{key}"
               for error in errors)


def test_estimate_rejects_invalid_line_item_provenance(tmp_path):
    data = estimate()
    data["projected_costs"]["breakdown"]["database"]["pricing_source"] = "imagined"
    _, errors = validate(tmp_path, "gcp-to-aws", {"estimation-infra.json": data})
    assert any(error.code == "ENUM_VIOLATION"
               and error.path == "projected_costs.breakdown.database.pricing_source"
               for error in errors)


@pytest.mark.parametrize("heading", ["Security Baseline entry", "Compliance Baseline entry"])
def test_security_mid_example_is_sum_of_components(heading):
    document = SKILLS / "gcp-to-aws/references/shared/schema-estimate-infra.md"
    block = next(block for block in VALIDATOR.extract_blocks(document) if block.heading == heading)
    findings = []
    value, _ = VALIDATOR.parse_block(block, document, findings)
    assert findings == []
    assert value["mid"] == pytest.approx(sum(value["components"].values()))


def test_gcp_index_is_checked_by_actual_manifest(tmp_path):
    checked, errors = validate(
        tmp_path, "gcp-to-aws", {"scenarios/index.json": scenario_index()}
    )
    assert checked == 1
    assert errors == []


@pytest.mark.parametrize(
    "missing", ["baseline_scenario_id", "active_scenario_id", "max_scenarios",
                "inventory_fingerprint", "scenarios"]
)
def test_gcp_index_rejects_missing_canonical_fields(tmp_path, missing):
    data = scenario_index()
    data.pop(missing)
    _, errors = validate(tmp_path, "gcp-to-aws", {"scenarios/index.json": data})
    assert any(error.code == "MISSING_REQUIRED" and error.path == missing for error in errors)


def test_gcp_index_rejects_shadow_selection_fields(tmp_path):
    data = scenario_index()
    data["active"] = "scenario-002"
    _, errors = validate(tmp_path, "gcp-to-aws", {"scenarios/index.json": data})
    assert any(error.code == "UNKNOWN_KEY" and error.path == "active" for error in errors)


def test_gcp_manifest_requires_source(tmp_path):
    source = PLUGIN_ROOT / "fixtures/gcp-workshop/after-graviton-reprice/scenarios/scenario-001.json"
    data = copy.deepcopy(json.loads(source.read_text()))
    data.pop("source")
    checked, errors = validate(
        tmp_path, "gcp-to-aws", {"scenarios/scenario-001.json": data}
    )
    assert checked == 1
    assert any(error.code == "MISSING_REQUIRED" and error.path == "source" for error in errors)


@pytest.mark.parametrize(
    "file,field",
    [("clarify-global.md", "gcp_monthly_spend"),
     ("clarify-compute.md", "cloud_run_monthly_spend")],
)
def test_unknown_spend_choice_has_no_fabricated_dollar_band(file, field):
    document = (
        SKILLS / "gcp-to-aws/references/phases/clarify" / file
    ).read_text()
    # The declarative producer's option-6 interpretation caused the observed
    # recap defect; keep the unknown route distinct from the default band.
    assert f'6 -> {field}: "unknown"' in document
    assert f'{field}: "unknown"' in document


@pytest.mark.parametrize("field", ["gcp_monthly_spend", "cloud_run_monthly_spend", "cud_status"])
def test_explicit_unknown_is_valid_in_preferences(tmp_path, field):
    data = {"metadata": {}, "design_constraints": {
        field: {
            "value": "unknown", "chosen_by": "user",
            "prompt": "What is known?", "design_consequence": "No confirmed value",
        },
    }}
    checked, errors = validate(tmp_path, "gcp-to-aws", {"preferences.json": data})
    assert checked == 1
    assert errors == []


@pytest.mark.parametrize(
    "question,field",
    [("Q3 — GCP spend", "gcp_monthly_spend"),
     ("Q3.5 — GCP CUDs", "cud_status"),
     ("Q11 — Cloud Run spend", "cloud_run_monthly_spend")],
)
def test_assembler_defaults_preserve_unknown_facts(question, field):
    document = (
        SKILLS / "gcp-to-aws/references/phases/clarify/clarify-assemble.md"
    ).read_text()
    row = next(line for line in document.splitlines() if line.startswith(f"| {question}"))
    columns = [cell.strip() for cell in row.split("|")]
    assert columns[2] == "unknown"
    assert f'{field}: "unknown"' in columns[3]
    rules = document.split("### Schema Rules", 1)[1].split("## Defaults Table", 1)[0]
    assert 'retain `value: "unknown"` with `chosen_by: "user"`' in rules


def test_cloud_run_returned_row_default_preserves_unknown():
    document = SKILLS / "gcp-to-aws/references/phases/clarify/clarify-compute.md"
    block = next(block for block in VALIDATOR.extract_blocks(document)
                 if block.heading == "Rows returned")
    value = json.loads(VALIDATOR.strip_jsonc("{\n" + block.text + "\n}")[0])
    assert value["design_constraints"]["cloud_run_monthly_spend"]["default"] == "unknown"


def test_unavailable_baseline_has_null_comparisons_and_valid_schema(tmp_path):
    document = SKILLS / "gcp-to-aws/references/shared/schema-estimate-infra.md"
    block = next(block for block in VALIDATOR.extract_blocks(document)
                 if block.heading == "Unavailable source baseline")
    value = json.loads(VALIDATOR.strip_jsonc(block.text)[0])
    assert value["current_costs"]["source"] == "unavailable"
    assert value["current_costs"]["gcp_monthly"] is None
    assert value["current_costs"]["gcp_annual"] is None
    assert value["cost_comparison"]["gcp_monthly_baseline"] is None
    for key in ("option_a_premium", "option_b_balanced", "option_c_optimized"):
        assert set(value["cost_comparison"][key].values()) == {None}
    assert set(value["roi_analysis"]["recurring_savings"].values()) == {None}
    assert set(value["financial_summary"].values()) == {None}
    data = estimate()
    data.update(value)
    checked, errors = validate(tmp_path, "gcp-to-aws", {"estimation-infra.json": data})
    assert checked == 1
    assert errors == []


def test_report_preserves_unknown_and_unavailable_baselines():
    document = (
        SKILLS / "gcp-to-aws/references/phases/generate/generate-artifacts-report.md"
    ).read_text()
    appendix = document.split("### Appendix Section F", 1)[1].split(
        "### Appendix Section G", 1
    )[0]
    assert "Cost comparison uses the default band" not in appendix
    assert "No spend band has been assumed" in appendix
    assert 'current_costs.source` is `"unavailable"`' in appendix
    assert "**Unavailable**, not `$0`" in appendix


@pytest.mark.parametrize("relative", [
    "phases/estimate/estimate-infra.md",
    "phases/workshop/workshop-refresh.md",
])
def test_runtime_instructions_do_not_require_repository_only_validator(relative):
    document = (SKILLS / "gcp-to-aws/references" / relative).read_text()
    assert "scripts/validate-artifacts.py" not in document
    assert "Independent repository acceptance enforces" in document
