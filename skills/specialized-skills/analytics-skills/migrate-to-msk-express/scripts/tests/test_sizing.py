"""Tests for sizing.py (compute + workbook fill via stdlib zipfile/re).

Run from the skill root:
    python3 -m pytest scripts/tests/

These tests verify the computed workload inputs, the workbook cell map, and the
in-place fill of the six input cells. The fill tests build a tiny synthetic
.xlsx in-process — no network and no real AWS workbook are required. The
workbook's own formulas are AWS's responsibility and are not exercised here.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

# Make scripts importable.
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import sizing as s  # noqa: E402


@pytest.fixture
def base_cfg() -> dict:
    """3 brokers × 50/100 MBps in/out, 1200 leader partitions (3600 replicas at RF 3), retention 48h/72h."""
    return {
        "cluster_name": "test-cluster",
        "kafka": {"version": "3.9.0", "coordination_mechanism": "KRaft"},
        "topology": {"num_brokers": 3, "num_azs": 3},
        "topics": [
            {
                "name": "t1",
                "num_partitions": 600,
                "replication_factor": 3,
                "configs": {"retention.ms": str(48 * 3600 * 1000)},
            },
            {
                "name": "t2",
                "num_partitions": 600,
                "replication_factor": 3,
                "configs": {"retention.ms": str(72 * 3600 * 1000)},
            },
        ],
        "broker_configs": {},
        "security": {"encryption_in_transit": "TLS", "authentication": "SASL_SCRAM"},
        "metrics": {
            "peak_bytes_in_per_broker_mbps": 50,
            "peak_bytes_out_per_broker_mbps": 100,
            "peak_partitions_per_broker": 100,
            "peak_connections_per_broker": 500,
        },
    }


# Cells the workbook fill targets, with synthetic default values to overwrite.
_DEFAULT_CELLS = {"C11": 500, "C12": 500, "C13": 500, "C14": 500, "C17": 24, "C20": 1000}


def _make_workbook_bytes(cells: dict[str, object] | None = None) -> bytes:
    """Build a minimal valid-enough .xlsx with the input cells on 'MSK Provisioned'.

    Includes workbook.xml (with a sheet entry + calcPr), the workbook rels, and
    a worksheet carrying the six input cells. Enough for fill_workbook to
    resolve the sheet and rewrite values.
    """
    cells = cells or _DEFAULT_CELLS
    rows = "".join(
        f'<row r="{ref[1:]}"><c r="{ref}" s="1"><v>{val}</v></c></row>'
        for ref, val in cells.items()
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{rows}</sheetData></worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="MSK Provisioned" sheetId="1" r:id="rId1"/>'
        '<sheet name="Other" sheetId="2" r:id="rId2"/></sheets>'
        '<calcPr calcId="191028"/></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        "</Types>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/worksheets/sheet2.xml", "<worksheet/>")
    return buf.getvalue()


def _read_cell(xlsx_bytes: bytes, cell_ref: str) -> str:
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    import re

    m = re.search(r'<c r="' + cell_ref + r'"[^>]*?>.*?<v>([^<]*)</v>', sheet, re.DOTALL)
    assert m, f"cell {cell_ref} or its <v> not found"
    return m.group(1)


class TestComputeInputs:
    def test_peaks_multiply_by_broker_count(self, base_cfg):
        out = s.compute_inputs(base_cfg)
        assert out["peak_in_mbps"] == 50 * 3
        assert out["peak_out_mbps"] == 100 * 3

    def test_partition_replicas_use_express_rf_3(self, base_cfg):
        # 600 + 600 = 1200 leader partitions; Express target RF 3 -> 3600.
        out = s.compute_inputs(base_cfg)
        assert out["leader_partitions"] == 1200
        assert out["total_partition_replicas"] == 3600

    def test_total_replicas_ignore_source_rf(self, base_cfg):
        # Source uses RF 2, but Express always lands at RF 3, so total is still
        # leaders x 3, not leaders x source RF.
        for t in base_cfg["topics"]:
            t["replication_factor"] = 2
        out = s.compute_inputs(base_cfg)
        assert out["leader_partitions"] == 1200
        assert out["total_partition_replicas"] == 3600

    def test_retention_max_over_topics_in_hours(self, base_cfg):
        out = s.compute_inputs(base_cfg)
        assert out["retention_hrs"] == 72.0

    def test_retention_defaults_to_24h_when_absent(self, base_cfg):
        for t in base_cfg["topics"]:
            t["configs"] = {}
        out = s.compute_inputs(base_cfg)
        assert out["retention_hrs"] == 24

    def test_metrics_missing_yields_zero_peaks(self, base_cfg):
        del base_cfg["metrics"]
        out = s.compute_inputs(base_cfg)
        assert out["peak_in_mbps"] == 0
        assert out["peak_out_mbps"] == 0

    def test_avg_from_contract_is_none_when_not_supplied(self, base_cfg):
        # base_cfg's metrics block has no avg_* fields → contract avg is None.
        out = s.compute_inputs(base_cfg)
        assert out["avg_in_mbps_from_contract"] is None
        assert out["avg_out_mbps_from_contract"] is None

    def test_avg_from_contract_multiplies_by_broker_count(self, base_cfg):
        base_cfg["metrics"]["avg_bytes_in_per_broker_mbps"] = 30
        base_cfg["metrics"]["avg_bytes_out_per_broker_mbps"] = 60
        out = s.compute_inputs(base_cfg)
        # 3 brokers (per fixture topology.num_brokers).
        assert out["avg_in_mbps_from_contract"] == 30 * 3
        assert out["avg_out_mbps_from_contract"] == 60 * 3


class TestResolveAvg:
    def test_cli_override_wins(self):
        # CLI > contract > peak/2
        assert s._resolve_avg(cli_override=100, contract_value=50, peak_mbps=200) == 100

    def test_contract_used_when_no_cli(self):
        assert s._resolve_avg(cli_override=None, contract_value=50, peak_mbps=200) == 50

    def test_peak_half_fallback(self):
        assert s._resolve_avg(cli_override=None, contract_value=None, peak_mbps=200) == 100


class TestBuildCellMap:
    def test_maps_six_input_cells(self):
        cells = s.build_cell_map(
            peak_in_mbps=600.0,
            peak_out_mbps=1200.0,
            total_partition_replicas=1200,
            retention_hrs=72.0,
            avg_in_mbps=300.0,
            avg_out_mbps=600.0,
        )
        by_cell = {row["cell"]: row["value"] for row in cells}
        assert by_cell == {
            "C11": 300.0,
            "C12": 600.0,
            "C13": 600.0,
            "C14": 1200.0,
            "C17": 72.0,
            "C20": 1200,
        }


class TestFmtNum:
    def test_integer_floats_render_without_decimal(self):
        assert s._fmt_num(75.0) == "75"
        assert s._fmt_num(3600) == "3600"

    def test_fractional_value_has_no_trailing_zeros(self):
        assert s._fmt_num(42.5) == "42.5"

    def test_large_value_avoids_scientific_notation(self):
        assert s._fmt_num(3_600_000) == "3600000"


class TestFillWorkbook:
    def test_replaces_targeted_cell_values(self):
        wb = _make_workbook_bytes()
        filled = s.fill_workbook(
            wb,
            {"C11": 75.0, "C12": 150.0, "C13": 100.0, "C14": 200.0, "C17": 72.0, "C20": 3600},
        )
        assert _read_cell(filled, "C11") == "75"
        assert _read_cell(filled, "C12") == "150"
        assert _read_cell(filled, "C17") == "72"
        assert _read_cell(filled, "C20") == "3600"

    def test_sets_full_calc_on_load(self):
        wb = _make_workbook_bytes()
        filled = s.fill_workbook(wb, {"C20": 3600})
        with zipfile.ZipFile(io.BytesIO(filled)) as z:
            workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
        assert 'fullCalcOnLoad="1"' in workbook_xml

    def test_preserves_other_zip_entries(self):
        wb = _make_workbook_bytes()
        filled = s.fill_workbook(wb, {"C20": 3600})
        with zipfile.ZipFile(io.BytesIO(filled)) as z:
            names = set(z.namelist())
        assert {"[Content_Types].xml", "xl/worksheets/sheet2.xml"} <= names

    def test_missing_cell_raises(self):
        # A workbook lacking C20 must fail loudly rather than ship wrong data.
        wb = _make_workbook_bytes({"C11": 1, "C12": 1, "C13": 1, "C14": 1, "C17": 1})
        with pytest.raises(ValueError, match="C20 not found"):
            s.fill_workbook(wb, {"C20": 3600})

    def test_missing_sheet_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(
                "xl/workbook.xml",
                '<workbook xmlns:r="r"><sheets><sheet name="Nope" r:id="rId1"/></sheets></workbook>',
            )
            z.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            )
        with pytest.raises(ValueError, match="MSK Provisioned"):
            s.fill_workbook(buf.getvalue(), {"C20": 3600})


def _read_inputs(path: Path) -> dict[str, object]:
    artifact = json.loads(path.read_text())
    return {row["cell"]: row["value"] for row in artifact["inputs"]}


class TestCLI:
    def test_main_writes_inputs_json(self, base_cfg, tmp_path):
        in_path = tmp_path / "cluster-config.json"
        in_path.write_text(json.dumps(base_cfg))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc = s.main([str(in_path), "--out-dir", str(out_dir)])
        assert rc == 0
        out_path = out_dir / "msk-sizing-inputs.test-cluster.json"
        assert out_path.exists()
        cells = _read_inputs(out_path)
        assert cells["C12"] == 150.0  # peak in: 50 × 3
        assert cells["C14"] == 300.0  # peak out: 100 × 3
        assert cells["C20"] == 3600  # 1200 leaders × RF 3
        assert cells["C11"] == 75.0  # avg in defaults to peak/2 = 150/2
        assert cells["C17"] == 72.0  # max retention 72h

    def test_artifact_carries_workbook_source_page(self, base_cfg, tmp_path):
        in_path = tmp_path / "cluster-config.json"
        in_path.write_text(json.dumps(base_cfg))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        s.main([str(in_path), "--out-dir", str(out_dir)])
        artifact = json.loads((out_dir / "msk-sizing-inputs.test-cluster.json").read_text())
        assert artifact["workbook"]["sheet"] == s.SHEET_NAME
        assert artifact["workbook"]["source_page"] == s.WORKBOOK_DOCS_URL

    def test_cli_avg_override_applied(self, base_cfg, tmp_path):
        in_path = tmp_path / "cluster-config.json"
        in_path.write_text(json.dumps(base_cfg))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        s.main([str(in_path), "--out-dir", str(out_dir), "--avg-in-mbps", "420", "--avg-out-mbps", "850"])
        cells = _read_inputs(out_dir / "msk-sizing-inputs.test-cluster.json")
        assert cells["C11"] == 420.0
        assert cells["C13"] == 850.0

    def test_main_fills_workbook_when_provided(self, base_cfg, tmp_path):
        in_path = tmp_path / "cluster-config.json"
        in_path.write_text(json.dumps(base_cfg))
        wb_path = tmp_path / "MSK_Sizing_Pricing.xlsx"
        wb_path.write_bytes(_make_workbook_bytes())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc = s.main([str(in_path), "--workbook", str(wb_path), "--out-dir", str(out_dir)])
        assert rc == 0
        filled = out_dir / "MSK_Sizing_Pricing.test-cluster.xlsx"
        assert filled.exists()
        # C20 = 3600 (1200 leaders × 3), C12 = 150 (peak in 50 × 3).
        assert _read_cell(filled.read_bytes(), "C20") == "3600"
        assert _read_cell(filled.read_bytes(), "C12") == "150"
