#!/usr/bin/env python3
"""Offline behavioral tests for `evaluate_traces.py` — no AWS, no external dependencies.

Stubs `boto3`/`botocore` so the bundled batch/matrix helper runs deterministically and its
contract is inspectable/reproducible. Covers: single-trace back-compat, the trace x evaluator
matrix with fetch-once, ground-truth gating (drop-mixed / die-if-all), the 50 / 10 / 100 caps and
the evaluate-call budget, `pairsScored` / `tracesScored` honesty, session de-duplication, and
real Omni-error propagation.

Run: `python test_evaluate_traces.py` (exits non-zero on any failure). This file is NOT executed
by the package's no-op build; it is a hand-run, reviewable regression suite for the helper.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
_N = 0


class _ClientError(Exception):
    def __init__(self, response=None, op=None):
        self.response = response or {}
        super().__init__(str(response))


class _BotoCoreError(Exception):
    pass


def _load(make_session):
    """Import a fresh copy of evaluate_traces with boto3/botocore stubbed."""
    global _N
    _N += 1
    be = types.ModuleType("botocore.exceptions")
    be.ClientError = _ClientError
    be.BotoCoreError = _BotoCoreError
    bc = types.ModuleType("botocore")
    bc.exceptions = be
    b3 = types.ModuleType("boto3")
    b3.Session = lambda **_k: make_session()
    sys.modules.update({"boto3": b3, "botocore": bc, "botocore.exceptions": be})

    spec = importlib.util.spec_from_file_location(
        "evaluate_traces_under_test_%d" % _N, os.path.join(HERE, "evaluate_traces.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.time.sleep = lambda _: None  # no-op poll delay so tests run instantly
    return mod


def _make_omni_rows(docs):
    """Convert span dicts to Omni SQL column-alias row format."""
    rows = []
    for d in docs:
        attrs = d.get("attributes") or {}
        row = {
            "traceId": d.get("traceId"),
            "spanId": d.get("spanId"),
            "parentSpanId": d.get("parentSpanId"),
            "name": d.get("name", "span"),
            "kind": d.get("kind", "INTERNAL"),
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000",
            "svc_name": ((d.get("resource") or {}).get("attributes") or {}).get("service.name", ""),
            "scope_name": "",
            "status_code": "",
            # span-kind attributes
            "oi_span_kind": attrs.get("openinference.span.kind", ""),
            "aws_genai_span_kind": attrs.get("aws.genai.span_kind", ""),
            "gen_ai_op_name": attrs.get("gen_ai.operation.name", ""),
            # input/output
            "input_value": attrs.get("input.value", ""),
            "output_value": attrs.get("output.value", ""),
            "gen_ai_input_value": "",
            "gen_ai_output_value": "",
            "gen_ai_input_messages": "",
            "gen_ai_output_messages": "",
            "llm_input_messages": "",
            "llm_output_messages": "",
            # tool
            "tool_name": attrs.get("tool.name", ""),
            "gen_ai_tool_name": "",
            "gen_ai_tool_call_id": "",
            # session
            "session_id_attr": attrs.get("session.id", ""),
            # LLM metadata
            "gen_ai_req_model": "",
            "gen_ai_resp_model": "",
            "gen_ai_system": "",
            # token counts
            "usage_input_tokens": "",
            "usage_output_tokens": "",
            "prompt_tokens": "",
            "completion_tokens": "",
        }
        rows.append(row)
    return rows


def _make_session(counters, *, tool_spans=1, session_id=None, eval_mode="ok", raise_cls=None):
    """Build a fake boto3 Session. `counters` records span-fetch and evaluate-call counts."""

    def _span(span_id, is_tool):
        attrs = {}
        if session_id:
            attrs["session.id"] = session_id
        if is_tool:
            attrs["gen_ai.operation.name"] = "execute_tool"
        return {"traceId": "t", "spanId": span_id, "kind": "INTERNAL",
                "attributes": attrs, "resource": {"attributes": {"service.name": "svc"}}}

    docs = [_span("0" * 16, False)] + [_span("%016x" % (i + 1), True) for i in range(tool_spans)]

    class FakeOmni:
        """Fake cloudwatchomni client for Omni SQL span queries."""
        _phase = {}  # queryId -> "polled"

        def start_telemetry_query_session(self, **k):
            return {"sessionId": "sess-1"}

        def start_telemetry_query(self, **k):
            qid = "q-%d" % len(FakeOmni._phase)
            FakeOmni._phase[qid] = {"sql": k.get("queryString", ""), "polled": False}
            return {"queryId": qid, "sessionId": k.get("sessionId")}

        def get_telemetry_query_results(self, queryId, maxResults=1, nextToken=None):
            if raise_cls is not None:
                raise raise_cls(
                    {"Error": {"Code": "AccessDeniedException", "Message": "no cloudwatchomni access"}},
                    "StartTelemetryQuery",
                )
            state = FakeOmni._phase.get(queryId, {})
            # Phase 1 poll (maxResults=1): just confirm Complete
            if maxResults == 1:
                FakeOmni._phase[queryId]["polled"] = True
                return {"status": "Complete", "rows": []}
            # Phase 2 fetch
            sql = state.get("sql", "")
            if "session_id" in sql and "session.id" in sql and "IS NOT NULL" in sql:
                # session resolution query
                rows = [{"session_id": session_id}] if session_id else []
                return {"status": "Complete", "rows": rows}
            # span fetch query
            counters["fetch"] = counters.get("fetch", 0) + 1
            return {"status": "Complete", "rows": _make_omni_rows(docs)}

        def stop_telemetry_query_session(self, **k):
            return {}

    class FakeLogs:
        """Fake logs client — writeback path only (put_log_events)."""
        def put_log_events(self, **k):
            return {}

        def create_log_group(self, **k):
            return {}

        def create_log_stream(self, **k):
            return {}

        def put_retention_policy(self, **k):
            return {}

    class FakeAC:
        def evaluate(self, **k):
            counters["eval"] = counters.get("eval", 0) + 1
            if eval_mode == "error":
                return {"evaluationResults": [{"evaluatorId": k["evaluatorId"], "value": None,
                                               "errorCode": "AgentSpanMappingException",
                                               "errorMessage": "boom"}]}
            return {"evaluationResults": [{"evaluatorId": k["evaluatorId"], "value": 0.5,
                                           "label": "ok", "explanation": "why"}]}

    class FakeSession:
        def client(self, name):
            if name == "cloudwatchomni":
                return FakeOmni()
            if name == "logs":
                return FakeLogs()
            return FakeAC()

    return FakeSession()


def _run(mod, **kw):
    ns = mod.argparse.Namespace(
        trace_id=None, trace_ids=None, session_id=None, evaluator_id=None, evaluator_ids=None,
        level="TRACE", region="us-east-1", window_days=30, no_writeback=True,
        retention_days=30, kms_key_id=None, include_explanations=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            mod._run(ns)
    except SystemExit:
        pass
    return json.loads(out.getvalue())


RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def test_single_trace_back_compat():
    c = {}
    mod = _load(lambda: _make_session(c))
    r = _run(mod, trace_id="aa")
    check("single-trace: one pair scored, one fetch", r["pairsScored"] == 1 and c["fetch"] == 1)
    check("single-trace: row tagged with traceId + evaluatorId",
          {"traceId", "evaluatorId", "value"} <= set(r["results"][0]))


def test_matrix_fetch_once():
    c = {}
    mod = _load(lambda: _make_session(c))
    r = _run(mod, trace_ids="aa,bb", evaluator_ids="E1,E2")
    check("matrix 2x2: 4 pairs scored", r["pairsScored"] == 4)
    check("matrix 2x2: fetch-once (2 fetches, not 4)", c["fetch"] == 2)


def test_ground_truth_gating():
    mod = _load(lambda: _make_session({}))
    r = _run(mod, trace_id="aa", evaluator_ids="Builtin.Helpfulness,Builtin.TrajectoryExactOrderMatch")
    check("mixed GT: drops trajectory matcher, scores the rest",
          r.get("evaluators") == ["Builtin.Helpfulness"])
    r2 = _run(mod, trace_id="aa", evaluator_ids="Builtin.TrajectoryExactOrderMatch")
    check("all-GT: refuses the run", "error" in r2)


def test_caps():
    mod = _load(lambda: _make_session({}))
    r = _run(mod, trace_ids=",".join("%02x" % i for i in range(60)))
    check("trace cap: 60 -> 50 with a note",
          r["tracesScored"] == 50 and any("capped to 50 traces" in n for n in r.get("notes", [])))
    r2 = _run(mod, trace_ids="aa,bb,cc", evaluator_ids=",".join("E%d" % i for i in range(12)))
    check("evaluator cap: 12 -> 10 with a note",
          len(r2["evaluators"]) == 10 and any("capped to 10 evaluators" in n for n in r2.get("notes", [])))
    r3 = _run(mod, trace_ids=",".join("%02x" % i for i in range(40)), evaluator_ids="E1,E2,E3")
    check("pair cap: 40x3 -> 33 traces (pair bound bites below the 50-trace bound)",
          r3["tracesScored"] == 33 and r3["pairsScored"] == 99
          and any("100-pair" in n for n in r3.get("notes", [])))


def test_evaluate_call_budget():
    c = {}
    mod = _load(lambda: _make_session(c, tool_spans=25))  # 25 tool spans -> 3 chunks/pair
    mod.MAX_EVALUATE_CALLS = 5
    r = _run(mod, trace_ids="aa,bb,cc", evaluator_ids="E1,E2", level="TOOL_CALL")
    check("TOOL_CALL: total evaluate calls bounded by budget", c["eval"] <= 5)
    check("TOOL_CALL: budget/truncation noted",
          any("budget" in n for n in r.get("notes", [])))


def test_pairs_scored_excludes_errors():
    mod = _load(lambda: _make_session({}, eval_mode="error"))
    r = _run(mod, trace_id="aa")
    check("error-only result: not counted in pairsScored", r["pairsScored"] == 0)
    check("error-only result: still surfaced in results",
          any(x.get("errorCode") for x in r["results"]))


def test_traces_scored_honesty_under_budget():
    c = {}
    mod = _load(lambda: _make_session(c, tool_spans=25))
    mod.MAX_EVALUATE_CALLS = 3  # only the first trace's chunks fit
    r = _run(mod, trace_ids="aa,bb,cc", level="TOOL_CALL")
    check("tracesScored < tracesFetched when budget truncates",
          r["tracesScored"] < r["tracesFetched"])
    check("tracesScored == distinct traces with a real score",
          r["tracesScored"] == len({
              x["traceId"] for x in r["results"]
              if x.get("value") is not None and not x.get("errorCode")
          }))


def test_session_dedup():
    c = {}
    mod = _load(lambda: _make_session(c, session_id="S1"))
    r = _run(mod, trace_ids="aa,bb", evaluator_ids="E1", level="SESSION")
    check("same-session: fetched once", c["fetch"] == 1)
    check("same-session: SESSION scored once (no duplicate)",
          len([x for x in r["results"] if x.get("value") is not None]) == 1)


def test_real_error_propagated():
    mod = _load(lambda: _make_session({}, raise_cls=_ClientError))
    r = _run(mod, trace_id="aa")
    blob = json.dumps(r)
    check("real Omni error surfaced (not the generic window message)",
          "AccessDenied" in blob or "cloudwatchomni" in blob)


def main():
    for fn in [test_single_trace_back_compat, test_matrix_fetch_once, test_ground_truth_gating,
               test_caps, test_evaluate_call_budget, test_pairs_scored_excludes_errors,
               test_traces_scored_honesty_under_budget, test_session_dedup,
               test_real_error_propagated]:
        fn()
    passed = sum(1 for _, ok in RESULTS if ok)
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
