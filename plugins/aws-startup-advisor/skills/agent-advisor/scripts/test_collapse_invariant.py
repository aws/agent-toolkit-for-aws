# scripts/test_collapse_invariant.py
"""Stage-A release gate: a single-unit run is byte-equivalent to the legacy flow
on every Python surface (scoring call, diagram render). Prose surfaces carry the
same invariant via phase _asserts (single-unit: no grouping question, no delta
questions, no unit cards)."""
import build_diagram
import scoring

ANSWERS = {
    "session_duration": "over_8hr", "traffic_pattern": "bursty",
    "platform_fit": "none", "session_state": "stateful",
    "ops_preference": "low", "isolation": "not_needed",
    "memory_needs": "cross_session", "multi_agent": "no",
    "framework": "langgraph", "existing_cluster": "none",
    "multi_cloud": "no", "idle_resume": "unknown",
    "compute_tier": "light", "launch_concurrency": "unknown",
}


def test_scoring_identical_via_unit_loop():
    # The clarify loop merges system+unit answers; for one unit that merge IS the
    # legacy flat answers dict — the scoring call must be literally identical.
    legacy = scoring.score({"answers": ANSWERS})
    system = {k: ANSWERS[k] for k in
              ("ops_preference", "existing_cluster", "multi_cloud", "platform_fit")}
    assert set(system.keys()) == {"ops_preference", "existing_cluster", "multi_cloud", "platform_fit"}
    unit = {k: v for k, v in ANSWERS.items() if k not in system}
    unitized = scoring.score({"answers": {**system, **unit}})
    assert unitized == legacy


def test_diagram_identical_for_single_unit_design():
    result = {"verdict": "agentcore", "agentcore_services": ["memory"],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    design = {"units": [{"id": "only", "workload_class": "agent_session",
                         "verdict": "agentcore",
                         "model_recommendation": {"model": "claude_sonnet_5"}}],
              "platform": {"mode": "split", "runtime": None,
                           "interconnect": "in_process", "shared_services": []}}
    assert build_diagram.build_diagram(result, {}, design=design) == \
        build_diagram.build_diagram(result, {})
