"""Guard: the shared EFS/ECR rate rows must not change azure-to-aws or heroku-to-aws estimates.

render-to-aws is the only consumer of the efs and ecr rows. These pins fail if an
azure or heroku golden estimate changes, or if any of their lines carries a non-null
EFS/ECR amount. Update a pin only as a deliberate decision to adopt the rows there.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN / "fixtures"

PINNED_SHA256 = {
    "azure-iac-terraform/after-estimate/estimation-infra.json": "55f52c50ece04b55dfa66e288e22eb5ea0e94bef2b5a840974dae9ce7f7ed034",
    "heroku-decision-gate/after-decide-complete/estimation-infra.json": "96d55a2a529acd9616fc9b28c6997f4c897a6dc5dc54e42748be238f09d67c4e",
    "heroku-decision-gate/retained-execution-pack/estimation-infra.json": "96d55a2a529acd9616fc9b28c6997f4c897a6dc5dc54e42748be238f09d67c4e",
    "heroku-workshop/after-arm64-reprice/estimation-infra.json": "6757c43f05efe9f5982be65dcab00e49f9059528baf6b112539b5fc0e8be861b",
    "heroku-workshop/seed/estimation-infra.json": "62da3cfffc002a7321056ddac96ed009c76724e432b7af8e3c225956466fdf5b",
}
EFS_ECR = re.compile(r"\b(efs|ecr|elastic file system|elastic container registry)\b", re.IGNORECASE)


def test_azure_and_heroku_golden_estimates_are_unchanged() -> None:
    for rel, expected in PINNED_SHA256.items():
        actual = hashlib.sha256((FIXTURES / rel).read_bytes()).hexdigest()
        assert actual == expected, f"{rel} changed; azure/heroku do not consume the efs/ecr rows"


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


# The amount fields each skill's estimate actually uses. A guard that reads a field the skill never writes cannot
# fail: Azure lines carry lift_monthly / right_sized_monthly, Heroku lines carry premium / mid / low.
AZURE_AMOUNTS = ("lift_monthly", "right_sized_monthly")
HEROKU_AMOUNTS = ("premium", "mid", "low")


def priced_efs_ecr_lines(estimate: dict) -> list[str]:
    """Names of EFS/ECR lines that carry a number, in an Azure- or Heroku-shaped estimate."""
    breakdown = estimate.get("projected_costs", {}).get("breakdown", {})
    offenders: list[str] = []
    for key, line in breakdown.items():
        if not isinstance(line, dict) or key == "total":
            continue
        label = f"{key} {line.get('aws_service', '')}"
        if not EFS_ECR.search(label):
            continue
        amounts = [line.get(field) for field in (*AZURE_AMOUNTS, *HEROKU_AMOUNTS)]
        priced = any(isinstance(value, (int, float)) for value in amounts)
        excluded = line.get("pricing_source") == "unavailable" and line.get("excluded_from_total") is True
        if priced or not excluded:
            offenders.append(key)
    return offenders


def _azure_estimate(**line: object) -> dict:
    return {"projected_costs": {"breakdown": {"total": {}, "efs-share": {"aws_service": "EFS", **line}}}}


def test_the_guard_detects_a_priced_efs_line_in_the_real_azure_shape() -> None:
    # The old guard read `monthly_amount`, which neither skill writes, so this mutation passed it.
    priced = _azure_estimate(lift_monthly=1.5, right_sized_monthly=1.5, pricing_source="cached")
    assert priced_efs_ecr_lines(priced) == ["efs-share"]
    half = _azure_estimate(lift_monthly=None, right_sized_monthly=2.0, pricing_source="cached")
    assert priced_efs_ecr_lines(half) == ["efs-share"]


def test_the_guard_detects_a_priced_ecr_line_in_the_real_heroku_shape() -> None:
    heroku = {"projected_costs": {"breakdown": {"total": {}, "Elastic Container Registry": {
        "premium": 3.0, "mid": 2.0, "low": 1.0, "pricing_source": "cached"}}}}
    assert priced_efs_ecr_lines(heroku) == ["Elastic Container Registry"]


def test_the_guard_accepts_the_stated_azure_outcome_for_efs_and_ecr() -> None:
    # The one outcome the Azure rules state: an excluded no_rate line with no amount.
    excluded = _azure_estimate(lift_monthly=None, right_sized_monthly=None, pricing_source="unavailable",
                               exclusion_reason="no_rate", excluded_from_total=True)
    assert priced_efs_ecr_lines(excluded) == []
    # null amounts alone are not enough: the line must also be marked unavailable and excluded from totals
    unmarked = _azure_estimate(lift_monthly=None, right_sized_monthly=None, pricing_source="cached")
    assert priced_efs_ecr_lines(unmarked) == ["efs-share"]


def test_azure_rules_state_that_efs_and_ecr_stay_excluded() -> None:
    # Removing efs/ecr from _absent_services took them off Azure's no-rate path, and nothing in Azure's rules read the
    # rows' _note text. The exclusion must be written where the Azure rules are.
    rules = (PLUGIN / "skills/azure-to-aws/references/phases/estimate/estimate-infra.md").read_text(encoding="utf-8")
    section = rules.split("### Services with no rate row", 1)[1].split("###", 1)[0]
    assert re.search(r"Azure Files \(NFS\).*Amazon EFS.*Azure Container Registry.*Amazon ECR", section, re.DOTALL)
    assert "stay excluded" in section and "never price it from those rows" in section
    assert 'exclusion_reason: "no_rate"' in section
    absent = json.loads((PLUGIN / "skills/shared/pricing/aws-infra-pricing.json").read_text())["_absent_services"]
    assert "efs" not in absent and "ecr" not in absent, "if these return to _absent_services, drop the Azure paragraph"


def test_azure_and_heroku_goldens_carry_no_priced_efs_or_ecr_line() -> None:
    for rel in PINNED_SHA256:
        data = json.loads((FIXTURES / rel).read_text(encoding="utf-8"))
        assert priced_efs_ecr_lines(data) == [], f"{rel}: EFS/ECR must stay an excluded line"
