"""Content lock for references/decision-refs/workload-classes.md.

Non-agent workload units are NOT scored by scoring.py — their verdicts come
from this deterministic table. These tests pin the rule order (first-match-wins)
and the load-bearing verdicts, in the same spirit as test_temporal_decision_refs.
"""
import pathlib
import re

WC_MD = (pathlib.Path(__file__).parent.parent
         / "references" / "decision-refs" / "workload-classes.md")


def _text():
    return WC_MD.read_text()


def test_file_exists():
    assert WC_MD.exists(), WC_MD


def test_first_match_wins_stated():
    assert "first match wins" in _text().lower()


def test_rules_present_in_order():
    text = _text()
    positions = [text.find(f"**W{i}**") for i in range(1, 7)]
    assert all(p != -1 for p in positions), f"missing rule ids: {positions}"
    assert positions == sorted(positions), "W1..W6 must appear in order"


def test_batch_never_agentcore():
    # AgentCore frames work as sessions with session-scoped billing (even the
    # Instances compute type, 14d ceiling) — wrong shape for batch schedulers.
    text = _text()
    assert "batch" in text
    assert re.search(r"batch.{0,400}never AgentCore", text, re.DOTALL | re.IGNORECASE)


def test_light_io_scale_to_zero_default():
    assert re.search(r"light_io.{0,300}Lambda", _text(), re.DOTALL)


def test_existing_cluster_respected():
    # W1: an existing EKS/ECS cluster pulls same-class workloads onto it.
    assert "existing_cluster" in _text()


def test_verdict_tokens_explicit():
    """Each workload-classes rule now states the verdict enum token explicitly
    (e.g., `batch` for W2, `lambda` for W3/W4, `fargate` for W5/W6) alongside
    the prose label. This prevents the bug where design.json.verdict drifted
    from workload_class (BUG-7: ocr had workload_class:batch but verdict:ecs).
    """
    text = _text()
    # W2 → `batch` token
    assert re.search(r"W2.*`batch`.*AWS Batch", text, re.DOTALL)
    # W3 → `lambda` token
    assert re.search(r"W3.*`lambda`.*Lambda", text, re.DOTALL)
    # W4 → `lambda` token
    assert re.search(r"W4.*`lambda`.*Lambda", text, re.DOTALL)
    # W5 → `fargate` token
    assert re.search(r"W5.*`fargate`.*Fargate", text, re.DOTALL)
    # W6 → `fargate` token
    assert re.search(r"W6.*`fargate`.*Fargate", text, re.DOTALL)


def test_design_md_asserts_verdict_workload_class_consistency():
    """design.md's _assert must include the invariant that verdict and
    workload_class are never contradictory (batch workload → batch verdict unless
    W1 existing-cluster reuse)."""
    design_md = WC_MD.parent.parent / "phases" / "design" / "design.md"
    assert design_md.exists()
    text = design_md.read_text()
    # Check for the assertion that verdict matches workload_class rule mapping
    assert re.search(r"verdict.*workload.*never contradictory", text, re.DOTALL | re.IGNORECASE)


def test_consolidated_does_not_rewrite_per_unit_verdict():
    """Live-test 0715 (consolidate onto ECS): the LLM overwrote every unit.verdict to the
    superset (ecs), violating design.md's own _assert (non-agent verdict == workload-classes
    token) and losing the raw verdict the downstream effective-runtime logic needs. design.md
    must state that consolidation lives only in the platform block, never in units[].verdict."""
    design_md = WC_MD.parent.parent / "phases" / "design" / "design.md"
    text = re.sub(r"\s+", " ", design_md.read_text())  # normalize prose line-wraps
    assert re.search(r"[Cc]onsolidated does NOT rewrite per-unit", text) or \
        re.search(r"never overwrites?.{0,40}verdict.{0,40}superset", text, re.IGNORECASE), \
        "design.md must state consolidated does not rewrite per-unit verdict"
    assert "effective_runtime" in text and \
        re.search(r"consolidated.{0,80}platform\.runtime", text, re.IGNORECASE), \
        "design.md must set per-unit effective_runtime to platform.runtime when consolidated"


def test_every_verdict_has_a_service_card_with_serving_notes():
    """Codex P1 #6: design.md derives each unit's key_change from the winning runtime's
    '## Serving & security notes' block. Every non-agent verdict a workload-classes rule
    can emit (batch/fargate/lambda/ecs/eks) must resolve to a card that HAS that block, or
    the derivation fabricates. fargate reuses ecs.md."""
    refs = WC_MD.parent  # decision-refs/
    # (verdict token -> card filename); fargate aliases to ecs.md
    verdict_cards = {
        "batch": "batch.md",
        "lambda": "lambda.md",
        "ecs": "ecs.md",
        "eks": "eks.md",
        "fargate": "ecs.md",  # ECS-on-Fargate shares the ecs card
    }
    for verdict, card in verdict_cards.items():
        path = refs / card
        assert path.exists(), f"{verdict} verdict has no service card ({card})"
        assert "## Serving & security notes" in path.read_text(), \
            f"{card} ({verdict}) lacks the '## Serving & security notes' block key_change needs"
    # design.md must state the fargate->ecs card alias so the loader resolves it.
    design_md = refs.parent / "phases" / "design" / "design.md"
    dtext = design_md.read_text()
    assert re.search(r"`fargate`.{0,40}`?ecs\.md`?|ecs\.md.{0,40}fargate", dtext, re.IGNORECASE), \
        "design.md must state fargate resolves to ecs.md for card loading"
