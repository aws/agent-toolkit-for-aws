#!/usr/bin/env python3
"""Scan bounded application metadata without retaining source snippets or values."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from render_common.atomic import PathBoundaryError, require_contained, write_json_atomic
from render_common.canonical import byte_sort_key, canonical_bytes, generated_id, sha256_digest

MAX_FILES = 10_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_DEPTH = 20
ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".kts", ".cs", ".csproj", ".rs", ".rb", ".php", ".sh", ".yaml", ".yml", ".json", ".toml", ".properties"}
ALLOWED_NAMES = {"Dockerfile", "Procfile", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt", "pyproject.toml", "go.mod", "go.sum", "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.toml", "Cargo.lock"}
EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".cache", "__pycache__", ".terraform", ".serverless", ".aws-sam", "cdk.out", ".migration"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
SENSITIVE_NAME = re.compile(r"(?i)(?:^|[._-])(secret|credential|private[_-]?key|token|password|passwd)(?:[._-]|$)|\.(?:pem|key|p12|pfx)$")
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9_]{2,127}\b")
MODEL_PATTERNS = {
    "openai": re.compile(r"\b(?:gpt-[A-Za-z0-9._-]+|o[134]-[A-Za-z0-9._-]+)\b", re.I),
    "anthropic": re.compile(r"\bclaude-[A-Za-z0-9._-]+\b", re.I),
    "google_gemini": re.compile(r"\bgemini-[A-Za-z0-9._-]+\b", re.I),
    "amazon_bedrock": re.compile(r"\b(?:anthropic|amazon|meta|mistral)\.[A-Za-z0-9._:-]+\b", re.I),
    "openrouter": re.compile(r"\b(?:anthropic|openai|google)/[A-Za-z0-9._-]+\b", re.I),
}
# Projection of Render-internal provider families onto the shared ai-workload-profile
# contract (scripts/contracts/ai-workload-profile.schema.json, issue #415). Identifier
# strings mirror upstream skills/shared/ai/ai-capability-catalog.json (catalog_version 2);
# `gemini_api` is brief-specified rather than catalog-listed. `amazon_bedrock` (an AWS
# target), `openrouter` (a gateway, never a provider), and `other` are intentionally absent.
AI_PROJECTION: dict[str, tuple[str, str]] = {
    "openai": ("openai", "openai_api"),
    "azure_openai": ("openai", "azure_openai"),
    "anthropic": ("anthropic", "anthropic_api"),
    "google_gemini": ("google", "gemini_api"),
    "google_vertex_ai": ("google", "vertex_ai"),
}
AI_DEFAULT_FAMILY = {"openai": "gpt", "anthropic": "claude", "google": "gemini"}
OPENROUTER_UPSTREAM: dict[str, tuple[str, str]] = {
    "anthropic": ("anthropic", "anthropic_api"),
    "openai": ("openai", "openai_api"),
    "google": ("google", "vertex_ai"),
}
OPENROUTER_GATEWAY = {"product": "openrouter", "type": "llm_router"}
FORBIDDEN_IDENTITIES = {"both", "unknown"}
MODEL_PREFIX = re.compile(r"^(?:anthropic|openai|google|models)/")
NORMALIZED_MODEL = re.compile(r"^[a-z0-9][a-z0-9._:/-]*$")

PROVIDERS: dict[str, dict[str, tuple[str, ...]]] = {
    "openai": {"dependency": ("openai",), "import": ("import openai", "from openai", "require('openai')", 'from "openai"'), "sdk_construction": ("OpenAI(", "AsyncOpenAI(", "new OpenAI("), "method_call": ("responses.create", "chat.completions.create"), "endpoint_hostname": ("api.openai.com",), "environment_name": ("OPENAI_API_KEY",)},
    "azure_openai": {"dependency": ("azure-ai-openai",), "import": ("AzureOpenAI", "AsyncAzureOpenAI"), "sdk_construction": ("AzureOpenAI(", "AsyncAzureOpenAI(", "new AzureOpenAI("), "method_call": ("get_chat_completions", "chat.completions.create"), "endpoint_hostname": ("openai.azure.com",), "environment_name": ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")},
    "anthropic": {"dependency": ("anthropic",), "import": ("import anthropic", "from anthropic"), "sdk_construction": ("Anthropic(", "new Anthropic("), "method_call": ("messages.create",), "endpoint_hostname": ("api.anthropic.com",), "environment_name": ("ANTHROPIC_API_KEY",)},
    "google_gemini": {"dependency": ("google-generativeai", "@google/generative-ai"), "import": ("google.generativeai", "GoogleGenerativeAI"), "sdk_construction": ("GenerativeModel(",), "method_call": ("generate_content", "generateContent"), "endpoint_hostname": ("generativelanguage.googleapis.com",), "environment_name": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    "google_vertex_ai": {"dependency": ("google-cloud-aiplatform",), "import": ("import vertexai", "from vertexai"), "sdk_construction": ("vertexai.init(",), "method_call": ("generate_content",), "endpoint_hostname": ("aiplatform.googleapis.com",), "environment_name": ("GOOGLE_CLOUD_PROJECT",)},
    "amazon_bedrock": {"dependency": ("@aws-sdk/client-bedrock-runtime",), "import": ("bedrock-runtime", "BedrockRuntimeClient"), "sdk_construction": ("client(\"bedrock-runtime\"", "BedrockRuntimeClient("), "method_call": ("invoke_model", "converse("), "endpoint_hostname": ("bedrock-runtime.",), "environment_name": ("AWS_REGION",)},
    "openrouter": {"dependency": ("openrouter",), "import": ("openrouter",), "sdk_construction": (), "method_call": ("chat.completions.create",), "endpoint_hostname": ("openrouter.ai",), "environment_name": ("OPENROUTER_API_KEY",)},
}

def _token(literal: str) -> re.Pattern[str]:
    """Case-insensitive literal that may not continue an identifier, so `OpenAI(` never matches inside `AzureOpenAI(`."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(literal), re.I)


# import / sdk_construction / method_call needles are matched as bounded tokens; the direct
# `from openai` import additionally requires that the line imports no Azure client.
BOUNDED_METHODS = {"import", "sdk_construction", "method_call"}
NEEDLE_PATTERNS: dict[tuple[str, str, str], re.Pattern[str]] = {
    (provider, method, needle): _token(needle)
    for provider, methods in PROVIDERS.items()
    for method, needles in methods.items()
    if method in BOUNDED_METHODS
    for needle in needles
}
NEEDLE_PATTERNS[("openai", "import", "from openai")] = re.compile(r"(?<![A-Za-z0-9_])from openai(?:\.[A-Za-z0-9_.]+)? import (?!.*Azure)", re.I)
# A method call shared by several clients binds to the client(s) constructed in the same
# file; when none of them is constructed there it stays with the first (direct) owner.
CLIENT_BOUND_CALLS: dict[str, tuple[str, ...]] = {"chat.completions.create": ("openai", "azure_openai")}
# Model identifiers of a family served by several clients bind to the client(s) constructed
# or called in the same file; otherwise they fall back to the provider-wide family owner.
MODEL_CLIENTS: dict[str, tuple[str, ...]] = {"openai": ("openai", "azure_openai")}
# `name = OpenAI(...)` style constructions and `name.responses.create(` / `name.chat.completions.create(`
# calls on the same line, used to bind a model identifier to the client it is actually called on.
CLIENT_CONSTRUCTOR = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_]\w*)\s*=\s*(AsyncAzureOpenAI|AzureOpenAI|AsyncOpenAI|OpenAI)\(")
CLIENT_CONSTRUCTOR_PROVIDER = {"AsyncAzureOpenAI": "azure_openai", "AzureOpenAI": "azure_openai", "AsyncOpenAI": "openai", "OpenAI": "openai"}
CALL_RECEIVER = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_]\w*)\.(?:responses\.create|chat\.completions\.create)\(")
METHOD_WEIGHTS = {"dependency": 35, "import": 35, "sdk_construction": 40, "method_call": 45, "model_identifier": 25, "endpoint_hostname": 35, "environment_name": 10, "framework": 30, "configuration": 20}
FRAMEWORKS = {"langgraph": "agent_orchestration", "crewai": "agent_orchestration", "autogen": "agent_orchestration", "strands": "agent_orchestration", "llamaindex": "retrieval", "llama_index": "retrieval"}
INFRASTRUCTURE = {
    "postgres_client": ("psycopg", "asyncpg", "pgx", "sequelize", "postgresql"),
    "key_value_client": ("redis", "valkey", "ioredis"),
    "queue_client": ("celery", "bullmq", "sqs", "rabbitmq", "kafka"),
    "object_storage_client": ("boto3", "@aws-sdk/client-s3", "minio"),
    "email_client": ("sendgrid", "postmark", "ses"),
    "authentication_client": ("auth0", "passport", "oauth", "openid"),
    "health_endpoint": ("/health", "/healthz", "/ready"),
    "background_worker": ("celery worker", "bullmq", "sidekiq", "rq worker"),
    "scheduled_task": ("cron", "schedule", "apscheduler"),
    "local_filesystem": ("/tmp/", "open(", "fs.writefile", "file.write"),
    "render_hostname": (".onrender.com",),
}


class ScanError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_regular(path: Path, root: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ScanError("file_not_regular")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ScanError("file_outside_root") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ScanError("file_open_failed") from exc
    try:
        before = os.fstat(fd)
        if before.st_size > MAX_FILE_BYTES:
            raise ScanError("file_too_large")
        data = bytearray()
        while len(data) <= MAX_FILE_BYTES:
            chunk = os.read(fd, min(64 * 1024, MAX_FILE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_BYTES:
        raise ScanError("file_too_large")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ScanError("file_changed_during_read")
    if b"\x00" in data:
        raise ScanError("binary_file")
    return bytes(data)


def _skipped(path: str, reason: str, size: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path_hash": sha256_digest(path.encode("utf-8")), "reason": reason}
    if size is not None:
        record["size_if_known"] = size
    return record


def _walk(root: Path, excluded_paths: frozenset[Path] = frozenset()) -> tuple[list[Path], list[dict[str, Any]]]:
    files: list[Path] = []
    skipped: list[dict[str, Any]] = []

    def visit(directory: Path, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ScanError("traversal_depth_exceeded")
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.encode("utf-8"))
        except OSError as exc:
            raise ScanError("directory_read_failed") from exc
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            if entry.is_symlink():
                skipped.append(_skipped(relative, "symlink"))
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name in EXCLUDED_DIRS or Path(entry.path) in excluded_paths:
                    skipped.append(_skipped(relative, "excluded_directory"))
                else:
                    visit(Path(entry.path), depth + 1)
                continue
            if not entry.is_file(follow_symlinks=False):
                skipped.append(_skipped(relative, "not_regular"))
                continue
            if entry.name in EXCLUDED_NAMES or entry.name.startswith(".env.") or SENSITIVE_NAME.search(entry.name):
                skipped.append(_skipped(relative, "sensitive_name", entry.stat(follow_symlinks=False).st_size))
                continue
            if entry.name.lower().endswith(".min.js"):
                skipped.append(_skipped(relative, "generated_file", entry.stat(follow_symlinks=False).st_size))
                continue
            if entry.name not in ALLOWED_NAMES and Path(entry.name).suffix.lower() not in ALLOWED_EXTENSIONS:
                skipped.append(_skipped(relative, "unsupported_type", entry.stat(follow_symlinks=False).st_size))
                continue
            files.append(Path(entry.path))
            if len(files) > MAX_FILES:
                raise ScanError("file_count_exceeded")

    visit(root, 0)
    skipped.sort(key=lambda item: (byte_sort_key(item["path_hash"]), byte_sort_key(item["reason"])))
    return files, skipped


def _component(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if len(parts) > 1 else Path(path).stem


def _evidence(path: str, method: str, symbol: str) -> dict[str, Any]:
    evidence_id = generated_id("aie", "evidence", path, method, symbol)
    fingerprint = sha256_digest(f"{path}\0{method}\0{symbol}".encode())
    return {"id": evidence_id, "path": path, "method": method, "symbol_or_env_name": symbol, "fingerprint": fingerprint}


def _qualifying_components(matches: list[dict[str, Any]]) -> dict[str, list[tuple[str, list[dict[str, Any]]]]]:
    """Group matches by component; keep (provider, items) pairs scoring >= 70 with strong evidence."""
    by_component_provider: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        by_component_provider[(match["component"], match["provider"])].append(match)
    qualifying: defaultdict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for (component, provider), items in by_component_provider.items():
        unique = {(item["method"], item["symbol"], item["path"]) for item in items}
        score = min(100, sum(METHOD_WEIGHTS[method] for method, _symbol, _path in unique))
        strong = any(method in {"method_call", "sdk_construction"} for method, _symbol, _path in unique)
        if score >= 70 and strong:
            qualifying[component].append((provider, items))
    return dict(qualifying)


def _normalize_model(raw: str) -> tuple[str, str]:
    normalized = MODEL_PREFIX.sub("", raw.lower())
    if not NORMALIZED_MODEL.match(normalized):
        raise ScanError("ai_profile_model_invalid")
    return normalized, normalized.split("-", 1)[0]


def _project_ai_profile(qualifying_components: dict[str, list[tuple[str, list[dict[str, Any]]]]]) -> dict[str, Any] | None:
    """Project qualifying Render AI evidence onto the shared ai-workload-profile contract (#415)."""
    if not qualifying_components:
        return None
    observations: defaultdict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    sources: set[tuple[str, str]] = set()
    openrouter_present = False
    upstream_vendors: set[str] = set()
    for provider_items in qualifying_components.values():
        for provider, items in provider_items:
            if provider == "openrouter":
                openrouter_present = True
            projected = AI_PROJECTION.get(provider)
            if projected is not None:
                sources.add(projected)
            strong_paths = {item["path"] for item in items if item["method"] in {"method_call", "sdk_construction"}}
            for item in items:
                if item["method"] != "model_identifier":
                    continue
                raw = item["symbol"]
                if provider == "openrouter":
                    vendor = raw.split("/", 1)[0].lower()
                    target = OPENROUTER_UPSTREAM[vendor]
                    upstream_vendors.add(vendor)
                elif projected is not None:
                    target = projected
                else:
                    continue
                sources.add(target)
                normalized, family = _normalize_model(raw)
                if item["attribution"] == "ambiguous":
                    confidence, detail = "low", f"{item['path']}:{item['line']}:unattributed"
                else:
                    confidence = "confirmed" if item["path"] in strong_paths else "medium"
                    detail = f"{item['path']}:{item['line']}"
                entry = observations[target].setdefault(normalized, {"raws": set(), "family": family, "evidence": set()})
                entry["raws"].add(raw)
                entry["evidence"].add((detail, confidence))
    ai_sources: list[dict[str, Any]] = []
    source_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for provider, source_service in sorted(sources, key=lambda key: (byte_sort_key(key[0]), byte_sort_key(key[1]))):
        observed = observations.get((provider, source_service), {})
        model_observations = [
            {
                "normalized_model": normalized,
                "raw_model": sorted(entry["raws"], key=byte_sort_key)[0],
                "model_family": entry["family"],
                "evidence": [{"provenance": "code", "confidence": confidence, "detail": detail} for detail, confidence in sorted(entry["evidence"], key=lambda pair: (byte_sort_key(pair[0]), byte_sort_key(pair[1])))],
            }
            for normalized, entry in sorted(observed.items(), key=lambda pair: byte_sort_key(pair[0]))
        ]
        families = sorted({entry["family"] for entry in observed.values()}, key=byte_sort_key) or [AI_DEFAULT_FAMILY[provider]]
        source = {
            "provider": provider,
            "source_service": source_service,
            "model_families": families,
            "model_evidence": "observed" if model_observations else "not_observed",
            "models": [item["normalized_model"] for item in model_observations],
            "model_observations": model_observations,
        }
        ai_sources.append(source)
        source_by_key[(provider, source_service)] = source
    gateways: list[dict[str, Any]] = []
    if openrouter_present:
        upstreams = []
        for vendor in sorted(upstream_vendors, key=byte_sort_key):
            provider, source_service = OPENROUTER_UPSTREAM[vendor]
            source = source_by_key[(provider, source_service)]
            upstreams.append({
                "provider": provider,
                "source_service": source_service,
                "model_families": [
                    {"family": family, "model_evidence": "observed", "models": [item["normalized_model"] for item in source["model_observations"] if item["model_family"] == family]}
                    for family in source["model_families"]
                ],
            })
        gateways.append({**OPENROUTER_GATEWAY, "upstream_evidence": "observed" if upstreams else "unresolved", "upstreams": upstreams})
    identities = [value for source in ai_sources for value in (source["provider"], source["source_service"], *source["model_families"], *source["models"])]
    identities += [value for gateway in gateways for value in (gateway["product"], gateway["type"])]
    identities += [value for gateway in gateways for upstream in gateway["upstreams"] for value in (upstream["provider"], upstream["source_service"])]
    if any(value in FORBIDDEN_IDENTITIES for value in identities) or any(source["provider"] == "openrouter" for source in ai_sources):
        raise ScanError("ai_profile_identity_invalid")
    return {"schema_version": "1.0", "ai_sources": ai_sources, "gateways": gateways}


def _build_ai_discovery(qualifying_components: dict[str, list[tuple[str, list[dict[str, Any]]]]], capabilities: dict[str, set[str]]) -> dict[str, Any] | None:
    """Build the Render-internal AI discovery graph (render-ai-discovery.json)."""
    if not qualifying_components:
        return None

    providers: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    gateways: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    workloads: list[dict[str, Any]] = []
    call_sites: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    for component in sorted(qualifying_components, key=byte_sort_key):
        provider_items = qualifying_components[component]
        component_capabilities = set(capabilities.get(component, {"text_generation"})) or {"text_generation"}
        primary = sorted(component_capabilities, key=byte_sort_key)[0]
        workload_id = generated_id("aiw", "workload", component, primary)
        provider_ids: list[str] = []
        evidence_ids: list[str] = []
        workload_call_ids: list[str] = []
        for provider, items in sorted(provider_items, key=lambda item: byte_sort_key(item[0])):
            provider_id = generated_id("aip", "provider", provider)
            providers[provider_id] = {"id": provider_id, "family": provider}
            provider_ids.append(provider_id)
            relation_id = generated_id("air", "relationship", "workload_uses_provider", workload_id, provider_id)
            relationships.append({"id": relation_id, "type": "workload_uses_provider", "from_id": workload_id, "to_id": provider_id})
            model_ids: list[str] = []
            for model_item in sorted((entry for entry in items if entry["method"] == "model_identifier"), key=lambda entry: byte_sort_key(entry["symbol"])):
                model_id = generated_id("aim", "model", provider_id, model_item["symbol"])
                models[model_id] = {"id": model_id, "provider_id": provider_id, "observed_identifier": model_item["symbol"]}
                model_ids.append(model_id)
                relationships.append({"id": generated_id("air", "relationship", "workload_uses_model", workload_id, model_id), "type": "workload_uses_model", "from_id": workload_id, "to_id": model_id})
            gateway_id = None
            if provider == "openrouter":
                gateway_id = generated_id("aig", "gateway", "openrouter", "openrouter.ai")
                gateways[gateway_id] = {"id": gateway_id, "family": "openrouter", "hostname": "openrouter.ai"}
                relationships.append({"id": generated_id("air", "relationship", "workload_uses_gateway", workload_id, gateway_id), "type": "workload_uses_gateway", "from_id": workload_id, "to_id": gateway_id})
            strong_items = [item for item in items if item["method"] in {"method_call", "sdk_construction"}]
            for ordinal, item in enumerate(sorted(strong_items, key=lambda value: (byte_sort_key(value["path"]), byte_sort_key(value["symbol"])))):
                item_evidence_ids: list[str] = []
                related = [candidate for candidate in items if candidate["path"] == item["path"]]
                for candidate in related:
                    entry = _evidence(candidate["path"], candidate["method"], candidate["symbol"])
                    evidence[entry["id"]] = entry
                    item_evidence_ids.append(entry["id"])
                    evidence_ids.append(entry["id"])
                call_id = generated_id("aic", "call-site", workload_id, item["path"], item["symbol"], str(ordinal))
                call_sites.append({"id": call_id, "workload_id": workload_id, "path": item["path"], "symbol": item["symbol"], "ordinal": ordinal, "provider_id": provider_id, "model_id": sorted(set(model_ids), key=byte_sort_key)[0] if model_ids else None, "gateway_id": gateway_id, "evidence_ids": sorted(set(item_evidence_ids), key=byte_sort_key)})
                workload_call_ids.append(call_id)
        workload_model_ids = sorted({item["model_id"] for item in call_sites if item["workload_id"] == workload_id and item["model_id"] is not None}, key=byte_sort_key)
        workload_gateway_ids = sorted({item["gateway_id"] for item in call_sites if item["workload_id"] == workload_id and item["gateway_id"] is not None}, key=byte_sort_key)
        workloads.append({"id": workload_id, "component": component, "capabilities": sorted(component_capabilities, key=byte_sort_key), "provider_ids": sorted(set(provider_ids), key=byte_sort_key), "model_ids": workload_model_ids, "gateway_ids": workload_gateway_ids, "evidence_ids": sorted(set(evidence_ids), key=byte_sort_key), "call_site_ids": sorted(set(workload_call_ids), key=byte_sort_key), "confidence": "deterministic"})
    discovery: dict[str, Any] = {
        "schema_version": "1.0", "discovery_id": "", "fingerprint": "",
        "workloads": sorted(workloads, key=lambda item: byte_sort_key(item["id"])),
        "providers": sorted(providers.values(), key=lambda item: byte_sort_key(item["id"])),
        "models": sorted(models.values(), key=lambda item: byte_sort_key(item["id"])),
        "gateways": sorted(gateways.values(), key=lambda item: byte_sort_key(item["id"])),
        "evidence": sorted(evidence.values(), key=lambda item: byte_sort_key(item["id"])),
        "call_sites": sorted(call_sites, key=lambda item: byte_sort_key(item["id"])),
        "relationships": sorted(relationships, key=lambda item: (byte_sort_key(item["type"]), byte_sort_key(item["from_id"]), byte_sort_key(item["to_id"]), byte_sort_key(item["id"]))),
    }
    fingerprint_input = {key: value for key, value in discovery.items() if key != "fingerprint"}
    fingerprint = sha256_digest(canonical_bytes(fingerprint_input))
    discovery["fingerprint"] = fingerprint
    discovery["discovery_id"] = "aidisc-" + fingerprint.removeprefix("sha256:")[:24]
    return discovery


def _client_bound(match: dict[str, Any], constructed: set[str]) -> bool:
    """Keep a shared method call only for the client constructed in this file (default owner when none is)."""
    clients = CLIENT_BOUND_CALLS.get(match["symbol"]) if match["method"] == "method_call" else None
    if clients is None or match["provider"] not in clients:
        return True
    bound = [client for client in clients if client in constructed]
    return match["provider"] in bound if bound else match["provider"] == clients[0]


def _model_targets(provider: str, active: set[str]) -> tuple[str, ...]:
    """Attribute a model family to the client(s) constructed or called in this file, else provider-wide."""
    clients = MODEL_CLIENTS.get(provider)
    if clients is None:
        return (provider,)
    return tuple(client for client in clients if client in active) or (provider,)


def _bind_model(provider: str, line_text: str, constructors: dict[str, str], active: set[str]) -> tuple[tuple[str, str], ...]:
    """Return (source, attribution) pairs for a model identifier on one line.

    A call whose receiver is a client constructed in this file binds the model to that client only
    ("bound"). Otherwise the model stays with the family's clients in this file, marked "ambiguous" when
    more than one client could own it, so it is never asserted as confirmed usage of a specific source.
    """
    clients = MODEL_CLIENTS.get(provider)
    if clients is None:
        return ((provider, "bound"),)
    called = {constructors[name] for name in CALL_RECEIVER.findall(line_text) if name in constructors} & set(clients)
    if called:
        return tuple((client, "bound") for client in clients if client in called)
    targets = _model_targets(provider, active)
    return tuple((target, "bound" if len(targets) == 1 else "ambiguous") for target in targets)


def scan(root: Path, migration_dir: Path | None = None) -> dict[str, Any]:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ScanError("workspace_root_invalid")
    resolved_root = root.resolve(strict=True)
    excluded_paths: set[Path] = set()
    if migration_dir is not None:
        resolved_migration = migration_dir.resolve(strict=True)
        if resolved_migration != resolved_root and resolved_migration.is_relative_to(resolved_root):
            excluded_paths.add(resolved_migration)
    files, skipped = _walk(resolved_root, frozenset(excluded_paths))
    total = 0
    file_records: list[dict[str, Any]] = []
    signals: defaultdict[str, set[str]] = defaultdict(set)
    matches: list[dict[str, Any]] = []
    capabilities: defaultdict[str, set[str]] = defaultdict(set)
    for path in files:
        relative = path.relative_to(resolved_root).as_posix()
        try:
            data = _read_regular(path, resolved_root)
        except ScanError as exc:
            if exc.code in {"file_too_large", "binary_file"}:
                skipped.append(_skipped(relative, exc.code, path.stat().st_size if path.exists() else None))
                continue
            raise
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ScanError("aggregate_bytes_exceeded")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            skipped.append(_skipped(relative, "invalid_utf8", len(data)))
            continue
        file_records.append({"path": relative, "size_bytes": len(data), "fingerprint": sha256_digest(data)})
        lowered = text.lower()
        component = _component(relative)
        for signal, needles in INFRASTRUCTURE.items():
            if any(needle.lower() in lowered for needle in needles):
                signals[signal].add(relative)
        for framework, capability in FRAMEWORKS.items():
            if framework in lowered:
                capabilities[component].add(capability)
        if any(token in lowered for token in ("embedding", "vectorstore", "retriev", "rerank")):
            capabilities[component].add("retrieval")
        if any(token in lowered for token in ("image.generate", "images.generate", "stablediffusion")):
            capabilities[component].add("image")
        if any(token in lowered for token in ("speech", "transcri", "text_to_speech")):
            capabilities[component].add("speech")
        if any(token in lowered for token in ("tool_call", "bind_tools", "function_call")):
            capabilities[component].add("agent_tools")
        environment_names = set(ENV_NAME.findall(text))
        file_matches: list[dict[str, Any]] = []
        for provider, methods in PROVIDERS.items():
            for method, needles in methods.items():
                for needle in needles:
                    if method == "environment_name":
                        present = needle in environment_names
                    elif method in BOUNDED_METHODS:
                        present = NEEDLE_PATTERNS[(provider, method, needle)].search(text) is not None
                    else:
                        present = needle.lower() in lowered
                    if present:
                        file_matches.append({"component": component, "provider": provider, "path": relative, "method": method, "symbol": needle})
        constructed = {match["provider"] for match in file_matches if match["method"] == "sdk_construction"}
        file_matches = [match for match in file_matches if _client_bound(match, constructed)]
        active_clients = {match["provider"] for match in file_matches if match["method"] in {"method_call", "sdk_construction"}}
        if active_clients:
            capabilities[component].add("text_generation")
        matches.extend(file_matches)
        constructors = {name: CLIENT_CONSTRUCTOR_PROVIDER[kind] for name, kind in CLIENT_CONSTRUCTOR.findall(text)}
        lines = text.split("\n")
        for provider, pattern in MODEL_PATTERNS.items():
            for identifier in sorted(set(pattern.findall(text)), key=byte_sort_key):
                # Match the identifier as a whole token: `find` would land inside `gpt-4o-mini` for `gpt-4o`.
                # Every occurrence line is bound on its own so each call site credits its own client.
                occurrence_lines = sorted({text.count("\n", 0, found.start()) + 1 for found in pattern.finditer(text) if found.group(0) == identifier})
                for line in occurrence_lines:
                    for target, attribution in _bind_model(provider, lines[line - 1], constructors, active_clients):
                        matches.append({"component": component, "provider": target, "path": relative, "method": "model_identifier", "symbol": identifier, "line": line, "attribution": attribution})
        if any(token in lowered for token in ("while true", "while(true)", "approval", "checkpoint", "fan_out", "fan-in", "compensat")):
            capabilities[component].add("agent_orchestration")
        if any(token in lowered for token in ("documentloader", "document_ingest", "ingest_documents")):
            capabilities[component].add("document_ingestion")
        if "rerank" in lowered:
            capabilities[component].add("reranking")
        if "embedding" in lowered:
            capabilities[component].add("embedding")
    file_records.sort(key=lambda item: byte_sort_key(item["path"]))
    skipped.sort(key=lambda item: (byte_sort_key(item["path_hash"]), byte_sort_key(item["reason"])))
    safe_signals = [{"kind": kind, "paths": sorted(paths, key=byte_sort_key)} for kind, paths in sorted(signals.items(), key=lambda item: byte_sort_key(item[0]))]
    qualifying_components = _qualifying_components(matches)
    ai_profile = _project_ai_profile(qualifying_components)
    ai_discovery = _build_ai_discovery(qualifying_components, capabilities)
    fingerprint_input = {"files": file_records, "signals": safe_signals, "skipped": skipped}
    return {"schema_version": "1.0", "files": file_records, "skipped": skipped, "signals": safe_signals, "fingerprint": sha256_digest(canonical_bytes(fingerprint_input)), "ai_profile": ai_profile, "ai_discovery": ai_discovery}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.migration_dir.is_absolute() or not args.migration_dir.is_dir() or args.migration_dir.is_symlink():
            raise ScanError("migration_dir_invalid")
        require_contained(args.output, args.migration_dir, "output")
        result = scan(args.workspace_root, args.migration_dir)
        write_json_atomic(args.output, args.migration_dir, result)
    except (ScanError, PathBoundaryError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ScanError) else str(exc)
        if not code or any(character.isspace() for character in code):
            code = "internal_validation_error"
        print(f"APP_SCAN_FAIL | code={code}", file=sys.stderr)
        return 1
    print(f"APP_SCAN_OK | output={args.output} | fingerprint={result['fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
