from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, Draft202012Validator

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "scan-render-application.py"
FIXTURE = SCRIPT_DIR.parent / "fixtures/render-application"
AI_SCHEMA = SCRIPT_DIR.parent / "references/contracts/ai-workload-profile.schema.json"
DISCOVERY_SCHEMA = SCRIPT_DIR.parent / "references/shared/schema-render-ai-discovery.json"
spec = importlib.util.spec_from_file_location("scan_render_application", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_closed_scan_emits_strong_provider_neutral_profile_without_snippets() -> None:
    first = module.scan(FIXTURE)
    second = module.scan(FIXTURE)
    assert first == second
    assert {item["kind"] for item in first["signals"]} >= {"postgres_client", "key_value_client"}
    profile = first["ai_profile"]
    discovery = first["ai_discovery"]
    assert profile is not None and discovery is not None
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    Draft202012Validator(json.loads(DISCOVERY_SCHEMA.read_text())).validate(discovery)
    assert "execution" not in profile
    openai_source = next(s for s in profile["ai_sources"] if s["provider"] == "openai" and s["source_service"] == "openai_api")
    assert "gpt-4o-mini" in openai_source["models"]
    assert {(s["provider"], s["source_service"]) for s in profile["ai_sources"]} == {("anthropic", "anthropic_api"), ("google", "gemini_api"), ("google", "vertex_ai"), ("openai", "openai_api")}
    assert profile["gateways"] == [{"product": "openrouter", "type": "llm_router", "upstream_evidence": "unresolved", "upstreams": []}]
    assert "gpt-4o-mini" in [model["observed_identifier"] for model in discovery["models"]]
    assert {provider["family"] for provider in discovery["providers"]} >= {"openai", "anthropic", "google_gemini", "google_vertex_ai", "amazon_bedrock", "openrouter"}
    assert {gateway["family"] for gateway in discovery["gateways"]} == {"openrouter"}
    capabilities = {capability for workload in discovery["workloads"] for capability in workload["capabilities"]}
    assert {"agent_orchestration", "agent_tools", "retrieval", "embedding", "reranking", "document_ingestion", "image", "speech"} <= capabilities
    serialized = json.dumps(first)
    assert "not retained by scanner" not in serialized
    assert "api_key=os.environ" not in serialized
    assert "OPENAI_API_KEY" in serialized


def test_environment_name_alone_does_not_cross_threshold(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text('name = "OPENAI_API_KEY"\n')
    result = module.scan(tmp_path)
    assert result["ai_profile"] is None
    assert result["ai_discovery"] is None


def test_openrouter_vendor_prefixed_model_yields_observed_upstream(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nfrom openai import OpenAI\n"
        'client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])\n'
        'client.chat.completions.create(model="anthropic/claude-3.5-sonnet")\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    gateway = next(g for g in profile["gateways"] if g["product"] == "openrouter")
    assert gateway["upstream_evidence"] == "observed"
    assert gateway["upstreams"] == [{"provider": "anthropic", "source_service": "anthropic_api", "model_families": [{"family": "claude", "model_evidence": "observed", "models": ["claude-3.5-sonnet"]}]}]
    anthropic_source = next(s for s in profile["ai_sources"] if s["provider"] == "anthropic")
    observation = anthropic_source["model_observations"][0]
    assert observation["raw_model"] == "anthropic/claude-3.5-sonnet"
    assert observation["normalized_model"] == "claude-3.5-sonnet"
    assert observation["evidence"][0] == {"provenance": "code", "confidence": "confirmed", "detail": "app.py:4"}
    assert not any(s["provider"] == "openrouter" for s in profile["ai_sources"])


AI_SOURCE = 'from openai import OpenAI\nclient = OpenAI()\nclient.responses.create(model="gpt-4o", input="x")\n'
# Shape of a retained scanner output: symbols survive as JSON string values.
RETAINED_AI_OUTPUT = json.dumps({"evidence": [{"symbol_or_env_name": symbol} for symbol in ("from openai", "OpenAI(", "responses.create")], "models": [{"observed_identifier": "gpt-4o"}]})


def _path_hash(relative: str) -> str:
    return module.sha256_digest(relative.encode("utf-8"))


def test_retained_migration_output_is_not_rescanned_as_source(tmp_path: Path) -> None:
    run_dir = tmp_path / ".migration" / "1021-1200"
    run_dir.mkdir(parents=True)
    (run_dir / "application.json").write_text(RETAINED_AI_OUTPUT)
    (tmp_path / "README.md").write_text("no application source\n")
    result = module.scan(tmp_path)
    assert result["ai_profile"] is None
    assert result["ai_discovery"] is None
    assert result["files"] == []
    assert {"path_hash": _path_hash(".migration"), "reason": "excluded_directory"} in result["skipped"]

    custom_dir = tmp_path / "runs" / "x"
    custom_dir.mkdir(parents=True)
    (custom_dir / "application.json").write_text(RETAINED_AI_OUTPUT)
    assert module.scan(tmp_path)["ai_profile"] is not None
    result = module.scan(tmp_path, migration_dir=custom_dir)
    assert result["ai_profile"] is None
    assert result["files"] == []
    assert {"path_hash": _path_hash("runs/x"), "reason": "excluded_directory"} in result["skipped"]

    (tmp_path / "app.py").write_text(AI_SOURCE)
    assert module.scan(tmp_path, migration_dir=custom_dir)["ai_profile"] is not None


def _sources(profile: dict) -> dict[tuple[str, str], list[str]]:
    return {(s["provider"], s["source_service"]): s["models"] for s in profile["ai_sources"]}


def test_azure_only_file_attributes_models_to_azure_openai(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nfrom openai import AzureOpenAI\n"
        'client = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"])\n'
        'client.chat.completions.create(model="gpt-4o")\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    assert _sources(profile) == {("openai", "azure_openai"): ["gpt-4o"]}
    azure = profile["ai_sources"][0]
    assert azure["model_evidence"] == "observed"
    assert azure["model_observations"][0]["evidence"][0]["confidence"] == "confirmed"


def test_mixed_direct_and_azure_file_keeps_both_sources_with_models(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nfrom openai import OpenAI, AzureOpenAI\n"
        'direct = OpenAI(api_key=os.environ["OPENAI_API_KEY"])\n'
        'azure = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"])\n'
        'direct.responses.create(model="gpt-4o-mini", input="x")\n'
        'azure.chat.completions.create(model="gpt-4o")\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    sources = _sources(profile)
    assert sources == {("openai", "openai_api"): ["gpt-4o-mini"], ("openai", "azure_openai"): ["gpt-4o"]}


def test_same_model_on_both_clients_on_separate_lines_binds_each_source(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nfrom openai import OpenAI, AzureOpenAI\n"
        'direct = OpenAI(api_key=os.environ["OPENAI_API_KEY"])\n'
        'azure = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"])\n'
        'direct.responses.create(model="gpt-4o", input="x")\n'
        'azure.chat.completions.create(model="gpt-4o")\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    sources = _sources(profile)
    assert sources == {("openai", "openai_api"): ["gpt-4o"], ("openai", "azure_openai"): ["gpt-4o"]}
    azure = next(s for s in profile["ai_sources"] if s["source_service"] == "azure_openai")
    assert azure["model_observations"][0]["evidence"] == [{"provenance": "code", "confidence": "confirmed", "detail": "app.py:6"}]


def test_shared_client_model_without_receiver_is_unattributed_not_confirmed(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nfrom openai import OpenAI, AzureOpenAI\n"
        'direct = OpenAI(api_key=os.environ["OPENAI_API_KEY"])\n'
        'azure = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"])\n'
        'direct.responses.create(model="gpt-4o-mini", input="x")\n'
        'MODEL = "gpt-4o"\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    Draft7Validator(json.loads(AI_SCHEMA.read_text())).validate(profile)
    sources = _sources(profile)
    assert sources[("openai", "openai_api")] == ["gpt-4o", "gpt-4o-mini"]
    assert sources[("openai", "azure_openai")] == ["gpt-4o"]
    unattributed = next(s for s in profile["ai_sources"] if s["provider"] == "openai" and s["source_service"] == "azure_openai")
    observation = unattributed["model_observations"][0]
    assert observation["evidence"] == [{"provenance": "code", "confidence": "low", "detail": "app.py:6:unattributed"}]
    direct = next(s for s in profile["ai_sources"] if s["source_service"] == "openai_api")
    assert {e["confidence"] for o in direct["model_observations"] for e in o["evidence"] if o["normalized_model"] == "gpt-4o-mini"} == {"confirmed"}


def test_direct_only_file_does_not_emit_azure_source(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'from openai import OpenAI\nclient = OpenAI()\nclient.chat.completions.create(model="gpt-4o")\n'
    )
    (tmp_path / "worker.py").write_text(
        'from openai import OpenAI\nclient = OpenAI()\nclient.chat.completions.create(model="gpt-4o")\n'
    )
    profile = module.scan(tmp_path)["ai_profile"]
    assert _sources(profile) == {("openai", "openai_api"): ["gpt-4o"]}


def test_symlink_secret_generated_binary_and_unsupported_files_are_metadata_only(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=secret")
    (tmp_path / "blob.py").write_bytes(b"abc\x00def")
    (tmp_path / "notes.txt").write_text("secret prose")
    generated = tmp_path / "node_modules"
    generated.mkdir()
    (generated / "index.js").write_text("OpenAI()")
    target = tmp_path / "target.py"
    target.write_text("print('safe')")
    (tmp_path / "link.py").symlink_to(target)
    result = module.scan(tmp_path)
    reasons = {item["reason"] for item in result["skipped"]}
    assert {"sensitive_name", "binary_file", "unsupported_type", "excluded_directory", "symlink"} <= reasons
    assert all("path" not in item and item["path_hash"].startswith("sha256:") for item in result["skipped"])
    assert "OPENAI_API_KEY=secret" not in json.dumps(result)


def test_minified_generated_javascript_contributes_no_metadata_or_signals(tmp_path: Path) -> None:
    (tmp_path / "bundle.min.js").write_text(
        'const client = new OpenAI(); client.chat.completions.create({model: "gpt-4o-mini"});'
    )
    result = module.scan(tmp_path)
    assert result["files"] == []
    assert result["signals"] == []
    assert result["ai_profile"] is None
    assert result["ai_discovery"] is None
    assert {item["reason"] for item in result["skipped"]} == {"generated_file"}


def test_non_utf8_and_file_bounds_skip_without_partial_content(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_bytes(b"\xff")
    (tmp_path / "large.py").write_bytes(b"x" * (module.MAX_FILE_BYTES + 1))
    result = module.scan(tmp_path)
    assert {item["reason"] for item in result["skipped"]} == {"invalid_utf8", "file_too_large"}


def test_root_must_be_absolute_regular_directory(tmp_path: Path) -> None:
    with pytest.raises(module.ScanError, match="workspace_root_invalid"):
        module.scan(Path("relative"))
    link = tmp_path / "link"
    target = tmp_path / "target"
    target.mkdir()
    link.symlink_to(target)
    with pytest.raises(module.ScanError, match="workspace_root_invalid"):
        module.scan(link)
