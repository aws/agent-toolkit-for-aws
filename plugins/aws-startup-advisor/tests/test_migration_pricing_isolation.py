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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

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


def test_azure_and_heroku_goldens_carry_no_priced_efs_or_ecr_line() -> None:
    for rel in PINNED_SHA256:
        data = json.loads((FIXTURES / rel).read_text(encoding="utf-8"))
        for obj in _walk(data):
            service = obj.get("aws_service")
            if isinstance(service, str) and EFS_ECR.search(service):
                assert obj.get("monthly_amount") is None, f"{rel}: {service} must stay an excluded line"
