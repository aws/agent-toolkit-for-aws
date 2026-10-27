"""Review 5620455181 (vagmur-aws, PR #483 comment 4353203451).

Graviton app-code profiling is infrastructure work owned by gcp-to-aws. A delegated
GCP run must still yield `graviton_profile` entries with `source: "app_code"`, and
direct BMA must not gain any infrastructure/Graviton logic.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GCP = ROOT / "skills/gcp-to-aws/references"
BMA = ROOT / "skills/bedrock-migration-assessment"
CONTROLLER = GCP / "phases/discover/discover.md"
GRAVITON = GCP / "phases/discover/discover-app-graviton.md"
SHIM = GCP / "phases/discover/discover-app-code.md"
BMA_APP_CODE = BMA / "references/phases/discover/discover-app-code.md"


def _step_1b(text: str) -> str:
    start = text.index("**1b. Check for source code / dependency manifests:**")
    end = text.index("**1c. Check for billing data:**")
    return text[start:end]


def test_gcp_controller_loads_graviton_scan_for_any_source_and_shim_only_for_candidates() -> None:
    text = CONTROLLER.read_text()
    step = _step_1b(text)
    graviton_at = step.index("references/phases/discover/discover-app-graviton.md")
    shim_at = step.index("references/phases/discover/discover-app-code.md")
    assert graviton_at < shim_at
    assert "regardless of `AI_CANDIDATE`" in step
    shim_line = next(line for line in step.splitlines() if "discover-app-code.md" in line)
    assert "`AI_CANDIDATE: true`" in shim_line
    assert "`AI_CANDIDATE: false`" in step and "Do not load the shim" in step
    # Sub-discovery list and completion gate know about the GCP-owned file.
    assert "**discover-app-graviton.md**" in text
    assert "If `discover-app-graviton.md` ran" in text
    assert "If `discover-app-code.md` ran (`AI_CANDIDATE: true` only)" in text


def test_gcp_graviton_file_emits_app_code_profiles() -> None:
    text = GRAVITON.read_text()
    assert 'source: "app_code"' in text and "graviton_profile" in text
    assert "`references/shared/schema-graviton.md`" in text
    assert "`references/shared/graviton.md`" in text
    assert (GCP / "shared/schema-graviton.md").is_file() and (GCP / "shared/graviton.md").is_file()
    for rule in (
        'tier: "ready"', "risk signals", "`conditional`", 'tier: "incompatible"',
        "`import cuda`", "`torch.cuda`", 'route to G5/G6', "`Dockerfile`", "`FROM`",
    ):
        assert rule in text, rule
    assert re.search(r"^1\. .*language runtime", text, re.MULTILINE)
    assert re.search(r"^4\. .*Dockerfile", text, re.MULTILINE)
    assert "whether or not the run is an `AI_CANDIDATE`" in text
    assert "`bedrock-migration-assessment` never emits, modifies, or drops `graviton_profile`" in text
    # The shim points at the GCP owner and does not re-implement the scan.
    shim = SHIM.read_text()
    assert "discover-app-graviton.md" in shim and 'source: "app_code"' in shim
    assert "schema-graviton" not in shim and 'tier: "ready"' not in shim


def test_consumers_still_reference_app_code_profiles() -> None:
    iac = (GCP / "phases/discover/discover-iac.md").read_text()
    assert re.search(r'`source: "app_code"`.*app-code signals win', iac)
    compute = (GCP / "phases/clarify/clarify-compute.md").read_text()
    assert re.search(r"^\|.*no `app_code` profile.*\| \*\*Ask\*\* Q11b\s*\|", compute, re.MULTILINE)
    # The only emitter of app_code profiles in gcp-to-aws is the GCP-owned file.
    emitters = [
        path for path in (GCP / "phases").rglob("*.md")
        if "graviton_profile" in path.read_text() and 'source: "app_code"' in path.read_text()
        and re.search(r"Write a `graviton_profile` array", path.read_text())
    ]
    assert emitters == [GRAVITON]


def test_direct_bma_has_no_infrastructure_graviton_logic() -> None:
    text = BMA_APP_CODE.read_text()
    assert "Step 2.7" in text
    for token in ("schema-graviton", 'tier: "ready"', "machine_type", "torch.cuda", "node-gyp"):
        assert token not in text, token
    assert "do not emit, modify, or drop its `graviton_profile`" in text
    assert not list((BMA / "references/shared").glob("*graviton*"))
    assert not list(BMA.rglob("*graviton*"))
    closure = json.loads((BMA / "references/runtime/closure.json").read_text())
    assert not any("graviton" in entry["destination"] for entry in closure["entries"])
    # No BMA runtime file carries Graviton tier logic.
    for entry in closure["entries"]:
        member = (BMA / entry["destination"]).read_text(errors="ignore")
        assert 'tier: "ready"' not in member and "schema-graviton" not in member, entry["destination"]


GATE_SCRIPT = GCP.parent / "scripts/gcp-route-gate.py"


def _run_graviton_gate(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--run-dir", str(run_dir), "--gate", "graviton"],
        capture_output=True, text=True, check=False,
    )


def _write_json(run_dir: Path, name: str, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text(json.dumps(payload))


def test_ai_only_run_passes_graviton_gate_as_not_applicable(tmp_path: Path) -> None:
    # P2: AI-only route (no GCP inventory, ai-workload-profile.json present) is n/a, not failed.
    _write_json(tmp_path, "ai-workload-profile.json", {"models": []})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("GATE_NA | phase=discover | gate=discover-app-graviton | route=ai_only"), result.stdout


def test_missing_graviton_profile_passes_with_not_yet_known_reason(tmp_path: Path) -> None:
    # Review 5661016215 (comment 4384076083): a missing profile is "not yet known", not a failure.
    # On main a missing profile only meant Clarify asked Q11b; the gate must not stop the run.
    _write_json(tmp_path, "gcp-resource-inventory.json", {"resources": []})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(
        "GATE_PASS | phase=discover | gate=discover-app-graviton | field=graviton_profile | reason=not_yet_known"
    ), result.stdout
    assert "clarify_q11b" in result.stdout


def test_billing_only_plus_source_code_passes_gate(tmp_path: Path) -> None:
    # Billing export + source code: billing writes no inventory and no AI profile exists,
    # so this is the infrastructure route with no profile yet. Must pass, not fail closed.
    _write_json(tmp_path, "billing-profile.json", {"services": []})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("GATE_PASS") and "reason=not_yet_known" in result.stdout, result.stdout


def test_inventory_with_metadata_graviton_profile_passes(tmp_path: Path) -> None:
    # Writer/gate agreement: a run that placed the array under `metadata` still passes.
    _write_json(tmp_path, "gcp-resource-inventory.json", {"resources": [], "metadata": {"graviton_profile": []}})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("GATE_PASS") and "location=metadata" in result.stdout, result.stdout


def test_malformed_graviton_profile_fails_closed(tmp_path: Path) -> None:
    # ROUTE_GATE_FAIL is reserved for genuinely malformed input.
    _write_json(tmp_path, "gcp-resource-inventory.json", {"graviton_profile": "x"})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 1
    assert result.stdout.startswith("ROUTE_GATE_FAIL") and "reason=malformed" in result.stdout, result.stdout


def test_unreadable_inventory_fails_closed(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "gcp-resource-inventory.json").write_text("not json")
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 1
    assert result.stdout.startswith("ROUTE_GATE_FAIL") and "reason=unreadable" in result.stdout, result.stdout


def test_infra_run_with_graviton_profile_passes(tmp_path: Path) -> None:
    _write_json(tmp_path, "gcp-resource-inventory.json", {"graviton_profile": []})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("GATE_PASS | phase=discover | gate=discover-app-graviton"), result.stdout
    assert "location=top_level" in result.stdout, result.stdout


def test_hybrid_run_accepts_graviton_profile_in_ai_workload_profile(tmp_path: Path) -> None:
    # Writer/gate agreement: discover-app-graviton.md may write the array next to the AI profile.
    _write_json(tmp_path, "gcp-resource-inventory.json", {"resources": []})
    _write_json(tmp_path, "ai-workload-profile.json", {"graviton_profile": []})
    result = _run_graviton_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_prose_points_at_the_script_and_keeps_fail_closed_stop() -> None:
    text = CONTROLLER.read_text()
    start = text.index("   - If `discover-app-graviton.md` ran")
    gate = text[start:text.index("   - If `discover-app-code.md` ran", start)]
    assert "scripts/gcp-route-gate.py" in gate and "--gate graviton" in gate, gate
    assert "GATE_NA" in gate and "ai_only" in gate, gate
    assert "ROUTE_GATE_FAIL" in gate and "STOP" in gate, gate
    assert "Recording a failed route gate and continuing is not permitted" in text
    assert "If any triggered route is missing its required artifact(s): STOP" in text
