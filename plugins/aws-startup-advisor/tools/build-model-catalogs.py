#!/usr/bin/env python3
"""build-model-catalogs.py: render the provider model-selection catalogs from the shared registry.

Why
---
agent-advisor's selectors read one catalog per provider module
(`skills/shared/ai/models/{anthropic,openai}-bedrock.json`). The OpenAI catalog carries Claude
models as cross-family Converse targets, so the same Claude facts used to be maintained twice,
in two capability vocabularies. `bedrock-model-registry.json` is now the single source:

- `models`: one record per Bedrock model, holding the facts every consumer shares (limits,
  model ids per path, inference profiles, feature flags, `selection_status`) and capabilities in
  one canonical vocabulary (`capability_vocabulary`).
- `views.<provider>`: what one provider module needs. The catalog header, its path definitions,
  the canonical-to-module capability map, and one entry per catalog model naming the registry
  record plus the view-specific fields (display_name, class, family, version, generation,
  capability_source, evidence), the paths the view exposes, and per-path evidence.

This tool renders each view to its catalog file. The rendered files are build output: edit the
registry and rerun this tool, never the catalogs. `--check` fails when a catalog differs from what
the registry renders, so a hand edit or a forgotten rebuild cannot merge. The rendered catalogs
keep the shape the selectors, loaders, phase files, pricing validator, drift check, and
model-selection-catalog.schema.json already use.

Usage
-----
    python3 plugins/aws-startup-advisor/tools/build-model-catalogs.py          # write
    python3 plugins/aws-startup-advisor/tools/build-model-catalogs.py --check  # exit 1 on drift

Then run `tools/sync-vendored.py` to refresh agent-advisor's vendored copies. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PLUGIN_ROOT / "skills" / "shared" / "ai" / "models"
REGISTRY = MODELS_DIR / "bedrock-model-registry.json"
CONTRACTS = PLUGIN_ROOT / "scripts" / "contracts"
REGISTRY_SCHEMA = CONTRACTS / "model-registry.schema.json"
CATALOG_SCHEMA = CONTRACTS / "model-selection-catalog.schema.json"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
GENERATED_FROM = ("bedrock-model-registry.json (rendered by tools/build-model-catalogs.py; edit the "
                  "registry, not this file)")

HEADER_KEYS = ("schema_version", "provider", "generated_from", "verified_at", "verified_region",
               "source", "disclaimer", "registry_exclusions")
VIEW_FIELDS = ("display_name", "family", "generation", "version", "class",
               "capability_source", "evidence")
# Output key order for a catalog model and a model path (the order of the catalog schema).
MODEL_ORDER = ("display_name", "selection_status", "family", "generation", "version", "class",
               "context_window", "output_token_ceiling", "capabilities", "capability_source",
               "evidence", "lifecycle_status", "launch_date", "eol_no_sooner_than",
               "default_effort", "adaptive_thinking_only", "batch_supported",
               "forced_tool_choice_supported", "native_structured_output_supported",
               "sampling_parameters_supported", "runtime_in_region_regions",
               "runtime_in_region_verified_at", "mantle_regions", "service_tiers",
               "inference_profiles", "region_availability", "pricing",
               "paths")
PATH_ORDER = ("available", "model_id", "requires_cris", "guardrails_supported",
              "prompt_caching_supported", "server_side_tools_supported", "evidence", "capabilities", "regions", "supported_regions", "inference_profile_regions")
REGISTRY_ONLY = ("provider",)  # registry bookkeeping, never rendered
FIELD_HINT = ("update MODEL_ORDER/PATH_ORDER/VIEW_FIELDS here, scripts/contracts/model-registry.schema.json, "
              "and scripts/contracts/model-selection-catalog.schema.json together")


class RegistryError(ValueError):
    pass


def _validate_schema(schema_path: Path, value: dict, label: str) -> None:
    """Validate with the plugin's draft-07-subset validator (scripts/validate-artifacts.py)."""
    spec = importlib.util.spec_from_file_location("build_model_catalogs__validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    findings: list = []
    module.validate_json_schema(json.loads(schema_path.read_text(encoding="utf-8")), value, "",
                                label, schema_path.name, findings)
    if findings:
        detail = "; ".join(str(getattr(f, "message", f)) for f in findings[:5])
        raise RegistryError(f"{label} does not match {schema_path.name}: {detail}")


def _ordered(record: dict, order: tuple[str, ...], where: str) -> dict:
    unknown = sorted(set(record) - set(order))
    if unknown:
        raise RegistryError(f"{where}: unknown field(s) {unknown}; {FIELD_HINT}")
    return {key: record[key] for key in order if key in record}


def _map_capabilities(canonical: list[str], vocabulary: dict, where: str) -> list[str]:
    """Map canonical terms to the module's terms. A null mapping drops the term by design
    (e.g. long_context has no OpenAI-module equivalent)."""
    out = []
    for capability in canonical:
        if capability not in vocabulary:
            raise RegistryError(f"{where}: capability {capability!r} has no mapping in this view")
        if vocabulary[capability] is not None:
            out.append(vocabulary[capability])
    return out


def render_view(registry: dict, name: str) -> dict:
    view = registry["views"][name]
    canonical_vocab = set(registry["capability_vocabulary"])
    vocabulary = view["capabilities"]
    stray = sorted(set(vocabulary) - canonical_vocab)
    if stray:
        raise RegistryError(f"views.{name}.capabilities maps non-canonical term(s) {stray}")
    targets = [term for term in vocabulary.values() if term is not None]
    if len(targets) != len(set(targets)):
        raise RegistryError(f"views.{name}.capabilities maps two canonical terms to the same module term")
    header = view["header"]
    unknown = sorted(set(header) - set(HEADER_KEYS) | ({"generated_from"} & set(header)))
    if unknown:
        raise RegistryError(f"views.{name}.header: unknown or generated field(s) {unknown}")
    header = {**header, "generated_from": GENERATED_FROM}
    catalog = {key: header[key] for key in HEADER_KEYS if key in header}
    catalog["paths"] = view["paths"]
    models = {}
    seen_sources: dict[str, str] = {}
    for view_key, entry in view["models"].items():
        where = f"views.{name}.models.{view_key}"
        source_key = entry.get("model")
        if source_key not in registry["models"]:
            raise RegistryError(f"{where}: references unknown registry model {source_key!r}")
        if source_key in seen_sources:
            raise RegistryError(f"{where}: registry model {source_key!r} already appears in this view "
                                f"as {seen_sources[source_key]!r}")
        seen_sources[source_key] = view_key
        source = registry["models"][source_key]
        leaked = sorted(set(source) & set(VIEW_FIELDS))
        if leaked:
            raise RegistryError(f"models.{source_key}: view-specific field(s) {leaked} belong in each view entry")
        extra = sorted(set(entry) - set(VIEW_FIELDS) - {"model", "paths"})
        if extra:
            raise RegistryError(f"{where}: field(s) {extra} belong in the registry record, not the view")
        model = {k: v for k, v in source.items() if k not in REGISTRY_ONLY and k != "paths"}
        model.update({k: entry[k] for k in VIEW_FIELDS if k in entry})
        model["capabilities"] = _map_capabilities(source["capabilities"], vocabulary, where)
        paths = {}
        for path_id, overrides in entry["paths"].items():
            if path_id not in view["paths"]:
                raise RegistryError(f"{where}: path {path_id!r} is not defined in views.{name}.paths")
            if path_id not in source["paths"]:
                raise RegistryError(f"{where}: registry model {source_key!r} has no {path_id!r} path")
            bad = sorted(set(overrides) - {"evidence"})
            if bad:
                raise RegistryError(f"{where}.paths.{path_id}: only evidence may be overridden, got {bad}")
            path = dict(source["paths"][path_id])
            path.update(overrides)
            if "capabilities" in path:
                path["capabilities"] = _map_capabilities(path["capabilities"], vocabulary,
                                                         f"{where}.paths.{path_id}")
            paths[path_id] = _ordered(path, PATH_ORDER, f"{where}.paths.{path_id}")
        model["paths"] = paths
        models[view_key] = _ordered(model, MODEL_ORDER, where)
    catalog["models"] = models
    return catalog


def check_vocabulary(registry: dict) -> None:
    """Every record capability must be a canonical term (checked before rendering)."""
    vocab = registry["capability_vocabulary"]
    if len(set(vocab)) != len(vocab):
        raise RegistryError("capability_vocabulary has duplicates")
    for key, record in registry["models"].items():
        stray = set(record["capabilities"]) - set(vocab)
        for path in record["paths"].values():
            stray |= set(path.get("capabilities", [])) - set(vocab)
        if stray:
            raise RegistryError(f"models.{key}: non-canonical capabilities {sorted(stray)}")


def check_usage(registry: dict) -> None:
    """Every record must be rendered by some view (checked after rendering)."""
    referenced = {entry["model"] for view in registry["views"].values() for entry in view["models"].values()}
    unused = sorted(set(registry["models"]) - referenced)
    if unused:
        raise RegistryError(f"registry model(s) {unused} are not used by any view")
    exposed: dict[str, set[str]] = {}
    for view in registry["views"].values():
        for entry in view["models"].values():
            exposed.setdefault(entry["model"], set()).update(entry["paths"])
    for key, record in registry["models"].items():
        hidden = sorted(set(record["paths"]) - exposed.get(key, set()))
        if hidden:
            raise RegistryError(f"models.{key}: path(s) {hidden} are not exposed by any view")


def render_all(registry: dict) -> dict[str, str]:
    _validate_schema(REGISTRY_SCHEMA, registry, "registry")
    check_vocabulary(registry)
    out = {}
    for name, view in registry["views"].items():
        filename = view["catalog"]
        if Path(filename).name != filename:
            raise RegistryError(f"views.{name}.catalog must be a plain file name, got {filename!r}")
        if filename in out:
            # Two views writing one file would silently drop the first; fail before writing.
            raise RegistryError(f"views.{name}.catalog {filename!r} is already rendered by another view")
        catalog = render_view(registry, name)
        _validate_schema(CATALOG_SCHEMA, catalog, f"rendered {filename}")
        out[filename] = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    check_usage(registry)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail if a catalog differs from the registry")
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    args = parser.parse_args(argv)
    registry_path = args.models_dir / REGISTRY.name
    try:
        rendered = render_all(json.loads(registry_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {registry_path.name}: {exc}")
        return 1
    stale = []
    for filename, text in rendered.items():
        target = args.models_dir / filename
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(filename + (" (missing)" if current is None else ""))
        else:
            target.write_text(text, encoding="utf-8")
            print(f"  wrote {filename}")
    if stale:
        print(f"ERROR: {', '.join(stale)} out of date with {REGISTRY.name}. Edit the registry, not the "
              "catalogs, then run `python3 tools/build-model-catalogs.py` and "
              "`python3 tools/sync-vendored.py`.")
        return 1
    print(f"model catalogs: {len(rendered)} rendered from {REGISTRY.name}"
          + (" and up to date" if args.check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
