"""Bedrock model/path recommendation orchestrator for agent-advisor.

Validates the shared input contract, dispatches each workload to its provider
module (anthropic_model_recommendation / openai_model_recommendation; anything
else falls through to the provisional generic path), aggregates per-workload
results with per-workload catalog provenance, and validates the shared output
contract. Provider-specific rules live in the provider modules, not here.
"""

import argparse
import json
import pathlib

import anthropic_model_recommendation
import openai_model_recommendation


SKILL_DIR = pathlib.Path(__file__).parent.parent
MODELS_DIR = SKILL_DIR / "references" / "models"
DEFAULT_CATALOG = MODELS_DIR / "anthropic-bedrock-2026-07-21.json"
OPENAI_CATALOG = MODELS_DIR / "openai-bedrock-2026-08-21.json"

# Which provider module owns a source. This is a TWO-way decision, not a per-provider table: OpenAI
# has its own module, and everything else goes to the Anthropic one — including `none`/`unknown` (no
# detected provider means the Bedrock-native pool) and the providers with no module yet
# (azure_openai, google_genai, bedrock). Routing those to the Anthropic module is deliberate rather
# than a silent default: that module classifies the source against its own ANTHROPIC_POOL and attaches
# a `provider_module_pending` [BLOCKS] finding to anything outside it, so the recommendation is
# produced but stays provisional. Enumerating the fall-through providers here would duplicate that
# classification in a second place and let the two drift.
def _provider_module(provider):
    return "openai" if provider == "openai" else "anthropic"



def load_catalog(path=DEFAULT_CATALOG):
    catalog_path = pathlib.Path(path)
    try:
        catalog = json.loads(catalog_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{catalog_path}: invalid JSON ({exc})") from exc
    required = {
        "schema_version",
        "provider",
        "verified_at",
        "verified_region",
        "paths",
        "models",
    }
    missing = sorted(required - set(catalog))
    if missing:
        raise ValueError(f"{catalog_path}: missing required keys {missing}")
    for model_key, model in catalog["models"].items():
        for field in (
            "display_name",
            "family",
            "version",
            "context_window",
            "output_token_ceiling",
            "capabilities",
            "paths",
        ):
            if field not in model:
                raise ValueError(f"{catalog_path}: {model_key} missing {field}")
    return catalog


def load_openai_catalog(path=OPENAI_CATALOG):
    """Load and validate the dated OpenAI/Bedrock path catalog.

    Unlike the Anthropic catalog, numeric limits may be the string "unknown"
    (the reference proves paths, not context/output ceilings), and each model
    carries a `generation` and per-path `evidence` citation.
    """
    catalog_path = pathlib.Path(path)
    try:
        catalog = json.loads(catalog_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{catalog_path}: invalid JSON ({exc})") from exc
    required = {
        "schema_version",
        "provider",
        "verified_at",
        "verified_region",
        "paths",
        "models",
    }
    missing = sorted(required - set(catalog))
    if missing:
        raise ValueError(f"{catalog_path}: missing required keys {missing}")
    for model_key, model in catalog["models"].items():
        for field in (
            "display_name",
            "family",
            "generation",
            "version",
            "context_window",
            "output_token_ceiling",
            "capabilities",
            "paths",
        ):
            if field not in model:
                raise ValueError(f"{catalog_path}: {model_key} missing {field}")
        for limit in ("context_window", "output_token_ceiling"):
            value = model[limit]
            if value != "unknown" and not (isinstance(value, int) and value > 0):
                raise ValueError(
                    f"{catalog_path}: {model_key} {limit} must be a positive int or "
                    f'"unknown", got {value!r}'
                )
    return catalog




def _catalog_provenance(catalog):
    return {
        "provider": catalog["provider"],
        "verified_at": catalog["verified_at"],
        "verified_region": catalog["verified_region"],
        "source": catalog.get("source"),
    }


def recommend(input_data, catalog=None, openai_catalog=None):
    """Dispatch each workload to its provider module.

    Anthropic (and none/unknown/generic) use `catalog`; OpenAI uses
    `openai_catalog`. Every workload records the provenance of the catalog that
    produced it so a mixed-provider run never mislabels a source.
    """
    if catalog is None:
        catalog = load_catalog()
    workloads = {}
    provenance = {}
    catalogs_used = {}
    for workload in input_data["workloads"]:
        workload_id = workload["workload_id"]
        if workload_id in workloads:
            raise ValueError(f"duplicate workload_id: {workload_id}")
        provider = workload["source"]["provider"]
        module = _provider_module(provider)
        if module == "openai":
            if openai_catalog is None:
                openai_catalog = load_openai_catalog()
            workloads[workload_id] = openai_model_recommendation.recommend_openai_workload(
                workload, input_data["region"], openai_catalog
            )
            provenance[workload_id] = _catalog_provenance(openai_catalog)
            catalogs_used["openai"] = openai_catalog
        else:
            workloads[workload_id] = anthropic_model_recommendation.recommend_anthropic_workload(
                workload, input_data["region"], catalog
            )
            provenance[workload_id] = _catalog_provenance(catalog)
            catalogs_used["anthropic"] = catalog
    primary_unit = input_data["primary_unit"]
    if primary_unit not in workloads:
        raise ValueError(f"primary_unit not found in workloads: {primary_unit}")
    # Backward-compatible top-level `catalog`: the primary unit's catalog, plus
    # explicit per-workload provenance so a mixed run keeps correct attribution.
    return {
        "schema_version": 2,
        "catalog": provenance[primary_unit],
        "catalog_provenance": provenance,
        "primary_unit": primary_unit,
        "workloads": workloads,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="agent-advisor Bedrock model recommendation"
    )
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="defaults to model-recommendation.json beside the input",
    )
    parser.add_argument("--catalog", type=pathlib.Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)

    try:
        import jsonschema
    except ImportError:
        jsonschema = None

    def validate(instance, schema_name):
        if jsonschema is None:
            return
        schemas = pathlib.Path(__file__).parent / "schemas"
        jsonschema.validate(instance, json.loads((schemas / schema_name).read_text()))

    input_data = json.loads(args.input.read_text())
    validate(input_data, "model-recommendation-input.json")
    result = recommend(input_data, load_catalog(args.catalog))
    validate(result, "model-recommendation.json")
    output = args.output or args.input.parent / "model-recommendation.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    validated = "no" if jsonschema is None else "yes"
    print(f"RESULT=ok WORKLOADS={len(result['workloads'])} SCHEMA_VALIDATED={validated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
