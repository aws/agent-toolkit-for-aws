"""Executable rubric and deterministic renderer for Render Workflow generation.

The rubric is deliberately narrow. A Workflow is generated only when its Design
``aws_config`` declares every semantic below and every declared semantic is in
the supported set. Anything else returns reasons and no Terraform (fail closed).
The Terraform text produced here is the golden ``workflow.tf`` content; contract
tests parse the ASL back out of it and compare with the source mapping.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

ORCHESTRATOR = "AWS Step Functions Standard"
LAMBDA_TARGET = "AWS Lambda"
ECS_TARGET = "ECS on Fargate task"
WORKFLOW_KIND = "render.workflow"
TASK_KIND = "render.workflow_task"
SOURCE_ONLY_KINDS = ("render.workflow_version", "render.task_run", "render.task_attempt")

# aws_config keys whose truthy value has no provable ASL mapping.
UNSUPPORTED_KEYS = {
    "branching": "task branching lives in customer code and is not captured",
    "dynamic_graph": "runtime-determined subtask calls are not captured",
    "approvals": "approval UX and identity are not provable from the source",
    "trigger": "Render starts runs through its API or SDK; no Step Functions trigger is tested",
    "schedule": "Render starts runs through its API or SDK; no Step Functions schedule is tested",
    "idempotency_key": "Step Functions has no matching execution-level control",
    "concurrency": "Step Functions has no matching execution-level control",
    "cancellation": "Step Functions has no matching execution-level control",
}
LAMBDA_MAX_SECONDS = 900
TIMEOUT_MIN_SECONDS, TIMEOUT_MAX_SECONDS = 30, 86400
MAP_MAX_CONCURRENCY = 40
RETRY_ERRORS = ["States.TaskFailed", "States.Timeout"]
CALLBACK_RETRY_ERRORS = ["States.TaskFailed"]
ECS_RULE = "StepFunctionsGetEventsForECSTaskRule"
ECS_INPUT_ENV = "STEP_INPUT"
LOG_RETENTION_VALUES = [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653]


@dataclass(frozen=True)
class Ref:
    """Raw Terraform expression (reference, interpolated string, type keyword)."""

    expr: str


@dataclass(frozen=True)
class Task:
    source_id: str
    res: str
    state: str
    service: str  # "lambda" or "ecs"
    timeout: int
    retry: dict[str, Any]
    fan_out: int | None = None
    compensation: str | None = None
    callback: bool = False


@dataclass(frozen=True)
class Spec:
    source_id: str
    res: str
    order: tuple[str, ...]
    tasks: dict[str, Task] = field(default_factory=dict)
    callback_timeout: int | None = None

    def task(self, source_id: str) -> Task:
        return self.tasks[source_id]

    def uses_ecs(self) -> bool:
        return any(task.service == "ecs" for task in self.tasks.values())


@dataclass(frozen=True)
class Plan:
    specs: tuple[Spec, ...]
    reasons: dict[str, str]  # source id -> "<key>: <explanation>" for every unsupported row

    def generated_ids(self) -> set[str]:
        ids: set[str] = set()
        for spec in self.specs:
            ids.add(spec.source_id)
            ids.update(spec.tasks)
        return ids


def res_name(source_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", source_id.lower()).strip("_")


def state_name(source_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", source_id).strip("_")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _timeout_seconds(config: dict[str, Any]) -> tuple[int | None, str | None]:
    has_s, has_m = "timeout_seconds" in config, "timeout_minutes" in config
    if has_s == has_m:
        return None, "timeout_missing: declare exactly one of timeout_seconds or timeout_minutes (Render defaults are not assumed)"
    value = config["timeout_seconds"] if has_s else config["timeout_minutes"]
    if not _is_int(value):
        return None, "timeout_invalid: timeout must be an integer"
    seconds = value if has_s else value * 60
    if not TIMEOUT_MIN_SECONDS <= seconds <= TIMEOUT_MAX_SECONDS:
        return None, "timeout_out_of_bounds: Render allows 30 to 86400 seconds per attempt"
    return seconds, None


def _retry(config: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    retry = config.get("retry")
    if not isinstance(retry, dict):
        return None, "retry_missing: Render applies an undocumented default retry when retry is omitted, so retry must be declared"
    if set(retry) != {"max_retries", "wait_duration_ms", "backoff_scaling"}:
        return None, "retry_invalid: retry must declare exactly max_retries, wait_duration_ms, backoff_scaling"
    retries, wait, scaling = retry["max_retries"], retry["wait_duration_ms"], retry["backoff_scaling"]
    if not (_is_int(retries) and retries >= 1):
        return None, "retry_invalid: max_retries must be an integer of at least 1"
    if not (_is_int(wait) and wait >= 1000 and wait % 1000 == 0):
        return None, "retry_invalid: wait_duration_ms must be a whole number of seconds (multiple of 1000)"
    if not (_is_number(scaling) and scaling >= 1.0):
        return None, "retry_invalid: backoff_scaling must be at least 1.0"
    return {"max_retries": retries, "wait_duration_ms": wait, "backoff_scaling": float(scaling)}, None


def _task_service(aws_service: str) -> str | None:
    return {LAMBDA_TARGET: "lambda", ECS_TARGET: "ecs"}.get(aws_service)


def _truthy_unsupported(config: dict[str, Any]) -> str | None:
    for key, why in UNSUPPORTED_KEYS.items():
        if config.get(key):
            return f"{key}_unsupported: {why}"
    return None


def _build_task(task_id: str, config: dict[str, Any], service: str, *, callback: bool) -> tuple[Task | None, str | None]:
    reason = _truthy_unsupported(config)
    if reason:
        return None, reason
    timeout, reason = _timeout_seconds(config)
    if reason:
        return None, reason
    assert timeout is not None
    if service == "lambda" and timeout > LAMBDA_MAX_SECONDS:
        return None, "lambda_timeout_over_900: Lambda cannot run longer than 900 seconds; the task target must be reconsidered in Design"
    retry, reason = _retry(config)
    if reason:
        return None, reason
    assert retry is not None
    fan_out = None
    if "fan_out" in config:
        fan = config["fan_out"]
        value = fan.get("max_concurrency") if isinstance(fan, dict) and set(fan) == {"max_concurrency"} else None
        if not (_is_int(value) and 1 <= value <= MAP_MAX_CONCURRENCY):
            return None, "fan_out_invalid: fan_out must be {max_concurrency: 1..40} (inline Map limit)"
        fan_out = value
    compensation = config.get("compensation_task")
    if compensation is not None and not (isinstance(compensation, str) and compensation):
        return None, "compensation_invalid: compensation_task must be a task mapping ID"
    if callback and service != "lambda":
        return None, "callback_ecs_unsupported: task-token callbacks are only contract-tested for Lambda tasks"
    if callback and fan_out is not None:
        return None, "callback_fan_out_unsupported: combining a task-token callback with Map fan-out is not contract-tested"
    return Task(task_id, res_name(task_id), state_name(task_id), service, timeout, retry, fan_out, compensation, callback), None


def classify(design: dict[str, Any]) -> Plan:
    """Return supported Workflow specs and a reason for every other Workflow or task row."""
    mappings = {row["source_resource_id"]: row for row in design["mappings"]}
    reasons: dict[str, str] = {}
    specs: list[Spec] = []
    owned: dict[str, str] = {}
    workflows = [row for row in design["mappings"] if row["render_kind"] == WORKFLOW_KIND]
    for workflow in workflows:
        wid = workflow["source_resource_id"]
        config = workflow["aws_config"]
        members: set[str] = set()
        reason = None
        order = config.get("task_order")
        if isinstance(order, list) and all(isinstance(item, str) for item in order):
            members.update(item for item in order if item in mappings)
            for item in order:
                comp_id = mappings.get(item, {}).get("aws_config", {}).get("compensation_task")
                if isinstance(comp_id, str) and comp_id in mappings:
                    members.add(comp_id)
        if workflow["aws_service"] != ORCHESTRATOR:
            reason = "orchestrator_unsupported: only Step Functions Standard has contract tests; Lambda durable functions and Express are not generated"
        elif config.get("history") != "auditable":
            reason = "history_not_auditable: retained run history is only proven for history=auditable"
        else:
            reason = _truthy_unsupported(config)
        callbacks = config.get("callbacks") is True
        callback_timeout = config.get("callback_timeout_seconds")
        if reason is None and "callbacks" in config and not isinstance(config["callbacks"], bool):
            reason = "callbacks_invalid: callbacks must be true or false"
        if reason is None and callbacks and not (_is_int(callback_timeout) and 1 <= callback_timeout <= TIMEOUT_MAX_SECONDS):
            reason = "callback_timeout_missing: callbacks require callback_timeout_seconds between 1 and 86400"
        if reason is None and not callbacks and "callback_timeout_seconds" in config:
            reason = "callback_timeout_without_callbacks: callback_timeout_seconds requires callbacks=true"
        if reason is None and not (isinstance(order, list) and order and all(isinstance(item, str) for item in order) and len(set(order)) == len(order)):
            reason = "task_order_missing: task_order must list at least one unique task mapping ID"
        tasks: dict[str, Task] = {}
        if reason is None:
            assert isinstance(order, list)
            pending = list(order)
            compensation_ids: list[str] = []
            for task_id in order:
                row = mappings.get(task_id)
                if row is None or row["render_kind"] != TASK_KIND:
                    reason = f"task_order_unmapped_task: {task_id} is not a mapped render.workflow_task"
                    break
            while reason is None and pending:
                task_id = pending.pop(0)
                row = mappings[task_id]
                members.add(task_id)
                service = _task_service(row["aws_service"])
                if service is None:
                    reason = f"task_target_unsupported: {task_id} targets {row['aws_service']}; only AWS Lambda and ECS on Fargate task have contract tests"
                    break
                in_order = task_id in order
                task, why = _build_task(task_id, row["aws_config"], service, callback=callbacks and in_order)
                if why:
                    reason = f"{why} ({task_id})"
                    break
                assert task is not None
                if task.callback and callback_timeout < task.timeout:
                    reason = f"callback_timeout_below_task_timeout: callback_timeout_seconds must be at least the task timeout ({task_id})"
                    break
                tasks[task_id] = task
                if task.compensation:
                    comp = mappings.get(task.compensation)
                    if comp is None or comp["render_kind"] != TASK_KIND or task.compensation in order:
                        reason = f"compensation_invalid: {task_id} names {task.compensation}, which is not a mapped task outside task_order"
                        break
                    if task.compensation not in compensation_ids:
                        compensation_ids.append(task.compensation)
                        pending.append(task.compensation)
                        members.add(task.compensation)
            if reason is None:
                for comp_id in compensation_ids:
                    comp_task = tasks[comp_id]
                    if comp_task.fan_out is not None or comp_task.compensation:
                        reason = f"compensation_invalid: compensation task {comp_id} must be a plain task without fan_out or its own compensation"
                        break
            if reason is None:
                for member in tasks:
                    if member in owned:
                        reason = f"task_shared: {member} is already owned by Workflow {owned[member]}"
                        break
        if reason is None:
            for member in tasks:
                owned[member] = wid
            specs.append(Spec(wid, res_name(wid), tuple(order), tasks, callback_timeout if callbacks else None))
        else:
            reasons[wid] = reason
            for member in members:
                reasons.setdefault(member, f"workflow_unsupported: parent Workflow {wid} is unsupported ({reason.split(':', 1)[0]})")
    for row in design["mappings"]:
        sid = row["source_resource_id"]
        if row["render_kind"] == TASK_KIND and sid not in owned and sid not in reasons:
            reasons[sid] = "task_orphan: task is not listed in any supported Workflow task_order or compensation_task"
    # A task unsupported through a failed Workflow must not remain generated.
    supported = []
    for spec in specs:
        if any(member in reasons for member in spec.tasks):
            reasons[spec.source_id] = "workflow_unsupported: a task of this Workflow is unsupported"
            for member in spec.tasks:
                reasons.setdefault(member, f"workflow_unsupported: parent Workflow {spec.source_id} is unsupported")
        else:
            supported.append(spec)
    for sid in [row["source_resource_id"] for row in design["mappings"] if row["render_kind"] in SOURCE_ONLY_KINDS]:
        reasons[sid] = "source_record_not_importable: Render run history is source evidence with no importable AWS equivalent"
    return Plan(tuple(supported), reasons)


REASON_KEYS = (
    "orchestrator_unsupported", "history_not_auditable", "callbacks_invalid", "callback_timeout_missing",
    "callback_timeout_without_callbacks", "callback_timeout_below_task_timeout", "callback_ecs_unsupported",
    "callback_fan_out_unsupported", "task_order_missing", "task_order_unmapped_task", "task_target_unsupported",
    "task_shared", "task_orphan", "timeout_missing", "timeout_invalid", "timeout_out_of_bounds",
    "lambda_timeout_over_900", "retry_missing", "retry_invalid", "fan_out_invalid", "compensation_invalid",
    "workflow_unsupported", "source_record_not_importable",
    *(f"{key}_unsupported" for key in UNSUPPORTED_KEYS),
)


def warnings_for(plan: Plan) -> list[dict[str, Any]]:
    """One ``conditional_workflow_generation_unsupported`` warning per unsupported Workflow row."""
    return [
        {"code": "conditional_workflow_generation_unsupported", "subject": sid, "detail": reason, "blocking": False}
        for sid, reason in sorted(plan.reasons.items(), key=lambda item: item[0].encode())
        if not reason.startswith(("workflow_unsupported", "source_record_not_importable"))
    ]


def workflow_specs(design: dict[str, Any]) -> list[Spec]:
    return list(classify(design).specs)


# ---------------------------------------------------------------------------
# ASL
# ---------------------------------------------------------------------------

def _retrier(retry: dict[str, Any], callback: bool) -> list[dict[str, Any]]:
    return [{
        "ErrorEquals": list(CALLBACK_RETRY_ERRORS if callback else RETRY_ERRORS),
        "IntervalSeconds": retry["wait_duration_ms"] // 1000,
        "MaxAttempts": retry["max_retries"],
        "BackoffRate": retry["backoff_scaling"],
    }]


def _task_state(task: Task, spec: Spec) -> dict[str, Any]:
    if task.service == "lambda":
        function = Ref(f"aws_lambda_function.{task.res}.arn")
        if task.callback:
            state: dict[str, Any] = {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                "Parameters": {"FunctionName": function, "Payload": {"input.$": "$", "TaskToken.$": "$$.Task.Token"}},
                "TimeoutSeconds": spec.callback_timeout,
            }
        else:
            state = {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {"FunctionName": function, "Payload.$": "$"},
                "OutputPath": "$.Payload",
                "TimeoutSeconds": task.timeout,
            }
    else:
        state = {
            "Type": "Task",
            "Resource": "arn:aws:states:::ecs:runTask.sync",
            "Parameters": {
                "LaunchType": "FARGATE",
                "Cluster": Ref("aws_ecs_cluster.main.arn"),
                "TaskDefinition": Ref(f"aws_ecs_task_definition.{task.res}.arn"),
                "NetworkConfiguration": {"AwsvpcConfiguration": {
                    "Subnets": Ref("aws_subnet.private[*].id"),
                    "SecurityGroups": [Ref("aws_security_group.worker.id")],
                    "AssignPublicIp": "DISABLED",
                }},
                # The state input (or the Map item) reaches the container as one JSON string.
                "Overrides": {"ContainerOverrides": [{
                    "Name": task.state,
                    "Environment": [{"Name": ECS_INPUT_ENV, "Value.$": "States.JsonToString($)"}],
                }]},
            },
            # runTask.sync returns the task description, not container output, so it is discarded and the
            # state input passes through. A non-null ResultPath fails on non-object Map items.
            "ResultPath": None,
            "TimeoutSeconds": task.timeout,
        }
    state["Retry"] = _retrier(task.retry, task.callback)
    return state


def build_asl(spec: Spec) -> dict[str, Any]:
    states: dict[str, Any] = {}
    order = [spec.task(task_id) for task_id in spec.order]
    compensated = False
    for index, task in enumerate(order):
        state = _task_state(task, spec)
        if task.fan_out is not None:
            inner = {"Type": "Task", **{k: v for k, v in state.items() if k != "Type"}}
            inner["End"] = True
            state = {
                "Type": "Map",
                "ItemsPath": "$.items",
                "MaxConcurrency": task.fan_out,
                "ItemProcessor": {"ProcessorConfig": {"Mode": "INLINE"}, "StartAt": task.state, "States": {task.state: inner}},
            }
        if task.compensation:
            state["Catch"] = [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": f"Compensate_{task.state}"}]
            compensated = True
        if index + 1 < len(order):
            state["Next"] = order[index + 1].state
        else:
            state["End"] = True
        states[task.state] = state
    if compensated:
        for task in order:
            if task.compensation:
                comp = spec.task(task.compensation)
                comp_state = _task_state(comp, spec)
                comp_state["Next"] = "CompensatedFailure"
                states[f"Compensate_{task.state}"] = comp_state
        states["CompensatedFailure"] = {"Type": "Fail", "Error": "CompensatedFailure", "Cause": "A task failed and its compensation task ran."}
    return {"Comment": f"Generated from Render Workflow {spec.source_id}", "StartAt": order[0].state, "States": states}


# ---------------------------------------------------------------------------
# HCL emission (already terraform-fmt shaped)
# ---------------------------------------------------------------------------

_BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _hcl_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")


def _hcl_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else _hcl_string(key)


def _scalar(value: Any) -> str | None:
    if isinstance(value, Ref):
        return value.expr
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _hcl_string(value)
    return None


def _entries(items: list[tuple[str, str]], indent: int) -> list[str]:
    """Render key/value pairs, aligning '=' across runs of single-line values."""
    pad = " " * indent
    lines: list[str] = []
    group: list[tuple[str, str]] = []

    def flush() -> None:
        width = max((len(key) for key, _ in group), default=0)
        lines.extend(f"{pad}{key.ljust(width)} = {value}" for key, value in group)
        group.clear()

    for key, value in items:
        if "\n" in value:
            flush()
            lines.append(f"{pad}{key} = {value}")
        else:
            group.append((key, value))
    flush()
    return lines


def hcl_value(value: Any, indent: int) -> str:
    scalar = _scalar(value)
    if scalar is not None:
        return scalar
    pad, inner = " " * indent, " " * (indent + 2)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if all(_scalar(item) is not None for item in value):
            return "[" + ", ".join(_scalar(item) or "" for item in value) + "]"
        return "[\n" + "".join(f"{inner}{hcl_value(item, indent + 2)},\n" for item in value) + f"{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [(_hcl_key(key), hcl_value(item, indent + 2)) for key, item in value.items()]
        return "{\n" + "\n".join(_entries(items, indent + 2)) + f"\n{pad}}}"
    raise TypeError(f"unsupported HCL value {type(value)!r}")


Body = list  # entries: ("a", key, value) | ("b", header, Body)


def _body(entries: Body, indent: int) -> list[str]:
    lines: list[str] = []
    group: list[tuple[str, str]] = []
    for entry in entries:
        if entry[0] == "a":
            group.append((entry[1], hcl_value(entry[2], indent)))
            continue
        lines.extend(_entries(group, indent))
        group = []
        lines.append(f"{' ' * indent}{entry[1]} {{")
        lines.extend(_body(entry[2], indent + 2))
        lines.append(f"{' ' * indent}}}")
    lines.extend(_entries(group, indent))
    return lines


def block(header: str, entries: Body) -> str:
    return "\n".join([f"{header} {{", *_body(entries, 2), "}"]) + "\n"


def A(key: str, value: Any) -> tuple[str, str, Any]:
    return ("a", key, value)


def B(header: str, entries: Body) -> tuple[str, str, Body]:
    return ("b", header, entries)


def S(expr: str) -> Ref:
    return Ref(expr)


def _tags(source_id: str) -> tuple[str, str, Any]:
    return A("tags", {"SourceResourceId": source_id})


def _assume(service: str) -> Any:
    return S("jsonencode(" + hcl_value({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}]}, 2) + ")")


def _variable(name: str, description: str, type_: str, condition: str, message: str) -> str:
    return block(f'variable "{name}"', [
        A("description", description),
        A("type", S(type_)),
        B("validation", [A("condition", S(condition)), A("error_message", message)]),
    ])


def _shared_variables() -> list[str]:
    retention = "[" + ", ".join(str(v) for v in LOG_RETENTION_VALUES) + "]"
    return [
        block('variable "workflow_log_retention_days"', [
            A("description", "CloudWatch retention in days for Workflow execution logs and task logs."),
            A("type", S("number")),
            A("default", 30),
            B("validation", [
                A("condition", S(f"contains({retention}, var.workflow_log_retention_days)")),
                A("error_message", "workflow_log_retention_days must be a CloudWatch Logs retention value."),
            ]),
        ]),
        block('variable "workflow_tracing_enabled"', [
            A("description", "Enable AWS X-Ray tracing on the state machines."),
            A("type", S("bool")),
            A("default", False),
        ]),
        block('variable "workflow_alarm_actions"', [
            A("description", "ARNs notified when a Workflow alarm changes state; empty keeps alarms visible in CloudWatch only."),
            A("type", S("list(string)")),
            A("default", []),
        ]),
    ]


def _lambda_task(task: Task) -> list[str]:
    r = n = task.res
    out = [
        _variable(f"{r}_package_path", f"Path to the reviewed deployment package for Render source resource {task.source_id}; this pack contains no function source.", "string",
                  f"length(var.{r}_package_path) > 0", f"{r}_package_path must be a non-empty path."),
        _variable(f"{r}_runtime", f"Lambda runtime for Render source resource {task.source_id}.", "string",
                  f"length(var.{r}_runtime) > 0", f"{r}_runtime must be a non-empty Lambda runtime identifier."),
        _variable(f"{r}_handler", f"Lambda handler for Render source resource {task.source_id}.", "string",
                  f"length(var.{r}_handler) > 0", f"{r}_handler must be a non-empty handler."),
        _variable(f"{r}_memory_mb", f"Lambda memory in MB for Render source resource {task.source_id}; Render compute plans are not converted.", "number",
                  f"var.{r}_memory_mb >= 128 && var.{r}_memory_mb <= 10240 && floor(var.{r}_memory_mb) == var.{r}_memory_mb", f"{r}_memory_mb must be a whole number from 128 to 10240."),
        block(f'resource "aws_cloudwatch_log_group" "{n}"', [
            A("name", S(f'"/aws/lambda/${{local.name_prefix}}-{task.source_id}"')),
            A("retention_in_days", S("var.workflow_log_retention_days")),
            _tags(task.source_id),
        ]),
        block(f'resource "aws_iam_role" "{n}"', [
            A("name", S(f'"${{local.name_prefix}}-{task.source_id}"')),
            A("assume_role_policy", _assume("lambda.amazonaws.com")),
            _tags(task.source_id),
        ]),
        block(f'resource "aws_iam_role_policy" "{n}"', [
            A("name", "write-own-logs"),
            A("role", S(f"aws_iam_role.{n}.id")),
            A("policy", S("jsonencode(" + hcl_value({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": [Ref(f'"${{aws_cloudwatch_log_group.{n}.arn}}:*"')]}],
            }, 2) + ")")),
        ]),
        block(f'resource "aws_lambda_function" "{n}"', [
            A("function_name", S(f'"${{local.name_prefix}}-{task.source_id}"')),
            A("role", S(f"aws_iam_role.{n}.arn")),
            A("runtime", S(f"var.{r}_runtime")),
            A("handler", S(f"var.{r}_handler")),
            A("filename", S(f"var.{r}_package_path")),
            A("source_code_hash", S(f"filebase64sha256(var.{r}_package_path)")),
            A("memory_size", S(f"var.{r}_memory_mb")),
            A("timeout", task.timeout),
            B("logging_config", [A("log_format", "Text"), A("log_group", S(f"aws_cloudwatch_log_group.{n}.name"))]),
            _tags(task.source_id),
            A("depends_on", S(f"[aws_iam_role_policy.{n}]")),
        ]),
    ]
    return out


def _ecs_task(task: Task) -> list[str]:
    r = task.res
    digest = r"^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
    container = [{
        "name": task.state,
        "image": S(f"var.{r}_image"),
        "essential": True,
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": S(f"aws_cloudwatch_log_group.{r}.name"),
                "awslogs-region": S("var.aws_region"),
                "awslogs-stream-prefix": task.state,
            },
        },
    }]
    return [
        _variable(f"{r}_image", f"Immutable ECR image for Render source resource {task.source_id}.", "string",
                  f'can(regex("{digest}", var.{r}_image))', f"{r}_image must be an immutable ECR digest reference."),
        _variable(f"{r}_cpu", f"Fargate CPU units for Render source resource {task.source_id}; Render compute plans are not converted.", "number",
                  f"contains([256, 512, 1024, 2048, 4096, 8192, 16384], var.{r}_cpu)", f"{r}_cpu must be a valid Fargate CPU value."),
        _variable(f"{r}_memory_mb", f"Fargate memory in MB for Render source resource {task.source_id}.", "number",
                  f"var.{r}_memory_mb >= 512 && floor(var.{r}_memory_mb) == var.{r}_memory_mb", f"{r}_memory_mb must be a whole number of at least 512."),
        block(f'resource "aws_cloudwatch_log_group" "{r}"', [
            A("name", S(f'"/aws/ecs/${{local.name_prefix}}-{task.source_id}"')),
            A("retention_in_days", S("var.workflow_log_retention_days")),
            _tags(task.source_id),
        ]),
        block(f'resource "aws_ecs_task_definition" "{r}"', [
            A("family", S(f'"${{local.name_prefix}}-{task.source_id}"')),
            A("network_mode", "awsvpc"),
            A("requires_compatibilities", ["FARGATE"]),
            A("cpu", S(f"var.{r}_cpu")),
            A("memory", S(f"var.{r}_memory_mb")),
            A("execution_role_arn", S("aws_iam_role.ecs_execution.arn")),
            A("task_role_arn", S("aws_iam_role.ecs_task.arn")),
            A("container_definitions", S("jsonencode(" + hcl_value(container, 2) + ")")),
            _tags(task.source_id),
        ]),
    ]


def _workflow(spec: Spec) -> list[str]:
    r = spec.res
    sid = spec.source_id
    tasks = list(spec.tasks.values())
    lambdas = [t for t in tasks if t.service == "lambda"]
    ecs = [t for t in tasks if t.service == "ecs"]
    out: list[str] = []
    for task in tasks:
        out.extend(_lambda_task(task) if task.service == "lambda" else _ecs_task(task))
    out.append(block(f'resource "aws_cloudwatch_log_group" "{r}"', [
        A("name", S(f'"/aws/vendedlogs/states/${{local.name_prefix}}-{sid}"')),
        A("retention_in_days", S("var.workflow_log_retention_days")),
        _tags(sid),
    ]))
    out.append(block(f'resource "aws_iam_role" "{r}"', [
        A("name", S(f'"${{local.name_prefix}}-{sid}"')),
        A("assume_role_policy", _assume("states.amazonaws.com")),
        _tags(sid),
    ]))
    statements: list[dict[str, Any]] = []
    if lambdas:
        statements.append({"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [Ref(f"aws_lambda_function.{t.res}.arn") for t in lambdas]})
    if ecs:
        statements.append({"Effect": "Allow", "Action": ["ecs:RunTask"], "Resource": [Ref(f"aws_ecs_task_definition.{t.res}.arn") for t in ecs]})
        statements.append({
            "Effect": "Allow",
            "Action": ["iam:PassRole"],
            "Resource": [Ref("aws_iam_role.ecs_execution.arn"), Ref("aws_iam_role.ecs_task.arn")],
            "Condition": {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
        })
        statements.append({
            "Effect": "Allow",
            "Action": ["events:PutTargets", "events:PutRule", "events:DescribeRule"],
            "Resource": [Ref(f'"arn:aws:events:${{var.aws_region}}:${{data.aws_caller_identity.{r}.account_id}}:rule/{ECS_RULE}"')],
        })
    if ecs:
        out.append(block(f'data "aws_caller_identity" "{r}"', []))
    out.append(block(f'resource "aws_iam_role_policy" "{r}_tasks"', [
        A("name", "invoke-declared-tasks"),
        A("role", S(f"aws_iam_role.{r}.id")),
        A("policy", S("jsonencode(" + hcl_value({"Version": "2012-10-17", "Statement": statements}, 2) + ")")),
    ]))
    doc: Body = [
        B("statement", [
            A("sid", "DeliverExecutionLogs"),
            A("actions", ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]),
            A("resources", ["*"]),
        ]),
        B('dynamic "statement"', [
            A("for_each", S("var.workflow_tracing_enabled ? [1] : []")),
            B("content", [
                A("sid", "WriteXRayTraces"),
                A("actions", ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]),
                A("resources", ["*"]),
            ]),
        ]),
    ]
    if ecs:
        doc.append(B("statement", [
            A("sid", "ManageStartedEcsTasks"),
            A("actions", ["ecs:StopTask", "ecs:DescribeTasks"]),
            A("resources", ["*"]),
        ]))
    out.append(block(f'data "aws_iam_policy_document" "{r}_service"', doc))
    out.append(block(f'resource "aws_iam_role_policy" "{r}_service"', [
        A("name", "service-integration-requirements"),
        A("role", S(f"aws_iam_role.{r}.id")),
        A("policy", S(f"data.aws_iam_policy_document.{r}_service.json")),
    ]))
    out.append(block(f'resource "aws_sfn_state_machine" "{r}"', [
        A("name", S(f'"${{local.name_prefix}}-{sid}"')),
        A("role_arn", S(f"aws_iam_role.{r}.arn")),
        A("type", "STANDARD"),
        A("definition", S("jsonencode(" + hcl_value(build_asl(spec), 2) + ")")),
        B("logging_configuration", [
            A("log_destination", S(f'"${{aws_cloudwatch_log_group.{r}.arn}}:*"')),
            A("include_execution_data", False),
            A("level", "ALL"),
        ]),
        B("tracing_configuration", [A("enabled", S("var.workflow_tracing_enabled"))]),
        _tags(sid),
        A("depends_on", S(f"[aws_iam_role_policy.{r}_tasks, aws_iam_role_policy.{r}_service]")),
    ]))
    for metric in ("ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"):
        out.append(block(f'resource "aws_cloudwatch_metric_alarm" "{r}_{metric.lower()}"', [
            A("alarm_name", S(f'"${{local.name_prefix}}-{sid}-{metric}"')),
            A("namespace", "AWS/States"),
            A("metric_name", metric),
            A("dimensions", {"StateMachineArn": Ref(f"aws_sfn_state_machine.{r}.arn")}),
            A("statistic", "Sum"),
            A("period", 300),
            A("evaluation_periods", 1),
            A("threshold", 0),
            A("comparison_operator", "GreaterThanThreshold"),
            A("treat_missing_data", "notBreaching"),
            A("alarm_actions", S("var.workflow_alarm_actions")),
            _tags(sid),
        ]))
    return out


def render_workflow_tf(specs: list[Spec] | tuple[Spec, ...]) -> str:
    parts: list[str] = []
    parts.extend(_shared_variables())
    for spec in specs:
        parts.extend(_workflow(spec))
    return "".join(parts)


def tfvars_example_lines(specs: list[Spec] | tuple[Spec, ...]) -> list[str]:
    """Obviously synthetic placeholder values for terraform.tfvars.example."""
    pairs: list[tuple[str, str]] = []
    for spec in specs:
        for task in spec.tasks.values():
            r = task.res
            if task.service == "lambda":
                pairs += [(f"{r}_package_path", '"build/replace-with-reviewed-package.zip"'), (f"{r}_runtime", '"replace-with-runtime"'), (f"{r}_handler", '"replace-with-handler"'), (f"{r}_memory_mb", "128")]
            else:
                pairs += [(f"{r}_image", '"000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:' + "5" * 64 + '"'), (f"{r}_cpu", "256"), (f"{r}_memory_mb", "512")]
    return [f"{key} = {value}" for key, value in pairs]


# ---------------------------------------------------------------------------
# Parsing the jsonencode argument back out of generated Terraform
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<ref>[A-Za-z_][A-Za-z0-9_.\-]*(?:\[\*\])?(?:\.[A-Za-z0-9_]+)*)|(?P<punct>[{}\[\],=:]))')


def _tokens(text: str) -> list[tuple[str, str]]:
    pos, out = 0, []
    while True:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise ValueError(f"unparseable HCL near {text[pos:pos + 30]!r}")
            return out
        pos = m.end()
        kind = m.lastgroup
        assert kind
        out.append((kind, m.group(kind)))


def parse_hcl_literal(text: str) -> Any:
    tokens = _tokens(text)
    index = 0

    def peek() -> tuple[str, str] | None:
        return tokens[index] if index < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal index
        token = tokens[index]
        index += 1
        return token

    def value() -> Any:
        kind, raw = take()
        if kind == "str":
            return json.loads(raw.replace("$${", "${").replace("%%{", "%{")) if "${" not in raw.replace("$${", "") else Ref(raw)
        if kind == "num":
            return float(raw) if re.search(r"[.eE]", raw) else int(raw)
        if kind == "ref":
            if raw in ("true", "false"):
                return raw == "true"
            if raw == "null":
                return None
            return Ref(raw)
        if raw == "[":
            items = []
            while peek() != ("punct", "]"):
                items.append(value())
                if peek() == ("punct", ","):
                    take()
            take()
            return items
        if raw == "{":
            result: dict[str, Any] = {}
            while peek() != ("punct", "}"):
                key_kind, key_raw = take()
                key = json.loads(key_raw) if key_kind == "str" else key_raw
                sep = take()
                if sep[1] not in ("=", ":"):
                    raise ValueError("expected '=' in object")
                result[key] = value()
                if peek() == ("punct", ","):
                    take()
            take()
            return result
        raise ValueError(f"unexpected token {raw!r}")

    parsed = value()
    if index != len(tokens):
        raise ValueError("trailing tokens after literal")
    return parsed


def extract_jsonencode(text: str, anchor: str) -> str:
    """Return the balanced argument of the first ``jsonencode(`` after ``anchor``."""
    start = text.index(anchor)
    start = text.index("jsonencode(", start) + len("jsonencode(")
    depth, pos, in_string = 1, start, False
    while depth:
        char = text[pos]
        if in_string:
            if char == "\\":
                pos += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        pos += 1
    return text[start:pos - 1]


def generated_asl(text: str, resource_name: str) -> dict[str, Any]:
    """Parse the state machine definition for ``aws_sfn_state_machine.<resource_name>``."""
    return parse_hcl_literal(extract_jsonencode(text, f'resource "aws_sfn_state_machine" "{resource_name}"'))
