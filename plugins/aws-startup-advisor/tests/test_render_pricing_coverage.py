"""Enforce the sizing-table / rate-row pair for render-to-aws.

Every AWS service component Render's design selectors can emit, and every instance
class or node type its sizing tables can emit, must resolve to a rate row, a
_no_cost_services entry, or an _absent_services entry in the vendored pricing file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills/render-to-aws"
PRICING = json.loads((SKILL_ROOT / "references/vendored/pricing/aws-infra-pricing.json").read_text(encoding="utf-8"))
RATE_MAP = json.loads((SKILL_ROOT / "knowledge/estimate/render-service-rate-map.json").read_text(encoding="utf-8"))
COMPONENTS: dict[str, dict[str, str]] = RATE_MAP["components"]
DESIGN_DIR = SKILL_ROOT / "knowledge/design"
KINDS = {"pricing", "no_cost", "absent", "topology"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _split(aws_service: str) -> list[str]:
    return [part.strip() for part in aws_service.split(" + ")]


def _resolve(path: str) -> object:
    node: object = PRICING
    for part in path.split("."):
        assert isinstance(node, dict) and part in node, f"no rate row at {path}"
        node = node[part]
    return node


def _emitted_components() -> set[str]:
    found: set[str] = set()
    for row in _load(DESIGN_DIR / "fast-path-services.json")["rows"]:
        if "aws_service" in row:
            found.update(_split(row["aws_service"]))
    for doc in sorted((SKILL_ROOT / "references/design-refs").glob("*.md")):
        for line in doc.read_text(encoding="utf-8").splitlines():
            if "andidate set" in line:
                found.update(re.findall(r"`([^`]+)`", line.split("andidate set", 1)[1]))
    design = _load(SKILL_ROOT / "fixtures/expected/aws-design.json")
    for mapping in design["mappings"]:
        found.update(_split(mapping["aws_service"]))
    return found


def test_every_emitted_service_component_is_mapped() -> None:
    missing = sorted(_emitted_components() - set(COMPONENTS))
    assert not missing, f"add to knowledge/estimate/render-service-rate-map.json: {missing}"


def test_every_mapped_component_resolves_to_exactly_one_row_or_entry() -> None:
    for name, target in COMPONENTS.items():
        assert len(target) == 1 and set(target) <= KINDS, name
        (kind, value), = target.items()
        assert value.strip(), name
        if kind == "pricing":
            row = _resolve(value)
            assert isinstance(row, dict) and row, name
            assert value.split(".")[0] not in PRICING["_absent_services"], f"{name}: priced and absent"
        elif kind == "no_cost":
            assert value in PRICING["_no_cost_services"], name
        elif kind == "absent":
            assert value in PRICING["_absent_services"], name
            assert value not in PRICING, f"{name}: has a section and an absent entry"


def test_absent_services_are_not_also_priced() -> None:
    absent = {key for key in PRICING["_absent_services"] if not key.startswith("_")}
    assert not absent & (set(PRICING) | set(PRICING["fast_path_services"]) | set(PRICING["_no_cost_services"]))


def test_rds_sizing_classes_have_rate_rows() -> None:
    classes = {row["instance_class"] for row in _load(DESIGN_DIR / "postgres-rds-sizing.json")["classes"]}
    assert classes - set(PRICING["rds_postgresql"]["instances"]) == set()


def test_elasticache_sizing_nodes_have_rate_rows() -> None:
    nodes = {row["node_type"] for row in _load(DESIGN_DIR / "keyvalue-elasticache-sizing.json")["node_targets"]}
    assert nodes - set(PRICING["elasticache"]["nodes"]) == set()


def test_beanstalk_sizing_instances_have_rate_rows() -> None:
    types = {row["instance_type"] for row in _load(DESIGN_DIR / "service-plan-eb-sizing.json")["x86_64_targets"]}
    assert types - set(PRICING["ec2"]["instances"]) == set()


def test_fargate_sizing_has_vcpu_and_memory_rates() -> None:
    assert _load(DESIGN_DIR / "service-plan-fargate-sizing.json")["valid_pairs"]
    for key in ("per_vcpu_hour", "per_gb_mem_hour", "per_vcpu_hour_arm64", "per_gb_mem_hour_arm64"):
        assert PRICING["fargate"][key] > 0


def test_golden_estimate_lines_are_null_only_for_absent_services() -> None:
    estimate = _load(SKILL_ROOT / "fixtures/expected/estimation-infra.json")
    for scenario in estimate["scenarios"].values():
        for line in scenario["lines"]:
            kinds = {next(iter(COMPONENTS[part])) for part in _split(line["aws_service"])}
            has_absent = "absent" in kinds
            assert (line["monthly_amount"] is None) == has_absent, (
                f"{line['line_id']} {line['aws_service']}: a line is null only when a component has no rate row"
            )
            if has_absent:
                assert line["line_id"] in scenario["unpriced_line_ids"]


def test_golden_warnings_name_only_services_without_rate_rows() -> None:
    warnings = _load(SKILL_ROOT / "fixtures/expected/generated/generation-warnings.json")["warnings"]
    estimate = _load(SKILL_ROOT / "fixtures/expected/estimation-infra.json")
    unpriced = any(s["unpriced_line_ids"] for s in estimate["scenarios"].values())
    assert ("unpriced_cost_floor" in {w["code"] for w in warnings}) is unpriced
