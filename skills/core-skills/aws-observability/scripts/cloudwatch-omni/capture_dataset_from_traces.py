#!/usr/bin/env python3
"""Turn CloudWatch Omni traces into an AgentCore evaluation dataset.

Bundled skill helper (retrieved via the skill's supplementary-file mechanism and run
with the agent's shell) for Section 5, Step B "build a dataset from traces". For each
trace it queries spans from CloudWatch Omni (traces.default) via Omni SQL, reshapes
them into one example (root-span COALESCE for the input, last-finishing AGENT span for the
expected response, ordered TOOL-name trajectory with adjacent dupes collapsed,
scenario_id/metadata provenance), validates it, and writes the batch into a NEW dataset
(--mode create) or an EXISTING one (--mode add). Prints a compact JSON receipt only —
raw spans never leave this process (kept out of the model's context).

--mode create always creates an AGENTCORE_EVALUATION_PREDEFINED_V1 dataset. --mode add
first reads the target dataset's immutable schemaType with get-dataset and renders the
examples in the shape that schema declares — PREDEFINED (nested `turns`) or
THIRD_PARTY_EVALUATION_V1 (flat `input`/`expected_output`, what the console writes for a
dataset created from traces). The two shapes are not interchangeable and validation is
all-or-nothing, so a dataset declaring any other schema is refused by name instead.

Requires boto3 + caller AWS credentials with cloudwatch-omni (Omni SQL query) +
bedrock-agentcore-control (dataset write). The caller must have an access grant on the
Space and cloudwatch:StartQuery / cloudwatch:GetQueryResults permissions.

Creating/extending a dataset is a real resource write. This helper refuses to write unless
the caller passes --i-have-confirmed, asserting the user confirmed this write. The flag is a
caller-side assertion, not a verification: it stops an accidental or unconfirmed run, but the
caller is responsible for adding it only AFTER the user has actually confirmed.

Examples:
  python capture_dataset_from_traces.py --mode create --dataset-name checkout_regressions \
      --trace-ids 6a7f...,6a80... --region us-east-1 --i-have-confirmed
  python capture_dataset_from_traces.py --mode add --dataset-id my_ds-AbC123 \
      --trace-ids 6a81... --i-have-confirmed
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import NoReturn
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# String-valued attribute keys only (COALESCE order). The OTel GenAI-semconv
# `gen_ai.input.messages`/`gen_ai.output.messages` are structured ARRAYS, not strings,
# so they're intentionally excluded — treating them as a plain string would either be
# dead (non-str skipped) or inject a raw serialized-array blob as the turn text.
INPUT_KEYS = ("input.value", "gen_ai.input_value")
OUTPUT_KEYS = ("output.value", "gen_ai.output_value")
PREDEFINED_SCHEMA = "AGENTCORE_EVALUATION_PREDEFINED_V1"
THIRD_PARTY_SCHEMA = "THIRD_PARTY_EVALUATION_V1"
# --mode create always creates a PREDEFINED dataset; --mode add renders into whichever of
# these two the target dataset declares. Any other schemaType (e.g. the SIMULATED one, which
# needs an author-written actor_profile.goal) cannot be derived from a trace at all.
CREATE_SCHEMA_TYPE = PREDEFINED_SCHEMA
ADD_SCHEMAS = (PREDEFINED_SCHEMA, THIRD_PARTY_SCHEMA)
MAX_TRACES = 25  # single write batch; excess is reported, never silently dropped
SPAN_ROW_LIMIT = 1000  # fetch LIMIT+1 (1001) so an exactly-full result is detectable as truncated
# Service limits (bedrock-agentcore-control datasets): each example must serialize to <= 1 MB
# (a 400 on the whole batch otherwise), and a dataset holds at most 1000 examples in total
# (a write past that is a 402 ServiceQuotaExceededException).
MAX_EXAMPLE_BYTES = 1_000_000
MAX_DATASET_EXAMPLES = 1000
QUERY_POLL_ATTEMPTS = (
    150  # × 2s = up to 5 min for the (heavy: 25 traces / 30-day) query to complete
)
# Trace ids are hex; validate before interpolating into the Omni SQL query string.
_TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{1,64}$")


def _die(payload) -> NoReturn:
    """Print an error receipt to stdout (so the agent sees it) and exit non-zero."""
    print(json.dumps(payload))
    sys.exit(1)


# ---- pure conversion (same mapping as references/dataset-from-traces.md) ----
def _attr_text(span, keys):
    attrs = (span or {}).get("attributes") or {}
    for k in keys:
        v = attrs.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _scan(spans, keys):
    for s in spans:
        t = _attr_text(s, keys)
        if t:
            return t
    return None


def _root(spans):
    return next((s for s in spans if not s.get("parentSpanId")), spans[0] if spans else None)


def _nano_key(v):
    """Sort key for a nanosecond timestamp string: compare by magnitude, not lexically."""
    return (len(v), v) if isinstance(v, str) else (0, "")


def _final_output(spans):
    """The trace's final answer: output of the last-FINISHING AGENT span.

    Ranking on *end* time, not start time, is the point: the span that produced the answer is
    the outermost one, which starts early and finishes last. Ordering by start time instead
    picks the innermost leaf the framework happened to invoke last — on a LangGraph trace that
    is the conditional-edge node (`should_continue`), whose output is the routing token
    `__end__`, and the helper would store that 7-character token as ground truth for every
    example.

    AGENT kind is preferred over the root span because the root is so often neither: on an
    HTTP-served agent it is the `POST` span, which carries no output at all, and on a trace
    whose spans are all parented the root fallback is the earliest graph span, whose output is
    the whole accumulated graph state rather than the answer. When the root *is* the agent span
    it also ends last among AGENT spans, so it is still selected. Falls back to the root, then
    to the last-finishing span of any kind, for frameworks that emit no span kind.
    """
    by_end = sorted(spans, key=lambda s: _nano_key(s.get("end")))
    agents = [s for s in by_end if _span_kind(s) == "AGENT"]
    for s in reversed(agents):
        t = _attr_text(s, OUTPUT_KEYS)
        if t:
            return t
    return _attr_text(_root(spans), OUTPUT_KEYS) or _scan(list(reversed(by_end)), OUTPUT_KEYS)


def _collapse_adjacent(items):
    out: list = []
    for x in items:
        if not out or out[-1] != x:
            out.append(x)
    return out


def _span_kind(s):
    a = s.get("attributes") or {}
    return a.get("openinference.span.kind") or a.get("aws.genai.span_kind")


def to_example(trace_id, spans, partial=False):
    spans = sorted(spans, key=lambda s: _nano_key(s.get("ts")))  # start-time order
    root = _root(spans)
    turn = {"input": _attr_text(root, INPUT_KEYS) or _scan(spans, INPUT_KEYS) or ""}
    out = _final_output(spans)
    if out:
        turn["expected_response"] = out
    session_id = next(
        (
            s["attributes"].get("session.id")
            for s in spans
            if (s.get("attributes") or {}).get("session.id")
        ),
        None,
    )
    metadata = {"sourceTraceId": trace_id}
    if session_id:
        metadata["sessionId"] = session_id
    if partial:
        metadata["partial"] = True
    example = {"scenario_id": trace_id, "turns": [turn], "metadata": metadata}
    tools = [
        (s.get("attributes") or {}).get("tool.name")
        for s in spans
        if _span_kind(s) == "TOOL" and (s.get("attributes") or {}).get("tool.name")
    ]
    trajectory = _collapse_adjacent(tools)
    if trajectory:
        example["expected_trajectory"] = trajectory
    return example


def to_third_party(example):
    """Re-render a PREDEFINED example in the THIRD_PARTY_EVALUATION_V1 shape.

    That schema is flat: the turn's `input` sits at the top level (the service rejects the
    whole batch with "Required field 'input' is missing from example content" when it is
    nested in `turns`) and the ground-truth response is `expected_output`. `scenario_id`,
    `metadata` and `expected_trajectory` carry over unchanged — the same shape the console
    writes when it builds a dataset from traces. Trace-derived examples are always
    single-turn, so the flattening is lossless.
    """
    turn = (example.get("turns") or [{}])[0]
    flat = {"input": turn.get("input"), "scenario_id": example.get("scenario_id")}
    if turn.get("expected_response"):
        flat["expected_output"] = turn["expected_response"]
    if example.get("metadata"):
        flat["metadata"] = example["metadata"]
    if example.get("expected_trajectory"):
        flat["expected_trajectory"] = example["expected_trajectory"]
    return flat


def invalid(example, schema_type=PREDEFINED_SCHEMA):
    """Return an error string if the example fails this schema's gate, else None.

    Each schema keeps the input in a different place, so the gate has to know which one the
    example was rendered for: PREDEFINED nests it under `turns[0].input`, THIRD_PARTY keeps it
    top-level. The service only checks that the field is *present* on a third-party dataset —
    an empty input is a useless example either way, so reject it here.
    """
    if schema_type == THIRD_PARTY_SCHEMA:
        val = example.get("input")
        missing_input = "missing a non-empty input"
    else:
        turns = example.get("turns")
        if not turns:
            return "no turns"
        val = turns[0].get("input")
        missing_input = "turn 1 missing a non-empty input"
    if not ((isinstance(val, str) and val.strip()) or (isinstance(val, dict) and val)):
        return missing_input
    # The service rejects the WHOLE batch if any single example exceeds 1 MB serialized.
    size = len(json.dumps(example, default=str).encode("utf-8"))
    if size > MAX_EXAMPLE_BYTES:
        return "example serializes to %d bytes; the service caps one example at %d bytes" % (size, MAX_EXAMPLE_BYTES)
    return None


# ---- span fetch via CloudWatch Omni SQL (traces.default) ----
def fetch_spans_by_trace(omni, trace_ids, window_days):
    """Fetch spans for the trace ids via Omni SQL, sorted by (traceId, startTimeUnixNano).

    Returns (by_trace, truncated, boundary). Because the query sorts by traceId asc, a
    row-cap hit only ever cuts the *last* returned trace mid-way — every lower-sorted trace
    is complete, and every higher-sorted (requested) trace was never reached. So on
    truncation only `boundary` (the last returned trace id) is partial; the caller flags the
    unreached traces distinctly from genuine misses.
    """
    quoted = ", ".join("'%s'" % t for t in trace_ids)  # ids are validated hex — safe to interpolate
    sql = (
        "SELECT traceId, spanId, parentSpanId, startTimeUnixNano, endTimeUnixNano, "
        "attributes['openinference.span.kind'] AS oi_span_kind, "
        "attributes['aws.genai.span_kind'] AS aws_genai_span_kind, "
        "attributes['tool.name'] AS tool_name, "
        "attributes['input.value'] AS input_value, "
        "attributes['output.value'] AS output_value, "
        # String-valued gen_ai.* fallbacks — the *.messages array keys are omitted
        # (they are not plain strings; the COALESCE in _attr_text skips non-str values).
        "attributes['gen_ai.input_value'] AS gen_ai_input_value, "
        "attributes['gen_ai.output_value'] AS gen_ai_output_value, "
        "attributes['session.id'] AS session_id_attr "
        "FROM \"traces.default\" "
        "WHERE traceId IN (%s) "
        "AND \"@timestamp\" BETWEEN NOW() - INTERVAL '%d days' AND NOW() "
        "ORDER BY traceId ASC, startTimeUnixNano ASC "
        # fetch one past the cap so an exactly-full result isn't mistaken for truncation
        "LIMIT %d"
    ) % (quoted, window_days, SPAN_ROW_LIMIT + 1)

    rows: list = []
    truncated = False
    session_id = None
    try:
        try:
            session_id = omni.start_telemetry_query_session(
                sessionName="capture-dataset"
            )["sessionId"]
        except (BotoCoreError, ClientError) as e:
            _die({"error": "Omni start_telemetry_query_session failed: %s" % e})

        try:
            qid = omni.start_telemetry_query(
                sessionId=session_id, queryString=sql
            )["queryId"]
        except (BotoCoreError, ClientError) as e:
            _die({"error": "Omni start_telemetry_query failed: %s" % e})

        # Phase 1: poll for completion (status only; rows are not stable until Complete)
        status = None
        for _ in range(QUERY_POLL_ATTEMPTS):
            time.sleep(2)
            try:
                poll = omni.get_telemetry_query_results(queryId=qid, maxResults=1)
            except (BotoCoreError, ClientError) as e:
                _die({"error": "Omni get_telemetry_query_results failed: %s" % e})
            status = poll.get("status")
            if status in ("Complete", "Failed", "Cancelled"):
                break

        if status != "Complete":
            _die(
                {
                    "error": "Omni SQL query did not complete (status=%s); "
                    "reduce --trace-ids or narrow --window-days" % status
                }
            )

        # Phase 2: paginate while session is still open, accumulating up to SPAN_ROW_LIMIT+1
        # rows. The SQL uses LIMIT SPAN_ROW_LIMIT+1 (1001) so if the LIMIT was hit the 1001st
        # row exists; once accumulated rows exceed SPAN_ROW_LIMIT we know it was hit. Paginating
        # rather than trusting a single page handles short pages (fewer than maxResults rows
        # returned with a nextToken) which are valid for any AWS paginated API.
        next_token = None
        while len(rows) <= SPAN_ROW_LIMIT:
            try:
                kwargs: dict = {"queryId": qid, "maxResults": 1000}
                if next_token:
                    kwargs["nextToken"] = next_token
                page = omni.get_telemetry_query_results(**kwargs)
            except (BotoCoreError, ClientError) as e:
                _die({"error": "Omni get_telemetry_query_results (fetch) failed: %s" % e})
            rows.extend(page.get("rows", []))
            next_token = page.get("nextToken")
            if not next_token:
                break
    finally:
        if session_id:
            try:
                omni.stop_telemetry_query_session(sessionId=session_id)
            except Exception:
                pass

    truncated = len(rows) > SPAN_ROW_LIMIT
    if truncated:
        rows = rows[:SPAN_ROW_LIMIT]  # drop the probe row before building spans

    by_trace: dict = {}
    order: list = []
    # rows is a list of dicts: column alias → string value
    _ATTR_COLS = [
        ("openinference.span.kind", "oi_span_kind"),
        ("aws.genai.span_kind", "aws_genai_span_kind"),
        ("tool.name", "tool_name"),
        ("input.value", "input_value"),
        ("output.value", "output_value"),
        ("gen_ai.input_value", "gen_ai_input_value"),
        ("gen_ai.output_value", "gen_ai_output_value"),
        ("session.id", "session_id_attr"),
    ]
    for row in rows:
        tid = row.get("traceId")
        if not tid:
            continue
        if tid not in by_trace:
            order.append(tid)
        attrs = {attr_key: row[col] for attr_key, col in _ATTR_COLS if row.get(col)}
        by_trace.setdefault(tid, []).append(
            {
                "spanId": row.get("spanId"),
                "parentSpanId": row.get("parentSpanId") or None,
                "ts": row.get("startTimeUnixNano"),
                # end time ranks the final-answer span (_final_output); start time cannot
                "end": row.get("endTimeUnixNano"),
                "attributes": attrs,
            }
        )
    boundary = order[-1] if (truncated and order) else None  # the only possibly-cut trace
    return by_trace, truncated, boundary


def _resolve_dataset_id(ctl, id_or_name):
    token = None
    while True:
        try:
            resp = ctl.list_datasets(**({"nextToken": token} if token else {}))
        except (BotoCoreError, ClientError) as e:
            _die({"error": "list_datasets failed: %s" % e})
        for d in resp.get("datasets", []):
            if d.get("datasetId") == id_or_name or d.get("datasetName") == id_or_name:
                return d.get("datasetId")
        token = resp.get("nextToken")
        if not token:
            _die({"error": "dataset %r not found" % id_or_name})


def _dataset_schema_and_count(ctl, dataset_id):
    """Read the target dataset's declared schemaType and its DRAFT example count.

    The schemaType read is NOT best-effort: it is fixed at creation, immutable, and decides
    where the example's input goes, so building examples without it is a guess that rejects the
    whole batch whenever it is wrong (validation is all-or-nothing). Refuse the write, naming
    the schema, rather than guess. The count stays tolerant of a missing or odd value -- the
    service enforces the 1000-example cap anyway.
    """
    try:
        resp = ctl.get_dataset(datasetId=dataset_id)
    except (BotoCoreError, ClientError) as e:
        _die({
            "error": "get_dataset failed for %s: %s. --mode add must read the dataset's "
            "schemaType before building examples (it decides the example shape, and the wrong "
            "shape rejects the whole batch), so this lookup cannot be skipped -- grant "
            "bedrock-agentcore-control GetDataset on this dataset and re-run." % (dataset_id, e)
        })
    schema = resp.get("schemaType")
    if schema not in ADD_SCHEMAS:
        _die({
            "error": "dataset %s declares schemaType %r; this helper can only build %s examples "
            "from traces. Add to a dataset declaring one of those, or create a new one with "
            "--mode create (which creates %s)."
            % (dataset_id, schema, " or ".join(ADD_SCHEMAS), CREATE_SCHEMA_TYPE),
            "schemaType": schema,
        })
    count = resp.get("exampleCount")
    return schema, (count if isinstance(count, int) else None)


def main():
    ap = argparse.ArgumentParser(
        description="Build an AgentCore eval dataset from CloudWatch Omni traces."
    )
    ap.add_argument("--trace-ids", required=True, help="comma-separated trace ids")
    ap.add_argument("--mode", choices=["create", "add"], default="create")
    ap.add_argument("--dataset-name", help="name for the new dataset (mode create)")
    ap.add_argument("--dataset-id", help="existing dataset id or name (mode add)")
    ap.add_argument("--description")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--window-days", type=int, default=30, help="trace lookback window")
    ap.add_argument(
        "--i-have-confirmed",
        action="store_true",
        help="REQUIRED to write. Assert that the user confirmed this create/add. Without it the "
        "helper refuses (exit 1) before any AWS call.",
    )
    args = ap.parse_args()

    # A create/add is a real resource write. Refuse outright unless the caller passes
    # --i-have-confirmed, which an agent may add only AFTER the user has confirmed. The
    # helper cannot verify that confirmation happened; it only guarantees that an unflagged
    # run exits non-zero having touched no AWS API.
    if not args.i_have_confirmed:
        _die({
            "error": "refusing to write: creating/extending a dataset is a real resource write. "
            "Confirm with the user first, then re-run with --i-have-confirmed. Do not pass the "
            "flag on a request that has not been confirmed.",
            "confirmationRequired": True,
        })

    if args.mode == "create" and not args.dataset_name:
        _die({"error": "--dataset-name is required for --mode create"})
    if args.mode == "add" and not (args.dataset_id or args.dataset_name):
        _die({"error": "--dataset-id or --dataset-name is required for --mode add"})

    seen, uniq, bad = set(), [], []
    # Normalize to lowercase once: span trace ids are stored lowercase, the filter is an exact
    # string match, and the boundary comparison relies on the query's case-sensitive `sort`.
    for t in (x.strip().lower() for x in args.trace_ids.split(",")):
        if not t or t in seen:
            continue
        if not _TRACE_ID_RE.match(t):
            bad.append(t)
            continue
        seen.add(t)
        uniq.append(t)
    if bad:
        _die({"error": "invalid trace id(s) (expected hex): %s" % ", ".join(bad[:5])})
    if not uniq:
        _die({"error": "no valid trace ids provided"})
    notes = []
    if len(uniq) > MAX_TRACES:
        notes.append(
            "captured the first %d of %d traces; run again for the rest" % (MAX_TRACES, len(uniq))
        )
        uniq = uniq[:MAX_TRACES]

    session = boto3.Session(region_name=args.region)
    omni = session.client("cloudwatchomni")
    ctl = session.client("bedrock-agentcore-control")

    # Resolve the target dataset's immutable schemaType BEFORE the (minutes-long) span query:
    # it decides the shape every example is built in, and a dataset declaring a schema this
    # helper cannot render should fail before any Omni work is paid for.
    schema_type, existing, dsid = CREATE_SCHEMA_TYPE, None, None
    if args.mode == "add":
        dsid = _resolve_dataset_id(ctl, args.dataset_id or args.dataset_name)
        schema_type, existing = _dataset_schema_and_count(ctl, dsid)

    by_trace, truncated, boundary = fetch_spans_by_trace(omni, uniq, args.window_days)
    if truncated:
        notes.append(
            "Omni SQL query hit the %d-row cap; only fully-fetched traces were captured. The boundary "
            "trace is flagged metadata.partial=true; any trace reported 'row cap reached before this "
            "trace' was not fetched — reduce --trace-ids or narrow --window-days and re-run for those."
            % SPAN_ROW_LIMIT
        )
    examples, conversion_errors = [], []
    for tid in uniq:
        spans = by_trace.get(tid) or []
        if not spans:
            # On truncation the query stops at `boundary` (traceId asc), so a requested id that
            # sorts after it was never reached — report that distinctly from a genuine miss.
            if (
                truncated and boundary is not None and tid > boundary
            ):  # both lowercase; matches `sort traceId asc`
                conversion_errors.append(
                    {
                        "traceId": tid,
                        "error": "row cap (%d) reached before this trace; not fetched"
                        % SPAN_ROW_LIMIT,
                    }
                )
            else:
                conversion_errors.append({"traceId": tid, "error": "no spans found in window"})
            continue
        # Only the boundary trace can be mid-cut; every lower-sorted trace is complete.
        partial = truncated and boundary is not None and tid == boundary
        example = to_example(tid, spans, partial=partial)
        if schema_type == THIRD_PARTY_SCHEMA:
            example = to_third_party(example)
        err = invalid(example, schema_type)
        if err:
            conversion_errors.append({"traceId": tid, "error": err})
            continue
        examples.append(example)

    if not examples:
        _die({"error": "no examples could be built", "conversionErrors": conversion_errors})

    source = {"inlineExamples": {"examples": examples}}
    if args.mode == "create":
        kwargs = {
            "datasetName": args.dataset_name,
            "schemaType": CREATE_SCHEMA_TYPE,
            "source": source,
            "clientToken": str(uuid4()),
        }
        if args.description:
            kwargs["description"] = args.description
        try:
            resp = ctl.create_dataset(**kwargs)
        except (BotoCoreError, ClientError) as e:
            _die({"error": "create_dataset failed: %s" % e, "conversionErrors": conversion_errors})
        receipt = {
            "mode": "create",
            "datasetId": resp.get("datasetId"),
            "status": resp.get("status"),
            "schemaType": schema_type,
            "examplesWritten": len(examples),
        }
    else:
        if existing is not None and existing + len(examples) > MAX_DATASET_EXAMPLES:
            _die({
                "error": "dataset %s already holds %d examples; adding %d would exceed the service cap of %d "
                "examples per dataset (the write would fail with 402 ServiceQuotaExceededException). "
                "Create a new dataset (--mode create) for the remainder." % (dsid, existing, len(examples), MAX_DATASET_EXAMPLES),
                "conversionErrors": conversion_errors,
            })
        try:
            resp = ctl.add_dataset_examples(datasetId=dsid, source=source, clientToken=str(uuid4()))
        except (BotoCoreError, ClientError) as e:
            _die(
                {
                    "error": "add_dataset_examples failed: %s" % e,
                    "schemaType": schema_type,  # the shape the examples were built in
                    "conversionErrors": conversion_errors,
                }
            )
        example_ids = resp.get("exampleIds") or []
        receipt = {
            "mode": "add",
            "datasetId": dsid,
            "schemaType": schema_type,
            "examplesWritten": len(example_ids) or len(examples),
            "exampleIds": example_ids,
        }
    if conversion_errors:
        receipt["conversionErrors"] = conversion_errors
    if notes:
        receipt["notes"] = notes
    print(json.dumps(receipt, default=str, indent=2))


if __name__ == "__main__":
    main()
