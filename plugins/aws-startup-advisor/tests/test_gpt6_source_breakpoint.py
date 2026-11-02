"""Guard: cost_compare.py prices a GPT-6-class pair at the long-context rate on
BOTH sides when its typical per-request size crosses the 272,000-input-token
breakpoint, instead of silently applying the short-context flat rate to a
long-context request (PR #433 round 3 review finding — leon1418,
databaseId 4240305151).

Reviewer's exact reproduction: 100 requests of GPT-6 Sol at 300,000 input /
10,000 output tokens each. The pre-fix script priced the full 30M input /
1M output volume at the flat <=272K rate ($2.00/$10.00), yielding $70 source
and a false 112.14% Bedrode regional/Geo premium. The whole request reprices
above the 272,000-input-token boundary (input 2x, cache 2x, output 1.5x) per
OpenAI's own contract, so the correct figures are:
  - source (long-context, $4.00/$15.00):      $135.00
  - Bedrock Global CRIS (long-context, parity, $4.00/$15.00): $135.00
  - Bedrock In-Region/Geo-CRIS (long-context, $4.40/$16.50):  $148.50
  - premium: (148.50 - 135.00) / 135.00 * 100 = +10.0%

This test extracts the actual embedded script from the agent markdown file,
following `test_report_generator_cost_pricing.py`'s established pattern, and
executes it as a subprocess against a constructed fixture, asserting on its
real numeric stdout.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"

PYTHON_BLOCK_RE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)


def _extract_cost_compare_script() -> str:
    """Pull the sole embedded ```python block out of the agent markdown."""
    text = REPORT_GENERATOR.read_text(encoding="utf-8")
    matches = PYTHON_BLOCK_RE.findall(text)
    assert len(matches) == 1, (
        f"expected exactly one embedded python block in {REPORT_GENERATOR.name}, "
        f"found {len(matches)} — update this test's extraction if the file now "
        f"embeds more than one script"
    )
    return matches[0]


def _write_fixture(tmp_path: Path, *, golden_rows: list[dict]) -> Path:
    """Write a golden-dataset/prompts.jsonl fixture under tmp_path and return
    the repo-root-shaped directory the extracted script expects
    (<repo>/.saws-migrate/golden-dataset/prompts.jsonl)."""
    golden_dir = tmp_path / ".saws-migrate" / "golden-dataset"
    golden_dir.mkdir(parents=True)
    import json

    with open(golden_dir / "prompts.jsonl", "w", encoding="utf-8") as f:
        for row in golden_rows:
            f.write(json.dumps(row) + "\n")
    return tmp_path


def _run_script(
    script_body: str,
    *,
    repo: Path,
    model_pairs_src: str,
    baseline_src: str,
    per_request_src: str,
    long_context_src: str,
    tier_distribution_src: str | None = None,
) -> str:
    """Substitute the markdown placeholders and the tunable dict/list
    literals, write the script to a temp file, and run it with the plugin's
    own interpreter. Returns combined stdout."""
    body = script_body.replace("<repo>", str(repo))
    body = re.sub(
        r"MODEL_PAIRS = \[\n(?:.*?\n)*?\]",
        model_pairs_src,
        body,
        count=1,
    )
    body = re.sub(
        r"BASELINE_TOKENS_BY_SOURCE = \{\n(?:.*?\n)*?\}",
        baseline_src,
        body,
        count=1,
    )
    body = re.sub(
        r"PER_REQUEST_TOKENS = \{\n(?:.*?\n)*?\}",
        per_request_src,
        body,
        count=1,
    )
    if tier_distribution_src is not None:
        body = re.sub(
            r"TIER_DISTRIBUTION_BY_SOURCE = \{\n(?:.*?\n)*?\}",
            tier_distribution_src,
            body,
            count=1,
        )
    body = re.sub(
        r"BEDROCK_LONG_CONTEXT = \{\n(?:.*?\n)*?\}",
        long_context_src,
        body,
        count=1,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(body)
        script_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    return result.stdout


def test_gpt6_sol_300k_input_crosses_breakpoint_on_both_sides(tmp_path: Path) -> None:
    script_body = _extract_cost_compare_script()

    # Golden dataset is irrelevant here — this pair is baseline-covered, so its
    # volume comes from BASELINE_TOKENS_BY_SOURCE, not the sample.
    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    # 100 requests of 300,000 input / 10,000 output tokens each.
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 30_000_000, "output": 1_000_000},\n'
        '}'
    )
    per_request_src = (
        'PER_REQUEST_TOKENS = {\n'
        '    "openai.gpt-6-sol": {"input": 300_000, "output": 10_000},\n'
        '}'
    )
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
    )

    assert "baseline-long-context" in stdout, stdout

    expected_source_cost = (30_000_000 * 4.00 + 1_000_000 * 15.00) / 1_000_000
    expected_bedrock_cost = (30_000_000 * 4.40 + 1_000_000 * 16.50) / 1_000_000
    assert expected_source_cost == 135.0
    assert expected_bedrock_cost == 148.5

    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout
    assert "source=$135.0000" in stdout, stdout
    assert "bedrock=$148.5000" in stdout, stdout

    # Must NOT be the buggy flat-rate figures the reviewer flagged.
    assert "source=$70.0000" not in stdout, stdout

    expected_premium_pct = (expected_bedrock_cost - expected_source_cost) / expected_source_cost * 100
    assert round(expected_premium_pct, 1) == 10.0

    expected_savings_pct = (expected_source_cost - expected_bedrock_cost) / expected_source_cost * 100
    assert f"Estimated savings: {expected_savings_pct:+.1f}%" in stdout, stdout
    assert "Estimated savings: -10.0%" in stdout, stdout
    # The buggy flat-rate comparison would have produced a ~-112.14% line.
    assert "-112.1%" not in stdout and "-112.14%" not in stdout, stdout


def test_pair_without_per_request_tokens_keeps_flat_rate_unchanged(tmp_path: Path) -> None:
    """Regression guard: a pair absent from PER_REQUEST_TOKENS must keep pricing
    through the pre-existing flat-rate path, even when it has long-context
    elements and the model also appears in BEDROCK_LONG_CONTEXT."""
    script_body = _extract_cost_compare_script()

    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 30_000_000, "output": 1_000_000},\n'
        '}'
    )
    # No PER_REQUEST_TOKENS entry for this source model -- request size unknown.
    per_request_src = "PER_REQUEST_TOKENS = {}"
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
    )

    # Must stay on the plain "baseline" basis (no "-long-context" suffix) and price
    # the full 30M/1M volume at the flat short-context rate.
    assert "(baseline):" in stdout, stdout
    assert "long-context" not in stdout, stdout

    expected_source_cost = (30_000_000 * 2.00 + 1_000_000 * 10.00) / 1_000_000
    expected_bedrock_cost = (30_000_000 * 2.20 + 1_000_000 * 11.00) / 1_000_000
    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout


def test_exact_boundary_272000_input_tokens_stays_short_context(tmp_path: Path) -> None:
    """272,000 input tokens is <=272K -- must stay on the short-context flat rate."""
    script_body = _extract_cost_compare_script()

    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 27_200_000, "output": 1_000_000},\n'
        '}'
    )
    per_request_src = (
        'PER_REQUEST_TOKENS = {\n'
        '    "openai.gpt-6-sol": {"input": 272_000, "output": 10_000},\n'
        '}'
    )
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
    )

    assert "long-context" not in stdout, stdout
    expected_source_cost = (27_200_000 * 2.00 + 1_000_000 * 10.00) / 1_000_000
    expected_bedrock_cost = (27_200_000 * 2.20 + 1_000_000 * 11.00) / 1_000_000
    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout


def test_exact_boundary_272001_input_tokens_reprices_whole_request(tmp_path: Path) -> None:
    """272,001 input tokens is just ABOVE the breakpoint -- the whole request
    (including output) reprices at the long-context rate."""
    script_body = _extract_cost_compare_script()

    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 27_200_100, "output": 1_000_000},\n'
        '}'
    )
    per_request_src = (
        'PER_REQUEST_TOKENS = {\n'
        '    "openai.gpt-6-sol": {"input": 272_001, "output": 10_000},\n'
        '}'
    )
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
    )

    assert "long-context" in stdout, stdout
    # Entire volume -- including output -- reprices at the long-context rate.
    expected_source_cost = (27_200_100 * 4.00 + 1_000_000 * 15.00) / 1_000_000
    expected_bedrock_cost = (27_200_100 * 4.40 + 1_000_000 * 16.50) / 1_000_000
    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout


def test_mixed_tier_distribution_partitions_before_pricing(tmp_path: Path) -> None:
    """Finding 2 (PR #433 round 4): PER_REQUEST_TOKENS records only ONE typical
    request size, so a pair whose real traffic mixes short and long requests gets
    the single breakpoint decision applied to the WHOLE blended volume. Reviewer's
    reproduction: 51 requests @ 300K input / 10K output + 49 requests @ 200K input /
    10K output, GPT-6 Sol pricing. The pre-fix all-or-nothing logic (treating a
    recorded "typical" 300K request as triggering long-context pricing for the
    entire blended 25.1M-input/1M-output pool) produces $115.40 source / $126.94
    Geo-Bedrock. Partitioning into true tiers BEFORE pricing produces the correct
    $93.35 source / $102.685 Geo-Bedrock."""
    script_body = _extract_cost_compare_script()
    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = "BASELINE_TOKENS_BY_SOURCE = {}"
    per_request_src = "PER_REQUEST_TOKENS = {}"
    tier_distribution_src = (
        'TIER_DISTRIBUTION_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": [\n'
        '        {"count": 51, "input": 300_000, "output": 10_000},\n'
        '        {"count": 49, "input": 200_000, "output": 10_000},\n'
        '    ],\n'
        '}'
    )
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
        tier_distribution_src=tier_distribution_src,
    )

    assert "tier-distribution" in stdout, stdout
    assert "source=$93.3500" in stdout, stdout
    assert "bedrock=$102.6850" in stdout, stdout
    # Must NOT be the buggy all-or-nothing figures.
    assert "source=$115.4000" not in stdout, stdout
    assert "bedrock=$126.9400" not in stdout, stdout


def test_tier_distribution_absent_falls_back_to_existing_behavior(tmp_path: Path) -> None:
    """Regression guard: an empty TIER_DISTRIBUTION_BY_SOURCE must leave the
    pre-existing PER_REQUEST_TOKENS + BASELINE_TOKENS_BY_SOURCE scalar logic
    completely unchanged (same as test_gpt6_sol_300k_input_crosses_breakpoint_on_both_sides)."""
    script_body = _extract_cost_compare_script()
    repo = _write_fixture(tmp_path, golden_rows=[])

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("openai.gpt-6-sol", "openai.gpt-6-sol", 2.00, 10.00, 2.20, 11.00, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 30_000_000, "output": 1_000_000},\n'
        '}'
    )
    per_request_src = (
        'PER_REQUEST_TOKENS = {\n'
        '    "openai.gpt-6-sol": {"input": 300_000, "output": 10_000},\n'
        '}'
    )
    tier_distribution_src = "TIER_DISTRIBUTION_BY_SOURCE = {}"
    long_context_src = (
        'BEDROCK_LONG_CONTEXT = {\n'
        '    "openai.gpt-6-sol": {"input": 4.40, "output": 16.50},\n'
        '}'
    )

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
        tier_distribution_src=tier_distribution_src,
    )

    assert "source=$135.0000" in stdout, stdout
    assert "bedrock=$148.5000" in stdout, stdout


def test_source_breakpoint_independent_of_flat_target(tmp_path: Path) -> None:
    """Finding 3 (PR #433 round 4): the source-side long-context decision must not
    be coupled to whether the TARGET also has a long-context tier. Reviewer's
    reproduction: 100 Sol requests @ 300K input / 10K output, a flat-priced target
    (no BEDROCK_LONG_CONTEXT entry at all). The pre-fix combined condition
    (`... and tgt in BEDROCK_LONG_CONTEXT`) made the source-side reprice contingent
    on the target also being tiered -- with an empty BEDROCK_LONG_CONTEXT, BOTH
    sides fell back to the flat short-context rate, producing a buggy $70 source
    figure and a 25.4% savings line instead of the correct $135 source and 61.3%
    savings. The flat target's own cost ($52.25) is unaffected by the fix -- the
    synthetic flat rate pair below is chosen so 100 requests of 300K in / 10K out
    costs exactly $52.25 on the target side, independent of this test."""
    script_body = _extract_cost_compare_script()
    repo = _write_fixture(tmp_path, golden_rows=[])

    # Solve for a flat (per-1M) target rate pair that produces exactly $52.25 for
    # 100 * (300_000 in, 10_000 out): 100 * (300_000*b_in + 10_000*b_out) / 1e6 = 52.25.
    # Pick b_out = 2.00 (arbitrary) and solve b_in: 30*b_in + 1*b_out = 52.25 -> b_in = 1.675.
    b_in, b_out = 1.675, 2.00
    assert round(100 * (300_000 * b_in + 10_000 * b_out) / 1_000_000, 4) == 52.25

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        f'    ("openai.gpt-6-sol", "flat-target", 2.00, 10.00, {b_in}, {b_out}, 4.00, 15.00),\n'
        ']'
    )
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "openai.gpt-6-sol": {"input": 30_000_000, "output": 1_000_000},\n'
        '}'
    )
    per_request_src = (
        'PER_REQUEST_TOKENS = {\n'
        '    "openai.gpt-6-sol": {"input": 300_000, "output": 10_000},\n'
        '}'
    )
    # Empty -- the flat target has no long-context tier at all.
    long_context_src = "BEDROCK_LONG_CONTEXT = {}"

    stdout = _run_script(
        script_body,
        repo=repo,
        model_pairs_src=model_pairs_src,
        baseline_src=baseline_src,
        per_request_src=per_request_src,
        long_context_src=long_context_src,
    )

    assert "source=$135.0000" in stdout, stdout
    assert "bedrock=$52.2500" in stdout, stdout
    assert "Estimated savings: +61.3%" in stdout, stdout
    # Must NOT be the buggy figures where the flat target suppressed the source breakpoint.
    assert "source=$70.0000" not in stdout, stdout
    assert "+25.4%" not in stdout, stdout
    assert "-112.1%" not in stdout, stdout
