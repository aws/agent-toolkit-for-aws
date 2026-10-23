"""Synthetic Estimate evidence tests; these are not real prices or IDE runs."""
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
WRITER = PLUGIN / "scripts/emit-plan-json.py"
RUN_ID = "00000000-0000-4000-8000-000000000001"


def writer():
    spec = importlib.util.spec_from_file_location("cost_export_writer", WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(run, name, data):
    path = run / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def read(run, name):
    return json.loads((run / name).read_text())


def seed(run):
    """Price two explicitly bound synthetic resources with a duplicated label."""
    run.mkdir(parents=True, exist_ok=True)
    save(run, ".phase-status.json", {"run_id": RUN_ID, "owning_skill": "GCP_TO_AWS"})
    save(run, "preferences.json", {"design_constraints": {"target_region": {"value": "us-east-1"}}})
    save(run, "aws-design.json", {"services": [
        {"source_resource_id": "run:web", "aws_config": {"cpu": 0.25, "memory": 0.5, "region": "us-east-1"}},
        {"source_resource_id": "run:worker", "aws_config": {"cpu": 0.5, "memory": 1, "region": "us-east-1"}},
    ]})
    module = writer()
    snapshot = module.capture_inputs(run, "estimation-infra.json")
    costs = {"projected_costs": {"aws_monthly_balanced": 30.3, "breakdown": {
        "web/service~1": {"service": "ECS Fargate", "monthly": 10.1, "mid": 1},
        "total": 30.3,
        "excluded": {"monthly": 99, "excluded_from_total": True},
        "worker": {"service": "ECS Fargate", "mid": 20.2},
    }}, "accuracy_confidence": "+/-5-10%", "export_inputs": {"snapshot": snapshot, "rows": {}}}
    for index, (pointer, amount, identifier) in enumerate([
        ("/projected_costs/breakdown/web~1service~01/monthly", 10.1, "run:web"),
        ("/projected_costs/breakdown/worker/mid", 20.2, "run:worker"),
    ]):
        costs["export_inputs"]["rows"][pointer] = {
            "monthlyCost": amount,
            "estimateInput": {
                "regionCode": "us-east-1", "upfrontCost": "0.00",
                "pricingBasis": "Synthetic explicitly recorded on-demand price; no prepaid commitment.",
                "configurationSummary": (
                    f"Synthetic {identifier}: {0.25 if index == 0 else 0.5} vCPU, "
                    f"{0.5 if index == 0 else 1} GiB memory, 100 task-hours/month."
                ),
                "source": {"resourceIds": [identifier]},
            },
            "resourceIdPointers": [f"/services/{index}/source_resource_id"],
            "configurationPointers": [f"/services/{index}/aws_config"],
        }
    save(run, "estimation-infra.json", costs)
    return run


def plan(run, version=2):
    return writer().build_plan(run, PLUGIN / ".claude-plugin/plugin.json", version)[0]


def first_entry(data):
    return next(iter(data["export_inputs"]["rows"].values()))


def add_ai(run, amount=0.2):
    save(run, "aws-design-ai.json", {"models": [{"name": "synthetic-model"}]})
    save(run, "ai-workload-profile.json", {"monthly_input_tokens": 1000, "monthly_output_tokens": 200})
    data = {
        "cost_comparison": {"projected_bedrock_monthly": amount},
        "accuracy_confidence": "+/-20-30%",
        "export_inputs": {
            "snapshot": writer().capture_inputs(run, "estimation-ai.json"),
            "rows": {"/cost_comparison/projected_bedrock_monthly": {
                "monthlyCost": amount,
                "estimateInput": {"regionCode": "us-east-1", "upfrontCost": "0",
                                  "pricingBasis": "Synthetic explicit on-demand inference with no prepaid charge.",
                                  "configurationSummary": "Synthetic complete aggregate: synthetic-model, 1000 input and 200 output tokens."},
            }},
        },
    }
    save(run, "estimation-ai.json", data)


def test_default_v1_ignores_retention_and_v2_copies_selected_rows(tmp_path):
    run = seed(tmp_path / "run")
    legacy = plan(run, 1)
    upgraded = plan(run)
    assert legacy["schemaVersion"] == 1
    assert upgraded["schemaVersion"] == 2
    assert upgraded["cost"]["awsMonthlyBasis"] == "BALANCED"
    assert upgraded["cost"]["awsMonthly"] == 30.3
    rows = upgraded["cost"]["awsServiceItems"]
    assert [row["monthlyCost"] for row in rows] == [10.1, 20.2]
    assert [row["estimateInput"]["source"]["resourceIds"] for row in rows] == [["run:web"], ["run:worker"]]
    assert rows[0]["estimateInput"]["source"]["costPointer"] == "/projected_costs/breakdown/web~1service~01/monthly"
    assert rows[0]["estimateInput"]["upfrontCost"] == "0"
    for row in rows:
        del row["estimateInput"]
    upgraded["schemaVersion"] = 1
    assert upgraded == legacy
    estimate = read(run, "estimation-infra.json")
    del estimate["export_inputs"]
    save(run, "estimation-infra.json", estimate)
    assert plan(run, 1) == legacy


@pytest.mark.parametrize("change", ["design", "preferences", "usage_added", "run", "skill"])
def test_changed_pricing_input_or_run_omits_stale_context(tmp_path, change):
    run = seed(tmp_path / "run")
    if change == "design":
        data = read(run, "aws-design.json")
        data["services"][0]["aws_config"]["cpu"] = 8
        save(run, "aws-design.json", data)
    elif change == "preferences":
        save(run, "preferences.json", {"design_constraints": {"target_region": {"value": "eu-west-1"}}})
    elif change == "usage_added":
        save(run, "billing-profile.json", {"services": [{"monthly_cost": 100}]})
    else:
        status = read(run, ".phase-status.json")
        status["run_id" if change == "run" else "owning_skill"] = (
            "00000000-0000-4000-8000-000000000002" if change == "run" else "HEROKU_TO_AWS")
        save(run, ".phase-status.json", status)
    result = plan(run)
    assert result["schemaVersion"] == 2
    assert all("estimateInput" not in row for row in result["cost"]["awsServiceItems"])


@pytest.mark.parametrize("change", ["amount", "id", "cross_resource_config", "source", "null", "unknown_field"])
def test_invalid_retained_row_does_not_reject_other_rows(tmp_path, change):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    entry = first_entry(data)
    if change == "amount":
        entry["monthlyCost"] = 99
    elif change == "id":
        entry["resourceIdPointers"] = ["/services/1/source_resource_id"]
    elif change == "cross_resource_config":
        entry["configurationPointers"] = ["/services/1/aws_config"]
    elif change == "source":
        entry["estimateInput"]["source"]["estimateFile"] = "estimation-ai.json"
    elif change == "null":
        entry["estimateInput"]["upfrontCost"] = None
    else:
        entry["estimateInput"]["newField"] = "unrecognized"
    save(run, "estimation-infra.json", data)
    rows = plan(run)["cost"]["awsServiceItems"]
    assert "estimateInput" not in rows[0]
    assert rows[1]["estimateInput"]["source"]["resourceIds"] == ["run:worker"]


def test_missing_upfront_is_not_zero_and_text_normalizes(tmp_path):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    context = first_entry(data)["estimateInput"]
    del context["upfrontCost"]
    context["description"] = "First\r\nSecond\rThird"
    save(run, "estimation-infra.json", data)
    context = plan(run)["cost"]["awsServiceItems"][0]["estimateInput"]
    assert "upfrontCost" not in context
    assert context["description"] == "First\nSecond\nThird"


@pytest.mark.parametrize("field", ["regionCode", "pricingBasis", "configurationSummary"])
def test_nonblank_checks_match_javascript_trim(field):
    module = writer()
    assert not module._valid_context({field: "\ufeff"})
    assert module._valid_context({field: "\u0085"})


def test_zero_cost_and_infra_precedence_are_preserved(tmp_path):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    data["projected_costs"]["aws_monthly_balanced"] = 20.2
    data["projected_costs"]["breakdown"]["web/service~1"]["monthly"] = 0
    first_entry(data)["monthlyCost"] = 0
    save(run, "estimation-infra.json", data)
    save(run, "estimation-billing.json", {"cost_comparison": {"aws_monthly_mid": 999}})
    rows = plan(run)["cost"]["awsServiceItems"]
    assert [row["monthlyCost"] for row in rows] == [0, 20.2]
    assert rows[0]["estimateInput"]["upfrontCost"] == "0"
    assert plan(run)["cost"]["awsMonthlyBasis"] == "BALANCED"


@pytest.mark.parametrize("value", ["-1", "1e2", "0\n", "00", "100000000.0001", "1" * 129])
def test_malformed_upfront_never_reaches_wire(tmp_path, value):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    first_entry(data)["estimateInput"]["upfrontCost"] = value
    save(run, "estimation-infra.json", data)
    assert "estimateInput" not in plan(run)["cost"]["awsServiceItems"][0]


def test_selected_scenario_requires_matching_snapshots(tmp_path):
    run = seed(tmp_path / "run")
    preferences = read(run, "preferences.json")
    preferences["workshop"] = {"active": True, "active_scenario_id": "scenario-002", "last_sheet_at": "synthetic"}
    save(run, "preferences.json", preferences)
    save(run, "scenarios/index.json", {"active_scenario_id": "scenario-002"})
    for name in ("preferences.json", "aws-design.json", "estimation-infra.json"):
        shutil.copyfile(run / name, run / "scenarios" / f"scenario-002.{name}")
    rows = plan(run)["cost"]["awsServiceItems"]
    assert all(row["estimateInput"]["source"]["scenarioId"] == "scenario-002" for row in rows)
    saved = read(run, "scenarios/scenario-002.aws-design.json")
    saved["services"][0]["aws_config"]["cpu"] = 4
    save(run, "scenarios/scenario-002.aws-design.json", saved)
    assert all("estimateInput" not in row for row in plan(run)["cost"]["awsServiceItems"])


def test_workshop_cpu_choice_is_not_ignored_as_bookkeeping(tmp_path):
    run = seed(tmp_path / "run")
    preferences = read(run, "preferences.json")
    preferences["workshop"] = {"cpu_architecture": "arm64"}
    save(run, "preferences.json", preferences)
    assert all("estimateInput" not in row for row in plan(run)["cost"]["awsServiceItems"])


def test_mixed_workshop_needs_ai_snapshots_too(tmp_path):
    run = seed(tmp_path / "run")
    add_ai(run)
    preferences = read(run, "preferences.json")
    preferences["workshop"] = {"active": True, "active_scenario_id": "scenario-002"}
    save(run, "preferences.json", preferences)
    save(run, "scenarios/index.json", {"active_scenario_id": "scenario-002"})
    for name in ("preferences.json", "aws-design.json", "estimation-infra.json"):
        shutil.copyfile(run / name, run / "scenarios" / f"scenario-002.{name}")
    rows = plan(run)["cost"]["awsServiceItems"]
    assert all("estimateInput" in row for row in rows[:2])
    assert "estimateInput" not in rows[2]
    for name in ("aws-design-ai.json", "estimation-ai.json"):
        shutil.copyfile(run / name, run / "scenarios" / f"scenario-002.{name}")
    assert plan(run)["cost"]["awsServiceItems"][2]["estimateInput"]["source"]["scenarioId"] == "scenario-002"


def test_full_decimal_sum_preserves_v1_and_omits_stale_ai_context(tmp_path):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    data["projected_costs"]["aws_monthly_balanced"] = 0.1
    data["projected_costs"]["breakdown"] = {"aggregate": 0.1}
    data.pop("export_inputs")
    save(run, "estimation-infra.json", data)
    add_ai(run)
    assert plan(run, 1)["cost"]["awsMonthly"] == 0.30000000000000004
    result = plan(run)
    assert result["cost"]["awsMonthly"] == 0.3
    assert result["cost"]["awsMonthlyBasis"] == "INFRA_PLUS_AI_SUM"
    assert len(result["cost"]["awsServiceItems"]) == 2
    assert result["cost"]["awsServiceItems"][1]["estimateInput"]["source"]["estimateFile"] == "estimation-ai.json"
    save(run, "ai-workload-profile.json", {"monthly_input_tokens": 2000})
    assert "estimateInput" not in plan(run)["cost"]["awsServiceItems"][1]


def test_unrepresentable_full_sum_returns_unchanged_v1(tmp_path):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    data["projected_costs"]["aws_monthly_balanced"] = 10000000
    save(run, "estimation-infra.json", data)
    add_ai(run, 1e-10)
    assert plan(run) == plan(run, 1)


def test_billing_context_follows_original_index_without_configuration_guess(tmp_path):
    run = seed(tmp_path / "run")
    (run / "estimation-infra.json").unlink()
    save(run, "aws-design-billing.json", {"services": [{"aws_target": "Amazon S3"}]})
    data = {"cost_comparison": {"aws_monthly_mid": 10.1},
            "aws_projection": {"services": [{"aws_target": "Total", "aws_mid": 10.1},
                                           {"aws_target": "Amazon S3", "aws_mid": 10.1}]},
            "export_inputs": {"snapshot": writer().capture_inputs(run, "estimation-billing.json"), "rows": {
                "/aws_projection/services/1/aws_mid": {"monthlyCost": 10.1, "estimateInput": {}},
            }}}
    save(run, "estimation-billing.json", data)
    result = plan(run)
    assert result["cost"]["awsMonthlyBasis"] == "BILLING_MID"
    assert result["cost"]["awsServiceItems"][0]["estimateInput"] == {
        "source": {"estimateFile": "estimation-billing.json", "costPointer": "/aws_projection/services/1/aws_mid"},
    }


def test_cli_capture_does_not_touch_plan_and_export_is_opt_in(tmp_path):
    run = seed(tmp_path / "run")
    old = b'{"existing":true}\n'
    (run / "plan.json").write_bytes(old)
    result = subprocess.run([sys.executable, str(WRITER), "--migration-dir", str(run),
                             "--capture-inputs", "estimation-infra.json"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["runId"] == RUN_ID
    assert (run / "plan.json").read_bytes() == old
    for options, expected_version in (([], 1), (["--schema-version", "2"], 2)):
        subprocess.run([sys.executable, str(WRITER), "--migration-dir", str(run), *options], check=True, capture_output=True)
        assert read(run, "plan.json")["schemaVersion"] == expected_version
        assert (run / "plan.json").stat().st_mode & 0o777 == 0o600


def test_oversized_context_returns_v1_instead_of_unimportable_file(tmp_path):
    run = seed(tmp_path / "run")
    data = read(run, "estimation-infra.json")
    # ASCII escaping makes valid UTF-16-bounded text exceed the file budget.
    context = {"configurationSummary": "\u4e00" * 4096, "description": "\u4e00" * 1024,
               "pricingBasis": "\u4e00" * 1024}
    data["projected_costs"]["breakdown"] = {str(i): 0 for i in range(100)}
    data["projected_costs"]["aws_monthly_balanced"] = 0
    data["export_inputs"]["rows"] = {f"/projected_costs/breakdown/{i}": {
        "monthlyCost": 0, "estimateInput": copy.deepcopy(context),
    } for i in range(100)}
    save(run, "estimation-infra.json", data)
    assert plan(run) == plan(run, 1)
