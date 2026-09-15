import json
import sys

"""
Filters deployable models based on constraints from a use case spec.

Usage:
    python filter_deployable_models.py <models_json_file> [constraint:value ...]

Behavior:
    Models are excluded when they lack metadata for a filtered field OR when
    their metadata positively mismatches a constraint. Only models with matching
    metadata for every applied filter are included in results.

    Multiple values for the same key are OR-ed together. For example:
        size:1b size:1b-10b size:7b
    matches models with ANY of those sizes.

    Different keys are AND-ed together. For example:
        size:1b-10b task:text generation
    matches models that have size 1b-10b AND task text generation.

Constraints (all optional, repeatable):
    task:<value>            - Match against 'tasks' field (substring match)
    data_type:<value>      - Match against 'data_types' field (substring match)
    input_modality:<value> - Match against 'input_modalities' field (substring match)
    output_modality:<value>- Match against 'output_modalities' field (substring match)
    license:<value>        - Match against 'license' field (substring match)
    size:<value>           - Match against 'size' field (exact match)
    context_window:<value> - Match against 'context_window' field (exact match)
    language:<value>       - Match against 'languages' field (substring match)
    model_type:<value>     - Match against 'model_type' field (exact match)
    provider:<value>       - Match against 'provider' field (substring match)
    bedrock:<true|false>   - Filter by Bedrock eligibility
    name:<value>           - Match against model 'name' (substring, case-insensitive)

Example:
    python filter_deployable_models.py models.json "task:text generation" "size:1b" "size:1b-10b"
"""

VALID_KEYS = {
    "task",
    "data_type",
    "input_modality",
    "output_modality",
    "license",
    "size",
    "context_window",
    "language",
    "model_type",
    "provider",
    "bedrock",
    "name",
}


def matches(model, constraints):
    """Check if a model matches all constraints.

    Models are excluded when they lack metadata for a filtered field OR when
    their metadata positively mismatches the constraint.

    Multiple values for the same key are OR-ed (match any).
    Different keys are AND-ed (must match all).

    Args:
        model: Model dict with metadata fields.
        constraints: Dict of filter key -> list of values.
    """
    for key, values in constraints.items():
        if key == "task":
            tasks = model.get("tasks", None)
            if tasks is None:
                return False
            if not any(v in t.lower() for v in values for t in tasks):
                return False

        elif key == "data_type":
            data_types = model.get("data_types", None)
            if data_types is None:
                return False
            if not any(v in d.lower() for v in values for d in data_types):
                return False

        elif key == "input_modality":
            modalities = model.get("input_modalities", None)
            if modalities is None:
                return False
            if not any(v in m.lower() for v in values for m in modalities):
                return False

        elif key == "output_modality":
            modalities = model.get("output_modalities", None)
            if modalities is None:
                return False
            if not any(v in m.lower() for v in values for m in modalities):
                return False

        elif key == "license":
            model_license = model.get("license", None)
            if model_license is None:
                return False
            if not any(v in model_license.lower() for v in values):
                return False

        elif key == "size":
            model_size = model.get("size", None)
            if model_size is None:
                return False
            if not any(v == model_size.lower() for v in values):
                return False

        elif key == "context_window":
            ctx = model.get("context_window", None)
            if ctx is None:
                return False
            if not any(v == ctx.lower() for v in values):
                return False

        elif key == "language":
            languages = model.get("languages", None)
            if languages is None:
                return False
            if not any(v in lang.lower() for v in values for lang in languages):
                return False

        elif key == "model_type":
            mt = model.get("model_type", None)
            if mt is None:
                return False
            if not any(v == mt.lower() for v in values):
                return False

        elif key == "provider":
            provider = model.get("provider", None)
            if provider is None:
                return False
            if not any(v in provider.lower() for v in values):
                return False

        elif key == "bedrock":
            bedrock_val = model.get("bedrock_eligible", None)
            if bedrock_val is None:
                return False
            # Use last value for bedrock (true/false is binary)
            value = values[-1]
            if value == "true" and not bedrock_val:
                return False
            elif value == "false" and bedrock_val:
                return False

        elif key == "name":
            model_name = model.get("name", "").lower()
            if not any(v in model_name for v in values):
                return False

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python filter_deployable_models.py <models_json_file> [constraint:value ...]")
        sys.exit(1)

    models_file = sys.argv[1]
    raw_constraints = sys.argv[2:] if len(sys.argv) > 2 else []

    # Parse constraints — accumulate multiple values per key
    constraints: dict[str, list[str]] = {}
    for c in raw_constraints:
        if ":" not in c:
            print(
                f"Warning: Ignoring malformed constraint (no ':' separator): {c}", file=sys.stderr
            )
            continue
        key, value = c.split(":", 1)
        if key not in VALID_KEYS:
            print(
                f"Warning: Unrecognized constraint key '{key}'. Valid keys: {', '.join(sorted(VALID_KEYS))}",
                file=sys.stderr,
            )
            continue
        constraints.setdefault(key, []).append(value.lower())

    # Load models
    try:
        with open(models_file, "r") as f:
            models = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {models_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {models_file}: {e}", file=sys.stderr)
        sys.exit(1)

    filtered = [m for m in models if matches(m, constraints)]

    # Output summary + results
    result = {
        "total_models": len(models),
        "filters_applied": constraints,
        "matched": len(filtered),
        "models": filtered,
    }

    print(json.dumps(result))
