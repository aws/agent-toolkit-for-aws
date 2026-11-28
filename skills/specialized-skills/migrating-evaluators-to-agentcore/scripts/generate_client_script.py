#!/usr/bin/env python3
"""Generate the ``{source}_agentcore.py`` deliverable script.

- ``--topology traces`` (pre-generated trace file): a complete script that evaluates every
  case through AgentCore and writes scores_after.json and summary.json to $ARTIFACTS_DIR.
  Set ``--field-map`` from the trace file's field names.
- ``--topology live`` (live agent): the same evaluation code plus two TODOs, ``_run_agent()``
  (the customer's agent, reproduced verbatim) and ``TEST_INPUTS``.

LLM-as-a-Judge evaluator IDs must be pasted into the generated ``EVALUATORS`` dict; Lambda
evaluator IDs resolve at runtime.

Usage:
    python3 generate_client_script.py --source-script comparison_eval.py \\
        --topology traces --traces-file traces/comparison_traces.json \\
        --field-map input=user_input,output=response,context=,reference=reference \\
        --mapping mapping.json --names names.json [--region us-east-1]
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import pprint
import re
import sys
from pathlib import Path

# Put scripts/ on sys.path so sibling modules resolve with static imports whether the package
# is installed or the skill directory is copied standalone. Dynamic import is not allowed.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from names import (  # noqa: E402
    validate_evaluator_name,
    validate_framework,
    validate_project_name,
)

#: --source-script is written into the generated script's docstring and names its output
#: file, so quotes, backslashes and newlines are refused rather than escaped.
_SOURCE_SCRIPT_PATTERN = re.compile(r"^[A-Za-z0-9_./-][A-Za-z0-9_. /-]{0,254}$")


# Emitted verbatim into the generated script by inspect.getsource(): keep it self-contained
# (hence the local import). It walks the AST instead of calling eval() because eval() with empty
# __builtins__ can still reach arbitrary code through attribute access.
def apply_metric_transform(expr: str, score: float) -> float:
    """Apply an arithmetic transform over ``score``, e.g. ``"score / 5"``.

    The expression is walked as an AST rather than passed to ``eval()``, so only numeric
    literals, ``score``, unary +/- and ``+ - * / // % **`` are accepted.
    """
    import ast

    def _walk(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"non-numeric constant in transform {expr!r}")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id != "score":
                raise ValueError(f"only 'score' may be referenced, got {node.id!r} in {expr!r}")
            return float(score)
        if isinstance(node, ast.UnaryOp):
            value = _walk(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            raise ValueError(f"unsupported unary operator in transform {expr!r}")
        if isinstance(node, ast.BinOp):
            left, right = _walk(node.left), _walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError(f"unsupported operator in transform {expr!r}")
        raise ValueError(
            f"unsupported expression element {type(node).__name__!r} in transform {expr!r}"
        )

    return _walk(ast.parse(expr, mode="eval").body)


_INLINE_BEGIN = "# === ADOT_INLINE_BEGIN ==="
_INLINE_END = "# === ADOT_INLINE_END ==="


def _adot_inline_source() -> str:
    """Extract the inline-able helper section from scripts/adot.py."""
    src = (Path(__file__).parent / "adot.py").read_text()
    start = src.index(_INLINE_BEGIN) + len(_INLINE_BEGIN)
    end = src.index(_INLINE_END)
    return src[start:end].strip("\n")


_HEADER_TEMPLATE = '''\
"""AgentCore migration of {source_script}.

Evaluates via AgentCore managed evaluation instead of the local {framework}
library. Self-sufficient: depends only on bedrock_agentcore + stdlib{agent_dep_note}.

Outputs (to $ARTIFACTS_DIR, default the current working directory):
- scores_after.json  — per-case and mean scores, keys matching scores_before.json
- summary.json       — migration metadata (evaluator IDs, divergence)
- evaluation_requests.jsonl — every evaluate() request sent (evaluator ID, input,
  ADOT documents), so the scores can be recomputed against the deployed evaluators
"""
import json
import os
import sys
import traceback
from pathlib import Path

import boto3
from botocore.config import Config
from bedrock_agentcore.evaluation import EvaluationClient

REGION = {region!r}
# Defaults to the working directory, where Step 0 writes scores_before.json; set
# ARTIFACTS_DIR to read and write the session artifacts somewhere else.
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "."))
WORKSPACE_DIR = ARTIFACTS_DIR / "workspace"

# Metric key → deployment info. Keys are aligned with scores_before.json —
# do NOT rename them; the comparison that checks this migration preserved the
# original scores is BY KEY.
# name_fragment is PROJECT-SCOPED ("{{project}}_{{evaluator}}") — bare evaluator
# names match stale evaluators from other runs and concurrent deployments.
EVALUATORS = {evaluators_literal}

# Evaluators whose handler recovers a list context from the JSON array the ADOT documents
# carry: the generated DeepEval and RAGAS handlers. They get the chunk list, because
# rank-aware metrics (ContextualPrecision, LLMContextPrecision and friends) score
# differently on one joined blob; every other evaluator gets the chunks joined into one
# string. Derived per evaluator from mapping.json, so a task that mixes frameworks still
# gets it right.
RANKED_CONTEXT_METRICS = {ranked_context_metrics}

# Evaluators sent the per-sample "Metric Inputs" section: the DeepEval handlers, and the
# RAGAS handlers whose metric needs per-sample fields or is multi-turn. Any other evaluator
# would read that section as part of the reference or take another metric's fields.
METRIC_INPUTS_METRICS = {metric_inputs_metrics}

# Post-extraction score transforms (mapping.json score_transform and/or
# --metric-transform overrides), e.g. the original script normalizes a 0-5
# metric to 0-1. Keys must match scores_before.json.
METRIC_TRANSFORMS = {transforms_literal}

# Author-chosen categorical labels, read at resolve time from each evaluator's own
# deployed ratingScale rather than guessed from a fixed table.
LABEL_SCORES = {{}}

# Every evaluate() request sent, written to evaluation_requests.jsonl so the scores can be
# recomputed against the deployed evaluators without re-running this script.
EVALUATION_REQUESTS = []


{transform_fn}


{adot_inline}


def resolve_all_evaluator_ids(client):
    """Resolve every evaluator's deployed ID.

    - Builtin.* IDs are fixed.
    - LLM-as-a-Judge evaluators (path "llm_judge") REQUIRE the ID returned by
      create_evaluator_and_wait() to be pasted into EVALUATORS above — SDK
      IDs are not project-prefixed, so fragment lookup could match another
      run's evaluator.
    - Lambda evaluators self-resolve via the project-scoped fragment.
    """
    resolved = {{}}
    for score_key, info in EVALUATORS.items():
        if info.get("evaluator_id"):  # Builtin.* or pasted SDK/deploy ID
            resolved[score_key] = info["evaluator_id"]
            continue
        if info.get("path") == "llm_judge":
            raise RuntimeError(
                f"EVALUATORS[{{score_key!r}}]['evaluator_id'] is not set. LLM-as-a-Judge "
                "evaluators must use the exact ID returned by create_evaluator_and_wait() "
                "— paste it into the EVALUATORS dict at the top of this script.")
        eid = resolve_evaluator_id(client._cp_client, info["name_fragment"])
        if not eid:
            raise RuntimeError(
                f"Cannot resolve deployed evaluator for {{score_key!r}} "
                f"(fragment {{info['name_fragment']!r}}). Was migration.sh run? "
                "Check: client._cp_client.list_evaluators()")
        resolved[score_key] = eid
    # Author-chosen labels: read each judge's own scale.
    for score_key, eid in resolved.items():
        if EVALUATORS[score_key].get("path") == "llm_judge":
            LABEL_SCORES[score_key] = fetch_label_scores(client._cp_client, eid)
    return resolved


def split_context(ctx):
    """Return (joined string, ranked list) for one case's context field.

    Both forms are kept: evaluate_case sends the ranked list only to
    RANKED_CONTEXT_METRICS and the joined string to every other evaluator.
    """
    if not ctx:
        return None, None
    if isinstance(ctx, list):
        return "\\n".join(ctx), list(ctx)
    return str(ctx), None


def evaluate_case(client, evaluator_ids, user_input, agent_response,
                  context=None, reference=None, metric_inputs=None,
                  context_list=None):
    """Send one case through every evaluator; returns {{score_key: score}}.

    Raises on evaluator errors — a silent 0.0 would poison the divergence
    comparison and is far more expensive to diagnose after the fact.

    metric_inputs (per-sample fields such as rubrics, image lists or the tools
    the agent called) are embedded ONLY in the docs sent to METRIC_INPUTS_METRICS,
    so no other handler reads them as part of the reference.

    context_list (the retrieval context as its original list of ranked chunks)
    is embedded ONLY in the docs sent to RANKED_CONTEXT_METRICS, so rank-aware
    metrics see the chunk boundaries while every other evaluator keeps the
    joined-string form.
    """
    # One document pair per (context form, Metric Inputs) combination, built once per case.
    docs_by_form = {{}}
    scores = {{}}
    for score_key, evaluator_id in evaluator_ids.items():
        ranked = bool(context_list) and score_key in RANKED_CONTEXT_METRICS
        with_mi = bool(metric_inputs) and score_key in METRIC_INPUTS_METRICS
        docs = docs_by_form.get((ranked, with_mi))
        if docs is None:
            docs = docs_by_form[(ranked, with_mi)] = build_adot_docs(
                user_input, agent_response,
                context=context_list if ranked else context,
                reference=reference,
                metric_inputs=metric_inputs if with_mi else None)
        try:
            response = client._dp_client.evaluate(
                evaluatorId=evaluator_id,
                evaluationInput={{"sessionSpans": docs}},
            )
        except Exception as exc:
            # The data-plane client uses read_timeout=300 (see main()) so Lambda
            # cold starts fit in one call window; this retry is a last-resort
            # safety net for timeout-shaped errors only — anything else re-raises.
            if "Timeout" not in type(exc).__name__ and "timed out" not in str(exc).lower():
                raise
            print(f"  cold-start timeout on {{evaluator_id}} — retrying once (Lambda is warming)")
            response = client._dp_client.evaluate(
                evaluatorId=evaluator_id,
                evaluationInput={{"sessionSpans": docs}},
            )
        score = extract_score(response, LABEL_SCORES.get(score_key))
        transform = METRIC_TRANSFORMS.get(score_key)
        if transform:
            score = apply_metric_transform(transform, score)
        scores[score_key] = score
        EVALUATION_REQUESTS.append({{
            "score_key": score_key,
            "evaluator_id": evaluator_id,
            "input": user_input,
            "transform": transform,
            "session_spans": docs,
        }})
    return scores
'''

_TRACES_MAIN_TEMPLATE = """\

TRACES_FILE = {traces_file!r}

# Trace-JSON field names → evaluation inputs (from reading the trace file).
FIELD_INPUT = {field_input!r}
FIELD_OUTPUT = {field_output!r}
FIELD_CONTEXT = {field_context!r}    # "" if the traces have no context field
FIELD_REFERENCE = {field_reference!r}  # "" if the traces have no reference field
# Per-sample metric fields (rubrics, image lists, tool calls) embedded as "Metric
# Inputs" for METRIC_INPUTS_METRICS: {{sample_field: trace_field}}
METRIC_INPUTS_MAP = {metric_inputs_map_literal}


def load_cases():
    with open(TRACES_FILE) as f:
        traces = json.load(f)
    cases = []
    for t in traces:
        context, context_list = split_context(
            t.get(FIELD_CONTEXT) if FIELD_CONTEXT else None)
        reference = None
        if FIELD_REFERENCE and t.get(FIELD_REFERENCE):
            ref = t[FIELD_REFERENCE]
            # Lists (e.g. reference tool calls/topics) are JSON-encoded so the
            # RagasAdapter can interpret them by shape.
            reference = json.dumps(ref) if isinstance(ref, (list, dict)) else str(ref)
        metric_inputs = {{
            sample_field: t[trace_field]
            for sample_field, trace_field in METRIC_INPUTS_MAP.items()
            if t.get(trace_field) is not None
        }} or None
        cases.append({{
            "input": t[FIELD_INPUT],
            "output": t[FIELD_OUTPUT],
            "context": context,
            "context_list": context_list,
            "reference": reference,
            "metric_inputs": metric_inputs,
        }})
    return cases
"""

_LIVE_MAIN_TEMPLATE = '''\
TRACES_FILE = ARTIFACTS_DIR / "traces.json"


def _run_agent(test_input: str) -> dict:
    """Run the customer's agent on a single test input.

    TODO(EVAL-MIGRATION): reproduce the customer's agent here VERBATIM — same
    model ID, same tools, same system prompt. Return:
        {"input": <user query>, "output": <agent response>,
          "context": <retrieval context/tool data or None — keep a ranked chunk
                      LIST as a list; do not join chunks>,
          "reference": <ground truth / expected output or None>,
          "metric_inputs": <per-sample dict or None. RAGAS: sample fields such
                            as rubrics, reference_contexts, image lists, and
                            for multi-turn metrics tools_called or user_input
                            (the conversation). DeepEval: tools_called,
                            expected_tools, context, retrieval_context,
                            expected_output, and {score_key: variant} as
                            "variants" for metrics with variants>,
          "metrics": <score keys the source scores on this case, or None for
                      all of them; the rest record None, as the source does>}
    Do NOT substitute a different agent framework (surrogate agents are an
    anti-pattern — scores become incomparable).
    """
    raise NotImplementedError("reproduce the customer agent (see docstring)")


def load_cases():
    """Two-phase trace management (MANDATORY for live topology).

    Phase 1: If traces.json does NOT exist, run the agent on all test cases
    and save the results. This is the ONLY place agent calls happen.

    Phase 2: If traces.json EXISTS, load from it (no agent calls). This enables
    retries, trace-pinning, and avoids timeout from repeated agent invocations.

    CRITICAL: Agent invocation is separated from evaluation to prevent the
    combined timeout (agent calls + Lambda cold starts) from exceeding budget.
    """
    if TRACES_FILE.exists():
        print(f"Loading cached traces from {TRACES_FILE}")
        with open(TRACES_FILE) as f:
            cases = json.load(f)
    else:
        print("No cached traces — running agent to capture traces...")
        # TODO(EVAL-MIGRATION): define TEST_INPUTS list matching the original script
        TEST_INPUTS = []  # e.g., ["What is X?", "How do I Y?", ...]
        if not TEST_INPUTS:
            raise NotImplementedError("define TEST_INPUTS from the original script")

        cases = []
        for test_input in TEST_INPUTS:
            cases.append(_run_agent(test_input))

        # Persist the RAW cases: the split below is derived, and saving it would
        # lose the ranked list on the next load.
        TRACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACES_FILE, "w") as f:
            json.dump(cases, f, indent=2)
        print(f"Saved {len(cases)} traces to {TRACES_FILE}")

    for case in cases:
        case["context"], case["context_list"] = split_context(case.get("context"))
    return cases
'''

_FOOTER_TEMPLATE = """\

# Built at runtime from two halves so this line never matches itself.
_SCAFFOLD_MARKER = "TODO(" + "EVAL-MIGRATION)"


def _fail_on_unfinished_scaffold():
    \"\"\"Exit before any AWS call while generated scaffold sections are unfinished.

    A live-topology scaffold ships _run_agent()/TEST_INPUTS as TODO stubs. Failing here
    gives a local checklist instead of a NotImplementedError midway through evaluation.
    \"\"\"
    source = Path(__file__).read_text()
    hits = [
        f"  line {{i}}: {{line.strip()}}"
        for i, line in enumerate(source.splitlines(), 1)
        if _SCAFFOLD_MARKER in line
    ]
    if hits:
        print("ERROR: unfinished scaffold — complete these markers, then re-run:")
        print("\\n".join(hits))
        sys.exit(3)


def _mean(values):
    \"\"\"Mean of the scores that exist, or None when no case scored the metric.\"\"\"
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _fmt(value):
    return "n/a" if value is None else f"{{value:.3f}}"


def main():
    _fail_on_unfinished_scaffold()
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # An unwritable ARTIFACTS_DIR is the first thing that fails. Say what to do
        # about it instead of surfacing a bare PermissionError traceback.
        sys.exit(
            f"ERROR: cannot create {{ARTIFACTS_DIR}} ({{exc}}).\\n"
            f"Set ARTIFACTS_DIR to a writable path, e.g.\\n"
            f"  ARTIFACTS_DIR=./artifacts python3 {{Path(__file__).name}}"
        )

    client = EvaluationClient(region_name=REGION)
    # Lambda cold starts (60-120s INIT on 200MB+ bundles) exceed boto3's default
    # 60s read timeout, and a retry alone still fails when INIT outlasts the
    # second window. Rebuild the data-plane client with read_timeout=300,
    # merging onto the SDK's config to keep its user-agent telemetry.
    client._dp_client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        config=client._dp_client.meta.config.merge(
            Config(read_timeout=300, connect_timeout=10)),
    )
    evaluator_ids = resolve_all_evaluator_ids(client)
    print(f"Resolved evaluators: {{json.dumps(evaluator_ids, indent=2)}}")

    cases = load_cases()
    print(f"Evaluating {{len(cases)}} cases x {{len(evaluator_ids)}} evaluators...")

    all_scores = []
    for i, case in enumerate(cases):
        # A case may list the metrics the source scores on it (a source that scores a
        # metric only on some cases). The others record None there, as the source does.
        applies = case.get("metrics")
        if applies is not None:
            unknown = sorted(set(applies) - set(evaluator_ids))
            if unknown:
                sys.exit(f"ERROR: case {{i + 1}} lists metrics not in EVALUATORS: {{unknown}}")
        active = {{k: v for k, v in evaluator_ids.items() if applies is None or k in applies}}
        scores = evaluate_case(client, active,
                               case["input"], case["output"],
                               context=case.get("context"),
                               reference=case.get("reference"),
                               metric_inputs=case.get("metric_inputs"),
                               context_list=case.get("context_list"))
        scores = {{key: scores.get(key) for key in evaluator_ids}}
        all_scores.append({{"input": case["input"], **scores}})
        print(f"  case {{i + 1}}/{{len(cases)}}: "
              + ", ".join(f"{{k}}={{_fmt(v)}}" for k, v in scores.items()))

    # Means over the cases that scored each metric, as the source averages them.
    mean_scores = {{key: _mean(s[key] for s in all_scores) for key in evaluator_ids}}

    (ARTIFACTS_DIR / "scores_after.json").write_text(json.dumps({{
        "evaluators": sorted(evaluator_ids.values()),
        "scores": all_scores,
        "mean_scores": mean_scores,
    }}, indent=2))
    with open(ARTIFACTS_DIR / "evaluation_requests.jsonl", "w") as f:
        for request in EVALUATION_REQUESTS:
            f.write(json.dumps(request) + "\\n")
    print(f"\\nMean scores: {{json.dumps(mean_scores, indent=2)}}")

    # Divergence vs the original scores (informational — the fix loop uses this).
    # None means one run scored the metric and the other scored it on no case.
    divergence = {{}}
    before_path = ARTIFACTS_DIR / "scores_before.json"
    if before_path.exists():
        before = json.loads(before_path.read_text())
        before_means = before.get("mean_scores", {{}})
        for key, after_val in mean_scores.items():
            if key not in before_means:
                continue
            before_val = before_means[key]
            if before_val is None and after_val is None:
                continue
            if before_val is None or after_val is None:
                divergence[key] = None
            else:
                divergence[key] = round(abs(before_val - after_val), 4)
        print(f"Per-metric divergence (threshold 0.1): {{json.dumps(divergence, indent=2)}}")
    measured = [v for v in divergence.values() if v is not None]

    (ARTIFACTS_DIR / "summary.json").write_text(json.dumps({{
        "source_script": {source_script!r},
        "source_framework": {framework!r},
        "source_evaluators": [e["class"] for e in EVALUATORS.values()],
        "target_evaluators": sorted(evaluator_ids.values()),
        "mapping_types": [e["path"] for e in EVALUATORS.values()],
        "deploy_success": True,
        "invoke_success": True,
        # The largest per-metric divergence: the 0.1 limit applies to every metric.
        "score_divergence": max(measured) if measured else None,
        "per_metric_divergence": divergence or None,
    }}, indent=2))

    failing = {{k: v for k, v in divergence.items() if v is None or v > 0.1}}
    if failing:
        print(f"\\nWARNING: metrics exceeding 0.1 divergence (None: scored in only one "
              f"run): {{failing}} — run the divergence fix loop before declaring success.")
        sys.exit(2)
    print(f"\\nDone. Artifacts in {{ARTIFACTS_DIR}}/")


def _run():
    \"\"\"Run main() and return the exit code the interpreter would have used.\"\"\"
    try:
        main()
    except SystemExit as exc:
        code = exc.code
    except BaseException:
        traceback.print_exc()
        return 1
    else:
        return 0
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    # sys.exit("message") prints the message and exits 1.
    print(code, file=sys.stderr)
    return 1


if __name__ == "__main__":
    # Exit without waiting for other threads. The customer's agent can leave a non-daemon
    # thread behind (PydanticAI's run_sync under nest_asyncio leaves an idle AnyIO worker
    # thread), and a normal exit then waits for it forever: the scores are written within
    # minutes but the command never returns. Every output file is closed by this point.
    _code = _run()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
"""


def _parse_field_map(raw: str) -> dict:
    fields = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        k, _, v = pair.partition("=")
        fields[k.strip()] = v.strip()
    missing = {"input", "output"} - set(k for k, v in fields.items() if v)
    if missing:
        raise SystemExit(
            f"[client-script] ERROR: --field-map must set {sorted(missing)} "
            "(read the trace file to find the right field names)"
        )
    return fields


def _set_literal(keys) -> str:
    keys = sorted(keys)
    return "{" + ", ".join(repr(k) for k in keys) + "}" if keys else "set()"


def _ranked_context_metrics_literal(mapping: dict) -> str:
    """Return a set literal of the score keys whose handler recovers a list context.

    The generated DeepEval and RAGAS handlers parse a JSON-array context back into ranked
    chunks. Derived per metric because one migration can mix frameworks under a single
    framework label.
    """
    return _set_literal(
        score_key
        for score_key, entry in mapping.items()
        if entry.get("adapter") in ("DeepEvalAdapter", "RagasAdapter")
    )


def _metric_inputs_metrics_literal(mapping: dict) -> str:
    """Return a set literal of the score keys the client sends the Metric Inputs section to.

    Every generated DeepEval handler gets it. A RAGAS handler gets it only when its metric
    needs per-sample fields or is multi-turn: a single-turn RAGAS handler adds every Metric
    Inputs field to its sample, so a field meant for another metric (an image list as
    retrieved_contexts, say) would replace its own.
    """
    return _set_literal(
        score_key
        for score_key, entry in mapping.items()
        if entry.get("adapter") == "DeepEvalAdapter"
        or (
            entry.get("adapter") == "RagasAdapter"
            and (entry.get("needs_metric_inputs") or entry.get("multi_turn"))
        )
    )


def _parse_transforms(raw_list: list[str]) -> dict:
    """Parse --metric-transform key=expr entries, checking each expr against a probe score."""
    transforms = {}
    for raw in raw_list or []:
        key, sep, expr = raw.partition("=")
        if not sep or not expr.strip():
            raise SystemExit(
                f"[client-script] ERROR: --metric-transform must be "
                f"key=expr (e.g. clarity=score/5), got {raw!r}"
            )
        expr = expr.strip()
        try:
            probe = apply_metric_transform(expr, 0.5)
            float(probe)
        except Exception as exc:
            raise SystemExit(
                f"[client-script] ERROR: transform {expr!r} for "
                f"{key.strip()!r} is not a valid expression over "
                f"'score': {exc}"
            )
        transforms[key.strip()] = expr
    return transforms


def generate(args: argparse.Namespace) -> Path:
    with open(args.mapping) as f:
        mapping = json.load(f)
    with open(args.names) as f:
        names = json.load(f)

    # These reach the generated script's source text, so they are validated first.
    if not _SOURCE_SCRIPT_PATTERN.fullmatch(args.source_script):
        raise SystemExit(
            f"[client-script] ERROR: --source-script {args.source_script!r} must match "
            f"{_SOURCE_SCRIPT_PATTERN.pattern}: it is written into the generated script."
        )
    framework = names.get("framework", "unknown")
    project_name = names.get("project_name", "")
    try:
        validate_framework(framework)
        if project_name:
            validate_project_name(project_name)
        for name in names.get("evaluators", {}).values():
            validate_evaluator_name(name)
    except ValueError as exc:
        raise SystemExit(f"[client-script] ERROR: {args.names}: {exc}") from None

    # Builtin IDs are fixed; Lambda IDs resolve at runtime from "{project}_{name}". SDK-created
    # llm_judge IDs have no project prefix, so they must be pasted into the generated script.
    evaluators = {}
    for score_key, entry in mapping.items():
        if entry["path"] == "unknown":
            raise SystemExit(
                f"[client-script] ERROR: metric {score_key!r} is unclassified "
                "(path=unknown) — resolve it in mapping.json first"
            )
        bare_name = names["evaluators"].get(score_key, "")
        evaluators[score_key] = {
            "class": entry["class"],
            "path": entry["path"],
            "evaluator_id": entry.get("evaluator_id"),  # Builtin.* pre-filled
            "name_fragment": f"{project_name}_{bare_name}" if bare_name else "",
            "needs_metric_inputs": bool(entry.get("needs_metric_inputs")),
        }
        if not evaluators[score_key]["evaluator_id"] and not bare_name:
            raise SystemExit(
                f"[client-script] ERROR: {score_key!r} has neither a fixed "
                "evaluator_id nor a name fragment in names.json"
            )

    # Transforms from mapping.json (score_transform) and --metric-transform; CLI wins per key.
    transforms = {}
    for score_key, entry in mapping.items():
        expr = entry.get("score_transform")
        if not expr:
            continue
        try:
            float(apply_metric_transform(expr, 0.5))
        except Exception as exc:
            raise SystemExit(
                f"[client-script] ERROR: mapping.json score_transform {expr!r} for "
                f"{score_key!r} is not a valid expression over 'score': {exc} — "
                "fix it in metrics.json and re-run classify.py"
            )
        transforms[score_key] = expr
    cli_transforms = _parse_transforms(args.metric_transform)
    unknown_transform_keys = set(cli_transforms) - set(evaluators)
    if unknown_transform_keys:
        raise SystemExit(
            f"[client-script] ERROR: --metric-transform keys not in "
            f"mapping.json: {sorted(unknown_transform_keys)}"
        )
    transforms.update(cli_transforms)

    # Live cases get metric_inputs from _run_agent(); only traces need --metric-inputs-map.
    needing = [k for k, e in evaluators.items() if e["needs_metric_inputs"]]
    if needing and args.topology == "traces" and not args.metric_inputs_map:
        wanted = sorted(
            {f for k in needing for f in mapping[k].get("metric_inputs_fields") or ["<field>"]}
        )
        raise SystemExit(
            f"[client-script] ERROR: metrics {needing} require per-sample inputs "
            f"({', '.join(wanted)}) — supply --metric-inputs-map "
            "sample_field=trace_field (e.g. rubrics=rubrics, tools_called=tool_calls)"
        )

    source_stem = re.sub(r"\.py$", "", Path(args.source_script).name)

    parts = [
        _HEADER_TEMPLATE.format(
            source_script=args.source_script,
            framework=framework,
            agent_dep_note=" + the agent framework" if args.topology == "live" else "",
            region=args.region,
            evaluators_literal=pprint.pformat(evaluators, indent=1, sort_dicts=True),
            ranked_context_metrics=_ranked_context_metrics_literal(mapping),
            metric_inputs_metrics=_metric_inputs_metrics_literal(mapping),
            transforms_literal=pprint.pformat(transforms, indent=1, sort_dicts=True),
            transform_fn=inspect.getsource(apply_metric_transform).rstrip(),
            adot_inline=_adot_inline_source(),
        )
    ]

    if args.topology == "traces":
        fields = _parse_field_map(args.field_map)
        mi_map = {}
        for raw in args.metric_inputs_map or []:
            k, sep, v = raw.partition("=")
            if not sep:
                raise SystemExit(
                    "[client-script] ERROR: --metric-inputs-map must be "
                    f"sample_field=trace_field, got {raw!r}"
                )
            mi_map[k.strip()] = v.strip()
        parts.append(
            _TRACES_MAIN_TEMPLATE.format(
                traces_file=args.traces_file,
                field_input=fields.get("input", ""),
                field_output=fields.get("output", ""),
                field_context=fields.get("context", ""),
                field_reference=fields.get("reference", ""),
                metric_inputs_map_literal=pprint.pformat(mi_map, indent=1, sort_dicts=True),
            )
        )
    else:
        # Appended without .format(), so a doubled brace would survive into the
        # deliverable and print literally; ast.parse() cannot see it.
        if "{{" in _LIVE_MAIN_TEMPLATE:
            raise SystemExit(
                "[client-script] ERROR: _LIVE_MAIN_TEMPLATE is not format-substituted; "
                "use single braces"
            )
        parts.append(_LIVE_MAIN_TEMPLATE)

    parts.append(
        _FOOTER_TEMPLATE.format(
            source_script=args.source_script,
            framework=framework,
        )
    )

    out_path = Path(args.output_dir) / f"{source_stem}_agentcore.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source = "".join(parts)
    # Syntax check without compile(): skill scripts must not use compile/eval/exec, and
    # ast.parse() raises the same SyntaxError.
    ast.parse(source, filename=str(out_path))
    out_path.write_text(source)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source-script", required=True, help="the customer's original script filename"
    )
    parser.add_argument("--topology", required=True, choices=["traces", "live"])
    parser.add_argument(
        "--traces-file", default=None, help="trace JSON path (required for --topology traces)"
    )
    parser.add_argument(
        "--field-map",
        default="",
        help="trace field mapping: input=<f>,output=<f>,context=<f>,reference=<f>",
    )
    parser.add_argument(
        "--metric-transform",
        action="append",
        default=[],
        help="post-extraction score transform, key=expr over 'score' "
        "(e.g. clarity=score/5). Transforms recorded in metrics.json "
        "(score_transform) apply automatically; this flag overrides "
        "them per key (repeatable)",
    )
    parser.add_argument(
        "--metric-inputs-map",
        action="append",
        default=[],
        help="per-sample metric field mapping sample_field=trace_field "
        "(e.g. rubrics=rubrics) for metrics flagged "
        "needs_metric_inputs (repeatable)",
    )
    parser.add_argument("--mapping", required=True, help="mapping.json from classify.py")
    parser.add_argument("--names", required=True, help="names.json from names.py")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    if args.topology == "traces" and not args.traces_file:
        raise SystemExit("[client-script] ERROR: --traces-file is required for --topology traces")

    out_path = generate(args)
    print(f"[client-script] generated: {out_path}")
    if args.topology == "live":
        print(
            "[client-script] ACTION REQUIRED: implement load_cases() — reproduce the "
            "customer's agent verbatim (see the TODO docstring in the generated file)"
        )


if __name__ == "__main__":
    main()
