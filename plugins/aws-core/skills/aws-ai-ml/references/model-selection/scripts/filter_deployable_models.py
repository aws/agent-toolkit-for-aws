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
    customization:<true|false> - Filter by fine-tuning (customization) eligibility
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
    "customization",
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

        elif key == "customization":
            customization_val = model.get("customization_eligible", None)
            if customization_val is None:
                return False
            value = values[-1]
            if value == "true" and not customization_val:
                return False
            elif value == "false" and customization_val:
                return False

        elif key == "name":
            model_name = model.get("name", "").lower()
            if not any(v in model_name for v in values):
                return False

    return True


def sort_models_newest_first(models):
    """Return models sorted deterministically, newest first.

    The ordering is total and stable, so identical input always produces
    identical output:

      1. Models WITH an ``original_creation_time`` come before models that lack
         one. Undated models are pushed to the end.
      2. Among dated models, sort by ``original_creation_time`` DESCENDING
         (most recent first). Creation times are ISO 8601 strings, which
         compare correctly lexicographically.
      3. ``name`` ASCENDING (case-insensitive) is the tie-breaker applied
         throughout. It orders dated models that share a creation time AND
         alphabetizes the undated group among themselves at the end. So if
         four models are undated, all four sit at the end of the list sorted
         A -> Z relative to each other.

    Implementation note: we split into dated/undated groups and use Python's
    stable sort with two passes (name ascending, then time descending), rather
    than a single composite key. This avoids comparing ``None`` to strings and
    avoids any per-character math on the timestamp: ISO 8601 strings of
    DIFFERENT lengths (e.g. with vs. without fractional seconds, since
    ``datetime.isoformat()`` omits microseconds when they are zero) compare
    correctly as-is under ``reverse=True``, whereas a per-character inversion
    would let a shorter string become a prefix of a longer one and sort wrong.

    Args:
        models: List of model dicts.

    Returns:
        A new sorted list (the input list is not mutated).
    """

    def name_key(model):
        return (model.get("name") or "").lower()

    dated = [m for m in models if m.get("original_creation_time") is not None]
    undated = [m for m in models if m.get("original_creation_time") is None]

    # Stable two-pass sort for the dated group: establish the name (A->Z)
    # tie-break first, then sort by time descending. Because the sort is
    # stable, models sharing a creation time keep the name ordering.
    dated.sort(key=name_key)
    dated.sort(key=lambda m: m["original_creation_time"], reverse=True)

    # Undated group: alphabetical by name.
    undated.sort(key=name_key)

    return dated + undated


def filter_models(models, constraints):
    """Apply every constraint and return the existing deterministic order.

    The public-Hub Search adapter reuses this complete List-and-filter behavior
    only when Search fails. Keeping one function for the CLI, private Hubs, and
    public fallback prevents their matching semantics from drifting.
    """
    return sort_models_newest_first(
        [model for model in models if matches(model, constraints)]
    )


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

    filtered = filter_models(models, constraints)

    # Output summary + results
    result = {
        "total_models": len(models),
        "filters_applied": constraints,
        "matched": len(filtered),
        "models": filtered,
    }

    print(json.dumps(result))
