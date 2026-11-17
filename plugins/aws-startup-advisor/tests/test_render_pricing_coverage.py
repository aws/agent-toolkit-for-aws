"""Enforce the sizing-table / rate-row pair for render-to-aws.

Every AWS service component Render's design selectors can emit, and every instance
class or node type its sizing tables can emit, must resolve to a rate row, a
_no_cost_services entry, or an _absent_services entry in the vendored pricing file.

Scanned scope. `_emitted_components()` discovers components from three sources only: the
fast-path rows, the backticked "candidate set" lines in references/design-refs/*.md, and the
golden design. A component a design-ref selects in prose, or that no design-ref names at all, is
invisible to that scan, so deleting it from the rate map would still pass. `PROSE_SELECTED` below
pins those components by name with the rate keys each needs; add to it when a selector starts
choosing a component in prose.
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


def test_aurora_sizing_classes_have_rate_rows_or_unavailable_entries() -> None:
    classes = {row["instance_class"] for row in _load(DESIGN_DIR / "postgres-rds-sizing.json")["classes"]}
    aurora = PRICING["aurora_postgresql"]
    covered = set(aurora["instances"]) | set(aurora["_unavailable_instances"])
    assert classes - covered == set()
    assert not set(aurora["instances"]) & set(aurora["_unavailable_instances"])
    assert all(reason.strip() for reason in aurora["_unavailable_instances"].values())


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


NULL_REASONS = {"no_rate", "no_quantity"}


def null_line_errors(line: dict, scenario: dict, kinds: set[str]) -> list[str]:
    """Why a line's amount is (il)legally null. A null needs a stated reason and an unpriced_line_ids entry;
    a priced component's line may be null only for `no_quantity`, never for a missing rate it does have."""
    problems: list[str] = []
    is_null = line["monthly_amount"] is None
    reason = line.get("exclusion_reason")
    if not is_null:
        if reason:
            problems.append("a priced line must not carry an exclusion_reason")
        if line["line_id"] in scenario["unpriced_line_ids"]:
            problems.append("a priced line must not be listed in unpriced_line_ids")
        if "absent" in kinds:
            problems.append("a line with an absent component has no rate to price it with")
        return problems
    if reason not in NULL_REASONS:
        problems.append(f"a null line needs exclusion_reason in {sorted(NULL_REASONS)}, got {reason!r}")
    if line["line_id"] not in scenario["unpriced_line_ids"]:
        problems.append("a null line must be listed in unpriced_line_ids")
    if reason == "no_rate" and "absent" not in kinds:
        problems.append("no_rate is only for a component in _absent_services")
    if reason == "no_quantity" and line.get("evidence_sufficient") is not False:
        problems.append("no_quantity must say what evidence is missing")
    return problems


def test_golden_estimate_lines_are_null_only_for_a_stated_reason() -> None:
    estimate = _load(SKILL_ROOT / "fixtures/expected/estimation-infra.json")
    for scenario in estimate["scenarios"].values():
        for line in scenario["lines"]:
            # A retention qualifier such as "(30-day retention)" names the sizing input, not a separate component.
            kinds = {next(iter(COMPONENTS[re.sub(r" \([^)]*\)$", "", part)])) for part in _split(line["aws_service"])}
            assert null_line_errors(line, scenario, kinds) == [], f"{line['line_id']} {line['aws_service']}"


def test_a_stated_no_quantity_null_is_legal_and_an_unexplained_null_is_not() -> None:
    scenario = {"unpriced_line_ids": ["cron-1"]}
    priced_kinds = {"pricing"}
    # a cron with no run history: priced component, quantity not established
    legal = {"line_id": "cron-1", "monthly_amount": None, "exclusion_reason": "no_quantity", "evidence_sufficient": False}
    assert null_line_errors(legal, scenario, priced_kinds) == []
    # the same null with no reason, or not listed as unpriced, must still fail
    no_reason = {**legal, "exclusion_reason": None}
    assert null_line_errors(no_reason, scenario, priced_kinds)
    unlisted = {**legal, "line_id": "cron-2"}
    assert null_line_errors(unlisted, scenario, priced_kinds)
    # an absent component keeps its own reason: no_rate, and no_quantity does not stand in for a missing rate row
    absent = {"line_id": "cron-1", "monthly_amount": None, "exclusion_reason": "no_rate"}
    assert null_line_errors(absent, scenario, {"absent"}) == []
    assert null_line_errors({**absent, "exclusion_reason": "no_rate"}, scenario, priced_kinds)
    # a priced line with an amount cannot also claim a reason or sit in unpriced_line_ids
    assert null_line_errors({"line_id": "x", "monthly_amount": 3.0, "exclusion_reason": "no_quantity"}, scenario, priced_kinds)
    assert null_line_errors({"line_id": "cron-1", "monthly_amount": 3.0}, scenario, priced_kinds)


def test_rate_map_rule_and_estimate_rules_state_the_same_two_null_cases() -> None:
    rule = RATE_MAP["rule"]
    guidance = (SKILL_ROOT / "references/phases/estimate/estimate-infra.md").read_text(encoding="utf-8")
    for text in (rule, guidance):
        assert "no_quantity" in text and "no_rate" in text, text[:80]
        assert "Never invent a quantity" in text
    assert "null only when a component is absent" not in rule


def test_golden_warnings_name_only_services_without_rate_rows() -> None:
    warnings = _load(SKILL_ROOT / "fixtures/expected/generated/generation-warnings.json")["warnings"]
    estimate = _load(SKILL_ROOT / "fixtures/expected/estimation-infra.json")
    unpriced = any(s["unpriced_line_ids"] for s in estimate["scenarios"].values())
    assert ("unpriced_cost_floor" in {w["code"] for w in warnings}) is unpriced


# Components a selector chooses in prose, or that no design-ref names, so the discovery scan cannot see them.
# Each needs the rate keys listed: removing the map entry, the row, or a key fails this test.
PROSE_SELECTED = {
    "Amazon CloudWatch Logs, Metrics, and Alarms": ("cloudwatch", {"log_ingestion_per_gb", "log_storage_per_gb_month", "standard_alarm_month"}),
    "Amazon Cognito": ("cognito", {"essentials_per_mau", "lite_per_mau_tiers", "plus_per_mau"}),
    "Amazon Route 53": ("route53", {"hosted_zone_monthly", "per_million_queries"}),
    "Application Load Balancer": ("alb", {"monthly_fixed", "per_lcu_hour"}),
    "CloudFront": ("fast_path_services.cloudfront", {"per_gb_first_10tb"}),
    "NAT Gateway": ("nat_gateway", {"monthly_fixed", "per_gb_processed"}),
}


def test_prose_selected_components_stay_mapped_with_their_rate_keys() -> None:
    for name, (path, keys) in PROSE_SELECTED.items():
        assert name in COMPONENTS, f"{name} was removed from the rate map"
        assert COMPONENTS[name] == {"pricing": path}, name
        row = _resolve(path)
        assert isinstance(row, dict)
        assert keys <= set(row), f"{name}: rate row {path} lost {sorted(keys - set(row))}"
        assert all(isinstance(row[key], (int, float, dict, list)) and row[key] for key in keys), name


def test_the_discovery_scan_cannot_see_the_prose_selected_components() -> None:
    # If the scan starts discovering one of these, drop it from PROSE_SELECTED: the scan then guards it.
    invisible = set(PROSE_SELECTED) - _emitted_components()
    assert invisible, "every prose-selected component is now discoverable; delete PROSE_SELECTED"
    # and the map must not hold a component that neither the scan nor the pinned set knows about
    unknown = set(COMPONENTS) - _emitted_components() - set(PROSE_SELECTED)
    assert not unknown, f"map entries nothing guards: {sorted(unknown)}"
