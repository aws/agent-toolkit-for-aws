#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# ///
"""
Fills the AWS-published MSK Sizing/Pricing workbook from the discovery
contract. This script does no sizing math of its own and ships no spreadsheet
library: it derives the six workload inputs from `cluster-config.json`, then
writes them into the "MSK Provisioned" sheet of a workbook the agent has
already downloaded, using only the standard library (`zipfile` + `re`).

The workbook is NOT packaged with this skill and this script does NOT download
it. The agent reads the AWS "Express best practices" page (link below), follows
the "MSK Sizing/Pricing workbook" hyperlink on that page to download the
`.xlsx` locally, and passes the local path via `--workbook`. The download URL
is intentionally resolved from the AWS page each time rather than hardcoded
here, so the skill always tracks the current AWS-published workbook.

Cell mapping (sheet "MSK Provisioned"):
    C11  Average Data In  MB/s   = avg_bytes_in_per_broker_mbps × num_brokers
                                   (falls back to peak_in / 2 if the contract
                                   doesn't carry avg; override via --avg-in-mbps)
    C12  Peak Data In     MB/s   = peak_bytes_in_per_broker_mbps × num_brokers
    C13  Average Data Out MB/s   = avg_bytes_out_per_broker_mbps × num_brokers
                                   (falls back to peak_out / 2; override via
                                   --avg-out-mbps)
    C14  Peak Data Out    MB/s   = peak_bytes_out_per_broker_mbps × num_brokers
    C17  Retention Hrs           = max retention.ms over topics, ÷ 3_600_000
    C20  Partitions              = sum(num_partitions over topics) x 3
                                   -- total partition replicas on the Express
                                   target (RF is always 3; source RF ignored)

Caveats:
- Average throughput precedence: CLI flag > discovery contract > peak/2
  fallback. The peak/2 fallback is a rough heuristic; supply real averages
  via the contract or CLI for accurate cost projection.
- Retention is per-topic in the contract; the workbook takes one number. We
  emit the max as an upper bound for storage cost. Override via --retention-hrs.

Usage:
    # Fill a workbook the agent downloaded from the AWS Express best-practices page:
    sizing.py <cluster-config.json> --workbook <downloaded.xlsx> [--out-dir <d>]
                                    [--avg-in-mbps N] [--avg-out-mbps N]
                                    [--retention-hrs N]

    # Without --workbook: emit the JSON inputs + a fill-in table only.
    sizing.py <cluster-config.json> [--out-dir <d>]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

SHEET_NAME = "MSK Provisioned"

# Pointer to the AWS page that links the workbook. The agent reads this page,
# finds the "MSK Sizing/Pricing workbook" hyperlink, and downloads the .xlsx
# itself. The direct download URL is deliberately NOT hardcoded here so the
# skill always resolves the current AWS-published workbook from the page.
WORKBOOK_DOCS_URL = (
    "https://docs.aws.amazon.com/msk/latest/developerguide/"
    "bestpractices-express.html#brokers-per-express-cluster"
)

# Cell mapping. Source: AWS workbook "MSK Provisioned" tab, cluster design
# inputs section starting at row 11.
CELL_AVG_IN_MBPS = "C11"
CELL_PEAK_IN_MBPS = "C12"
CELL_AVG_OUT_MBPS = "C13"
CELL_PEAK_OUT_MBPS = "C14"
CELL_RETENTION_HRS = "C17"
CELL_PARTITIONS = "C20"

# MSK Express always creates topics at replication factor 3 (enforced; not
# configurable). The target replica count is therefore the source's leader
# partition count times 3, independent of the source cluster's own RF.
EXPRESS_REPLICATION_FACTOR = 3


def compute_inputs(cfg: dict) -> dict:
    """Derive workbook input values from the discovery contract.

    Returns peaks (always present), totals, retention, and contract-supplied
    averages if the contract carries them. The averages are None when the
    contract did not supply them; the caller is responsible for falling back
    to peak/2 in that case.
    """
    metrics = cfg.get("metrics") or {}
    bc = int(cfg["topology"]["num_brokers"])

    # Peaks: per-broker × num_brokers = total cluster peak.
    peak_in_per_broker = float(metrics.get("peak_bytes_in_per_broker_mbps") or 0)
    peak_out_per_broker = float(metrics.get("peak_bytes_out_per_broker_mbps") or 0)
    peak_in_total = peak_in_per_broker * bc
    peak_out_total = peak_out_per_broker * bc

    # Averages from the contract (optional). When present, prefer these over
    # the peak/2 heuristic. None means "fall back".
    avg_in_per_broker = metrics.get("avg_bytes_in_per_broker_mbps")
    avg_out_per_broker = metrics.get("avg_bytes_out_per_broker_mbps")
    avg_in_total = float(avg_in_per_broker) * bc if avg_in_per_broker is not None else None
    avg_out_total = float(avg_out_per_broker) * bc if avg_out_per_broker is not None else None

    # Partition counts. Two distinct quantities matter:
    #   leader_partitions     = sum(num_partitions) -- one leader per partition
    #   total_partition_replicas = leaders x Express RF (3)
    # Workbook cell C20 ("Partitions") is divided by a per-broker capacity that
    # AWS defines as partitions "including leader and follower replicas" (MSK
    # Express broker partition quota), so C20 must be the TOTAL replica count.
    # The target is always Express (RF=3), so the source cluster's own
    # replication factor is irrelevant here.
    leader_partitions = sum(int(t["num_partitions"]) for t in cfg.get("topics", []))
    total_partition_replicas = leader_partitions * EXPRESS_REPLICATION_FACTOR

    # Retention: max retention.ms across topics, in hours. Default 24 if no
    # topic carries an explicit retention.ms in its configs.
    max_retention_ms = 0
    for t in cfg.get("topics", []):
        cfgs = t.get("configs") or {}
        if "retention.ms" in cfgs:
            try:
                max_retention_ms = max(max_retention_ms, int(cfgs["retention.ms"]))
            except (TypeError, ValueError):
                pass
    retention_hrs = max_retention_ms / 3_600_000 if max_retention_ms else 24

    return {
        "peak_in_mbps": peak_in_total,
        "peak_out_mbps": peak_out_total,
        "avg_in_mbps_from_contract": avg_in_total,
        "avg_out_mbps_from_contract": avg_out_total,
        "leader_partitions": leader_partitions,
        "total_partition_replicas": total_partition_replicas,
        "retention_hrs": retention_hrs,
    }


def _resolve_avg(
    cli_override: float | None,
    contract_value: float | None,
    peak_mbps: float,
) -> float:
    """Return the avg-throughput value for the workbook.

    Precedence: CLI override > contract value > peak/2 fallback. The peak/2
    fallback exists for discovery outputs that don't carry the optional
    avg_bytes_*_per_broker_mbps fields.
    """
    if cli_override is not None:
        return cli_override
    if contract_value is not None:
        return contract_value
    return peak_mbps / 2


def build_cell_map(
    peak_in_mbps: float,
    peak_out_mbps: float,
    total_partition_replicas: int,
    retention_hrs: float,
    avg_in_mbps: float,
    avg_out_mbps: float,
) -> list[dict]:
    """Return the ordered list of workbook input cells and their values."""
    return [
        {"cell": CELL_AVG_IN_MBPS, "label": "Average Data In (MB/s)", "value": avg_in_mbps},
        {"cell": CELL_PEAK_IN_MBPS, "label": "Peak Data In (MB/s)", "value": peak_in_mbps},
        {"cell": CELL_AVG_OUT_MBPS, "label": "Average Data Out (MB/s)", "value": avg_out_mbps},
        {"cell": CELL_PEAK_OUT_MBPS, "label": "Peak Data Out (MB/s)", "value": peak_out_mbps},
        {"cell": CELL_RETENTION_HRS, "label": "Retention (hours)", "value": retention_hrs},
        {
            "cell": CELL_PARTITIONS,
            "label": "Partitions (total replicas, replication factor 3)",
            "value": total_partition_replicas,
        },
    ]


# --------------------------------------------------------------------------- #
# Workbook filling (standard library only: zipfile + re).
#
# An .xlsx is a zip of XML parts. We rewrite only the numeric <v> values of the
# six input cells on the "MSK Provisioned" sheet, leaving the workbook's own
# formulas, formatting, and charts untouched. No spreadsheet library and no XML
# parser of untrusted content -- just targeted, anchored string replacement on
# the known input cells.
# --------------------------------------------------------------------------- #


def _fmt_num(value: float | int) -> str:
    """Format a number for an xlsx <v> element without scientific notation."""
    f = round(float(value), 6)
    if f.is_integer():
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def _resolve_sheet_path(workbook_xml: str, zin: zipfile.ZipFile) -> str:
    """Resolve '<SHEET_NAME>' to its xl/worksheets/sheetN.xml part.

    Reads the sheet's relationship id from workbook.xml, then the matching
    Target from xl/_rels/workbook.xml.rels. Avoids assuming a fixed sheet
    ordering.
    """
    sheet_m = re.search(
        r'<sheet\b[^>]*\bname="' + re.escape(SHEET_NAME) + r'"[^>]*?/>',
        workbook_xml,
    )
    if not sheet_m:
        raise ValueError(f"sheet {SHEET_NAME!r} not found in workbook.xml")
    rid_m = re.search(r'r:id="([^"]+)"', sheet_m.group(0))
    if not rid_m:
        raise ValueError(f"no relationship id on sheet {SHEET_NAME!r}")
    rid = rid_m.group(1)

    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rel_m = re.search(
        r'<Relationship\b[^>]*\bId="' + re.escape(rid) + r'"[^>]*?/>',
        rels,
    )
    if not rel_m:
        raise ValueError(f"relationship {rid!r} not found in workbook.xml.rels")
    tgt_m = re.search(r'Target="([^"]+)"', rel_m.group(0))
    if not tgt_m:
        raise ValueError(f"no Target on relationship {rid!r}")
    target = tgt_m.group(1).lstrip("/")
    if not target.startswith("xl/"):
        target = "xl/" + target
    return target


def _set_cell_value(sheet_xml: str, cell_ref: str, value: float | int) -> str:
    """Replace the numeric value of a single cell, anchored on its r="..." ref.

    Handles both populated (`<c r=".." ..><v>old</v></c>`) and empty/self-closing
    (`<c r=".." ../>`) cells, and strips any cell type attribute so the value is
    treated as a number. Raises if the cell is absent (loud failure rather than
    a silently wrong workbook).
    """
    pattern = re.compile(
        r'(<c\s+r="' + re.escape(cell_ref) + r'"[^>]*?)(?:/>|>.*?</c>)',
        re.DOTALL,
    )
    m = pattern.search(sheet_xml)
    if not m:
        raise ValueError(f"cell {cell_ref} not found in worksheet {SHEET_NAME!r}")
    head = re.sub(r'\s+t="[^"]*"', "", m.group(1))
    new_cell = f"{head}><v>{_fmt_num(value)}</v></c>"
    return sheet_xml[: m.start()] + new_cell + sheet_xml[m.end() :]


def _force_full_calc(workbook_xml: str) -> str:
    """Set calcPr/@fullCalcOnLoad=1 so dependent formulas recompute on open."""
    if "<calcPr" not in workbook_xml:
        return workbook_xml

    def repl(match: re.Match) -> str:
        tag = match.group(0)
        if "fullCalcOnLoad=" in tag:
            return re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
        return re.sub(r"\s*/?>$", ' fullCalcOnLoad="1"/>', tag)

    return re.sub(r"<calcPr\b[^>]*?/?>", repl, workbook_xml, count=1)


def fill_workbook(xlsx_bytes: bytes, cell_values: dict[str, float | int]) -> bytes:
    """Return a copy of the workbook with the given cells set on SHEET_NAME.

    Only the targeted input cells and calcPr are modified; every other zip
    entry is copied through byte-for-byte.
    """
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        workbook_xml = zin.read("xl/workbook.xml").decode("utf-8")
        sheet_path = _resolve_sheet_path(workbook_xml, zin)
        sheet_xml = zin.read(sheet_path).decode("utf-8")
        for cell, val in cell_values.items():
            sheet_xml = _set_cell_value(sheet_xml, cell, val)
        workbook_xml_new = _force_full_calc(workbook_xml)

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == sheet_path:
                    data: bytes = sheet_xml.encode("utf-8")
                elif item.filename == "xl/workbook.xml":
                    data = workbook_xml_new.encode("utf-8")
                else:
                    data = zin.read(item.filename)
                zout.writestr(item, data)
    return out.getvalue()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Fill the AWS MSK Sizing/Pricing workbook from a discovery "
            "cluster-config.json. The agent downloads the workbook from the "
            "AWS Express best-practices page and passes it via --workbook; "
            "without it, this emits a JSON artifact and a fill-in table only."
        ),
    )
    p.add_argument(
        "cluster_config",
        type=Path,
        help="Path to migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json (discovery output).",
    )
    p.add_argument(
        "--workbook",
        type=Path,
        default=None,
        help=(
            "Path to the AWS-published MSK Sizing/Pricing workbook (.xlsx) that "
            "the agent downloaded from the Express best-practices page. When "
            "provided, the script fills the six input cells and writes the "
            "filled workbook to the out-dir."
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write msk-sizing-inputs.<cluster_name>.json and the filled workbook.",
    )
    p.add_argument(
        "--avg-in-mbps",
        type=float,
        default=None,
        help=(
            "Override average ingress MBps. Defaults to peak/2 — accurate cost "
            "projection requires the real average."
        ),
    )
    p.add_argument(
        "--avg-out-mbps",
        type=float,
        default=None,
        help="Override average egress MBps. Defaults to peak/2.",
    )
    p.add_argument(
        "--retention-hrs",
        type=float,
        default=None,
        help=(
            "Override retention hours. Defaults to max retention.ms across "
            "topics ÷ 3_600_000, or 24h if no topic specifies retention.ms."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    cfg = json.loads(args.cluster_config.read_text())

    inputs = compute_inputs(cfg)
    retention_hrs = args.retention_hrs if args.retention_hrs is not None else inputs["retention_hrs"]
    avg_in = _resolve_avg(args.avg_in_mbps, inputs["avg_in_mbps_from_contract"], inputs["peak_in_mbps"])
    avg_out = _resolve_avg(args.avg_out_mbps, inputs["avg_out_mbps_from_contract"], inputs["peak_out_mbps"])

    cell_map = build_cell_map(
        peak_in_mbps=inputs["peak_in_mbps"],
        peak_out_mbps=inputs["peak_out_mbps"],
        total_partition_replicas=inputs["total_partition_replicas"],
        retention_hrs=retention_hrs,
        avg_in_mbps=avg_in,
        avg_out_mbps=avg_out,
    )

    cluster_name = cfg["cluster_name"]
    artifact = {
        "cluster_name": cluster_name,
        "workbook": {
            "sheet": SHEET_NAME,
            "source_page": WORKBOOK_DOCS_URL,
            "note": (
                "Follow the 'MSK Sizing/Pricing workbook' link on the source "
                "page to download the workbook, then pass it via --workbook."
            ),
        },
        "inputs": cell_map,
    }
    out_path = args.out_dir / f"msk-sizing-inputs.{cluster_name}.json"
    out_path.write_text(json.dumps(artifact, indent=2) + "\n")
    print(out_path, file=sys.stderr)

    if args.workbook is not None:
        cell_values = {row["cell"]: row["value"] for row in cell_map}
        filled = fill_workbook(args.workbook.read_bytes(), cell_values)
        filled_path = args.out_dir / f"MSK_Sizing_Pricing.{cluster_name}.xlsx"
        filled_path.write_bytes(filled)
        print(f"  Filled workbook written: {filled_path}", file=sys.stderr)
        print(
            "  Open it in Excel, LibreOffice, or Google Sheets to read the "
            "recommended instance type, broker count, and monthly cost. The "
            "formulas recalculate on open.",
            file=sys.stderr,
        )
        return 0

    # No workbook supplied: emit the fill-in table and tell the agent how to
    # obtain the workbook (resolve the link from the AWS page, do not hardcode).
    print(
        f"  No --workbook supplied. Read the AWS Express best-practices page "
        f"and follow its 'MSK Sizing/Pricing workbook' link to download the "
        f"workbook, then re-run with --workbook <path>:\n    {WORKBOOK_DOCS_URL}",
        file=sys.stderr,
    )
    print(f"  Values to enter on the '{SHEET_NAME}' sheet:", file=sys.stderr)
    print(f"    {'Cell':<5} {'Field':<34} Value", file=sys.stderr)
    for row in cell_map:
        val = row["value"]
        val_str = f"{val:g}" if isinstance(val, float) else str(val)
        print(f"    {row['cell']:<5} {row['label']:<34} {val_str}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
