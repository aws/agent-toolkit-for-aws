"""Target status, tier and rates come from the vendored pricing cache, never from a hand list in the runtime.

`pricing_registry` parses every Status-bearing table of references/vendored/ai/bedrock-pricing-cache.md,
normalizes inference-profile prefixes onto the base model ID, and applies the lifecycle Legacy / EOL table
and Removed list as a fail-closed exclusion. `design_target` resolves embedding / image_generation targets
by table and Tier. Every target the runtime can emit must therefore be Active and priced in the cache.
"""
from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BMA = ROOT / "skills/bedrock-migration-assessment"
PATH = BMA / "scripts/bma-runtime.py"

runtime = types.ModuleType("bma_runtime_target_registry")
runtime.__dict__["__file__"] = str(PATH)  # the runtime reads the pricing cache beside its own path
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)

EXPECTED_ACTIVE = {
    "openai.gpt-5.6-terra",
    "openai.gpt-6-luna",
    "amazon.nova-pro-v1:0",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "amazon.titan-embed-text-v2:0",
    "stability.stable-image-core-v1:0",
    "stability.stable-image-ultra-v1:0",
    "anthropic.claude-opus-5-5",
}


def lifecycle_retired_ids() -> set[str]:
    """Every backticked ID in the lifecycle Legacy / EOL section (table rows and Removed bullets).

    Read from the vendored registry rather than listed here, so the test names no retired model ID itself
    (lint:model-id) and keeps tracking the registry as rows move between the table and Removed.
    """
    text = (BMA / runtime.LIFECYCLE_REGISTRY_RELATIVE).read_text(encoding="utf-8")
    section = text.split(runtime.LIFECYCLE_LEGACY_SECTION, 1)[1].split("\n## ", 1)[0]
    ids: set[str] = set()
    for _heading, header, body in runtime._markdown_tables(section):
        if "Model ID" in header and "Status" in header:
            for row in body:
                status = row[header.index("Status")].strip("*").lower()
                if not status.startswith("active"):
                    ids.add(row[header.index("Model ID")].strip("`"))
    removed = section.split("**Removed", 1)[1] if "**Removed" in section else ""
    for line in removed.splitlines()[1:]:
        if not line.strip():
            continue
        if not line.startswith("- "):
            break
        ids.update(re.findall(r"`([^`]+)`", line))
    return {runtime.normalize_model_id(model) for model in ids}


def _priced(row: dict) -> bool:
    # Image models are priced per image; embeddings are input-only (no output rate); text models need both.
    if row["per_image"] is not None:
        return True
    if "Embeddings" in row["table"]:
        return row["input"] is not None
    return row["input"] is not None and row["output"] is not None


@pytest.mark.parametrize(
    ("capability", "priority"),
    [("embedding", "balanced"), ("image_generation", "balanced"), ("image_generation", "cost"), ("image_generation", "quality")],
)
def test_every_emittable_design_target_resolves_to_active_and_priced(capability: str, priority: str) -> None:
    target = runtime.design_target(capability, priority, BMA)
    assert set(target) == {"capability", "target_aws_service", "target_bedrock_model"}
    model = target["target_bedrock_model"]
    assert model in runtime.registered_active_models(BMA)
    assert _priced(runtime.pricing_registry(BMA)[model])


def test_design_target_resolves_by_table_and_tier() -> None:
    assert runtime.design_target("embedding", "balanced", BMA)["target_bedrock_model"] == "amazon.titan-embed-text-v2:0"
    assert runtime.design_target("image_generation", "quality", BMA)["target_bedrock_model"] == "stability.stable-image-ultra-v1:0"
    assert runtime.design_target("image_generation", "balanced", BMA)["target_bedrock_model"] == "stability.stable-image-core-v1:0"
    with pytest.raises(ValueError, match="design_target_not_deterministic"):
        runtime.design_target("text_generation", "balanced", BMA)


def test_every_model_targets_target_is_active_and_priced() -> None:
    registry = runtime.pricing_registry(BMA)
    active = runtime.registered_active_models(BMA)
    assert len(runtime.MODEL_TARGETS) == 3
    for source, row in runtime.MODEL_TARGETS.items():
        target, migration_path = row  # 2-tuples: no rate literals in the runtime
        assert runtime.normalize_model_id(target) in active, source
        assert runtime.target_rates(registry, target) is not None, source
    assert runtime.MODEL_TARGETS["gpt-4o"] == ("openai.gpt-5.6-terra", "direct_api")


@pytest.mark.parametrize("prefix", ["us.", "eu.", "au.", "apac.", "global.", "us-gov.", "jp."])
def test_inference_profile_prefixes_normalize_to_base_id(prefix: str) -> None:
    assert runtime.normalize_model_id(f"{prefix}anthropic.claude-opus-5-5") == "anthropic.claude-opus-5-5"
    assert runtime.normalize_model_id("anthropic.claude-opus-5-5") == "anthropic.claude-opus-5-5"


def test_prefixed_target_is_active_and_priced_through_the_base_row() -> None:
    registry = runtime.pricing_registry(BMA)
    assert "anthropic.claude-opus-5-5" in runtime.registered_active_models(BMA)
    assert runtime.target_rates(registry, "us.anthropic.claude-opus-5-5") is not None
    assert runtime.target_rates(registry, "us.anthropic.claude-opus-5-5") == runtime.target_rates(registry, "anthropic.claude-opus-5-5")


def test_registry_reads_pricing_cache_status_not_a_hand_list() -> None:
    active = runtime.registered_active_models(BMA)
    assert EXPECTED_ACTIVE <= active
    assert "anthropic.claude-sonnet-5-5" not in active  # no row in the cache: unverified, never priced
    registry = runtime.pricing_registry(BMA)
    # Every cache row whose Status is not active (excluded / legacy / EOL) is inactive, prefix-normalized.
    cache_inactive = {base for base, row in registry.items() if row["status"] == "inactive"}
    assert cache_inactive and not cache_inactive & active
    assert any("excluded" in row.lower() or "eol" in row.lower() for row in (
        line for line in (BMA / runtime.PRICING_CACHE_RELATIVE).read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
    ))
    # The lifecycle Legacy / EOL table and Removed list (globs included) win over the cache.
    retired = lifecycle_retired_ids()
    assert len(retired) >= 10
    for pattern in retired:
        matching = {base for base in active if fnmatch.fnmatchcase(base, pattern)}
        assert not matching, pattern
        if not any(char in pattern for char in "*?["):
            assert registry[pattern]["status"] == "inactive", pattern
    source = PATH.read_text(encoding="utf-8")
    assert "Verified Active Models" not in source
    assert not hasattr(runtime, "IMAGE_GENERATION_TARGETS")
    assert not hasattr(runtime, "EMBEDDING_TARGET")
    assert not hasattr(runtime, "LIFECYCLE_SECTION")


def test_design_target_cli_output_shape_unchanged() -> None:
    completed = subprocess.run(
        [sys.executable, str(PATH), "design-target", "--capability", "image_generation", "--priority", "quality"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert set(output) == {"capability", "target_aws_service", "target_bedrock_model"}
    assert output["target_bedrock_model"] == "stability.stable-image-ultra-v1:0"


def test_registry_fails_closed_when_cache_missing(tmp_path: Path) -> None:
    copy = tmp_path / "bedrock-migration-assessment"
    shutil.copytree(BMA / "references/vendored/ai", copy / "references/vendored/ai")
    (copy / runtime.PRICING_CACHE_RELATIVE).unlink()
    with pytest.raises(ValueError, match="lifecycle_registry_missing"):
        runtime.pricing_registry(copy)
    with pytest.raises(ValueError, match="lifecycle_registry_missing"):
        runtime.registered_active_models(copy)
    with pytest.raises(ValueError, match="lifecycle_registry_missing"):
        runtime.design_target("embedding", "balanced", copy)
