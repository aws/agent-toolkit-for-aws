#!/usr/bin/env python3
"""Fail-closed render-only pass over a generated Render migration report.

The plugin-root ``scripts/validate-migration-report.py`` owns report structure
(shared section IDs, TOC, decision core, appendix depth), readability,
accessibility, the visual shell, and the shared cost anchors
(``current_monthly``, ``aws_monthly_balanced``, ``aws_monthly_optimized``,
``aws_monthly_premium``). This script owns only the render-specific checks:

* ``exec-targets`` mapping rows against ``aws-design.json`` mappings
  (attribute pairs and visible service text);
* the ``data-accounted-count`` figure against the generation ledger;
* ledger reconciliation (``generation-warnings.json`` schema, per-bucket rows,
  accounting counts, warning codes) and the deferred-surface prose those
  warnings require;
* render-required sections (including Appendix I, ``appendix-assumptions``, which the shared
  default set treats as optional) and their TOC links, plus the required phrases per
  migration section;
* the render-local ``delta`` cost anchor (``rightsizing_delta.monthly``, like-for-like
  minus Balanced);
* the render-local ``like_for_like_monthly`` cost anchor (``scenarios.like_for_like.known_cost_monthly_usd``,
  exactly one inside ``exec-costs``, compared after whole-dollar half-even rounding like the
  shared anchors; codes ``COST_LIKE_FOR_LIKE_MONTHLY_MISSING`` / ``_MISMATCH`` / ``_SOURCE_INVALID``);
* exactly one ``aws_monthly_optimized`` anchor inside ``exec-costs`` (plus one
  ``aws_monthly_premium`` anchor when ``projected_costs.aws_monthly_premium`` exists), and
  ``projected_costs.aws_monthly_premium`` / ``aws_monthly_balanced`` / ``aws_monthly_optimized``
  equal to ``scenarios.premium`` / ``balanced`` / ``optimized`` ``.known_cost_monthly_usd``;
* the unavailable-baseline literal when ``current_costs.render_monthly`` is null;
* Appendix G lists every resource address ``terraform/baseline.tf`` emits
  (``SECURITY_BASELINE_RESOURCE_MISSING`` / ``SECTION_APPENDIX_SECURITY_MISSING``);
  inert when no ``baseline.tf`` sits beside the report;
* secrets, keys, and local-path exclusions in rendered text.

Paths must be absolute and inside ``--migration-dir``; ``aws-design.json`` and
``estimation-infra.json`` are read from ``--migration-dir`` and
``generation-warnings.json`` and ``terraform/baseline.tf`` from the report's own
directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

import jsonschema

MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
RENDER_SECTIONS = (
    "exec-architecture", "exec-targets", "migration-data", "migration-storage",
    "migration-deployment", "cutover", "rollback", "verification",
    "deferred-surfaces", "appendix-accounting", "appendix-assumptions",
)
INERT = {"script", "style", "template"}
COST_PATHS = {
    "delta": ("rightsizing_delta", "monthly"),
}
# Anchors compared after the same display rounding the shared anchors use (whole dollars,
# half-to-even, for monthly-scale figures; cents below $2), exactly one inside exec-costs.
ROUNDED_COST_PATHS = {
    "like_for_like_monthly": ("scenarios", "like_for_like", "known_cost_monthly_usd"),
}
SECTION_TERMS = {
    "exec-architecture": (("build-once", "build once"), ("private",), ("managed",)),
    "migration-data": (("postgres",), ("database migration service", "pg_dump"), ("quiesc",), ("integrity",), ("source retention",)),
    "migration-storage": (("efs",), ("/var/data",), ("pre-copy",), ("delta",), ("ownership",), ("permissions",), ("integrity",)),
    "migration-deployment": (("ecr",), ("digest",), ("serving deploy",), ("auto-deploy",), ("rollback",)),
    "cutover": (("dns",), ("ttl",), ("certificate",), ("traffic",), ("writer quiescence",)),
    "rollback": (("source retention",), ("render",), ("restore",), ("dns",), ("writer",)),
    "verification": (("endpoint",), ("database",), ("cache",), ("disk",), ("workflow",)),
}
MONEY_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:USD\s*)?([-\u2212])?\s*\$?\s*([-\u2212])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
)
BASELINE_RESOURCE_RE = re.compile(r'^resource\s+"([a-z0-9_]+)"\s+"([a-z0-9_]+)"', re.M)


class ReportParser(HTMLParser):
    """Collect rendered structure while excluding hidden and inert subtrees."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.sections: dict[str, list[str]] = {}
        self.section_stack: list[str] = []
        self.ids: list[str] = []
        self.toc_links: list[str] = []
        self.mapping_rows: list[tuple[str, str, str]] = []
        self.mapping_stack: list[dict] = []
        self.incomplete_mapping_rows = 0
        self.costs: dict[str, list[str]] = {}
        self.cost_stack: list[dict] = []
        self.exec_costs: dict[str, list[str]] = {}
        self.accounted_values: list[str] = []
        self.rendered_text: list[str] = []

    def _skipped(self) -> bool:
        return bool(self.stack and self.stack[-1]["skip"])

    def _inside_toc(self) -> bool:
        for frame in self.stack:
            if frame["tag"] == "nav" and frame.get("toc"):
                return True
        return False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            popped = self.stack[index:]
            del self.stack[index:]
            for frame in reversed(popped):
                if frame.get("cost") is not None:
                    cost = frame["cost"]
                    if cost in self.cost_stack:
                        self.cost_stack.remove(cost)
                    self.costs.setdefault(cost["key"], []).append("".join(cost["parts"]))
                    if cost["in_exec_costs"]:
                        self.exec_costs.setdefault(cost["key"], []).append("".join(cost["parts"]))
                if frame.get("mapping") is not None:
                    mapping = frame["mapping"]
                    if mapping in self.mapping_stack:
                        self.mapping_stack.remove(mapping)
                    self.mapping_rows.append((mapping["source_id"], mapping["aws_service"], "".join(mapping["parts"])))
                if frame.get("section") is not None and frame["section"] in self.section_stack:
                    self.section_stack.remove(frame["section"])
            return

    def handle_data(self, data: str) -> None:
        if self._skipped():
            return
        self.rendered_text.append(data)
        for section_id in self.section_stack:
            self.sections[section_id].append(data)
        for cost in self.cost_stack:
            cost["parts"].append(data)
        for mapping in self.mapping_stack:
            mapping["parts"].append(data)

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        parent_skip = self._skipped()
        skip = parent_skip or tag in INERT or "hidden" in attrs or attrs.get("aria-hidden", "").lower() == "true"
        frame = {"tag": tag, "skip": skip, "section": None, "cost": None, "toc": False, "mapping": None}
        if not skip:
            element_id = attrs.get("id")
            if element_id:
                self.ids.append(element_id)
            if tag == "section" and element_id:
                self.sections.setdefault(element_id, [])
                self.section_stack.append(element_id)
                frame["section"] = element_id
            if tag == "nav" and "toc" in (attrs.get("class") or "").split():
                frame["toc"] = True
            if tag == "a" and self._inside_toc() and (attrs.get("href") or "").startswith("#"):
                self.toc_links.append((attrs.get("href") or "")[1:])
            source_id = attrs.get("data-source-resource-id")
            aws_service = attrs.get("data-aws-service")
            if source_id is not None or aws_service is not None:
                if source_id and aws_service:
                    mapping = {"source_id": source_id, "aws_service": aws_service, "parts": []}
                    self.mapping_stack.append(mapping)
                    frame["mapping"] = mapping
                else:
                    self.incomplete_mapping_rows += 1
            cost_key = attrs.get("data-cost-key")
            if cost_key:
                cost_frame = {"key": cost_key, "parts": [], "in_exec_costs": "exec-costs" in self.section_stack}
                self.cost_stack.append(cost_frame)
                frame["cost"] = cost_frame
            accounted = attrs.get("data-accounted-count")
            if accounted is not None:
                self.accounted_values.append(accounted)
        if tag not in self.VOID:
            self.stack.append(frame)


def _contained_regular(path: Path, root: Path, max_bytes: int) -> Path:
    if not path.is_absolute() or not root.is_absolute():
        raise ValueError("paths_must_be_absolute")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("migration_dir_not_regular")
    if path.is_symlink() or not path.is_file():
        raise ValueError("input_not_regular")
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("input_outside_migration_dir")
    if resolved.stat().st_size > max_bytes:
        raise ValueError("input_too_large")
    return resolved


def _load_json(path: Path, root: Path) -> dict:
    resolved = _contained_regular(path, root, MAX_JSON_BYTES)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("json_root_not_object")
    return value


def _dig(value: dict, path: tuple[str, ...]):
    current: object = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _money(text: str) -> Decimal | None:
    """Parse a rendered dollar figure; the minus may precede or follow the sign (-$62, $-62, \u2212$62)."""
    match = MONEY_RE.search(text)
    if not match:
        return None
    try:
        value = Decimal(match.group(3).replace(",", ""))
    except InvalidOperation:
        return None
    return -value if (match.group(1) or match.group(2)) else value


def _display_money(value: Decimal) -> Decimal:
    """Display form of a dollar figure: whole dollars half-to-even at $2 and above, cents below."""
    whole = value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    if abs(whole) >= 2:
        return whole
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
def _ai_deferred(design: dict) -> bool:
    ai_track = design.get("ai_track")
    return isinstance(ai_track, dict) and ai_track.get("status") == "deferred_shared_ai_engine"


def _validate_current_monthly(estimate: dict, values: list[str]) -> list[str]:
    """Render-unique baseline rule: a null render_monthly must render as the literal 'unavailable'.

    A numeric baseline is asserted in dollars by the shared validator, so nothing
    is checked here in that case.
    """
    current = estimate.get("current_costs")
    if not isinstance(current, dict):
        current = {}
    if current.get("render_monthly") is not None:
        return []
    if current.get("source") != "unavailable":
        return ["COST_CURRENT_MONTHLY_MISSING"]
    if len(values) != 1:
        return ["COST_CURRENT_MONTHLY_MISSING"]
    if values[0].strip().casefold() != "unavailable":
        return ["COST_CURRENT_MONTHLY_UNAVAILABLE_TEXT_MISMATCH"]
    return []


# Estimate-phase mapping the report depends on: projected_costs.<key> must equal the
# scenario total it is labelled with (render-to-aws estimate-assemble.md; report-decision-core.md
# "Render scenario semantics"). The shared validator only compares the report to projected_costs,
# so this render-local pass closes the gap between projected_costs and scenarios.
SCENARIO_COSTS = (
    ("aws_monthly_premium", ("projected_costs", "aws_monthly_premium"), ("scenarios", "premium", "known_cost_monthly_usd")),
    ("aws_monthly_balanced", ("projected_costs", "aws_monthly_balanced"), ("scenarios", "balanced", "known_cost_monthly_usd")),
    ("aws_monthly_optimized", ("projected_costs", "aws_monthly_optimized"), ("scenarios", "optimized", "known_cost_monthly_usd")),
)
def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
def _validate_scenario_costs(estimate: dict, exec_costs: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    for key, projected_path, scenario_path in SCENARIO_COSTS:
        projected = _dig(estimate, projected_path)
        scenario = _dig(estimate, scenario_path)
        if projected is None and scenario is None:
            continue
        projected_decimal, scenario_decimal = _decimal(projected), _decimal(scenario)
        if projected_decimal is None or scenario_decimal is None or projected_decimal != scenario_decimal:
            errors.append(f"COST_{key.upper()}_SCENARIO_MISMATCH")
    # Optimized is required whenever the estimate carries it; premium whenever its value exists.
    # Exactly one anchor inside exec-costs, so a stale or duplicated figure cannot hide.
    for key in ("aws_monthly_optimized", "aws_monthly_premium"):
        if _dig(estimate, ("projected_costs", key)) is None and not (
            key == "aws_monthly_optimized" and _dig(estimate, ("scenarios", "optimized", "known_cost_monthly_usd")) is not None
        ):
            continue
        if len(exec_costs.get(key, [])) != 1:
            errors.append(f"COST_{key.upper()}_MISSING")
    return errors
def _validate_ledger(ledger: dict, design: dict) -> list[str]:
    errors: list[str] = []
    mappings = design.get("mappings")
    if not isinstance(mappings, list):
        return ["DESIGN_MAPPINGS_INVALID"]
    design_ids = [row.get("source_resource_id") for row in mappings if isinstance(row, dict)]
    classified: list[str] = []
    for bucket in ("generated", "consumed_topology", "deferred", "unsupported"):
        rows = ledger.get(bucket)
        if not isinstance(rows, list):
            errors.append(f"LEDGER_{bucket.upper()}_INVALID")
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("source_resource_id"), str):
                errors.append(f"LEDGER_{bucket.upper()}_ROW_INVALID")
            else:
                classified.append(row["source_resource_id"])
    if len(classified) != len(set(classified)):
        errors.append("ACCOUNTING_DUPLICATE_SOURCE")
    if sorted(classified) != sorted(design_ids):
        errors.append("ACCOUNTING_SOURCE_MISMATCH")
    accounting = ledger.get("accounting")
    if not isinstance(accounting, dict):
        return errors + ["ACCOUNTING_INVALID"]
    expected_counts = {
        "design_count": len(design_ids),
        "generated_count": len(ledger.get("generated", [])),
        "consumed_topology_count": len(ledger.get("consumed_topology", [])),
        "deferred_count": len(ledger.get("deferred", [])),
        "unsupported_count": len(ledger.get("unsupported", [])),
        "accounted_count": len(classified),
    }
    for key, expected in expected_counts.items():
        if accounting.get(key) != expected:
            errors.append(f"ACCOUNTING_{key.upper()}_MISMATCH")
    if accounting.get("source_resource_ids") != sorted(classified, key=str.encode):
        errors.append("ACCOUNTING_IDS_NOT_CANONICAL")
    warnings = ledger.get("warnings")
    if not isinstance(warnings, list):
        errors.append("WARNINGS_INVALID")
    else:
        codes = {row.get("code") for row in warnings if isinstance(row, dict)}
        if _ai_deferred(design) and "deferred_shared_ai_engine" not in codes:
            errors.append("AI_DEFERRED_WARNING_MISSING")
        if design.get("ai_track") is None and "deferred_shared_ai_engine" in codes:
            errors.append("AI_DEFERRED_WARNING_UNEXPECTED")
        if ledger.get("unsupported") and "conditional_workflow_generation_unsupported" not in codes:
            errors.append("WORKFLOW_WARNING_MISSING")
    return errors


def _validate_security_baseline(report_dir: Path, migration_dir: Path, parser: ReportParser) -> list[str]:
    """Appendix G must name every ``resource "<type>" "<name>"`` address of terraform/baseline.tf.

    Inert when no baseline.tf sits beside the report (the account baseline was
    opted out or never generated).
    """
    baseline = report_dir / "terraform" / "baseline.tf"
    if not baseline.is_file():
        return []
    baseline_text = _contained_regular(baseline, migration_dir, MAX_JSON_BYTES).read_text(encoding="utf-8")
    if "appendix-security" not in parser.ids:
        return ["SECTION_APPENDIX_SECURITY_MISSING"]
    text = " ".join(parser.sections.get("appendix-security", []))
    addresses = {f"{resource_type}.{name}" for resource_type, name in BASELINE_RESOURCE_RE.findall(baseline_text)}
    if any(address not in text for address in addresses):
        return ["SECURITY_BASELINE_RESOURCE_MISSING"]
    return []


def validate(report: Path, migration_dir: Path) -> list[str]:
    errors: list[str] = []
    report = _contained_regular(report, migration_dir, MAX_REPORT_BYTES)
    try:
        html = report.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ["REPORT_NOT_UTF8"]
    parser = ReportParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ["REPORT_HTML_PARSE_FAILED"]

    for section_id in RENDER_SECTIONS:
        count = parser.ids.count(section_id)
        code = section_id.upper().replace("-", "_")
        if count != 1:
            errors.append(f"SECTION_{code}_{'MISSING' if count == 0 else 'DUPLICATE'}")
        elif not " ".join(parser.sections.get(section_id, [])).strip():
            errors.append(f"SECTION_{code}_EMPTY")
    if not set(RENDER_SECTIONS) <= set(parser.toc_links):
        errors.append("TOC_RENDER_SECTION_MISSING")
    if len(parser.ids) != len(set(parser.ids)):
        errors.append("DUPLICATE_HTML_ID")
    for section_id, groups in SECTION_TERMS.items():
        text = " ".join(parser.sections.get(section_id, [])).lower()
        for alternatives in groups:
            if not any(term in text for term in alternatives):
                errors.append(f"CONTENT_{section_id.upper().replace('-', '_')}_{alternatives[0].upper().replace(' ', '_')}")
    rendered = " ".join(parser.rendered_text)
    privacy_patterns = {
        "PRIVACY_EMAIL": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "PRIVACY_RENDER_API_KEY": r"rnd_[A-Za-z0-9]{16,}",
        "PRIVACY_AWS_ACCESS_KEY": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "PRIVACY_PRIVATE_KEY": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "PRIVACY_LOCAL_PATH": r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\)",
    }
    for code, pattern in privacy_patterns.items():
        if re.search(pattern, rendered, re.IGNORECASE):
            errors.append(code)

    design = _load_json(migration_dir / "aws-design.json", migration_dir)
    estimate = _load_json(migration_dir / "estimation-infra.json", migration_dir)
    ledger_path = report.parent / "generation-warnings.json"
    ledger = _load_json(ledger_path, migration_dir)
    warnings_schema_path = Path(__file__).resolve().parents[1] / "references/shared/schema-generation-warnings.json"
    try:
        warnings_schema = json.loads(warnings_schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(warnings_schema).validate(ledger)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.SchemaError, jsonschema.ValidationError):
        errors.append("GENERATION_WARNINGS_SCHEMA_INVALID")
    errors.extend(_validate_ledger(ledger, design))
    errors.extend(_validate_security_baseline(report.parent, migration_dir, parser))

    if parser.incomplete_mapping_rows:
        errors.append("TARGET_ROW_ATTRIBUTES_INCOMPLETE")
    expected_pairs = sorted(
        (row["source_resource_id"], row["aws_service"])
        for row in design.get("mappings", []) if isinstance(row, dict)
    )
    actual_pairs = sorted((source_id, aws_service) for source_id, aws_service, _ in parser.mapping_rows)
    if actual_pairs != expected_pairs:
        errors.append("TARGET_MAPPING_MISMATCH")
    for _, aws_service, visible_text in parser.mapping_rows:
        normalized_text = " ".join(visible_text.split()).casefold()
        if aws_service.casefold() not in normalized_text:
            errors.append("TARGET_VISIBLE_TEXT_MISMATCH")
    for key, path in COST_PATHS.items():
        expected = _dig(estimate, path)
        values = parser.costs.get(key, [])
        if expected is None or len(values) != 1:
            errors.append(f"COST_{key.upper()}_MISSING")
            continue
        try:
            expected_decimal = Decimal(str(expected))
        except InvalidOperation:
            errors.append(f"COST_{key.upper()}_SOURCE_INVALID")
            continue
        if _money(values[0]) != expected_decimal:
            errors.append(f"COST_{key.upper()}_MISMATCH")
    for key, path in ROUNDED_COST_PATHS.items():
        expected = _dig(estimate, path)
        values = parser.exec_costs.get(key, [])
        if expected is None or len(values) != 1:
            errors.append(f"COST_{key.upper()}_MISSING")
            continue
        expected_decimal = _decimal(expected)
        if expected_decimal is None or not expected_decimal.is_finite():
            errors.append(f"COST_{key.upper()}_SOURCE_INVALID")
            continue
        if _money(values[0]) != _display_money(expected_decimal):
            errors.append(f"COST_{key.upper()}_MISMATCH")
    errors.extend(_validate_current_monthly(estimate, parser.costs.get("current_monthly", [])))
    errors.extend(_validate_scenario_costs(estimate, parser.exec_costs))
    accounted = ledger.get("accounting", {}).get("accounted_count")
    if parser.accounted_values != [str(accounted)]:
        errors.append("REPORT_ACCOUNTED_COUNT_MISMATCH")
    deferred_text = " ".join(parser.sections.get("deferred-surfaces", []))
    if _ai_deferred(design) and "deferred_shared_ai_engine" not in deferred_text:
        errors.append("AI_DEFERRED_STATE_MISSING")
    if design.get("ai_track") is None and "deferred_shared_ai_engine" in deferred_text:
        errors.append("AI_DEFERRED_WARNING_UNEXPECTED")
    if ledger.get("unsupported") and "conditional_workflow_generation_unsupported" not in deferred_text:
        errors.append("WORKFLOW_LIMIT_MISSING")
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--migration-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        errors = validate(args.report, args.migration_dir)
    except (OSError, ValueError) as exc:
        errors = [str(exc).upper()]
    if errors:
        for code in errors:
            print(f"REPORT_FAIL | code={code}")
        return 1
    print("REPORT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
