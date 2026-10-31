"""Retained Estimate structures must pass the registered main/scenario CLI contracts.

Fixed repository/example inputs exercise structure only, not pricing or an IDE run.
"""
import copy
import json

import pytest

from test_cost_export_inputs import writer
from test_validate_artifacts import PLUGIN_ROOT, _doc_example, _run, _write_run


ARTIFACTS = ("estimation-infra.json", "scenarios/scenario-017.estimation-infra.json")
POINTER = "/projected_costs/breakdown/compute/monthly"


@pytest.fixture
def retained_estimate(tmp_path):
    fixture = PLUGIN_ROOT / "fixtures/gcp-decision-gate/after-decide-complete"
    seed = PLUGIN_ROOT / "fixtures/gcp-workshop/seed"
    inputs = tmp_path / "capture"
    inputs.mkdir()
    for name in (".phase-status.json", "preferences.json", "aws-design.json"):
        source = fixture / name if (fixture / name).exists() else seed / name
        (inputs / name).write_bytes(source.read_bytes())
    snapshot = writer().capture_inputs(inputs, "estimation-infra.json")
    estimate = json.loads((fixture / "estimation-infra.json").read_text())
    doc = PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/schema-estimate-infra.md"
    # Copy an existing documented row without calculating a new price. The fixture's
    # aggregate is unchanged; these tests do not claim total reconciliation/CSV readiness.
    compute = _doc_example(doc, "estimation-infra.json schema")["projected_costs"]["breakdown"]["compute"]
    estimate["projected_costs"]["breakdown"] = {"compute": compute}
    estimate["export_inputs"] = {
        "snapshot": snapshot,
        "rows": {POINTER: {"monthlyCost": compute["monthly"], "estimateInput": {}}},
    }
    return estimate


def validate(tmp_path, artifact, estimate):
    run = _write_run(tmp_path, "run", artifact, estimate)
    result = _run("--run-dir", str(run), "--skill", "gcp-to-aws", "--json")
    report = json.loads(result.stdout)
    assert report["checked_artifacts"] == 1
    assert report["stale_baseline_entries"] == []
    return result, report


@pytest.mark.parametrize("artifact", ARTIFACTS)
@pytest.mark.parametrize("retention", ["absent", "empty_rows", "row", "optional_context"])
def test_registered_estimate_retention_is_optional_and_typed(tmp_path, retained_estimate, artifact, retention):
    estimate = retained_estimate
    if retention == "absent":
        del estimate["export_inputs"]
    elif retention == "empty_rows":
        estimate["export_inputs"]["rows"] = {}
    elif retention == "optional_context":
        entry = estimate["export_inputs"]["rows"][POINTER]
        # No fabricated joins: absent pointer lists remain absent; empty lists are
        # structurally permitted when the context contains no resource IDs.
        entry["resourceIdPointers"] = []
        entry["configurationPointers"] = []
        entry["estimateInput"] = {
            "description": "Fixed documented row; region/upfront/configuration unknown.",
            "source": {"estimateFile": "estimation-infra.json", "costPointer": POINTER},
        }
    result, report = validate(tmp_path, artifact, estimate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["errors"] == []


INVALID = [
    (("export_inputs",), None),
    (("export_inputs",), []),
    (("export_inputs", "snapshot"), None),
    (("export_inputs", "snapshot", "version"), True),
    (("export_inputs", "snapshot", "version"), 2),
    (("export_inputs", "snapshot", "runId"), 1),
    (("export_inputs", "snapshot", "owningSkill"), []),
    (("export_inputs", "snapshot", "files"), []),
    (("export_inputs", "snapshot", "files", "aws-design.json"), 1),
    (("export_inputs", "snapshot", "invented"), "x"),
    (("export_inputs", "rows"), []),
    (("export_inputs", "rows", POINTER), None),
    (("export_inputs", "rows", POINTER, "monthlyCost"), "174"),
    (("export_inputs", "rows", POINTER, "monthlyCost"), True),
    (("export_inputs", "rows", POINTER, "estimateInput"), None),
    (("export_inputs", "rows", POINTER, "estimateInput", "regionCode"), 1),
    (("export_inputs", "rows", POINTER, "estimateInput", "upfrontCost"), 0),
    (("export_inputs", "rows", POINTER, "estimateInput", "source"), []),
    (("export_inputs", "rows", POINTER, "estimateInput", "source"), {"resourceIds": [1]}),
    (("export_inputs", "rows", POINTER, "estimateInput", "invented"), "x"),
    (("export_inputs", "rows", POINTER, "resourceIdPointers"), [1]),
    (("export_inputs", "rows", POINTER, "configurationPointers"), "/services/0/config"),
    (("export_inputs", "rows", POINTER, "invented"), "x"),
    (("export_inputs", "invented"), "x"),
]


@pytest.mark.parametrize("artifact", ARTIFACTS)
@pytest.mark.parametrize("path,value", INVALID)
def test_registered_estimate_rejects_invalid_retention(tmp_path, retained_estimate, artifact, path, value):
    estimate = copy.deepcopy(retained_estimate)
    target = estimate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result, report = validate(tmp_path, artifact, estimate)
    assert result.returncode == 1
    assert any(e["code"] == "SCHEMA_VIOLATION" and e["path"].startswith("export_inputs")
               for e in report["errors"]), report


@pytest.mark.parametrize("artifact", ARTIFACTS)
@pytest.mark.parametrize("missing", ["snapshot", "rows", "monthlyCost", "estimateInput"])
def test_registered_estimate_requires_retention_members(tmp_path, retained_estimate, artifact, missing):
    retained = retained_estimate["export_inputs"]
    if missing in ("snapshot", "rows"):
        del retained[missing]
    else:
        del retained["rows"][POINTER][missing]
    result, report = validate(tmp_path, artifact, retained_estimate)
    assert result.returncode == 1
    assert any(e["code"] == "SCHEMA_VIOLATION" and e["path"].endswith(missing) for e in report["errors"])


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_retention_does_not_open_unrelated_estimate_keys(tmp_path, retained_estimate, artifact):
    retained_estimate["unrelated_root"] = {}
    retained_estimate["projected_costs"]["breakdown"]["compute"]["unrelated_row"] = 1
    result, report = validate(tmp_path, artifact, retained_estimate)
    assert result.returncode == 1
    errors = {(e["code"], e["path"]) for e in report["errors"]}
    assert ("UNKNOWN_KEY", "unrelated_root") in errors
    assert ("UNKNOWN_KEY", "projected_costs.breakdown.compute.unrelated_row") in errors
