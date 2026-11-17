"""A4b (#566): llm-to-bedrock reads model ids, profile prefixes and endpoint Regions from the
shared model catalogs (vendored at references/vendored/ai/models/) instead of restating them."""
import json
from pathlib import Path

import pytest

import iam_policy
import model_catalog
import preflight_bedrock

SKILL = Path(__file__).resolve().parent.parent
SHARED_MODELS = SKILL.parent / "shared" / "ai" / "models"


def _catalog_profile_ids():
    for model in model_catalog.catalog_models().values():
        runtime_id = next((p["model_id"] for p in model.get("paths", {}).values() if p.get("model_id")), None)
        for prefix in model.get("inference_profiles", {}):
            yield f"{prefix}.{runtime_id}"


def test_the_vendored_catalogs_are_the_shared_ones():
    for name in model_catalog.CATALOG_FILES:
        assert (model_catalog.MODELS_DIR / name).read_bytes() == (SHARED_MODELS / name).read_bytes(), name


def test_prefixes_cover_every_catalog_profile_and_the_old_list():
    assert {"us", "eu", "apac", "au", "jp", "in", "us-gov", "global", "ca"} <= model_catalog.profile_prefixes()


@pytest.mark.parametrize("model_id", sorted(set(_catalog_profile_ids())))
def test_every_catalog_profile_id_gets_an_inference_profile_policy(model_id):
    assert iam_policy.is_inference_profile(model_id), model_id


def test_ca_haiku_5_5_gets_the_profile_and_model_arns_not_a_bogus_foundation_arn():
    policy = iam_policy.generate_policy(["ca.anthropic.claude-haiku-5-5"], "ca-central-1", "123456789012")
    resources = [r for s in policy["Statement"] for r in (s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]])]
    assert "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-5-5" in resources
    assert "arn:aws:bedrock:ca-central-1:123456789012:inference-profile/ca.anthropic.claude-haiku-5-5" in resources
    assert not any("foundation-model/ca." in r for r in resources)


def test_bare_opus_5_5_is_mantle_only_where_the_catalog_serves_mantle():
    mantle = model_catalog.opus_55_mantle_regions()
    assert mantle == {"us-east-1", "ap-southeast-4", "us-gov-west-1"}
    for region in mantle:
        assert iam_policy.is_mantle_model("anthropic.claude-opus-5-5", region), region
    for region in ("eu-west-2", "us-west-2", "ca-central-1"):
        assert not iam_policy.is_mantle_model("anthropic.claude-opus-5-5", region), region
    assert iam_policy.is_mantle_model("anthropic.claude-opus-5-5")  # Region unknown


def test_preflight_opus_gate_reads_the_catalog_in_region_list():
    assert model_catalog.opus_55_runtime_in_region_regions() == {"eu-west-2"}

    class Client:
        class meta:
            region_name = "us-west-2"
    v = preflight_bedrock.probe_model(Client, "anthropic.claude-opus-5-5")
    assert v["reason"] == "inference_profile_required"
    assert "eu-west-2 (shared model catalog)" in v["detail"]


def test_embedding_vendor_is_read_through_any_catalog_prefix():
    assert preflight_bedrock._embed_request_body("ca.amazon.titan-embed-text-v2:0") == {"inputText": "ping"}


def test_resolver_and_delta_docs_list_every_gpt_6_model_and_scope_in_and_us_gov():
    resolver = " ".join((SKILL / "references/helpers/resolve-bedrock-model-id/resolve-bedrock-model-id.md").read_text().split())
    delta = " ".join((SKILL / "references/helpers/behavior-delta-detection/references/openai-to-bedrock.md").read_text().split())
    gpt6 = sorted(p["model_id"] for k, m in model_catalog.catalog_models().items() if k.startswith("openai_gpt_6")
                  for name, p in m["paths"].items() if name == "mantle_openai_responses")
    assert len(gpt6) == 5
    assert "The five bare GPT-6 IDs" in resolver and all(f"`{mid}`" in resolver for mid in gpt6)
    assert "All five GPT-6 models (Astra, Sol, Luna, 6.1 Sol, 6.1 Terra)" in delta
    assert "for GPT-5.6 Terra and Luna only, `in.` in India Regions and `us-gov.` in GovCloud" in resolver
    assert "`in.openai.gpt-5.6-*` in India Regions" not in resolver


def test_scripts_load_by_path_without_their_directory_on_sys_path(tmp_path):
    # Review P1: agent-advisor's tests load these files with spec_from_file_location.
    import subprocess
    import sys
    code = (
        "import importlib.util, sys\n"
        "for name in ('iam_policy', 'preflight_bedrock', 'bedrock_pricing', 'model_identity'):\n"
        f"    spec = importlib.util.spec_from_file_location(name, r'{Path(__file__).parent}/' + name + '.py')\n"
        "    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr


def test_model_identity_strips_every_catalog_prefix():
    import model_identity
    assert model_identity._identity("ca.anthropic.claude-haiku-5-5", "anthropic", True) == "claude-haiku-5-5"
    assert model_identity._identity("us-gov.openai.gpt-5.6-terra", "openai", True) == "gpt-5.6-terra"


def test_pricing_reads_opus_regions_from_the_catalog():
    import bedrock_pricing
    assert bedrock_pricing._OPUS55_MANTLE_REGIONS == model_catalog.opus_55_mantle_regions()
    assert bedrock_pricing._OPUS55_RUNTIME_IN_REGION_REGIONS == model_catalog.opus_55_runtime_in_region_regions()
    assert bedrock_pricing._OPUS55_PROFILE_REGIONS == model_catalog.opus_55_profile_regions()
    assert bedrock_pricing._PROFILE_PREFIXES == model_catalog.profile_prefixes()


def test_catalog_disagreement_fails_loudly(monkeypatch):
    models = dict(model_catalog.catalog_models())
    clone = json.loads(json.dumps(models["claude_opus_5_5"]))
    clone["runtime_in_region_regions"] = ["eu-west-2", "eu-central-1"]
    models["zz_conflicting_opus"] = clone
    monkeypatch.setattr(model_catalog, "catalog_models", lambda: models)
    with pytest.raises(ValueError, match="catalogs disagree"):
        model_catalog.opus_55_runtime_in_region_regions()
