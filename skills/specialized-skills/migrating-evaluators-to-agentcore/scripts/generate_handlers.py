#!/usr/bin/env python3
"""Generate Lambda handler files from mapping.json + names.json.

Writes one handler .py per code-based metric, plus an evaluators.json manifest of
(name, level, handler_file) entries for deployer.generate_migration_sh(). Handlers are
self-contained: they import nothing from this skill directory. A handler with a
TODO(EVAL-MIGRATION) block still needs code from the source script (a metric rule, a
DAG, a schema class); migration.sh refuses to deploy it until the block is complete.

Usage:
    python3 generate_handlers.py --mapping mapping.json --names names.json \\
        --output-dir handlers/
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

# Put scripts/ on sys.path so sibling modules resolve with static imports whether the package
# is installed or the skill directory is copied standalone. Dynamic import is not allowed.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from classify import (  # noqa: E402
    DEEPEVAL_METRIC_CLASSES,
    DEEPEVAL_SOURCE_OBJECT,
    RAGAS_METRIC_CLASSES,
    VARIANT_NAME_PATTERN,
)
from deployer import EMBEDDINGS_MODEL, judge_model_id  # noqa: E402
from names import validate_evaluator_name, validate_score_key  # noqa: E402

#: Must match deployer.py's default region so the handler's model ID and the IAM policy agree.
_DEFAULT_REGION = "us-east-1"


def default_region() -> str:
    """Deploy region for model-ID substitution, from the environment."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or _DEFAULT_REGION


def _region_arg(value: str) -> str:
    """argparse ``type`` for ``--region``: reject regions with no judge inference profile."""
    judge_model_id(value)
    return value


_DEEPEVAL_ENV_PRELUDE = """\
import os
# Lambda's filesystem is read-only outside /tmp — set BEFORE any deepeval import.
os.environ["DEEPEVAL_HOME"] = "/tmp/.deepeval"
os.environ["DEEPEVAL_CACHE_FOLDER"] = "/tmp/.deepeval"
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
"""

_ADAPTER_TEMPLATE = '''\
"""Lambda handler: {score_key} via DeepEvalAdapter.

Deployed as an AgentCore code-based evaluator. _test_case() builds the LLMTestCase
from the incoming ADOT spans, DeepEvalAdapter runs the actual {metric_class}
pipeline on it and returns the EvaluatorOutput.

The adapter is imported from the pinned bedrock-agentcore wheel, which ships the
third_party adapters from 1.23.0 onward.
"""
{env_prelude}
import json

from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator, EvaluatorOutput
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.deepeval.adapter import DeepEvalAdapter
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.span_mappers import map_spans
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.span_mappers.common import FieldExtractionError
from deepeval.metrics import {metric_class}
from deepeval.test_case import LLMTestCase, ToolCall
{model_import}{param_import}

{model_setup}{source_objects}
{test_case_helpers}{variants_block}

def _metric({metric_params}):
    """Build a new metric for every invocation.

    A metric keeps state between measure() calls. GEval caches the evaluation steps it
    generates, so a module-level instance would score every case with the steps drawn for
    the first one for as long as the Lambda stays warm.
    """
{async_note}    return {metric_class}({metric_kwargs})


@custom_code_based_evaluator()
def handler(eval_input, context=None):
{handler_body}'''

_HANDLER_BODY = """\
    return DeepEvalAdapter(metric=_metric(), custom_mapper=_test_case)(eval_input, context)
"""

# For a metric with variants. Inserted as format() values and never formatted themselves.
_VARIANT_HELPER = '''

def _variant(eval_input):
    """The variant this case names in its Metric Inputs section, or None."""
    result = map_spans(
        _target_spans(eval_input), eval_input.reference_inputs, eval_input.target_trace_id
    )
    named = _split_user_message(result.input or "")[3].get("variants")
    return named.get(_VARIANT_KEY) if isinstance(named, dict) else None
'''

_VARIANT_HANDLER_BODY = """\
    try:
        variant = _variant(eval_input)
    except FieldExtractionError as exc:
        return EvaluatorOutput(errorCode="FIELD_EXTRACTION_ERROR", errorMessage=str(exc))
    if not isinstance(variant, str) or variant not in _VARIANTS:
        return EvaluatorOutput(
            errorCode="MISSING_REQUIRED_FIELD",
            errorMessage=(
                f"this case names no {_VARIANT_KEY} variant (got {variant!r}): its Metric "
                f"Inputs must map {_VARIANT_KEY!r} under 'variants' to one of {sorted(_VARIANTS)}"
            ),
        )
    return DeepEvalAdapter(metric=_metric(variant), custom_mapper=_test_case)(eval_input, context)
"""


def _join(*blocks: str) -> str:
    """Join top-level code blocks with two blank lines, as PEP 8 separates definitions."""
    return "\n\n\n".join(block.strip("\n") for block in blocks) + "\n"


# Helpers pasted into the adapter handlers. Each is inserted as a format() value and never
# formatted itself, so its braces stay single.
#
# The embedded sections of the first user message.
_SPLIT_HELPERS = '''\
# The migrated client embeds each case's context, reference and per-sample fields in the
# first user message, on these separators (see scripts/adot.py).
_CONTEXT_SEPARATOR = "\\n\\nContext:\\n"
_REFERENCE_SEPARATOR = "\\n\\nReference Answer:\\n"
_METRIC_INPUTS_SEPARATOR = "\\n\\nMetric Inputs:\\n"


def _split_user_message(text):
    """Return (query, context, reference, metric_inputs) from the first user message."""
    metric_inputs = {}
    if _METRIC_INPUTS_SEPARATOR in text:
        # The last section. JSON escapes newlines, so no separator can occur inside it.
        text, _, raw = text.rpartition(_METRIC_INPUTS_SEPARATOR)
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            metric_inputs = parsed
    reference = None
    if _REFERENCE_SEPARATOR in text:
        text, _, reference = text.partition(_REFERENCE_SEPARATOR)
    context = None
    if _CONTEXT_SEPARATOR in text:
        text, _, context = text.partition(_CONTEXT_SEPARATOR)
    return text, context, reference, metric_inputs
'''

# The chunk-list context and the spans one invocation scores.
_SPAN_HELPERS = '''\
def _strings(value):
    """A non-empty list of strings, or None."""
    if isinstance(value, str):
        return [value] if value else None
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return value
    return None


def _chunks(context):
    """The client JSON-encodes a chunk list, so the chunks survive; plain text is one chunk."""
    try:
        parsed = json.loads(context)
    except ValueError:
        return [context]
    return (_strings(parsed) if isinstance(parsed, list) else None) or [context]


def _span_field(span, camel, snake):
    return span.get(camel, span.get(snake)) if isinstance(span, dict) else None


def _target_spans(eval_input):
    """The spans this invocation scores, scoped by level the way the adapter scopes them."""
    spans = eval_input.session_spans
    if eval_input.evaluation_level == "TRACE" and eval_input.target_trace_id:
        target = eval_input.target_trace_id
        return [s for s in spans if _span_field(s, "traceId", "trace_id") == target]
    if eval_input.evaluation_level == "TOOL_CALL" and eval_input.target_span_id:
        target_id = eval_input.target_span_id
        target = next((s for s in spans if _span_field(s, "spanId", "span_id") == target_id), {})
        parent = _span_field(target, "parentSpanId", "parent_span_id")
        wanted = {target_id, parent} - {None}
        return [s for s in spans if _span_field(s, "spanId", "span_id") in wanted]
    return spans
'''

# The DeepEval handler's span-to-LLMTestCase mapping.
_DEEPEVAL_TEST_CASE_MAPPER = '''\
def _text(value):
    return value if isinstance(value, str) and value else None


def _tool_calls(items):
    """ToolCall objects from tool names or {"name", "input_parameters", "output"} dicts."""
    calls = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            calls.append(ToolCall(name=item))
            continue
        name = (item.get("name") or item.get("tool")) if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue
        args = item.get("input_parameters", item.get("args", item.get("arguments")))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        calls.append(
            ToolCall(
                name=name,
                input_parameters=args if isinstance(args, dict) else None,
                output=item.get("output"),
            )
        )
    return calls


def _tools(extra, key, from_spans):
    """A case's tool calls from Metric Inputs, else from the spans.

    A list in Metric Inputs is used even when empty, since an empty list means the source
    expected or called no tools. An empty list from the spans means only that they carry none.
    """
    if isinstance(extra.get(key), list):
        return _tool_calls(extra[key])
    return _tool_calls(from_spans) or None


def _test_case(eval_input):
    """Build the LLMTestCase, reading the sections the migrated client embeds.

    The adapter's default mapping reads none of those sections and passes the whole first
    user message on as input, so context metrics would fail with MISSING_REQUIRED_FIELD and
    every other metric would judge an input the source never saw. Spans without the
    sections map as the default does, so the evaluator can also score traces from the live
    agent. Each field comes from the Metric Inputs section first, then from the spans or
    evaluationReferenceInputs, then from the embedded section.
    """
    result = map_spans(
        _target_spans(eval_input), eval_input.reference_inputs, eval_input.target_trace_id
    )
    query, context, reference, extra = _split_user_message(result.input or "")
    if not query:
        raise FieldExtractionError("no user message found in the evaluation spans")
    retrieval = (
        _strings(extra.get("retrieval_context"))
        or result.retrieval_context
        or (_chunks(context) if context else None)
    )
    return LLMTestCase(
        input=query,
        actual_output=result.actual_output,
        expected_output=_text(extra.get("expected_output")) or result.expected_output or reference,
        # Assertions first, else the retrieval context, as the adapter's default mapping does.
        context=_strings(extra.get("context")) or result.assertions or retrieval,
        retrieval_context=retrieval,
        tools_called=_tools(extra, "tools_called", result.tools_called),
        expected_tools=_tools(extra, "expected_tools", result.expected_tools),
    )
'''

_DEEPEVAL_TEST_CASE_HELPERS = _join(_SPLIT_HELPERS, _SPAN_HELPERS, _DEEPEVAL_TEST_CASE_MAPPER)

# For each classify.DEEPEVAL_SOURCE_OBJECT metric: the object mapping.json cannot carry.
_SOURCE_OBJECT_TEMPLATE = """

# TODO(EVAL-MIGRATION): {metric_class} takes {kwarg}= as a Python object, which mapping.json
# cannot carry. Make _source_{kwarg}({params}) build and return it, copied VERBATIM from the source
# script with the imports it needs: {what}.{variants_note}
# Then delete this comment. migration.sh refuses to deploy a handler that still has it.
def _source_{kwarg}({params}):
    raise NotImplementedError("copy {kwarg}= from the source script into _source_{kwarg}()")
"""

_DEEPEVAL_MODEL_IMPORT = "from deepeval.models import AmazonBedrockModel"

# Enum class for GEval's evaluation_params, which deepeval takes as enum members, not strings.
_PARAM_ENUM = {"GEval": "SingleTurnParams"}
# {judge_model_id} comes from deployer.judge_model_id(region), never a literal: inference
# profile IDs vary by region, and the IAM policy grants only the one that function returns.
_DEEPEVAL_MODEL_SETUP = """\
import os as _os
# Kwargs are model= and region= (NOT model_name=) — both required.
_model = AmazonBedrockModel(
    model="{judge_model_id}",
    region=_os.environ.get("AWS_REGION", "{region}"),
)
"""

# Extraction helpers shared by the handlers that do not use an adapter. Inserted as a
# format() value and never formatted itself, so its braces stay single.
_EXTRACT_HELPERS = '''\
def _texts(content_json):
    """Decode a '[{"text": ...}]' JSON string into concatenated text."""
    try:
        parts = json.loads(content_json)
        return "\\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (json.JSONDecodeError, TypeError):
        return str(content_json or "")


def _iter_bodies(eval_input):
    """Yield log-record body dicts from the session documents.

    The AgentCore service TRANSFORMS spans before Lambda delivery: the log
    record body arrives in span_events[*].body, not top-level "body". The
    top-level fallback keeps local testing against raw ADOT docs working.
    """
    docs = getattr(eval_input, "session_spans", None) or []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for event in (doc.get("span_events") or []):
            if isinstance(event, dict) and isinstance(event.get("body"), dict):
                yield event["body"]
        if isinstance(doc.get("body"), dict):
            yield doc["body"]
'''


_DETERMINISTIC_TEMPLATE = '''\
"""Lambda handler: {score_key} — deterministic metric.

Deterministic metrics (exact match / regex / schema validation) MUST run as
code — an LLM judge cannot replicate them. Field extraction below is complete
(handles the service-transformed span_events format); implement the metric
rule where marked.
"""
import json

from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator, EvaluatorOutput


{extract_helpers}

def extract_fields(eval_input):
    """Extract (user_input, actual_output) from the session documents.

    The expected value / pattern / schema is typically embedded in the user
    message context — split it out if the original metric compares against
    an expected value.
    """
    user_input, actual_output = "", ""
    for body in _iter_bodies(eval_input):
        for msg in (body.get("input") or {{}}).get("messages", []):
            content = (msg.get("content") or {{}}).get("content")
            if content and not user_input:
                user_input = _texts(content)
        for msg in (body.get("output") or {{}}).get("messages", []):
            content = (msg.get("content") or {{}}).get("message")
            if content:
                actual_output = _texts(content)
    return user_input, actual_output


@custom_code_based_evaluator()
def handler(eval_input, context=None):
    user_input, actual_output = extract_fields(eval_input)

    # TODO(EVAL-MIGRATION): implement the EXACT rule from the customer's original
    # metric ({metric_class}). Examples:
    #   exact match:   score = 1.0 if actual_output.strip() == expected.strip() else 0.0
    #   pattern match: score = 1.0 if re.fullmatch(pattern, actual_output) else 0.0
    #   json schema:   validate with pydantic model_validate_json; 1.0 on success
    # Replicate the original's edge-case behavior (e.g., 0.0 when expected data
    # is absent). Remove this TODO block when done.
    raise NotImplementedError("implement the {metric_class} rule before deploying")

    return EvaluatorOutput(value=score, label="Pass" if score >= 0.5 else "Fail", explanation=reason)
'''


# ragas reports usage analytics to a non-AWS endpoint unless this is set before its first import.
_RAGAS_TELEMETRY_OPT_OUT = """\
os.environ["RAGAS_DO_NOT_TRACK"] = "true"
"""

_RAGAS_STUB_NOTE = """\
# NOTE: package_ragas_lambda.py prepends the datasets/langchain_community stub
# prelude to this file before deployment (ragas imports both at module level;
# the adapter uses neither). Do not add those imports here.
"""

_RAGAS_ADAPTER_TEMPLATE = '''\
"""Lambda handler: {score_key} via RagasAdapter.

Deployed as an AgentCore code-based evaluator. _fields() builds the ragas sample fields
from the incoming ADOT spans, RagasAdapter scores them with the metric's own
{scoring_method}() and returns the EvaluatorOutput.

The RagasAdapter import resolves from bedrock-agentcore==<v>, which ships the
third_party adapters and is pinned in pyproject.toml by
scripts/package_ragas_lambda.py. The heavy ragas transitives are excluded by
overrides.txt rather than bundled — all handled by migration.sh (framework="ragas").
"""
{stub_note}
import json
import os

{telemetry_opt_out}
from ragas.metrics import {metric_class}
{messages_import}from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.ragas import RagasAdapter
{mapper_imports}
_REGION = os.environ.get("AWS_REGION", "us-east-1")
{component_setup}

{field_helpers}

adapter = RagasAdapter(metric={metric_class}({init_kwargs}), custom_mapper=_fields{adapter_kwargs})


@custom_code_based_evaluator()
def handler(eval_input, context=None):
    return adapter(eval_input, context)
'''

_FIELD_EXTRACTION_IMPORT = (
    "from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.span_mappers"
    ".common import FieldExtractionError\n"
)
_RAGAS_SINGLE_TURN_IMPORTS = (
    "from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.span_mappers"
    " import map_spans\n" + _FIELD_EXTRACTION_IMPORT
)
_RAGAS_MESSAGES_IMPORT = (
    "from ragas.messages import AIMessage, HumanMessage, ToolCall, ToolMessage\n"
)

# The single-turn RAGAS mapping. With no Metric Inputs section it builds exactly the fields
# the adapter's default mapping builds, so the migrated client can also send per-sample
# fields (rubrics, reference_contexts, image lists, context IDs) that no span carries.
_RAGAS_SINGLE_TURN_MAPPER = '''\
def _fields(eval_input):
    """Build the ragas sample fields, reading the sections the migrated client embeds.

    Without a Metric Inputs section these are the adapter's default fields: the reference
    comes from evaluationReferenceInputs, then the embedded Reference Answer, then the
    assertions, and the retrieved contexts from tool results, then the embedded Context,
    where a JSON chunk list keeps its chunks. Metric Inputs fields (rubrics,
    reference_contexts, image lists, context IDs) are added last and take precedence.
    """
    result = map_spans(
        _target_spans(eval_input), eval_input.reference_inputs, eval_input.target_trace_id
    )
    query, context, reference, extra = _split_user_message(result.input or "")
    if not query:
        raise FieldExtractionError("no user message found in the evaluation spans")
    fields = {"user_input": query, "response": result.actual_output}
    reference = result.expected_output or reference or "\\n".join(result.assertions or [])
    if reference:
        fields["reference"] = reference
    retrieved = result.retrieval_context or (_chunks(context) if context else None)
    if retrieved:
        fields["retrieved_contexts"] = retrieved
    fields.update(extra)
    return fields
'''

# The multi-turn RAGAS mapping. The adapter builds a multi-turn sample from the fields it is
# given, so the conversation and the reference tool calls or topics, which the migrated
# client embeds in the ADOT documents, are read here.
_RAGAS_MULTI_TURN_MAPPER = '''\
def _tool_calls(items):
    """ragas ToolCalls from {"name" or "tool", "args", "arguments" or "input_parameters"} dicts."""
    calls = []
    for item in items if isinstance(items, list) else []:
        name = (item.get("name") or item.get("tool")) if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue
        args = item.get("args", item.get("arguments", item.get("input_parameters")))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        calls.append(ToolCall(name=name, args=args if isinstance(args, dict) else {}))
    return calls


def _messages(items):
    """ragas messages from {"type" or "role", "content", "tool_calls"} dicts, in order."""
    messages = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("role") or "").lower()
        content = item.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)
        if kind in ("human", "user"):
            messages.append(HumanMessage(content=content))
        elif kind in ("ai", "assistant"):
            calls = _tool_calls(item.get("tool_calls")) or None
            messages.append(AIMessage(content=content, tool_calls=calls))
        elif kind == "tool":
            messages.append(ToolMessage(content=content))
    return messages


def _reference_fields(text):
    """The embedded reference, read by shape: tool calls, topics, or plain text."""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, list) and parsed:
        if all(isinstance(i, dict) and "name" in i for i in parsed):
            return {"reference_tool_calls": _tool_calls(parsed)}
        if all(isinstance(i, str) for i in parsed):
            return {"reference_topics": parsed}
    return {"reference": text}


def _fields(eval_input):
    """Build the ragas multi-turn sample fields from the conversation in the session.

    Each user message becomes a human turn, with the client's embedded sections stripped,
    and each assistant message an AI turn carrying its tool calls. The embedded Reference
    Answer is read by shape. Metric Inputs take precedence: user_input (the whole
    conversation), tools_called (put on the last AI turn when no turn carries any),
    reference, reference_topics and reference_tool_calls.
    """
    messages, reference, extra = [], None, {}
    for body in _iter_bodies(eval_input):
        for msg in (body.get("input") or {}).get("messages", []):
            content = (msg.get("content") or {}).get("content")
            if not content:
                continue
            text, _, found_reference, found_extra = _split_user_message(_texts(content))
            reference = found_reference or reference
            extra = found_extra or extra
            messages.append(HumanMessage(content=text))
        for msg in (body.get("output") or {}).get("messages", []):
            content = (msg.get("content") or {}).get("message")
            if content:
                # An empty list would put a bare "Tools:" line in the conversation the
                # judge reads, which the source's AIMessage(tool_calls=None) does not.
                calls = _tool_calls(msg.get("tool_calls")) or None
                messages.append(AIMessage(content=_texts(content), tool_calls=calls))
    if isinstance(extra.get("user_input"), list):
        messages = _messages(extra["user_input"])
    if not messages:
        raise FieldExtractionError("no conversation turns found in the evaluation spans")
    called = _tool_calls(extra.get("tools_called"))
    ai_turns = [i for i, message in enumerate(messages) if isinstance(message, AIMessage)]
    if called and ai_turns and not any(messages[i].tool_calls for i in ai_turns):
        last = ai_turns[-1]
        messages[last] = AIMessage(content=messages[last].content, tool_calls=called)
    fields = {"user_input": messages}
    if reference:
        fields.update(_reference_fields(reference))
    for key in ("reference", "reference_topics"):
        if extra.get(key):
            fields[key] = extra[key]
    if isinstance(extra.get("reference_tool_calls"), list):
        fields["reference_tool_calls"] = _tool_calls(extra["reference_tool_calls"])
    return fields
'''

_RAGAS_SINGLE_TURN_FIELDS = _join(_SPLIT_HELPERS, _SPAN_HELPERS, _RAGAS_SINGLE_TURN_MAPPER)
_RAGAS_MULTI_TURN_FIELDS = _join(_SPLIT_HELPERS, _EXTRACT_HELPERS, _RAGAS_MULTI_TURN_MAPPER)

# {judge_model_id}: see the note on _DEEPEVAL_MODEL_SETUP.
_RAGAS_LLM_SETUP = """\
from langchain_aws import ChatBedrockConverse
from ragas.llms import LangchainLLMWrapper

# Missing llm= makes the adapter return METRIC_ERROR for LLM-based metrics.
eval_llm = LangchainLLMWrapper(ChatBedrockConverse(
    model_id="{judge_model_id}",
    region_name=_REGION,
))
"""

# {embeddings_model} is deployer.EMBEDDINGS_MODEL, the same constant the IAM policy grants.
_RAGAS_EMBEDDINGS_SETUP = """\
# langchain_aws (NOT langchain_community — that module is stubbed in Lambda).
from langchain_aws import BedrockEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper

eval_embeddings = LangchainEmbeddingsWrapper(BedrockEmbeddings(
    model_id="{embeddings_model}",
    region_name=_REGION,
))
"""

_RAGAS_CUSTOM_TEMPLATE = '''\
"""Lambda handler: {score_key} — custom code-based evaluator.

{metric_class} cannot ship inside a ragas Lambda bundle (see mapping notes).
Field extraction below is complete (handles the service-transformed
span_events format); implement the metric logic where marked, using its
direct dependencies only (NO ragas import in this handler).
"""
import json

from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator, EvaluatorOutput


{extract_helpers}

def extract_fields(eval_input):
    """Extract (user_input, actual_output) from the session documents."""
    user_input, actual_output = "", ""
    for body in _iter_bodies(eval_input):
        for msg in (body.get("input") or {{}}).get("messages", []):
            content = (msg.get("content") or {{}}).get("content")
            if content and not user_input:
                user_input = _texts(content)
        for msg in (body.get("output") or {{}}).get("messages", []):
            content = (msg.get("content") or {{}}).get("message")
            if content:
                actual_output = _texts(content)
    return user_input, actual_output


@custom_code_based_evaluator()
def handler(eval_input, context=None):
    user_input, actual_output = extract_fields(eval_input)

    # TODO(EVAL-MIGRATION): implement the {metric_class} logic here using its
    # direct dependencies only — declare just what the metric itself needs in
    # this evaluator's pyproject.toml, NOT ragas or deepeval. Replicate the
    # original metric's exact scoring semantics. Remove this block when done.
    raise NotImplementedError("implement the {metric_class} logic before deploying")

    return EvaluatorOutput(value=score, label="Pass" if score >= 0.5 else "Fail", explanation=reason)
'''


# =============================================================================
# Input validation. mapping.json values are written into handler source that runs in the
# customer's Lambda, so none is pasted unchecked and init_kwargs admits literal values only.
# =============================================================================

#: Members of the pinned deepeval==4.2.3 enums named in _PARAM_ENUM.
_ENUM_MEMBERS = {
    "SingleTurnParams": frozenset(
        {
            "INPUT",
            "ACTUAL_OUTPUT",
            "EXPECTED_OUTPUT",
            "CONTEXT",
            "RETRIEVAL_CONTEXT",
            "METADATA",
            "TAGS",
            "TOOLS_CALLED",
            "EXPECTED_TOOLS",
            "MCP_SERVERS",
            "MCP_TOOLS_CALLED",
            "MCP_RESOURCES_CALLED",
            "MCP_PROMPTS_CALLED",
        }
    ),
}

#: Names a RAGAS handler defines, mapped to the entry flag that enables each. These are the
#: only non-literal values init_kwargs may use.
_RAGAS_COMPONENT_NAMES = {"eval_llm": "needs_llm", "eval_embeddings": "needs_embeddings"}

_LITERAL_TYPES = (str, int, float, bool, type(None))


def _metric_class(entry: dict, known: frozenset, library: str) -> str:
    """Return ``entry["class"]`` if it is one of the ``known`` classes, else raise ValueError."""
    cls = entry.get("class")
    if isinstance(cls, str) and cls in known:
        return cls
    hint = None
    if isinstance(cls, str):
        hint = next(
            (k for k in sorted(known) if k.lower() in (cls.lower(), f"{cls}metric".lower())), None
        )
    raise ValueError(
        f"metric class {cls!r} is not a {library} class this skill generates handlers for."
        + (f" Did you mean {hint!r}?" if hint else "")
    )


def _label(value: object, what: str) -> str:
    """Return ``value`` if it is a plain identifier, else raise ValueError.

    For names the handler only mentions in comments, docstrings and strings, where an
    identifier is safe because it cannot contain a quote or newline.
    """
    if isinstance(value, str) and value.isascii() and value.isidentifier() and len(value) <= 64:
        return value
    raise ValueError(
        f"{what} {value!r} must be a plain identifier (letters, digits, underscore): it is "
        "written into the generated handler source."
    )


def _is_literal(node: ast.AST, names: frozenset) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, _LITERAL_TYPES)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = node.operand
        return (
            isinstance(operand, ast.Constant)
            and isinstance(operand.value, (int, float))
            and not isinstance(operand.value, bool)
        )
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal(elt, names) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_literal(k, frozenset()) for k in node.keys) and all(
            _is_literal(v, names) for v in node.values
        )
    return isinstance(node, ast.Name) and node.id in names


def _render_init_kwargs(
    entry: dict, drop: tuple[str, ...] = (), names: frozenset = frozenset()
) -> str:
    """Re-render ``init_kwargs`` from its parse tree, admitting literal keyword values only.

    A value may also be one of ``names``, which the handler defines. Keywords in ``drop``
    are skipped because the handler supplies them, and a duplicate keyword is a SyntaxError.
    """
    raw = (entry.get("init_kwargs") or "").strip()
    if not raw:
        return ""
    call = _parse_kwargs(raw)
    if call is None:
        raise ValueError(f"init_kwargs {raw!r} does not parse as constructor keyword arguments")
    parts, refused, seen = [], [], set()
    refused += [ast.unparse(arg) for arg in call.args]
    for kw in call.keywords:
        if kw.arg in drop:
            continue
        shown = f"{kw.arg}={ast.unparse(kw.value)}" if kw.arg else f"**{ast.unparse(kw.value)}"
        if kw.arg is None or not _is_literal(kw.value, names):
            refused.append(shown)
        elif kw.arg in seen:
            raise ValueError(f"init_kwargs repeats the keyword {kw.arg!r}")
        else:
            seen.add(kw.arg)
            parts.append(shown)
    if refused:
        raise ValueError(
            f"init_kwargs for {entry.get('class')!r} contains {', '.join(refused)}, which is "
            "not a keyword argument with a literal value. Only strings, numbers, booleans, "
            "None and lists/tuples/dicts of them are copied into the generated handler, "
            "because it runs in the customer's Lambda. Remove it from init_kwargs in "
            "metrics.json and re-run classify.py and generate_handlers.py; if the metric "
            "needs an object from the source script (a schema class, a rubric), define it "
            "in the generated handler yourself and review it before deploying."
        )
    return ", ".join(parts)


def _generate_ragas_handler(entry: dict, region: str) -> str | None:
    path = entry["path"]
    if path not in ("lambda_custom", "lambda_adapter"):
        return None
    score_key = validate_score_key(entry["score_key"])
    if path == "lambda_custom":
        return _RAGAS_CUSTOM_TEMPLATE.format(
            score_key=score_key,
            metric_class=_label(entry.get("class"), "metric class"),
            extract_helpers=_EXTRACT_HELPERS,
        )
    metric_class = _metric_class(entry, RAGAS_METRIC_CLASSES, "ragas==0.4.4")
    defined = frozenset(n for n, flag in _RAGAS_COMPONENT_NAMES.items() if entry.get(flag))
    init_kwargs = _render_init_kwargs(entry, names=defined)
    setup, kwargs = [], []
    if entry.get("needs_llm"):
        setup.append(_RAGAS_LLM_SETUP.format(judge_model_id=judge_model_id(region)))
        kwargs.append("llm=eval_llm")
    if entry.get("needs_embeddings"):
        setup.append(_RAGAS_EMBEDDINGS_SETUP.format(embeddings_model=EMBEDDINGS_MODEL))
        kwargs.append("embeddings=eval_embeddings")
        # Also on the constructor: AnswerCorrectness builds its AnswerSimilarity sub-metric in
        # __post_init__, before the adapter can assign metric.embeddings.
        if "embeddings" not in _keywords(init_kwargs):
            init_kwargs = ", ".join(p for p in (init_kwargs, "embeddings=eval_embeddings") if p)
    # A multi-turn metric scores a conversation, so its fields come from every message in the
    # session rather than from the first user message alone.
    multi_turn = bool(entry.get("multi_turn"))
    return _RAGAS_ADAPTER_TEMPLATE.format(
        score_key=score_key,
        metric_class=metric_class,
        init_kwargs=init_kwargs,
        telemetry_opt_out=_RAGAS_TELEMETRY_OPT_OUT,
        stub_note=_RAGAS_STUB_NOTE,
        scoring_method="multi_turn_score" if multi_turn else "single_turn_score",
        messages_import=_RAGAS_MESSAGES_IMPORT if multi_turn else "",
        mapper_imports=_FIELD_EXTRACTION_IMPORT if multi_turn else _RAGAS_SINGLE_TURN_IMPORTS,
        component_setup="".join(setup),
        field_helpers=_RAGAS_MULTI_TURN_FIELDS if multi_turn else _RAGAS_SINGLE_TURN_FIELDS,
        adapter_kwargs="".join(f", {kwarg}" for kwarg in kwargs),
    )


def _parse_kwargs(raw: str) -> ast.Call | None:
    """Parse a raw kwargs string as a call's argument list, or None if it will not parse."""
    try:
        node = ast.parse(f"_f({raw})", mode="eval").body
    except SyntaxError:
        return None
    # The callee must be _f itself: "x)(y" parses as _f(x)(y), hiding x where no check looks.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_f":
        return node
    return None


#: Metrics whose constructor requires name=, which mapping.json carries as the entry's "name".
_NAMED_METRICS = frozenset({"GEval", "DAGMetric"})

#: Literal constructor arguments deepeval==4.2.3 requires, which only init_kwargs can supply.
#: Checked at generation, since a handler without one fails on every invocation instead.
# Metrics whose score is computed in code and whose judge model only writes the reason.
# The judge sometimes returns invalid JSON, which fails the whole evaluation with
# METRIC_ERROR, so the reason is turned off: the score is unchanged and the evaluator
# no longer fails intermittently. Only scores are compared with the source.
_REASON_ONLY_JUDGE = frozenset({"JsonCorrectnessMetric"})

_REQUIRED_INIT_KWARGS = {
    "PatternMatchMetric": ("pattern",),
    "PromptAlignmentMetric": ("prompt_instructions",),
}


def _named_kwargs(entry: dict, existing: list[str]) -> tuple[list[str], str]:
    """Render the name= of a named metric, GEval's rubric kwargs, and the enum import.

    Returns ``(kwargs, import_line)``, or ``([], "")`` for other metrics. Keywords already in
    ``existing`` are skipped: a duplicate keyword is a SyntaxError.
    """
    if entry["class"] not in _NAMED_METRICS:
        return [], ""

    call = _parse_kwargs(", ".join(k for k in existing if k))
    spelled = {kw.arg for kw in call.keywords if kw.arg} if call else set()

    kwargs: list[str] = []
    name = entry.get("name")
    if name and "name" not in spelled:
        if not isinstance(name, str):
            raise ValueError(f"name must be a string, got {name!r}")
        kwargs.append(f"name={name!r}")

    enum = _PARAM_ENUM.get(entry["class"])
    if enum is None:
        return kwargs, ""

    params = entry.get("evaluation_params")
    needs_enum = False
    if params and "evaluation_params" not in spelled:
        if not isinstance(params, (list, tuple)) or not all(isinstance(p, str) for p in params):
            raise ValueError(f"evaluation_params must be a list of strings, got {params!r}")
        # Accept "INPUT", "input", or "SingleTurnParams.INPUT" in metrics.json.
        members = [p.rsplit(".", 1)[-1].upper() for p in params]
        unknown = sorted(set(members) - _ENUM_MEMBERS[enum])
        if unknown:
            raise ValueError(
                f"evaluation_params {unknown} are not {enum} members in deepeval==4.2.3. "
                f"Valid: {', '.join(sorted(_ENUM_MEMBERS[enum]))}"
            )
        kwargs.append("evaluation_params=[" + ", ".join(f"{enum}.{m}" for m in members) + "]")
        needs_enum = True

    for field in ("criteria", "evaluation_steps"):
        value = entry.get(field)
        if value and field not in spelled:
            kwargs.append(f"{field}={value!r}")

    import_line = f"\nfrom deepeval.test_case import {enum}" if needs_enum else ""
    return kwargs, import_line


def _keywords(raw: str) -> set[str]:
    """The keyword names in a rendered kwargs string."""
    call = _parse_kwargs(raw) if raw else None
    return {kw.arg for kw in call.keywords if kw.arg} if call else set()


def _render_variants(entry: dict, drop: tuple[str, ...]) -> dict[str, str]:
    """Render each variant's kwargs the way init_kwargs is rendered: literal values only.

    mapping.json can be edited by hand, so the names are checked again here.
    """
    variants = entry.get("variants")
    if variants is None:
        return {}
    if not isinstance(variants, dict) or not variants:
        raise ValueError(
            f"variants must map variant names to init_kwargs strings, got {variants!r}"
        )
    rendered = {}
    for name, raw in variants.items():
        named = isinstance(name, str) and VARIANT_NAME_PATTERN.fullmatch(name)
        if not named or not isinstance(raw, str):
            raise ValueError(
                f"variant {name!r} must match {VARIANT_NAME_PATTERN.pattern} and map to an "
                "init_kwargs string"
            )
        try:
            rendered[name] = _render_init_kwargs(
                {"class": entry.get("class"), "init_kwargs": raw}, drop=drop
            )
        except ValueError as exc:
            raise ValueError(f"variant {name!r}: {exc}") from None
    return rendered


def _variants_block(score_key: str, variants: dict[str, str]) -> str:
    """The handler's _VARIANTS table and the _variant() helper that picks one per case."""
    rows = "".join(f"    {name!r}: dict({kwargs}),\n" for name, kwargs in sorted(variants.items()))
    return (
        "\n\n# Constructor arguments the source passes per case. Each case names its variant in\n"
        f'# its Metric Inputs section, as {{"variants": {{{score_key!r}: <variant>}}}}.\n'
        f"_VARIANT_KEY = {score_key!r}\n"
        f"_VARIANTS = {{\n{rows}}}\n"
        f"{_VARIANT_HELPER}"
    )


def generate_handler(
    entry: dict, framework: str = "deepeval", region: str | None = None
) -> str | None:
    """Render the handler source for one mapping entry (None for non-Lambda paths).

    ``region`` picks the judge model's inference profile; defaults to :func:`default_region`.
    """
    if region is None:
        region = default_region()
    if framework == "ragas" or entry.get("adapter") == "RagasAdapter":
        return _generate_ragas_handler(entry, region)
    path = entry["path"]
    if path not in ("lambda_adapter", "lambda_custom"):
        return None
    score_key = validate_score_key(entry["score_key"])
    if path == "lambda_adapter":
        metric_class = _metric_class(entry, DEEPEVAL_METRIC_CLASSES, "deepeval==4.2.3")
        needs_model = entry.get("needs_model", True)
        source_object = DEEPEVAL_SOURCE_OBJECT.get(metric_class)
        # The handler supplies its own model, async_mode and source object, so the source
        # script's values for them are dropped.
        drop: tuple[str, ...] = ("model", "async_mode") if needs_model else ()
        if metric_class in _REASON_ONLY_JUDGE:
            drop += ("include_reason",)
        if source_object:
            drop += (source_object[0],)
        raw = _render_init_kwargs(entry, drop=drop)
        variants = _render_variants(entry, drop)
        # With variants, each must supply what init_kwargs does not.
        for name, variant_kwargs in (variants or {"": ""}).items():
            spelled = _keywords(raw) | _keywords(variant_kwargs)
            missing = [k for k in _REQUIRED_INIT_KWARGS.get(metric_class, ()) if k not in spelled]
            if missing:
                where = f"init_kwargs or variant {name!r}" if name else "init_kwargs"
                raise ValueError(
                    f"{metric_class} requires {', '.join(f'{k}=' for k in missing)} in {where}. "
                    "Copy the value from the source script into metrics.json and re-run "
                    "classify.py."
                )
        kwargs = [k for k in (raw,) if k]
        named_kwargs, param_import = _named_kwargs(entry, kwargs)
        kwargs = named_kwargs + kwargs
        variant_arg = "variant" if variants else ""
        source_objects = ""
        if source_object:
            kwarg, what = source_object
            kwargs.append(f"{kwarg}=_source_{kwarg}({variant_arg})")
            variants_note = (
                "\n# The source builds one per case: return the one for `variant`, one of "
                + ", ".join(repr(n) for n in sorted(variants))
                + "."
            )
            source_objects = _SOURCE_OBJECT_TEMPLATE.format(
                metric_class=metric_class,
                kwarg=kwarg,
                what=what,
                params=variant_arg,
                variants_note=variants_note if variants else "",
            )
        if needs_model:
            # LLM metrics need async_mode=False in Lambda (event loop conflict).
            kwargs.append("model=_model")
            kwargs.append("async_mode=False")
        if metric_class in _REASON_ONLY_JUDGE:
            kwargs.append("include_reason=False")
        if variants:
            # A keyword passed twice is a TypeError on every invocation.
            passed = _keywords(", ".join(kwargs))
            for name, variant_kwargs in variants.items():
                clash = sorted(passed & _keywords(variant_kwargs))
                if clash:
                    raise ValueError(
                        f"variant {name!r} sets {clash}, which init_kwargs or the handler "
                        "already passes. Set each keyword in one place."
                    )
            kwargs.append("**_VARIANTS[variant]")
        return _ADAPTER_TEMPLATE.format(
            variants_block=_variants_block(score_key, variants) if variants else "",
            metric_params=variant_arg,
            handler_body=_VARIANT_HANDLER_BODY if variants else _HANDLER_BODY,
            score_key=score_key,
            metric_class=metric_class,
            env_prelude=_DEEPEVAL_ENV_PRELUDE,
            model_import=_DEEPEVAL_MODEL_IMPORT if needs_model else "",
            param_import=param_import,
            model_setup=(
                _DEEPEVAL_MODEL_SETUP.format(judge_model_id=judge_model_id(region), region=region)
                if needs_model
                else ""
            ),
            source_objects=source_objects,
            test_case_helpers=_DEEPEVAL_TEST_CASE_HELPERS,
            async_note=(
                "    # async_mode=False is MANDATORY in Lambda (event loop conflict otherwise).\n"
                if needs_model
                else ""
            ),
            metric_kwargs=", ".join(kwargs),
        )
    if "deterministic" in (entry.get("notes") or "").lower():
        # The class names a rule the agent implements; the template only mentions it.
        return _DETERMINISTIC_TEMPLATE.format(
            score_key=score_key,
            metric_class=_label(entry.get("class"), "metric class"),
            extract_helpers=_EXTRACT_HELPERS,
        )
    raise ValueError(
        "path lambda_custom has a DeepEval template only for a deterministic rule, selected "
        "when the entry's notes contain the word deterministic. DeepEval multi-turn metrics "
        "are not supported in this version."
    )


def _enforce_classifier_routes(mapping: dict) -> None:
    """Refuse mapping.json entries that route a DeepEval or RAGAS metric to llm_judge.

    classify.py deploys every DeepEval and RAGAS metric as a Lambda that runs the metric's
    own code through the SDK adapter. An LLM-as-a-Judge stand-in diverges from it.
    """
    rerouted = [
        f"{key} ({entry.get('class')})"
        for key, entry in mapping.items()
        if entry.get("path") == "llm_judge"
        and entry.get("class") in DEEPEVAL_METRIC_CLASSES | RAGAS_METRIC_CLASSES
    ]
    if rerouted:
        raise SystemExit(
            "[handlers] ERROR: DeepEval/RAGAS metric(s) routed to llm_judge in mapping.json: "
            f"{', '.join(rerouted)}. These run their own code through the SDK adapter in "
            "Lambda; an LLM-as-a-Judge stand-in diverges from the source. Never hand-edit "
            "'path' or 'adapter' in mapping.json — re-run classify.py."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mapping", required=True, help="mapping.json from classify.py")
    parser.add_argument("--names", required=True, help="names.json from names.py")
    parser.add_argument("--output-dir", default="handlers", help="handler output directory")
    parser.add_argument(
        "--region",
        default=default_region(),
        # argparse also applies type= to a string default, so a bad $AWS_REGION fails here too.
        type=_region_arg,
        help=(
            "deploy region, selecting the judge model's inference-profile prefix "
            "(us/eu/apac/au/jp). Must match the region deployer.py is run with, or the "
            "IAM policy will not cover the model the handler invokes. "
            "Defaults to $AWS_REGION, then $AWS_DEFAULT_REGION, then us-east-1."
        ),
    )
    args = parser.parse_args()

    with open(args.mapping) as f:
        mapping = json.load(f)
    with open(args.names) as f:
        names = json.load(f)

    _enforce_classifier_routes(mapping)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    evaluators = []
    todos = []

    framework = names.get("framework", "deepeval")
    for score_key, entry in mapping.items():
        try:
            source = generate_handler(entry, framework=framework, region=args.region)
        except ValueError as exc:
            raise SystemExit(f"[handlers] ERROR: {score_key!r}: {exc}") from None
        if source is None:
            continue  # builtin, llm_judge or unknown path: no Lambda handler
        evaluator_name = names["evaluators"].get(score_key)
        if not evaluator_name:
            raise SystemExit(
                f"[handlers] ERROR: no evaluator name for {score_key!r} in {args.names} — "
                "regenerate names.json with all code-based metric keys"
            )
        # score_key becomes a file name and evaluator_name is written into migration.sh.
        try:
            validate_score_key(score_key)
            validate_evaluator_name(evaluator_name)
        except ValueError as exc:
            raise SystemExit(f"[handlers] ERROR: {exc}") from None
        handler_file = f"{score_key}_handler.py"
        handler_path = out_dir / handler_file
        if handler_path.resolve().parent != out_dir.resolve():
            raise SystemExit(f"[handlers] ERROR: {handler_path} resolves outside {out_dir}")
        handler_path.write_text(source)
        # Syntax-check the handler with ast.parse; compile() is not allowed.
        ast.parse(source, filename=handler_file)
        evaluators.append(
            {
                "name": evaluator_name,
                "level": entry.get("level", "TRACE"),
                "handler_file": handler_file,
            }
        )
        marker = ""
        if "TODO(EVAL-MIGRATION)" in source:
            todos.append(handler_file)
            marker = "  [TODO: copy code from the source script]"
        print(f"[handlers] {handler_file}: {entry['path']} ({entry['class']}){marker}")

    manifest = out_dir / "evaluators.json"

    # Validate before writing the manifest so a rejected value never reaches disk.
    _VALID_LEVELS = {"TRACE", "SESSION", "TOOL_CALL"}
    for entry in evaluators:
        if entry["level"] not in _VALID_LEVELS:
            # Don't default to TRACE: an evaluator at the wrong level silently scores nothing.
            raise SystemExit(
                f"[handlers] ERROR: invalid level '{entry['level']}' for evaluator "
                f"'{entry['name']}'. Expected one of {sorted(_VALID_LEVELS)}. Fix the "
                "metric's level in mapping.json (classify.py assigns SESSION for "
                "conversation-scoped metrics and TRACE otherwise) rather than letting "
                "it default."
            )
        if not entry["handler_file"].endswith(".py"):
            print(
                f"[handlers] WARNING: handler_file '{entry['handler_file']}' for "
                f"'{entry['name']}' doesn't look like a Python file."
            )
    manifest.write_text(json.dumps(evaluators, indent=2))
    print(f"[handlers] {len(evaluators)} handler(s) → {out_dir}/, manifest: {manifest}")

    # The agent reads this output, so show the exact deployer call.
    print("\n[handlers] NEXT STEP: generate migration.sh using the manifest:")
    print("  from scripts.deployer import generate_migration_sh")
    print(f"  entries = json.load(open('{manifest}'))")
    print("  evaluator_names = [(e['name'], e['level'], e['handler_file']) for e in entries]")
    print(
        f"  generate_migration_sh(evaluator_names, '{out_dir}', 'deploy', "
        f"project_name=names['project_name'], framework=names['framework'])"
    )

    if todos:
        print(
            f"\n[handlers] ACTION REQUIRED: complete the TODO(EVAL-MIGRATION) blocks in "
            f"{todos}, copying from the source script VERBATIM, before generating "
            "migration.sh. migration.sh refuses to deploy a handler that still has one."
        )


if __name__ == "__main__":
    main()
