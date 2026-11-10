"""Text contract: the infra migration skills target ElastiCache for Valkey by default.

Valkey is ElastiCache's default engine for new clusters, is Redis OSS-compatible, costs 20%
less per node, and is the only ElastiCache engine Database Savings Plans cover. The Estimate
phases of gcp-to-aws, azure-to-aws, and heroku-to-aws already priced Savings Plans on that
basis while Design still emitted Redis OSS; this test pins the Design/Generate side so the two
phases agree:

- the three skills' direct mappings for a Redis cache source emit `ElastiCache Valkey`;
- the heroku design step records `aws_config.engine: "valkey"` and the Terraform template
  reads the engine from the design instead of hardcoding `"redis"`;
- the shared infra pricing file prices ElastiCache nodes at the Valkey rate and carries the
  Redis OSS multiplier for the exception path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"


def test_gcp_memorystore_fast_path_targets_valkey() -> None:
    text = (SKILLS / "gcp-to-aws" / "references" / "design-refs" / "fast-path.md").read_text(encoding="utf-8")
    row = next(ln for ln in text.splitlines() if ln.startswith("| `google_redis_instance`"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "ElastiCache Valkey", cells
    assert '`aws_config.engine: "valkey"`' in row


def test_azure_cache_fast_path_targets_valkey() -> None:
    data = json.loads((SKILLS / "azure-to-aws" / "knowledge" / "design" / "fast-path-services.json").read_text(encoding="utf-8"))
    row = data["direct_mappings"]["Microsoft.Cache/Redis"]
    assert row["aws_service"] == "ElastiCache Valkey", row
    assert "valkey" in row["notes"].lower()


def test_heroku_redis_design_step_records_valkey_engine() -> None:
    text = (SKILLS / "heroku-to-aws" / "references" / "phases" / "design" / "design-mapping.md").read_text(encoding="utf-8")
    start = text.index("### 2C: Redis Mapping (ElastiCache)")
    stop = text.index("### 2D:", start)
    section = text[start:stop]
    assert '"aws_service": "ElastiCache Valkey"' in section
    assert '"engine": "valkey"' in section
    assert '"aws_service": "ElastiCache Redis"' not in section


def test_heroku_cache_terraform_reads_engine_from_design() -> None:
    text = (SKILLS / "heroku-to-aws" / "references" / "phases" / "generate" / "generate-terraform.md").read_text(encoding="utf-8")
    start = text.index("## Step 8: Generate `cache.tf`")
    stop = text.index("## Step 9:", start)
    section = text[start:stop]
    assert not re.search(r'engine\s*=\s*"redis"', section), "cache.tf must not hardcode the Redis OSS engine"
    assert "<aws_config.engine>" in section
    assert 'family = "redis<major_version>"' not in section


def test_shared_pricing_prices_elasticache_nodes_at_the_valkey_rate() -> None:
    data = json.loads((SKILLS / "shared" / "pricing" / "aws-infra-pricing.json").read_text(encoding="utf-8"))
    cache = data["elasticache"]
    assert cache["engine"] == "valkey"
    assert cache["redis_oss_multiplier"] == 1.25
    # Valkey node-based pricing is 20% below Redis OSS; spot-check the rates read 2026-11-09.
    assert cache["nodes"]["cache.t4g.micro"] == 0.0128
    assert cache["nodes"]["cache.m6g.large"] == 0.1192
