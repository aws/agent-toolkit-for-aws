#!/usr/bin/env python3
"""Deterministic project/evaluator naming for AgentCore deployments.

Naming limits, enforced before any CLI call is made:

- Project name (CloudFormation stack): ``{PascalTask}{UID4}``, pattern
  ``^[A-Za-z][A-Za-z0-9]{0,35}$`` (max 36 chars). Kept to 16 chars (12 + 4-char UID) to
  leave room for evaluator names. The random UID keeps concurrent runs off the same stack.
- Evaluator name: ``{framework}_{metric}``, pattern ``^[a-zA-Z][a-zA-Z0-9_]{0,47}$`` (max 48
  chars, AgentCore API limit). The CDK adds the project itself: Lambda function name
  ``{ProjectName}-eval-{EvaluatorName}`` (max 64 chars) and construct ID
  ``{ProjectName}_{EvaluatorName}`` (max 48 chars). The effective evaluator-name max is
  therefore ``min(48, 64 - 6 - len(project), 48 - len(project) - 1)``.

Usage (CLI):
    python3 names.py --task rag_pipeline --framework deepeval \\
        --metric faithfulness --metric bias --output names.json

Usage (library):
    from names import generate_names
    names = generate_names("rag_pipeline", "deepeval", ["faithfulness", "bias"])
"""

from __future__ import annotations

import argparse
import json
import re
import uuid

# The CDK names each Lambda "{ProjectName}-eval-{EvaluatorName}" (functionName in
# @aws/agentcore-cdk's AgentCoreEvaluator), so the overhead is 6 ("-eval-") + len(project).
CDK_NAME_OVERHEAD_FORMULA = lambda project_len: 6 + project_len  # noqa: E731
LAMBDA_NAME_LIMIT = 64
PROJECT_NAME_MAX = 36  # AgentCore API limit
PROJECT_TARGET_MAX = 16  # Keep short: 12 pascal + 4 UID, leaves evaluator room
EVALUATOR_NAME_MAX = 48  # AgentCore API limit
EVALUATOR_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,35}$")
UID_LEN = 4

# The validate_* helpers guard values interpolated into shell commands and file paths.
#: What classify.py emits: snake_case, plus the "_[geval]" suffix GEval keys carry.
SCORE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\[\]]{0,95}$")
#: A bare file name: no directory part, so it cannot resolve outside the handler dir.
HANDLER_FILE_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\[\]]{0,127}\.py$")
#: A token rather than an enum, so values such as "custom" or "mixed" are accepted.
FRAMEWORK_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _validate(value: object, pattern: re.Pattern, what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(
            f"invalid {what} {value!r}: must match {pattern.pattern}. It is interpolated into "
            "shell commands and file paths, so it is refused rather than escaped. Regenerate "
            "mapping.json / names.json / evaluators.json with the skill's scripts instead of "
            "editing them by hand."
        )
    return value


def validate_evaluator_name(name: object) -> str:
    return _validate(name, EVALUATOR_NAME_PATTERN, "evaluator name")


def validate_project_name(name: object) -> str:
    return _validate(name, PROJECT_NAME_PATTERN, "project name")


def validate_score_key(key: object) -> str:
    return _validate(key, SCORE_KEY_PATTERN, "score key")


def validate_handler_file(name: object) -> str:
    return _validate(name, HANDLER_FILE_PATTERN, "handler file name")


def validate_framework(framework: object) -> str:
    return _validate(framework, FRAMEWORK_PATTERN, "framework")


def lambda_function_name(project_name: str, evaluator_name: str) -> str:
    """The name the CDK gives an evaluator's Lambda, and so its /aws/lambda/ log group."""
    return f"{project_name}-eval-{evaluator_name}"


def _generate_uid() -> str:
    """Generate a 4-char uppercase hex UID."""
    return uuid.uuid4().hex[:UID_LEN].upper()


def pascal_case(text: str) -> str:
    """Convert text to PascalCase, dropping non-alphanumerics (rag-pipeline_v2 → RagPipelineV2)."""
    words = re.split(r"[^A-Za-z0-9]+", text)
    return "".join(w.capitalize() for w in words if w)


def sanitize_metric(metric: str) -> str:
    """Sanitize a metric key for use inside an evaluator name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", metric).strip("_")
    return cleaned or "metric"


def generate_project_name(task: str, uid: str | None = None) -> str:
    """Generate a CloudFormation-safe project name, ``{PascalTask}{UID4}``.

    The task part is cut to 12 chars so evaluator names fit the Lambda name limit.
    """
    if uid is None:
        uid = _generate_uid()
    if len(uid) != UID_LEN or not re.fullmatch(r"[A-Za-z0-9]+", uid):
        raise ValueError(f"uid must be {UID_LEN} alphanumeric chars, got {uid!r}")

    pascal = pascal_case(task)
    max_pascal = PROJECT_TARGET_MAX - UID_LEN
    pascal = pascal[:max_pascal]

    project = f"{pascal}{uid}"
    if not project or not project[0].isalpha():
        project = "P" + project

    project = project[:PROJECT_NAME_MAX]
    return project


def generate_evaluator_name(project_name: str, framework: str, metric: str) -> str:
    """Generate a ``{framework}_{metric}`` evaluator name, truncated to fit the naming limits.

    Raises ValueError if the result still violates a naming limit.
    """
    framework = re.sub(r"[^a-zA-Z0-9_]", "_", framework).strip("_")
    metric = sanitize_metric(metric)

    lambda_overhead = CDK_NAME_OVERHEAD_FORMULA(len(project_name))
    lambda_available = LAMBDA_NAME_LIMIT - lambda_overhead

    # CDK construct ID "{ProjectName}_{EvaluatorName}" is limited to 48 chars.
    cdk_construct_available = 48 - len(project_name) - 1

    max_name = min(lambda_available, EVALUATOR_NAME_MAX, cdk_construct_available)
    if max_name < 8:
        max_name = 12  # safety floor for very long project names

    name = f"{framework}_{metric}"
    name = name[:max_name].rstrip("_")

    if name and not name[0].isalpha():
        name = "e" + name[1:]

    if not EVALUATOR_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"generated evaluator name {name!r} violates {EVALUATOR_NAME_PATTERN.pattern}"
        )

    lambda_name = lambda_function_name(project_name, name)
    if len(lambda_name) > LAMBDA_NAME_LIMIT:
        raise ValueError(
            f"Lambda function name {lambda_name!r} ({len(lambda_name)} chars) "
            f"exceeds {LAMBDA_NAME_LIMIT}-char limit"
        )

    cdk_construct = f"{project_name}_{name}"
    if len(cdk_construct) > 48:
        raise ValueError(
            f"CDK construct ID {cdk_construct!r} ({len(cdk_construct)} chars) "
            f"exceeds 48-char CloudFormation limit"
        )
    return name


def generate_names(
    task: str,
    framework: str,
    metrics: list[str],
    uid: str | None = None,
) -> dict:
    """Generate the full naming manifest for a deployment.

    Shortens the project name as needed so the truncated evaluator names are all unique.

    Returns::

        {
          "project_name": "RagPipelineA1B2",
          "framework": "deepeval",
          "evaluators": {"faithfulness": "deepeval_faithfulness", ...}
        }
    """
    # names.json carries the framework to deployer.py and generate_client_script.py, which
    # write it into migration.sh and the generated script.
    validate_framework(framework)
    if uid is None:
        uid = _generate_uid()
    if len(uid) != UID_LEN or not re.fullmatch(r"[A-Za-z0-9]+", uid):
        raise ValueError(f"uid must be {UID_LEN} alphanumeric chars, got {uid!r}")

    pascal = pascal_case(task)
    max_start = min(PROJECT_TARGET_MAX - UID_LEN, len(pascal)) if pascal else 1

    # Try progressively shorter project names until evaluators don't collide.
    for max_pascal in range(max_start, 0, -1):
        project_name = f"{pascal[:max_pascal]}{uid}"
        if not project_name[0].isalpha():
            project_name = "P" + project_name

        evaluators = {}
        for metric in metrics:
            evaluators[metric] = generate_evaluator_name(project_name, framework, metric)

        if len(set(evaluators.values())) == len(evaluators):
            if max_pascal < max_start:
                print(
                    f"[names] auto-shortened project to {project_name!r} "
                    f"to resolve evaluator name collision"
                )
            return {
                "project_name": project_name,
                "framework": framework,
                "evaluators": evaluators,
            }

    raise ValueError(
        "evaluator name collision persists even with minimal (1-char) project "
        f"prefix — metric names are too similar to differentiate within the "
        f"{EVALUATOR_NAME_MAX}-char limit: {metrics}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", required=True, help="task/eval name (any format)")
    parser.add_argument(
        "--framework", required=True, help="source framework (deepeval, ragas, phoenix, strands)"
    )
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        default=None,
        help="metric score key (repeatable); prefer --mapping",
    )
    parser.add_argument(
        "--mapping",
        default=None,
        help="mapping.json from classify.py — read every metric key "
        "from it. Preferred over --metric because it avoids "
        "shell quoting and globbing damage to keys such as "
        "'helpfulness_[geval]'.",
    )
    parser.add_argument(
        "--uid", default=None, help=f"override the {UID_LEN}-char collision-avoidance suffix"
    )
    parser.add_argument("--output", default="names.json", help="output path")
    args = parser.parse_args()

    if args.mapping and args.metrics:
        parser.error("pass either --mapping or --metric, not both")
    if args.mapping:
        with open(args.mapping) as f:
            metrics = list(json.load(f))
    elif args.metrics:
        metrics = args.metrics
    else:
        parser.error("one of --mapping or --metric is required")

    try:
        names = generate_names(args.task, args.framework, metrics, uid=args.uid)
    except ValueError as exc:
        parser.error(str(exc))
    with open(args.output, "w") as f:
        json.dump(names, f, indent=2)
    print(f"[names] project: {names['project_name']}")
    for metric, name in names["evaluators"].items():
        print(f"[names]   {metric}: {name}")
    print(f"[names] written to {args.output}")


if __name__ == "__main__":
    main()
