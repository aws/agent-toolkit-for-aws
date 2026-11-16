"""Contract tests for Render Workflow generation.

Every supported semantic in the rubric (``render_workflow_asl``) is proven twice:
against the ASL built from the source mapping and against the ASL parsed back out
of the generated ``workflow.tf``. Expected values come from the fixture mappings,
not from the emitter.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess  # nosec B404 - fixed local validation tools, no shell
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_pipeline_harness as harness  # noqa: E402
import render_workflow_asl as asl  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "plugins/aws-startup-advisor"
SKILL_ROOT = PLUGIN / "skills/render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures/expected"
CONTRACTS = EXPECTED / "workflow-contracts"
GOLDEN_TF = EXPECTED / "generated/terraform"
POLICY = PLUGIN / "skills/tf-best-practices/scripts/validate-terraform-policy.py"
FRAGMENT = SKILL_ROOT / "references/phases/generate/generate-infra-workflow.md"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def golden_design() -> dict[str, Any]:
    return load(EXPECTED / "aws-design.json")


def config(design: dict[str, Any], source_id: str) -> dict[str, Any]:
    return next(row for row in design["mappings"] if row["source_resource_id"] == source_id)["aws_config"]


def variant_design() -> dict[str, Any]:
    return load(CONTRACTS / "ecs-map-compensation.mappings.json")


def spec_of(design: dict[str, Any]) -> asl.Spec:
    plan = asl.classify(design)
    assert plan.reasons == {}, plan.reasons
    assert len(plan.specs) == 1
    return plan.specs[0]


def both_asl(design: dict[str, Any]) -> tuple[asl.Spec, str, dict[str, Any], dict[str, Any]]:
    """Return the spec, generated Terraform, built ASL, and ASL parsed from the Terraform."""
    spec = spec_of(design)
    text = asl.render_workflow_tf([spec])
    return spec, text, asl.build_asl(spec), asl.generated_asl(text, spec.res)


@pytest.fixture(scope="module")
def golden() -> tuple[asl.Spec, str, dict[str, Any], dict[str, Any]]:
    return both_asl(golden_design())


@pytest.fixture(scope="module")
def variant() -> tuple[asl.Spec, str, dict[str, Any], dict[str, Any]]:
    return both_asl(variant_design())


def each(pair: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Both ASL renderings: the builder output and the definition parsed from Terraform."""
    return [pair[2], pair[3]]


def test_builder_and_generated_terraform_agree(golden: Any, variant: Any) -> None:
    for pair in (golden, variant):
        assert pair[2] == pair[3]


def test_sequence_chain_matches_task_order(variant: Any) -> None:
    design = variant_design()
    order = config(design, "wf-ship")["task_order"]
    assert order == ["task-prepare", "task-render"]
    for definition in each(variant):
        assert definition["StartAt"] == "task_prepare"
        states = definition["States"]
        assert states["task_prepare"]["Next"] == "task_render"
        assert "End" not in states["task_prepare"]
        assert states["task_render"]["End"] is True
        assert "Next" not in states["task_render"]
        # task_order contains no other reachable regular state: the rest are the compensation path.
        assert set(states) == {"task_prepare", "task_render", "Compensate_task_render", "CompensatedFailure"}


def test_lambda_task_integration_and_packaging(golden: Any, variant: Any) -> None:
    spec, text, _, _ = variant
    prepare = variant[2]["States"]["task_prepare"]
    parsed = variant[3]["States"]["task_prepare"]
    for state in (prepare, parsed):
        assert state["Type"] == "Task"
        assert state["Resource"] == "arn:aws:states:::lambda:invoke"
        assert state["Parameters"] == {"FunctionName": asl.Ref("aws_lambda_function.task_prepare.arn"), "Payload.$": "$"}
        assert state["OutputPath"] == "$.Payload"
    assert 'resource "aws_lambda_function" "task_prepare"' in text
    body = text.split('resource "aws_lambda_function" "task_prepare"', 1)[1].split("\nresource ", 1)[0]
    assert "filename         = var.task_prepare_package_path" in body
    assert "source_code_hash = filebase64sha256(var.task_prepare_package_path)" in body
    assert "runtime          = var.task_prepare_runtime" in body and "handler          = var.task_prepare_handler" in body
    assert "memory_size      = var.task_prepare_memory_mb" in body
    # The pack carries no function source, no inline archive, and no defaults for owner-supplied packaging.
    gtext = golden[1]
    for forbidden in ("source_code ", "archive_file", "inline", "zip_file", "s3_bucket"):
        assert forbidden not in gtext
    for suffix in ("package_path", "runtime", "handler", "memory_mb"):
        block = re.search(rf'variable "rr_workflow_task_{suffix}" \{{(.*?)\n\}}', gtext, re.S)
        assert block and "default" not in block.group(1)
    # Each Lambda role may only write its own log group.
    policy = asl.parse_hcl_literal(asl.extract_jsonencode(text, 'resource "aws_iam_role_policy" "task_prepare"'))
    assert policy["Statement"] == [{
        "Effect": "Allow",
        "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": [asl.Ref('"${aws_cloudwatch_log_group.task_prepare.arn}:*"')],
    }]
    assert spec.task("task-prepare").service == "lambda"


def test_ecs_task_integration_and_iam(variant: Any) -> None:
    for definition in each(variant):
        render = definition["States"]["task_render"]["ItemProcessor"]["States"]["task_render"]
        assert render["Resource"] == "arn:aws:states:::ecs:runTask.sync"
        params = render["Parameters"]
        assert params["LaunchType"] == "FARGATE"
        assert params["TaskDefinition"] == asl.Ref("aws_ecs_task_definition.task_render.arn")
        network = params["NetworkConfiguration"]["AwsvpcConfiguration"]
        assert network["AssignPublicIp"] == "DISABLED"
        assert network["SecurityGroups"] == [asl.Ref("aws_security_group.worker.id")]
        assert network["Subnets"] == asl.Ref("aws_subnet.private[*].id")
        # F1: the container must receive the state input (the Map item inside the Map) as STEP_INPUT.
        assert params["Overrides"] == {"ContainerOverrides": [{
            "Name": "task_render",
            "Environment": [{"Name": "STEP_INPUT", "Value.$": "States.JsonToString($)"}],
        }]}
        # Output contract: the task description is discarded, so the input passes through and
        # non-object Map items cannot hit States.ResultPathMatchFailure.
        assert render["ResultPath"] is None
    text = variant[1]
    assert 'resource "aws_ecs_task_definition" "task_render"' in text
    assert 'requires_compatibilities = ["FARGATE"]' in text
    assert "var.task_render_image" in text
    assert re.search(r'variable "task_render_image" \{(?:(?!\n\}).)*?validation', text, re.S)
    assert "default" not in re.search(r'variable "task_render_image" \{(.*?)\n\}', text, re.S).group(1)  # type: ignore[union-attr]


def test_every_supported_ecs_state_receives_input(variant: Any) -> None:
    """F1 guard: no generated runTask.sync state, at any depth, may run without the step input."""

    def walk(states: dict[str, Any]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for state in states.values():
            if state.get("Resource") == "arn:aws:states:::ecs:runTask.sync":
                found.append(state)
            if "ItemProcessor" in state:
                found.extend(walk(state["ItemProcessor"]["States"]))
        return found

    for definition in each(variant):
        ecs_states = walk(definition["States"])
        assert ecs_states
        for state in ecs_states:
            overrides = state["Parameters"].get("Overrides", {}).get("ContainerOverrides", [])
            assert [entry["Environment"] for entry in overrides] == [[{"Name": asl.ECS_INPUT_ENV, "Value.$": "States.JsonToString($)"}]]
            assert state["ResultPath"] is None


def test_assemble_reads_every_infra_fragment_and_workflow_contribution_is_conditional() -> None:
    """F2 guard."""
    assemble = (SKILL_ROOT / "references/phases/generate/generate-assemble.md").read_text(encoding="utf-8")
    assert "\n  - artifacts-infra-workflow\n" in assemble
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert re.search(r"_contributes:\n  - \{ file: terraform/workflow\.tf, _when: \"[^\"]+\" \}", fragment)


def test_timeout_matches_source_and_lambda_bound(golden: Any, variant: Any) -> None:
    design = variant_design()
    prepare_seconds = config(design, "task-prepare")["timeout_seconds"]
    render_seconds = config(design, "task-render")["timeout_minutes"] * 60
    undo_seconds = config(design, "task-undo")["timeout_seconds"]
    for definition in each(variant):
        states = definition["States"]
        assert states["task_prepare"]["TimeoutSeconds"] == prepare_seconds == 120
        assert states["task_render"]["ItemProcessor"]["States"]["task_render"]["TimeoutSeconds"] == render_seconds == 1200
        assert states["Compensate_task_render"]["TimeoutSeconds"] == undo_seconds == 60
    text = variant[1]
    assert re.search(r'resource "aws_lambda_function" "task_prepare" \{.*?\n  timeout\s+= 120\n', text, re.S)
    assert re.search(r'resource "aws_lambda_function" "task_undo" \{.*?\n  timeout\s+= 60\n', text, re.S)
    # The golden Lambda keeps the task timeout while the callback state waits for the callback timeout.
    golden_design_value = golden_design()
    task_seconds = config(golden_design_value, "rr-workflow-task")["timeout_minutes"] * 60
    assert re.search(rf'resource "aws_lambda_function" "rr_workflow_task" \{{.*?\n  timeout\s+= {task_seconds}\n', golden[1], re.S)
    assert task_seconds <= asl.LAMBDA_MAX_SECONDS


def test_retry_mapping_exact_and_absent_means_unsupported(golden: Any, variant: Any) -> None:
    design = variant_design()
    for task_id, state_path in (("task-prepare", ("task_prepare",)), ("task-undo", ("Compensate_task_render",))):
        source = config(design, task_id)["retry"]
        for definition in each(variant):
            state = definition["States"][state_path[0]]
            assert state["Retry"] == [{
                "ErrorEquals": ["States.TaskFailed", "States.Timeout"],
                "IntervalSeconds": source["wait_duration_ms"] // 1000,
                "MaxAttempts": source["max_retries"],
                "BackoffRate": source["backoff_scaling"],
            }]
    render_source = config(design, "task-render")["retry"]
    for definition in each(variant):
        inner = definition["States"]["task_render"]["ItemProcessor"]["States"]["task_render"]
        assert inner["Retry"][0]["MaxAttempts"] == render_source["max_retries"] == 4
        assert inner["Retry"][0]["IntervalSeconds"] == 10
    # Callback states never retry a timed-out token wait.
    golden_source = config(golden_design(), "rr-workflow-task")["retry"]
    for definition in each(golden):
        retry = definition["States"]["rr_workflow_task"]["Retry"]
        assert retry == [{"ErrorEquals": ["States.TaskFailed"], "IntervalSeconds": golden_source["wait_duration_ms"] // 1000, "MaxAttempts": golden_source["max_retries"], "BackoffRate": golden_source["backoff_scaling"]}]
    # Render applies an undocumented default retry when retry is omitted, so omission fails closed.
    omitted = variant_design()
    del omitted["mappings"][1]["aws_config"]["retry"]
    assert asl.classify(omitted).reasons["wf-ship"].startswith("retry_missing")


def test_fan_out_fan_in_map_structure(variant: Any) -> None:
    source = config(variant_design(), "task-render")["fan_out"]
    for definition in each(variant):
        state = definition["States"]["task_render"]
        assert state["Type"] == "Map"
        assert state["ItemsPath"] == "$.items"
        assert state["MaxConcurrency"] == source["max_concurrency"] == 4
        processor = state["ItemProcessor"]
        assert processor["ProcessorConfig"] == {"Mode": "INLINE"}
        assert processor["StartAt"] == "task_render"
        assert processor["States"]["task_render"]["End"] is True
        assert processor["States"]["task_render"]["Type"] == "Task"
        # Any item failure fails the Map: no tolerated-failure fields, and no Map-level Parameters rewrite.
        assert not {"ToleratedFailureCount", "ToleratedFailurePercentage", "ResultPath", "ResultSelector"} & set(state)
        # The Map output array is the fan-in value passed to whatever follows (here the end of the task order).
        assert state["End"] is True


def test_catch_routes_to_compensation_then_fail(variant: Any) -> None:
    design = variant_design()
    assert config(design, "task-render")["compensation_task"] == "task-undo"
    for definition in each(variant):
        states = definition["States"]
        assert states["task_render"]["Catch"] == [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Compensate_task_render"}]
        assert "Catch" not in states["task_prepare"]  # no compensation_task, so failure is unhandled and fails the execution
        compensation = states["Compensate_task_render"]
        assert compensation["Resource"] == "arn:aws:states:::lambda:invoke"
        assert compensation["Parameters"]["FunctionName"] == asl.Ref("aws_lambda_function.task_undo.arn")
        assert compensation["Next"] == "CompensatedFailure"
        assert states["CompensatedFailure"]["Type"] == "Fail"
        assert states["CompensatedFailure"]["Error"] == "CompensatedFailure"
        assert "Catch" not in compensation
    # A compensated run must still end failed: nothing routes out of the Fail state.
    spec = variant[0]
    assert spec.task("task-undo").compensation is None


def test_callback_uses_task_token_and_timeout(golden: Any) -> None:
    source = golden_design()
    wf = config(source, "rr-workflow")
    assert wf["callbacks"] is True
    for definition in each(golden):
        state = definition["States"]["rr_workflow_task"]
        assert state["Resource"] == "arn:aws:states:::lambda:invoke.waitForTaskToken"
        assert state["Parameters"]["Payload"] == {"input.$": "$", "TaskToken.$": "$$.Task.Token"}
        assert state["Parameters"]["FunctionName"] == asl.Ref("aws_lambda_function.rr_workflow_task.arn")
        assert state["TimeoutSeconds"] == wf["callback_timeout_seconds"] == 3600
        assert "OutputPath" not in state  # the callback sender's output is the state output
    text = golden[1]
    # Sender-side actions cannot be scoped to one state machine, so Terraform never grants them.
    assert "states:SendTask" not in text


def test_standard_logging_retention_and_alarms(golden: Any, variant: Any) -> None:
    for pair in (golden, variant):
        text, res = pair[1], pair[0].res
        machine = text.split(f'resource "aws_sfn_state_machine" "{res}"', 1)[1].split("\nresource ", 1)[0]
        assert 'type     = "STANDARD"' in machine
        assert 'level                  = "ALL"' in machine
        assert "include_execution_data = false" in machine
        assert f'log_destination        = "${{aws_cloudwatch_log_group.{res}.arn}}:*"' in machine
        assert "enabled = var.workflow_tracing_enabled" in machine
        assert f'"/aws/vendedlogs/states/${{local.name_prefix}}-{pair[0].source_id}"' in text
        for metric in ("ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"):
            alarm = re.search(rf'resource "aws_cloudwatch_metric_alarm" "{res}_{metric.lower()}" \{{(.*?)\n\}}', text, re.S)
            assert alarm, metric
            assert f'metric_name = "{metric}"' in alarm.group(1)
            assert 'namespace   = "AWS/States"' in alarm.group(1)
            assert f"StateMachineArn = aws_sfn_state_machine.{res}.arn" in alarm.group(1)
            assert "alarm_actions       = var.workflow_alarm_actions" in alarm.group(1)
        # Every log group uses the validated retention variable; no literal retention and no never-expire.
        assert re.findall(r"retention_in_days\s+= (.+)", text) == ["var.workflow_log_retention_days"] * text.count("aws_cloudwatch_log_group\" \"")
    text = golden[1]
    assert re.search(r'variable "workflow_tracing_enabled" \{.*?default\s+= false', text, re.S)
    assert re.search(r'variable "workflow_alarm_actions" \{.*?default\s+= \[\]', text, re.S)
    retention = re.search(r'variable "workflow_log_retention_days" \{(.*?)\n\}', text, re.S)
    assert retention and "contains([1, 3, 5, 7, 14, 30, 60, 90," in retention.group(1) and "default     = 30" in retention.group(1)
    # No DLQ: Step Functions invokes tasks synchronously, so nothing is asynchronous and nothing is dropped.
    assert "aws_sqs_queue" not in text and "dead_letter" not in text


def _statements(text: str, anchor: str) -> list[dict[str, Any]]:
    return asl.parse_hcl_literal(asl.extract_jsonencode(text, anchor))["Statement"]


def test_iam_scope_is_exact(golden: Any, variant: Any) -> None:
    # Lambda-only Workflow: exactly one invoke statement on the one declared function ARN.
    assert _statements(golden[1], 'resource "aws_iam_role_policy" "rr_workflow_tasks"') == [
        {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [asl.Ref("aws_lambda_function.rr_workflow_task.arn")]}
    ]
    statements = _statements(variant[1], 'resource "aws_iam_role_policy" "wf_ship_tasks"')
    assert statements == [
        {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [asl.Ref("aws_lambda_function.task_prepare.arn"), asl.Ref("aws_lambda_function.task_undo.arn")]},
        {"Effect": "Allow", "Action": ["ecs:RunTask"], "Resource": [asl.Ref("aws_ecs_task_definition.task_render.arn")]},
        {"Effect": "Allow", "Action": ["iam:PassRole"], "Resource": [asl.Ref("aws_iam_role.ecs_execution.arn"), asl.Ref("aws_iam_role.ecs_task.arn")], "Condition": {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}},
        {"Effect": "Allow", "Action": ["events:PutTargets", "events:PutRule", "events:DescribeRule"], "Resource": [asl.Ref('"arn:aws:events:${var.aws_region}:${data.aws_caller_identity.wf_ship.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"')]},
    ]
    # No wildcard Action or Resource in any literal role policy of either Terraform.
    for text in (golden[1], variant[1]):
        for match in re.finditer(r'resource "aws_iam_role_policy" "[a-z0-9_]+"', text):
            if match.group(0).endswith('_service"'):
                continue
            policy = asl.parse_hcl_literal(asl.extract_jsonencode(text, match.group(0)))
            for statement in policy["Statement"]:
                assert "*" not in statement["Action"] and statement["Resource"] != ["*"]
                assert all(isinstance(r, asl.Ref) or "*" != r for r in statement["Resource"])
    # Resource "*" is confined to documented service requirements: log delivery, optional X-Ray, ECS stop/describe.
    doc = golden[1].split('data "aws_iam_policy_document" "rr_workflow_service"', 1)[1].split("\nresource ", 1)[0]
    assert doc.count('resources = ["*"]') == 2 and "ecs:" not in doc
    variant_doc = variant[1].split('data "aws_iam_policy_document" "wf_ship_service"', 1)[1].split("\nresource ", 1)[0]
    assert re.search(r'actions   = \["ecs:StopTask", "ecs:DescribeTasks"\]', variant_doc)
    assert "ecs:RunTask" not in variant_doc and "iam:PassRole" not in variant_doc and "lambda:" not in variant_doc
    xray = re.search(r'dynamic "statement" \{(.*?)\n  \}', golden[1], re.S)
    assert xray and "var.workflow_tracing_enabled ? [1] : []" in xray.group(1)
    # A Lambda role trusts only lambda.amazonaws.com; the state machine role only states.amazonaws.com.
    assert 'Service = "lambda.amazonaws.com"' in golden[1] and 'Service = "states.amazonaws.com"' in golden[1]
    assert "ecs-tasks.amazonaws.com" not in golden[1].replace("iam:PassedToService", "")


def mutate(design: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(design)
    row = next(item for item in result["mappings"] if item["source_resource_id"] == case["target"])
    if "aws_service" in case:
        row["aws_service"] = case["aws_service"]
    for key in case.get("remove", []):
        row["aws_config"].pop(key)
    row["aws_config"].update(case.get("set", {}))
    return result


UNSUPPORTED_CASES = load(CONTRACTS / "unsupported-cases.json")["cases"]


@pytest.mark.parametrize("case", UNSUPPORTED_CASES, ids=[case["name"] for case in UNSUPPORTED_CASES])
def test_unsupported_cases_fail_closed(case: dict[str, Any]) -> None:
    plan = asl.classify(mutate(golden_design(), case))
    assert plan.specs == ()
    assert plan.reasons["rr-workflow"].startswith(case["expect"] + ":") or plan.reasons["rr-workflow"].startswith(case["expect"] + "_")
    assert case["expect"] in asl.REASON_KEYS
    # The Workflow and its task are both unsupported together: no partial or approximate emission.
    assert set(plan.reasons) >= {"rr-workflow", "rr-workflow-task"}
    assert plan.generated_ids() == set()
    warnings = asl.warnings_for(plan)
    by_subject = {w["subject"]: w for w in warnings}
    assert set(by_subject) <= {"rr-workflow", "rr-workflow-task"} and "rr-workflow" in by_subject
    assert all(w["code"] == "conditional_workflow_generation_unsupported" and not w["blocking"] for w in warnings)
    assert by_subject["rr-workflow"]["detail"] == plan.reasons["rr-workflow"]
    # A task is only warned about separately when it has no parent Workflow to explain it.
    if "rr-workflow-task" in by_subject:
        assert plan.reasons["rr-workflow-task"].startswith("task_orphan")


def test_unsupported_warning_validates_against_the_ledger_schema() -> None:
    schema = load(SKILL_ROOT / "references/shared/schema-generation-warnings.json")
    ledger = load(EXPECTED / "generated/generation-warnings.json")
    case = {"target": "rr-workflow", "set": {"branching": True}}
    plan = asl.classify(mutate(golden_design(), case))
    ledger["generated"] = [row for row in ledger["generated"] if not row["source_resource_id"].startswith("rr-workflow")]
    ledger["unsupported"] = [
        {"source_resource_id": sid, "render_kind": "render.workflow" if sid == "rr-workflow" else "render.workflow_task", "aws_service": "x", "reason": reason, "target_files": []}
        for sid, reason in sorted(plan.reasons.items())
    ]
    ledger["warnings"] = [*asl.warnings_for(plan), *ledger["warnings"]]
    ledger["accounting"].update({"generated_count": 11, "unsupported_count": 2})
    jsonschema.Draft202012Validator(schema).validate(ledger)


def test_no_declared_semantics_stays_unsupported() -> None:
    design = golden_design()
    row = next(item for item in design["mappings"] if item["source_resource_id"] == "rr-workflow")
    row["aws_config"] = {"history": "auditable", "callbacks": True}
    task = next(item for item in design["mappings"] if item["source_resource_id"] == "rr-workflow-task")
    task["aws_config"] = {"timeout_minutes": 5}
    plan = asl.classify(design)
    assert plan.specs == () and plan.reasons["rr-workflow"].startswith("callback_timeout_missing")
    assert plan.reasons["rr-workflow-task"].startswith("task_orphan")  # no task_order, so nothing owns the task


def test_orphan_tasks_and_source_only_records_are_never_generated() -> None:
    design = golden_design()
    design["mappings"].append({"source_resource_id": "rr-extra-task", "render_kind": "render.workflow_task", "aws_service": "AWS Lambda", "aws_config": {"timeout_minutes": 1}})
    for kind in asl.SOURCE_ONLY_KINDS:
        design["mappings"].append({"source_resource_id": f"rr-{kind}", "render_kind": kind, "aws_service": "metadata", "aws_config": {}})
    plan = asl.classify(design)
    assert [spec.source_id for spec in plan.specs] == ["rr-workflow"]
    assert plan.reasons["rr-extra-task"].startswith("task_orphan")
    assert all(plan.reasons[f"rr-{kind}"].startswith("source_record_not_importable") for kind in asl.SOURCE_ONLY_KINDS)
    assert "rr-workflow-task" in plan.generated_ids() and "rr-extra-task" not in plan.generated_ids()


def test_harness_mixed_pipeline_declares_no_semantics_and_stays_unsupported() -> None:
    # The harness writes only selection_source/source_kind into aws_config for every kind.
    config_shape = {"selection_source": "canonical_inventory_and_completed_preferences"}
    design = {"mappings": [
        {"source_resource_id": "mixed-wf", "render_kind": "render.workflow", "aws_service": harness.TARGETS["render.workflow"], "aws_config": {**config_shape, "source_kind": "render.workflow"}},
        {"source_resource_id": "mixed-task", "render_kind": "render.workflow_task", "aws_service": harness.TARGETS["render.workflow_task"], "aws_config": {**config_shape, "source_kind": "render.workflow_task"}},
    ]}
    plan = asl.classify(design)
    assert plan.specs == () and set(plan.reasons) == {"mixed-wf", "mixed-task"}
    assert {"render.workflow", "render.workflow_task"} <= harness.WORKFLOW_KINDS


def test_golden_workflow_tf_matches_emitter() -> None:
    design = golden_design()
    expected = asl.render_workflow_tf(asl.workflow_specs(design))
    assert (GOLDEN_TF / "workflow.tf").read_text(encoding="utf-8") == expected
    example = (GOLDEN_TF / "terraform.tfvars.example").read_text(encoding="utf-8")
    for line in asl.tfvars_example_lines(asl.workflow_specs(design)):
        key, value = line.split(" = ", 1)
        assert re.search(rf"^{key}\s+= {re.escape(value)}$", example, re.M)


def test_no_source_code_or_captured_values_in_workflow_terraform(golden: Any, variant: Any) -> None:
    for text in (golden[1], variant[1]):
        assert not re.search(r"\bsource_code\b|\bzip_file\b|\binline_code\b|\bdata\s+\"archive_file\"", text)
        assert not re.search(r"(?i)password|secret_access|api[_-]?key|token\s*=\s*\"[^$]", text)
        for name in re.findall(r'variable "([a-z0-9_]+_(?:package_path|runtime|handler|memory_mb|image|cpu))"', text):
            block = re.search(rf'variable "{name}" \{{(.*?)\n\}}', text, re.S)
            assert block and "default" not in block.group(1) and "validation {" in block.group(1)
    # ECR digests in tfvars examples are synthetic placeholders.
    assert "000000000000" in "".join(asl.tfvars_example_lines([variant[0]]))


def _terraform(tmp_path: Path, workflow_text: str) -> Path:
    target = tmp_path / "terraform"
    shutil.copytree(GOLDEN_TF, target, ignore=shutil.ignore_patterns(".terraform", ".terraform.lock.hcl"))
    (target / "workflow.tf").write_text(workflow_text, encoding="utf-8")
    return target


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)  # nosec B603 - fixed local tools


@pytest.mark.parametrize("name", ["golden", "ecs_map_compensation"])
def test_workflow_terraform_toolchain(name: str, tmp_path: Path) -> None:
    design = golden_design() if name == "golden" else variant_design()
    text = asl.render_workflow_tf([spec_of(design)])
    if name == "ecs_map_compensation":
        # Needs the baseline network, cluster, and execution role the Workflow references.
        assert all(token in (GOLDEN_TF / file).read_text(encoding="utf-8") for token, file in (
            ('resource "aws_ecs_cluster" "main"', "compute.tf"),
            ('resource "aws_iam_role" "ecs_execution"', "compute.tf"),
            ('resource "aws_security_group" "worker"', "network.tf"),
            ('resource "aws_subnet" "private"', "network.tf"),
        ))
    target = _terraform(tmp_path, text)
    compute = target / "compute.tf"
    if 'resource "aws_iam_role" "ecs_task"' not in compute.read_text(encoding="utf-8"):
        # The compute fragment owns the task role; stand in for it until the golden compute.tf declares it.
        compute.write_text(compute.read_text(encoding="utf-8") + '\nresource "aws_iam_role" "ecs_task" {\n  name               = "${local.name_prefix}-ecs-task"\n  assume_role_policy = aws_iam_role.ecs_execution.assume_role_policy\n}\n', encoding="utf-8")
    policy = _run([sys.executable, str(POLICY), str(target)], tmp_path)
    assert policy.returncode == 0 and policy.stdout.startswith("POLICY_OK"), policy.stdout + policy.stderr
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("terraform is not installed")
    fmt = _run([terraform, "fmt", "-check", "-recursive", "-diff"], target)
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr
    init = _run([terraform, "init", "-backend=false", "-input=false", "-no-color"], target)
    if init.returncode != 0:
        if harness.classify_terraform_init_failure(init.stdout + init.stderr) == "provider_registry_unavailable":
            pytest.skip("provider registry unavailable; fmt and policy passed")
        pytest.fail(init.stdout + init.stderr)
    validate = _run([terraform, "validate", "-no-color"], target)
    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_generation_guidance_names_every_rubric_key() -> None:
    text = FRAGMENT.read_text(encoding="utf-8")
    assert "_fragment: artifacts-infra-workflow" in text and "_of_phase: generate" in text
    for key in (*asl.REASON_KEYS, *asl.UNSUPPORTED_KEYS):
        assert f"`{key}`" in text, key
    for token in ("States.TaskFailed", "States.Timeout", "waitForTaskToken", "runTask.sync", "MaxConcurrency", "CompensatedFailure", "ALL", "Render execution parity"):
        assert token in text
    generate = (SKILL_ROOT / "references/phases/generate/generate.md").read_text(encoding="utf-8")
    assert "_id: artifacts-infra-workflow" in generate and "phases/generate/generate-infra-workflow.md" in generate


def test_ecs_workflow_input_and_no_return_data_reach_the_owner_guide() -> None:
    # The fragment says an ECS task gets its input only as STEP_INPUT and returns no data. Without the same words in
    # the guide, an owner who moves a Render task image unchanged starts it without arguments and nothing fails.
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert "`STEP_INPUT`" in fragment and "8192" in fragment and "`ResultPath` is `null`" in fragment
    docs = (SKILL_ROOT / "references/phases/generate/generate-artifacts-docs.md").read_text(encoding="utf-8")
    cutover = next(line for line in docs.splitlines() if line.startswith("7. **Deployment and service cutover**"))
    limits = next(line for line in docs.splitlines() if line.startswith("11. **Known limitations**"))
    for needed in ("`STEP_INPUT`", "8192", "nothing would fail", "make the container read"):
        assert needed in cutover, needed
    for needed in ("returns no data", "`ResultPath` is `null`", "Map fan-in", "S3 or DynamoDB"):
        assert needed in limits, needed



def test_ecs_task_roles_logs_and_dependencies_are_stated_and_passable(variant: Any) -> None:
    text = variant[1]
    definition = re.search(r'resource "aws_ecs_task_definition" "task_render" \{(.*?)\n\}', text, re.S).group(1)  # type: ignore[union-attr]
    roles = re.findall(r"(?:execution|task)_role_arn\s+= (aws_iam_role\.\w+\.arn)", definition)
    assert roles == ["aws_iam_role.ecs_execution.arn", "aws_iam_role.ecs_task.arn"]
    # Every role the task definition passes is covered by iam:PassRole.
    passed = next(s for s in _statements(text, 'resource "aws_iam_role_policy" "wf_ship_tasks"') if s["Action"] == ["iam:PassRole"])
    assert passed["Resource"] == [asl.Ref(role) for role in roles]
    # Log group with retention variable, and awslogs configuration referencing it.
    assert re.search(r'resource "aws_cloudwatch_log_group" "task_render" \{.*?retention_in_days = var\.workflow_log_retention_days', text, re.S)
    assert re.search(r"awslogs-group\s+= aws_cloudwatch_log_group\.task_render\.name", text)
    fragment = FRAGMENT.read_text(encoding="utf-8")
    for token in ("aws_ecs_cluster.main", "aws_iam_role.ecs_execution", "aws_iam_role.ecs_task", "`awslogs`", "`observability.log_retention`", "compute-owned"):
        assert token in fragment, token
    # The compute dependency is described in the fragment; the compute trigger itself belongs to the compute PR.
    assert "needs the compute fragment to run too" in fragment


def test_workflow_retention_default_follows_clarify_default() -> None:
    assert 'default     = 30' in (GOLDEN_TF / "workflow.tf").read_text(encoding="utf-8").split('variable "workflow_tracing_enabled"')[0]
    example = (GOLDEN_TF / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert re.search(r"^workflow_log_retention_days\s+= 30$", example, re.M)


def test_workflow_cutover_does_not_promise_unqualified_parallel_runs() -> None:
    docs = (SKILL_ROOT / "references/phases/generate/generate-artifacts-docs.md").read_text(encoding="utf-8")
    guide = (EXPECTED / "generated/MIGRATION_GUIDE.md").read_text(encoding="utf-8")
    assert "side-effect-free verification executions" in docs and "`cutover.downtime_window`" in docs
    assert "side-effect-free verification executions" in guide and "Run a few executions in parallel" not in guide
    assert "\n### Workflow cutover\n" in guide and "\n## Workflow cutover\n" not in guide
