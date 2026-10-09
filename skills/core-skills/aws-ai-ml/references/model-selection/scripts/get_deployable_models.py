"""
Retrieves all deployable models from a SageMaker Hub and outputs structured metadata as JSON.

Usage:
    python get_deployable_models.py <hub-name> [--list-values] [--create-snapshot]
        [--snapshot-file <path>] [region]

Arguments:
    hub-name       Name of the SageMaker Hub to query (e.g., SageMakerPublicHub)
    region         Optional AWS region override (defaults to boto3 session default)
    snapshot-file  Optional short-lived selection-session cache for public-Hub Search

Output:
    JSON array of model objects with fields: name, data_types, input_modalities,
    output_modalities, size, license, languages, context_window, model_type,
    framework, provider, tasks, bedrock_eligible.
"""

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone

import boto3
import botocore.exceptions

os.environ.setdefault("AWS_SDK_UA_APP_ID", "AWSSkill-SageMaker")

SNAPSHOT_SCHEMA_VERSION = 1
USAGE = (
    "Usage: python get_deployable_models.py <hub-name> [--list-values] "
    "[--create-snapshot] [--snapshot-file <path>] [region]"
)

# Canonical, non-overlapping size buckets. The hub's raw @model-size values are
# inconsistent — a mix of ranges (e.g. "1b-10b", "10b-70b") and exact parameter
# counts (e.g. "2b", "7b", "30b", "550b"), plus "<1b" and "unknown". Because the
# size filter is an EXACT match, that inconsistency makes deterministic
# soft->hard mapping impossible (e.g. "small" -> "1b-10b" would silently miss a
# model tagged "7b"). We normalize every raw value into one of these buckets so
# the filter and the soft-constraint mapping only ever deal with a clean set.
SIZE_BUCKETS = ("<=10b", "11b-70b", "71b-100b", ">100b", "unknown")


class CatalogSnapshotError(ValueError):
    """A selection-session catalog snapshot is missing or malformed."""


def normalize_size_bucket(raw):
    """Map a raw @model-size value to a canonical, non-overlapping bucket.

    Assignment rule by parameter count N (in billions):
        N <= 10   -> "<=10b"
        10 < N <= 70  -> "11b-70b"
        70 < N <= 100 -> "71b-100b"
        N > 100   -> ">100b"
        unparseable / missing -> "unknown"

    Handles both exact values ("7b", "30b", "550b") and the hub's own range
    labels ("1b-10b", "10b-70b", "70b-100b", ">100b", "<1b"). Range labels are
    classified by their UPPER bound (the largest models the range can contain),
    except ">100b" which is unbounded above and maps to ">100b". This keeps the
    mapping total and deterministic.

    Args:
        raw: The raw size string from the @model-size keyword, or None.

    Returns:
        One of SIZE_BUCKETS.
    """
    if not raw:
        return "unknown"

    value = raw.strip().lower()
    if value == "unknown":
        return "unknown"

    def bucket_for(n):
        if n <= 10:
            return "<=10b"
        if n <= 70:
            return "11b-70b"
        if n <= 100:
            return "71b-100b"
        return ">100b"

    # ">100b" (or any ">Nb") is unbounded above -> largest bucket.
    if value.startswith(">"):
        return ">100b"

    # "<1b" (or any "<Nb") -> use the upper bound N (e.g. <1b has upper bound 1).
    if value.startswith("<"):
        num = _parse_billions(value[1:])
        return bucket_for(num) if num is not None else "unknown"

    # Range label like "1b-10b" / "10b-70b" / "70b-100b": classify by upper bound.
    if "-" in value:
        upper = _parse_billions(value.split("-", 1)[1])
        return bucket_for(upper) if upper is not None else "unknown"

    # Exact value like "7b", "30b", "550b".
    num = _parse_billions(value)
    return bucket_for(num) if num is not None else "unknown"


def _parse_billions(token):
    """Parse a size token like '7b', '550b', '10' into a number of billions.

    Returns a float, or None if it cannot be parsed.
    """
    if not token:
        return None
    t = token.strip().lower().rstrip("b").strip()
    try:
        return float(t)
    except ValueError:
        return None


# Document fields read when the matching keyword is absent. The Hub writes at
# most 50 keywords per model and a model with many languages can run out of
# slots before these are written, while the document still carries them. Only
# Search returns HubContentDocument; ListHubContents does not, so the snapshot
# is unaffected. normalized field -> (document field, keyword prefix)
_DOCUMENT_FALLBACK_FIELDS = {
    "size": ("ModelSize", "@model-size:"),
    "context_window": ("ContextWindow", "@context-window:"),
}


def _document_scalar(model, field):
    """Return one lower-cased string value of a top-level document field, or None.

    Keywords are the lower-cased document value, so lower-casing here keeps the
    normalized shape identical whichever source supplied it.
    """
    document = model.get("HubContentDocument")
    if not isinstance(document, str) or not document:
        return None
    try:
        parsed = json.loads(document)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get(field)
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str) and item), None)
    if isinstance(value, str) and value:
        return value.lower()
    return None


def normalize_hub_content(model):
    """Convert a List or Search HubContent model to the skill's normalized shape.

    Args:
        model: A HubContent model mapping returned by ListHubContents or Search.

    Returns:
        A model dict with extracted and normalized metadata fields.
    """
    keywords = model.get("HubContentSearchKeywords", [])
    entry = {
        "name": model.get("HubContentName"),
    }

    for kw in keywords:
        if kw.startswith("@data-type:"):
            entry.setdefault("data_types", []).append(kw.split(":", 1)[1])
        elif kw.startswith("@input-modality:"):
            entry.setdefault("input_modalities", []).append(kw.split(":", 1)[1])
        elif kw.startswith("@output-modality:"):
            entry.setdefault("output_modalities", []).append(kw.split(":", 1)[1])
        elif kw.startswith("@model-size:"):
            # Preserve the raw hub value for display, and store the normalized
            # canonical bucket used by the filter and soft-constraint mapping.
            raw_size = kw.split(":", 1)[1]
            entry["size_raw"] = raw_size
            entry["size"] = normalize_size_bucket(raw_size)
        elif kw.startswith("@license:"):
            entry["license"] = kw.split(":", 1)[1]
        elif kw.startswith("@language:"):
            entry.setdefault("languages", []).append(kw.split(":", 1)[1])
        elif kw.startswith("@context-window:"):
            entry["context_window"] = kw.split(":", 1)[1]
        elif kw.startswith("@model-type:"):
            entry["model_type"] = kw.split(":", 1)[1]
        elif kw.startswith("@framework:"):
            # Framework is stored separately from provider for display and
            # future structured filtering.
            entry["framework"] = kw.split(":", 1)[1]
        elif kw.startswith("@provider:"):
            entry["provider"] = kw.split(":", 1)[1]
        elif kw.startswith("@task:"):
            entry.setdefault("tasks", []).append(kw.split(":", 1)[1])

    entry["bedrock_eligible"] = "@capability:bedrock_console" in keywords
    entry["customization_eligible"] = "@capability:customization" in keywords

    # A keyword, when present, is authoritative; the document fills in only
    # what the keyword cap dropped.
    for normalized_field, (document_field, prefix) in _DOCUMENT_FALLBACK_FIELDS.items():
        if any(kw.startswith(prefix) for kw in keywords):
            continue
        value = _document_scalar(model, document_field)
        if value is None:
            continue
        if normalized_field == "size":
            entry["size_raw"] = value
            entry["size"] = normalize_size_bucket(value)
        else:
            entry[normalized_field] = value

    # ListHubContents exposes this model-level catalog date, while Search only
    # exposes version-level CreationTime. Cache the List field so a version
    # import cannot silently reorder the customer-visible first 20 models.
    original_creation_time = model.get("OriginalCreationTime")
    if original_creation_time:
        entry["original_creation_time"] = (
            original_creation_time.isoformat()
            if hasattr(original_creation_time, "isoformat")
            else str(original_creation_time)
        )

    return entry


def get_deployable_models(hub_name, region_name=None, sm_client=None):
    """Query a SageMaker Hub and return structured model metadata.

    Args:
        hub_name: Name of the SageMaker Hub.
        region_name: Optional AWS region override.
        sm_client: Optional existing SageMaker client. The CLI supplies one so
            snapshot metadata uses the exact region that served the List call.

    Returns:
        List of model dicts with extracted metadata fields.
    """
    sm_client = sm_client or boto3.client("sagemaker", region_name=region_name)

    # Retrieve all models with pagination
    all_contents = []
    next_token = None

    while True:
        params = {
            "HubName": hub_name,
            "HubContentType": "Model",
            "MaxResults": 100,
        }

        if next_token:
            params["NextToken"] = next_token

        response = sm_client.list_hub_contents(**params)
        all_contents.extend(response.get("HubContentSummaries", []))

        next_token = response.get("NextToken")
        if not next_token:
            break

    return [normalize_hub_content(model) for model in all_contents]


def list_available_values(models):
    """Extract all unique values for each metadata field across all models.

    Returns a dict of field_name -> sorted list of unique values.
    """
    values: dict[str, set[str]] = {
        "tasks": set(),
        "data_types": set(),
        "input_modalities": set(),
        "output_modalities": set(),
        "sizes": set(),
        "licenses": set(),
        "languages": set(),
        "context_windows": set(),
        "model_types": set(),
        "providers": set(),
        "frameworks": set(),
    }

    for model in models:
        for task in model.get("tasks", []):
            values["tasks"].add(task)
        for dt in model.get("data_types", []):
            values["data_types"].add(dt)
        for im in model.get("input_modalities", []):
            values["input_modalities"].add(im)
        for om in model.get("output_modalities", []):
            values["output_modalities"].add(om)
        if "size" in model:
            values["sizes"].add(model["size"])
        if "license" in model:
            values["licenses"].add(model["license"])
        for lang in model.get("languages", []):
            values["languages"].add(lang)
        if "context_window" in model:
            values["context_windows"].add(model["context_window"])
        if "model_type" in model:
            values["model_types"].add(model["model_type"])
        if "provider" in model:
            values["providers"].add(model["provider"])
        if "framework" in model:
            values["frameworks"].add(model["framework"])

    return {k: sorted(v) for k, v in values.items()}


def build_catalog_snapshot(hub_name, region_name, models, fetched_at=None):
    """Build the short-lived catalog cache used across the confirmation pause.

    ``catalog_models`` contains compact, normalized ListHubContents summaries.
    Search query construction needs their exact values, including inconsistent
    license spellings such as ``Apache 2.0`` and ``Apache-2.0``. The same complete
    summaries support local fallback. HubContentDocument, markdown, and
    credentials never enter this normalized shape.
    """
    if not isinstance(hub_name, str) or not hub_name:
        raise CatalogSnapshotError("Snapshot hub_name must be a non-empty string")
    if not isinstance(region_name, str) or not region_name:
        raise CatalogSnapshotError(
            "A configured AWS region is required to create a catalog snapshot"
        )
    if not isinstance(models, list) or not all(
        isinstance(model, Mapping) for model in models
    ):
        raise CatalogSnapshotError("Snapshot catalog_models must be a list of objects")

    timestamp = fetched_at or datetime.now(timezone.utc)
    if hasattr(timestamp, "isoformat"):
        timestamp = timestamp.isoformat()
    if not isinstance(timestamp, str) or not timestamp:
        raise CatalogSnapshotError("Snapshot fetched_at must be a non-empty timestamp")

    original_creation_times = {
        model["name"]: model["original_creation_time"]
        for model in models
        if isinstance(model.get("name"), str)
        and isinstance(model.get("original_creation_time"), str)
    }
    raw_sizes_by_bucket = {
        bucket: sorted(
            {
                model["size_raw"]
                for model in models
                if model.get("size") == bucket
                and isinstance(model.get("size_raw"), str)
            },
            key=str.lower,
        )
        for bucket in SIZE_BUCKETS
    }

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "hub_name": hub_name,
        "region": region_name,
        "fetched_at": timestamp,
        "model_count": len(models),
        "available_values": list_available_values(models),
        "raw_sizes_by_bucket": raw_sizes_by_bucket,
        "original_creation_times": original_creation_times,
        "catalog_models": models,
    }


def validate_catalog_snapshot(snapshot, expected_hub=None, expected_region=None):
    """Validate a snapshot before using it for Search or local fallback."""
    if not isinstance(snapshot, Mapping):
        raise CatalogSnapshotError("Catalog snapshot must be a JSON object")
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise CatalogSnapshotError(
            f"Unsupported catalog snapshot schema: {snapshot.get('schema_version')!r}"
        )

    hub_name = snapshot.get("hub_name")
    region = snapshot.get("region")
    fetched_at = snapshot.get("fetched_at")
    models = snapshot.get("catalog_models")
    model_count = snapshot.get("model_count")

    if not isinstance(hub_name, str) or not hub_name:
        raise CatalogSnapshotError("Catalog snapshot hub_name must be a non-empty string")
    if expected_hub is not None and hub_name != expected_hub:
        raise CatalogSnapshotError(
            f"Catalog snapshot is for Hub {hub_name!r}, not {expected_hub!r}"
        )
    if not isinstance(region, str) or not region:
        raise CatalogSnapshotError("Catalog snapshot region must be a non-empty string")
    if expected_region is not None and region != expected_region:
        raise CatalogSnapshotError(
            f"Catalog snapshot is for region {region!r}, not {expected_region!r}"
        )
    if not isinstance(fetched_at, str) or not fetched_at:
        raise CatalogSnapshotError("Catalog snapshot fetched_at must be a timestamp string")
    if not isinstance(models, list) or not all(
        isinstance(model, Mapping) for model in models
    ):
        raise CatalogSnapshotError("Catalog snapshot catalog_models must be a list of objects")
    if not isinstance(model_count, int) or isinstance(model_count, bool):
        raise CatalogSnapshotError("Catalog snapshot model_count must be an integer")
    if model_count != len(models):
        raise CatalogSnapshotError(
            "Catalog snapshot model_count does not match catalog_models length"
        )

    names = [model.get("name") for model in models]
    if any(not isinstance(name, str) or not name for name in names):
        raise CatalogSnapshotError("Every cached model must have a non-empty name")
    if len(names) != len(set(names)):
        raise CatalogSnapshotError("Catalog snapshot contains duplicate model names")

    for field in (
        "available_values",
        "raw_sizes_by_bucket",
        "original_creation_times",
    ):
        if not isinstance(snapshot.get(field), Mapping):
            raise CatalogSnapshotError(f"Catalog snapshot {field} must be an object")

    return snapshot


def write_catalog_snapshot(path, snapshot):
    """Write a validated per-session snapshot with private file permissions."""
    validate_catalog_snapshot(snapshot)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        # os.open's mode applies only to new files. Restrict an existing
        # caller-owned path before writing any snapshot content as well.
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as snapshot_file:
            descriptor = None
            json.dump(snapshot, snapshot_file)
    except OSError as error:
        raise CatalogSnapshotError(f"Could not write catalog snapshot: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def create_catalog_snapshot_file(snapshot):
    """Create a unique snapshot path and remove it if writing fails."""
    validate_catalog_snapshot(snapshot)
    descriptor, path = tempfile.mkstemp(prefix="sherpa-model-catalog.")
    os.close(descriptor)
    try:
        write_catalog_snapshot(path, snapshot)
    except Exception:
        # This function owns the path, so failed creation must not leave an
        # unknown cache file behind. Do not apply this cleanup to caller-owned
        # paths accepted by write_catalog_snapshot().
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise
    return path


def load_catalog_snapshot(path, expected_hub=None, expected_region=None):
    """Read and validate a selection-session cache from disk."""
    try:
        with open(path, encoding="utf-8") as snapshot_file:
            snapshot = json.load(snapshot_file)
    except FileNotFoundError as error:
        raise CatalogSnapshotError(f"Catalog snapshot not found: {path}") from error
    except json.JSONDecodeError as error:
        raise CatalogSnapshotError(f"Catalog snapshot is not valid JSON: {error}") from error
    except OSError as error:
        raise CatalogSnapshotError(f"Could not read catalog snapshot: {error}") from error

    return validate_catalog_snapshot(snapshot, expected_hub, expected_region)


def _parse_cli_args(argv):
    """Parse the legacy positional region plus snapshot options."""
    args = list(argv)
    list_values_mode = False
    create_snapshot = False
    snapshot_path = None

    if "--list-values" in args:
        list_values_mode = True
        args.remove("--list-values")

    if "--create-snapshot" in args:
        create_snapshot = True
        args.remove("--create-snapshot")

    if "--snapshot-file" in args:
        option_index = args.index("--snapshot-file")
        if option_index + 1 >= len(args):
            raise CatalogSnapshotError("--snapshot-file requires a path")
        snapshot_path = args[option_index + 1]
        del args[option_index : option_index + 2]

    if create_snapshot and snapshot_path:
        raise CatalogSnapshotError(
            "Use either --create-snapshot or --snapshot-file, not both"
        )
    if create_snapshot and not list_values_mode:
        raise CatalogSnapshotError("--create-snapshot requires --list-values")
    if not args or len(args) > 2 or any(arg.startswith("-") for arg in args):
        raise CatalogSnapshotError(USAGE)

    return (
        args[0],
        args[1] if len(args) == 2 else None,
        list_values_mode,
        create_snapshot,
        snapshot_path,
    )


def main(argv=None):
    """Run the catalog CLI, optionally creating a selection-session cache."""
    try:
        (
            hub_name,
            region_name,
            list_values_mode,
            create_snapshot,
            snapshot_path,
        ) = _parse_cli_args(sys.argv[1:] if argv is None else argv)
    except CatalogSnapshotError as error:
        print(str(error), file=sys.stderr)
        return 1

    try:
        sm_client = boto3.client("sagemaker", region_name=region_name)
        results = get_deployable_models(
            hub_name,
            region_name,
            sm_client=sm_client,
        )
        snapshot = None
        if create_snapshot or snapshot_path:
            resolved_region = region_name or sm_client.meta.region_name
            snapshot = build_catalog_snapshot(hub_name, resolved_region, results)
            if create_snapshot:
                snapshot_path = create_catalog_snapshot_file(snapshot)
            else:
                write_catalog_snapshot(snapshot_path, snapshot)
    except botocore.exceptions.ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"Error: AWS API call failed ({error_code}): {error_msg}", file=sys.stderr)
        return 1
    except botocore.exceptions.NoCredentialsError:
        print(
            "Error: No AWS credentials found. Configure credentials via 'aws configure' or environment variables.",
            file=sys.stderr,
        )
        return 1
    except botocore.exceptions.EndpointConnectionError as e:
        print(f"Error: Could not connect to SageMaker endpoint: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if create_snapshot:
        assert snapshot is not None
        print(
            json.dumps(
                {
                    "snapshot_file": snapshot_path,
                    "available_values": snapshot["available_values"],
                }
            )
        )
    elif list_values_mode:
        print(
            json.dumps(
                snapshot["available_values"]
                if snapshot is not None
                else list_available_values(results)
            )
        )
    else:
        print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
