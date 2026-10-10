"""Guard: cost_compare.py prices both sides of a baseline-covered pair from
the same real-monthly token volume, never the golden-dataset sample.

PR #425 Cursor review finding 12 (reproduced, numerically confirmed, in
.agents/tasks/pr425-cursor-fixes/reproductions.md; fix design in plan.md
Cluster H — HIGHEST PRIORITY, financial correctness):

Before this fix, `agents/llm2bedrock-report-generator.md` §6.3's precedence
check overrode the SOURCE-side dollar figure with `usage-baseline.json`'s
real monthly total when a baseline existed, but left the embedded
`cost_compare.py` script's BEDROCK-side computation unconditionally priced
on the golden-dataset sample's tiny token volume. A savings percentage
computed by comparing those two numbers compares a real-month source figure
against a sample-volume Bedrock figure — financially meaningless, and
systematically overstates savings (confirmed in reproductions.md finding 12
with a worked example: a $1,000/month real baseline compared against a
sample-volume Bedrock cost of ~$0.02 for the same model pair).

The fix adds a `BASELINE_TOKENS_BY_SOURCE` dict to the script: when a model
pair's source model is present in `usage-baseline.json`'s `usage_by_model[]`,
BOTH `source_cost` and `bedrock_cost` for that pair are computed from the
baseline's real monthly token volume. A pair whose source model is NOT in
the baseline still falls back to the golden-dataset-sample aggregation
(unchanged behavior) — the two volume sources are never mixed within one
pair.

This test extracts the actual embedded script from the agent markdown file
(following `scripts/test_validate_migration_report_decision_core.py`'s
established pattern of loading real plugin code rather than re-describing
it) and EXECUTES it as a subprocess against a constructed fixture, asserting
on its real numeric stdout — not just "no exception raised". This satisfies
the task brief's hard requirement that finding 12's fix be verified
numerically, not by code review alone.
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


def _write_fixture(tmp_path: Path, *, golden_rows: list[dict], baseline_source: str) -> Path:
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


def _run_script(script_body: str, *, repo: Path, model_pairs_src: str, baseline_src: str) -> str:
    """Substitute the markdown placeholders and MODEL_PAIRS/BASELINE_TOKENS_BY_SOURCE
    literals, write the script to a temp file, and run it with the plugin's own
    interpreter. Returns combined stdout."""
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


def test_baseline_covered_pair_prices_both_sides_from_baseline_volume(tmp_path: Path) -> None:
    script_body = _extract_cost_compare_script()

    # Golden dataset carries a deliberately TINY sample volume for gpt-4o (2000/800
    # tokens total) -- if the bug were still present, the Bedrock side would be priced
    # on this sample instead of the baseline.
    repo = _write_fixture(
        tmp_path,
        golden_rows=[
            {"source_model": "gpt-4o", "tokens": {"prompt": 1000, "completion": 400}},
            {"source_model": "gpt-4o", "tokens": {"prompt": 1000, "completion": 400}},
        ],
        baseline_source="gpt-4o",
    )

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("gpt-4o", "anthropic.claude-sonnet-4-6", 2.50, 10.00, 3.00, 15.00),\n'
        ']'
    )
    # Deliberately much larger than, and different in ratio from, the golden sample --
    # this is the baseline's real monthly volume for the same model.
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "gpt-4o": {"input": 42_000_000, "output": 9_000_000},\n'
        '}'
    )

    stdout = _run_script(
        script_body, repo=repo, model_pairs_src=model_pairs_src, baseline_src=baseline_src
    )

    # The row must be tagged "(baseline)" and carry the baseline's token counts, not
    # the golden dataset's (2000 input / 800 output).
    assert "gpt-4o -> anthropic.claude-sonnet-4-6 (baseline): input=42000000 output=9000000" in stdout, stdout
    assert "input=2000" not in stdout, "Bedrock side was priced on the golden-dataset sample, not the baseline"

    # Compute expected costs from the SAME (baseline) volume on both sides.
    expected_source_cost = (42_000_000 * 2.50 + 9_000_000 * 10.00) / 1_000_000
    expected_bedrock_cost = (42_000_000 * 3.00 + 9_000_000 * 15.00) / 1_000_000
    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout

    expected_savings_pct = (expected_source_cost - expected_bedrock_cost) / expected_source_cost * 100
    assert f"Estimated savings: {expected_savings_pct:+.1f}%" in stdout, stdout


def test_pair_not_covered_by_baseline_falls_back_to_golden_dataset_sample(tmp_path: Path) -> None:
    script_body = _extract_cost_compare_script()

    repo = _write_fixture(
        tmp_path,
        golden_rows=[
            {"source_model": "gpt-4o-mini", "tokens": {"prompt": 500, "completion": 200}},
        ],
        baseline_source="gpt-4o",
    )

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("gpt-4o-mini", "amazon.nova-lite-v1:0", 0.15, 0.60, 0.06, 0.24),\n'
        ']'
    )
    # The baseline covers a DIFFERENT model (gpt-4o), not this pair's source
    # (gpt-4o-mini) -- this pair must fall back to the golden-dataset sample.
    baseline_src = (
        'BASELINE_TOKENS_BY_SOURCE = {\n'
        '    "gpt-4o": {"input": 42_000_000, "output": 9_000_000},\n'
        '}'
    )

    stdout = _run_script(
        script_body, repo=repo, model_pairs_src=model_pairs_src, baseline_src=baseline_src
    )

    assert "gpt-4o-mini -> amazon.nova-lite-v1:0 (sample): input=500 output=200" in stdout, stdout

    expected_source_cost = (500 * 0.15 + 200 * 0.60) / 1_000_000
    expected_bedrock_cost = (500 * 0.06 + 200 * 0.24) / 1_000_000
    assert f"source=${expected_source_cost:.4f}" in stdout, stdout
    assert f"bedrock=${expected_bedrock_cost:.4f}" in stdout, stdout


def test_no_baseline_at_all_matches_pre_fix_golden_dataset_behavior(tmp_path: Path) -> None:
    """When BASELINE_TOKENS_BY_SOURCE is left empty (no `Usage baseline path:` line in
    context, per §6.3), every pair resolves from the golden-dataset sample exactly as
    it did before this fix -- this is the explicit "no baseline" path the plan says
    must stay untouched."""
    script_body = _extract_cost_compare_script()

    repo = _write_fixture(
        tmp_path,
        golden_rows=[
            {"source_model": "gpt-4o", "tokens": {"prompt": 1000, "completion": 400}},
            {"source_model": "gpt-4o", "tokens": {"prompt": 1000, "completion": 400}},
        ],
        baseline_source="gpt-4o",
    )

    model_pairs_src = (
        'MODEL_PAIRS = [\n'
        '    ("gpt-4o", "anthropic.claude-sonnet-4-6", 2.50, 10.00, 3.00, 15.00),\n'
        ']'
    )
    baseline_src = "BASELINE_TOKENS_BY_SOURCE = {}"

    stdout = _run_script(
        script_body, repo=repo, model_pairs_src=model_pairs_src, baseline_src=baseline_src
    )

    assert "gpt-4o -> anthropic.claude-sonnet-4-6 (sample): input=2000 output=800" in stdout, stdout
