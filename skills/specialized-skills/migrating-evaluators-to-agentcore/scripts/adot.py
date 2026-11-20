#!/usr/bin/env python3
"""ADOT document construction, score extraction and evaluator ID resolution.

Format mistakes fail without a useful error: a flat log body is ignored ("no spans to
evaluate") and context outside the first user message scores 0.0. Reuse this format (see
references/adot-domain-knowledge.md) rather than re-deriving it.

Prefer the SDK converter when OTel spans exist:
    convert_strands_to_adot(raw_spans)  # from bedrock_agentcore.evaluation
Use build_adot_docs() for pre-generated traces or when the converter is unavailable.

generate_client_script.py copies the code between the INLINE markers verbatim into the
generated ``*_agentcore.py`` script, which therefore needs no skill files at runtime.
"""

# === ADOT_INLINE_BEGIN ===
import json as _json
import time as _time
import uuid as _uuid

# AgentCore accepts only a few instrumentation scopes; this one works for synthetic documents.
_ADOT_SCOPE = "strands.telemetry.tracer"

# The RagasAdapter splits context and reference out of the first user message on these exact
# strings, so do not change them.
_CONTEXT_SEPARATOR = "\n\nContext:\n"
_REFERENCE_SEPARATOR = "\n\nReference Answer:\n"
# Per-sample metric fields (rubrics, image lists, tool calls, variants) as JSON. Send it only
# to the evaluators that read it (METRIC_INPUTS_METRICS in the generated client): any other
# handler would read the section as part of the reference.
_METRIC_INPUTS_SEPARATOR = "\n\nMetric Inputs:\n"

_SECTION_SEPARATORS = (
    _CONTEXT_SEPARATOR,
    _REFERENCE_SEPARATOR,
    _METRIC_INPUTS_SEPARATOR,
)


def _reject_separators(value, field):
    if isinstance(value, str):
        for separator in _SECTION_SEPARATORS:
            if separator in value:
                raise ValueError(
                    f"{field} contains the section separator {separator!r}. The evaluator "
                    f"splits the first user message on the first occurrence, so this would "
                    f"silently re-partition the fields and score the metric against the "
                    f"wrong text. Strip or rephrase it in the case data."
                )
    return value


# Well-known labels, used when the evaluator's own ratingScale does not resolve a label.
LABEL_TO_SCORE = {
    "correct": 1.0,
    "incorrect": 0.0,
    "faithful": 1.0,
    "unfaithful": 0.0,
    "relevant": 1.0,
    "irrelevant": 0.0,
    "concise": 1.0,
    "verbose": 0.0,
    "helpful": 1.0,
    "unhelpful": 0.0,
    "pass": 1.0,
    "fail": 0.0,
    "yes": 1.0,
    "no": 0.0,
}


def build_adot_docs(
    user_input,
    agent_response,
    context=None,
    reference=None,
    metric_inputs=None,
    session_id=None,
    service_name="eval-migration",
):
    """Build a minimal ADOT document pair, ``[span_doc, log_record_doc]``, for one case.

    Context and reference go in the first user message, the only place LLM judges and the
    RagasAdapter read them. A change to this shape fails quietly, as "no spans to evaluate"
    or 0.0 scores.

    Args:
        context: retrieval context, tool data or conversation history. A list of ranked chunks
            is embedded as a JSON array so rank-aware metrics (e.g. LLMContextPrecision) keep
            the chunk boundaries.
        reference: ground truth. A JSON list of ``{"name": ..., "args": ...}`` objects is read
            as reference tool calls, and a JSON list of strings as reference topics.
        metric_inputs: per-sample metric fields such as ``{"rubrics": ...}``. Include them only
            for evaluators that read this section; other evaluators do not strip it.
        session_id: stable session ID; random if omitted.
    """
    if session_id is None:
        session_id = str(_uuid.uuid4())
    user_content = _reject_separators(user_input, "user_input")
    if context:
        if isinstance(context, (list, tuple)):
            # JSON, not a Python repr, so the adapter can recover the ranked chunk list.
            context = _json.dumps(list(context))
        else:
            context = _reject_separators(context, "context")
        user_content += f"{_CONTEXT_SEPARATOR}{context}"
    if reference:
        # Must follow the context: the adapter splits off the reference first, then the context.
        if isinstance(reference, (list, dict)):
            # JSON, not a Python repr, so the handler's json.loads() recovers the structure.
            reference = _json.dumps(reference)
        else:
            reference = _reject_separators(reference, "reference")
        user_content += f"{_REFERENCE_SEPARATOR}{reference}"
    if metric_inputs:
        # Last section: the generated handlers split it off before any other parsing.
        user_content += f"{_METRIC_INPUTS_SEPARATOR}{_json.dumps(metric_inputs)}"

    trace_id = session_id.replace("-", "")[:32].ljust(32, "0")
    span_id = trace_id[:16]
    now_ns = int(_time.time() * 1e9)
    resource = {"attributes": {"service.name": service_name, "session.id": session_id}}

    span_doc = {
        "resource": resource,
        "scope": {"name": _ADOT_SCOPE, "version": "1.0.0"},
        "traceId": trace_id,
        "spanId": span_id,
        "flags": 3,
        "name": "invoke_agent",
        "kind": "INTERNAL",
        "startTimeUnixNano": now_ns - 1_000_000_000,
        "endTimeUnixNano": now_ns,
        "durationNano": 1_000_000_000,
        "attributes": {
            "gen_ai.operation.name": "invoke_agent",
            "session.id": session_id,
        },
        "status": {"code": "OK"},
    }
    log_doc = {
        "resource": resource,
        "scope": {"name": _ADOT_SCOPE},
        "timeUnixNano": now_ns,
        "observedTimeUnixNano": now_ns + 100_000,
        "severityNumber": 9,
        "severityText": "",
        "body": {
            "input": {
                "messages": [
                    {"content": {"content": _json.dumps([{"text": user_content}])}, "role": "user"}
                ]
            },
            "output": {
                "messages": [
                    {
                        "content": {
                            "message": _json.dumps([{"text": agent_response}]),
                            "finish_reason": "end_turn",
                        },
                        "role": "assistant",
                    }
                ]
            },
        },
        "attributes": {"event.name": _ADOT_SCOPE},
        "flags": 1,
        "traceId": trace_id,
        "spanId": span_id,
    }
    return [span_doc, log_doc]


def label_scores_from_config(config):
    """Derive label -> score from an evaluator's own ratingScale.

    Numerical scales carry their own values; categorical scales are ordered best-first, so the
    i-th of N labels scores (N-1-i)/(N-1).
    """
    scale = (config or {}).get("llmAsAJudge", {}).get("ratingScale", {})
    numerical = scale.get("numerical") or []
    if numerical:
        return {
            e["label"].lower(): float(e["value"])
            for e in numerical
            if e.get("label") and e.get("value") is not None
        }
    labels = [e["label"].lower() for e in (scale.get("categorical") or []) if e.get("label")]
    if not labels:
        return {}
    if len(labels) == 1:
        return {labels[0]: 1.0}
    derived = {lb: (len(labels) - 1 - i) / (len(labels) - 1) for i, lb in enumerate(labels)}
    # Only a two-label scale has unambiguous semantics, so the table is a valid
    # cross-check: a mismatch means worst-first ordering, which inverts every score.
    if len(labels) == 2:
        for lb, sc in derived.items():
            known = LABEL_TO_SCORE.get(lb)
            if known is not None and known != sc:
                raise RuntimeError(
                    f"ratingScale {labels!r} looks ordered worst-first: {lb!r} would "
                    f"score {sc} but means {known} — list the best label first"
                )
    return derived


def fetch_label_scores(cp_client, evaluator_id):
    """Read a deployed evaluator's ratingScale to map its categorical labels.

    Returns {} if GetEvaluator fails (e.g. not permitted) or the evaluator has no rating scale.
    """
    try:
        config = cp_client.get_evaluator(evaluatorId=evaluator_id).get("evaluatorConfig", {})
    except Exception:
        return {}
    return label_scores_from_config(config)


def extract_score(response, label_scores=None):
    """Return the mean score across the results of an evaluate() response.

    Categorical labels map through label_scores (see fetch_label_scores), then LABEL_TO_SCORE.
    Raises on evaluator errors and unmapped labels rather than recording a guessed score.
    """
    results = response.get("evaluationResults", [])
    if not results:
        raise RuntimeError(f"evaluator returned no results: {response}")
    scores = []
    for r in results:
        if r.get("errorCode") or r.get("error"):
            raise RuntimeError(f"evaluator error: {r}")
        if r.get("value") is not None:
            scores.append(float(r["value"]))
        elif r.get("label"):
            label = r["label"].lower()
            score = (label_scores or {}).get(label, LABEL_TO_SCORE.get(label))
            if score is None:
                raise RuntimeError(
                    f"unmapped categorical label {label!r} — the evaluator's own "
                    "ratingScale did not resolve it (is bedrock-agentcore:GetEvaluator "
                    "permitted?); otherwise add the label to LABEL_TO_SCORE"
                )
            scores.append(score)
    if not scores:
        raise RuntimeError(f"no numerical values or labels in results: {results}")
    return sum(scores) / len(scores)


def resolve_evaluator_id(client, name_fragment, status_filter="ACTIVE"):
    """Return the deployed evaluator ID matching name_fragment, or None.

    Pass the project-scoped fragment ``{project}_{evaluator_name}``; a bare evaluator name can
    match evaluators from other deployments. Prefix matches win over substring matches, and
    within each, an evaluator with status ``status_filter`` wins. Reads every page, because a
    new evaluator is often not on the first one.
    """
    next_token = None
    prefix_fallback = None
    substring_active = None
    substring_fallback = None
    while True:
        kwargs: dict[str, str] = {}
        if next_token:
            kwargs["nextToken"] = next_token
        response = client.list_evaluators(**kwargs)
        for e in response.get("evaluators", []):
            eid = e.get("evaluatorId", "")
            if not name_fragment or name_fragment not in eid:
                continue
            is_active = status_filter is None or e.get("status") == status_filter
            if eid.startswith(name_fragment):
                if is_active:
                    return eid  # best possible match; stop paging
                prefix_fallback = prefix_fallback or eid
            elif is_active:
                substring_active = substring_active or eid
            else:
                substring_fallback = substring_fallback or eid
        next_token = response.get("nextToken")
        if not next_token:
            break
    return prefix_fallback or substring_active or substring_fallback


# === ADOT_INLINE_END ===


if __name__ == "__main__":
    # Smoke test: build a doc pair and validate the structural rules.
    docs = build_adot_docs(
        "What causes earthquakes?",
        "Tectonic plate movement along fault lines.",
        context="Earthquakes occur when plates slip.",
        reference="Plates slipping along faults release seismic energy.",
    )
    span, log = docs
    assert span["flags"] == 3 and span["kind"] == "INTERNAL"
    assert span["status"]["code"] == "OK"
    assert span["attributes"]["gen_ai.operation.name"] == "invoke_agent"
    assert log["flags"] == 1
    inner = _json.loads(log["body"]["input"]["messages"][0]["content"]["content"])
    text = inner[0]["text"]
    assert text.startswith("What causes earthquakes?")
    # Round-trip: split with the adapter's exact separators and recover fields
    head, _, ref = text.partition(_REFERENCE_SEPARATOR)
    query, _, ctx = head.partition(_CONTEXT_SEPARATOR)
    assert query == "What causes earthquakes?"
    assert ctx == "Earthquakes occur when plates slip."
    assert ref == "Plates slipping along faults release seismic energy."
    assert extract_score({"evaluationResults": [{"value": 0.75}]}) == 0.75
    # List context round-trips as a JSON array preserving chunk order
    chunks = ["plates slip", "faults release energy", "unrelated chunk"]
    span2, log2 = build_adot_docs("q?", "a.", context=chunks)
    inner2 = _json.loads(log2["body"]["input"]["messages"][0]["content"]["content"])
    _, _, ctx2 = inner2[0]["text"].partition(_CONTEXT_SEPARATOR)
    assert _json.loads(ctx2) == chunks
    assert extract_score({"evaluationResults": [{"label": "correct", "value": None}]}) == 1.0
    try:
        extract_score({"evaluationResults": [{"errorCode": "MISSING_COMPONENT"}]})
        raise AssertionError("expected RuntimeError on evaluator error")
    except RuntimeError:
        pass
    print("[adot] all structural checks passed")
