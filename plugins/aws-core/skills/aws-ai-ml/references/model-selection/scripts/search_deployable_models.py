"""Build and run exact SageMaker Search queries for public Hub models.

A short-lived ListHubContents snapshot provides exact value resolution, local
fallback, and stable OriginalCreationTime ordering. Search performs candidate
retrieval for SageMakerPublicHub; private Hubs continue to use the existing
List-and-filter workflow.

Constraints map to two Search fields. Data type, input and output modality,
model type, Bedrock eligibility, size, and context window use ``Metadata.*``
filters over the model's HubContentDocument. Task, license, language,
provider, and customization use ``HubContentSearchKeywords`` tags. See
``_METADATA_CONSTRAINTS`` for why the split sits where it does.

Usage:
    python search_deployable_models.py SageMakerPublicHub \
        --snapshot-file /tmp/sherpa-model-catalog.ABC123.json \
        --region us-east-2 \
        "task:text generation" "task:generation-text" "size:<=10b"

The snapshot is optional for direct developer use. Without one, this script
loads the catalog immediately before Search for backward CLI compatibility.
The activated skill always supplies the session snapshot so it does not repeat
the catalog call after the user confirms filters.

Dependency: boto3 and botocore must meet the ``MINIMUM_SDK_VERSION`` defined
below for native ``Search(Resource="HubContent")`` response support. SageMaker
PySDK v3 has no equivalent HubContent Search operation, so this adapter
intentionally uses the low-level boto3 client and gates its version before
calling Search.
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import boto3
import botocore
import botocore.exceptions

from filter_deployable_models import filter_models, sort_models_newest_first
from get_deployable_models import (
    CatalogSnapshotError,
    get_deployable_models,
    load_catalog_snapshot,
    normalize_hub_content,
)

PUBLIC_HUB_NAME = "SageMakerPublicHub"
MINIMUM_SDK_VERSION = (1, 43, 100)
MAX_EXPRESSION_ITEMS = 20
MAX_FILTER_VALUE_LENGTH = 1024
SEARCH_PAGE_SIZE = 100
# Paging key only. Candidate order is restored from OriginalCreationTime.
SEARCH_SORT_BY = "HubContentName"

SUPPORTED_CONSTRAINT_KEYS = (
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
)

# field in the normalized catalog, raw Hub keyword prefix, match behavior
_KEYWORD_CONSTRAINTS = {
    "task": ("tasks", "@task:", "substring"),
    "license": ("license", "@license:", "substring"),
    "language": ("languages", "@language:", "substring"),
    "provider": ("provider", "@provider:", "substring"),
}

# Constraints served by Search ``Metadata.*`` filters instead of keyword tags.
#
# The Search index stores every top-level string or string-array field of a
# model's HubContentDocument as a metadata entry. A filter names the field as
# ``Metadata.<DocumentField>``, and ``Equals``/``In`` compare the stored value
# exactly, case included. These fields each have one document source and no
# alternate spellings, so exact metadata replaces the derived ``@<tag>:``
# keyword one for one. Task, license, language, and provider stay on keywords:
# their values are inconsistent (``Apache 2.0`` and ``Apache-2.0``) or capped
# by the 50-keyword limit in ways not yet handled.
#
# Metadata can reach models whose keyword slot ran out. A model with many
# languages can exhaust its 50 keywords before ``@model-size:`` or
# ``@context-window:`` is written, while the document still carries the field.
# The values this adapter sends are still learned from the snapshot, which is
# built from ListHubContents and never sees the document. So an overflowed
# model is reached only when its raw label is also carried by a model that
# kept its keyword. Every overflowed model in the public Hub today shares
# ``<1B``, ``1B-10B``, or ``<4K`` with hundreds of tagged models, so all are
# reached, and normalize_hub_content reads their size and context window from
# the document. A label carried only by overflowed models stays undiscoverable
# until values are derived from documents rather than keywords.
#
# The Hub builds each ``@<tag>:`` keyword by lower-casing the document value,
# so the catalog snapshot only knows the lower-cased spelling while metadata
# keeps the document's own casing. ``enum`` fields (``ModelTypes``,
# ``Capabilities``) are upper-case by schema. Free-text fields arrive from
# three producers with three conventions: the Studio manifest lower-cases
# (``"text"``), the open-source SDK spec capitalizes (``["Text"]``), and the
# proprietary spec upper-cases (``["TEXT"]``). The adapter sends every
# convention as exact alternatives so a casing difference cannot silently
# empty a result.
#
# constraint key -> (normalized catalog field, Metadata filter, match, casing)
_METADATA_CONSTRAINTS = {
    "data_type": ("data_types", "Metadata.DataType", "substring", "free_text"),
    "input_modality": (
        "input_modalities",
        "Metadata.InputModalities",
        "substring",
        "free_text",
    ),
    "output_modality": (
        "output_modalities",
        "Metadata.OutputModalities",
        "substring",
        "free_text",
    ),
    "model_type": ("model_type", "Metadata.ModelTypes", "exact", "enum"),
    "context_window": (
        "context_window",
        "Metadata.ContextWindow",
        "exact",
        "free_text",
    ),
}

# ``size`` is the one constraint whose request value is not a catalog value.
# The customer picks a canonical bucket (``<=10b``); the Hub stores raw labels
# (``7B``, ``1B-10B``, ``<1B``). The bucket expands to every raw catalog value
# that normalize_size_bucket maps into it, and those raw values are what the
# metadata filter sends. The bucket mapping stays in Sherpa because raw labels
# mix exact counts and ranges and cannot be filtered as a range server-side.
_SIZE_METADATA_FILTER = "Metadata.ModelSize"

# Capability constraints served by ``Metadata.Capabilities``. The document
# field is an upper-case enum array; the keyword was its lower-cased copy.
_METADATA_CAPABILITIES = {
    "bedrock": ("Metadata.Capabilities", "BEDROCK_CONSOLE"),
}

# Capability constraints still served by the lower-cased keyword tag.
_CAPABILITY_TAGS = {
    "customization": "@capability:customization",
}


@dataclass(frozen=True)
class OrderingSummary:
    """Timestamp coverage and provenance for deterministic candidate ordering."""

    field: str
    timestamp_source: str
    dated_models: int
    undated_models: int


@dataclass(frozen=True)
class FallbackReason:
    """Why public-Hub Search used the complete local catalog fallback."""

    type: str
    message: str


@dataclass(frozen=True)
class PublicHubSelection:
    """Typed result for Search-backed public-Hub candidate selection."""

    retrieval_backend: str
    ordering: OrderingSummary
    warnings: list[str]
    models: list[dict]
    fallback_reason: FallbackReason | None = None

    def to_output_dict(self):
        """Return the stable JSON shape, omitting an absent fallback reason."""
        output = asdict(self)
        if output["fallback_reason"] is None:
            del output["fallback_reason"]
        return output


@dataclass(frozen=True)
class SelectionCatalog:
    """Catalog data and provenance used for one CLI selection."""

    models: list[dict]
    region_name: str | None
    source: str


class SearchAdapterError(Exception):
    """Base error for public-Hub Search adapter failures."""


class ConstraintValidationError(SearchAdapterError):
    """A constraint cannot be represented by the public-Hub query contract."""


class UnsupportedSdkError(SearchAdapterError):
    """The installed SDK does not understand HubContent Search records."""


class SearchServiceError(SearchAdapterError):
    """The SageMaker Search request failed."""


class SearchResponseError(SearchAdapterError):
    """The Search response does not contain the expected HubContent shape."""


def _parse_version(version):
    """Return the first three numeric components of an SDK version."""
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", str(version))
    if not match:
        raise UnsupportedSdkError(f"Cannot parse SDK version: {version!r}")
    return tuple(int(part) for part in match.groups())


def validate_sdk_versions(boto3_version=None, botocore_version=None):
    """Require the first boto3/botocore versions with HubContent Search support."""
    versions = {
        "boto3": boto3.__version__ if boto3_version is None else boto3_version,
        "botocore": botocore.__version__ if botocore_version is None else botocore_version,
    }
    minimum = ".".join(str(part) for part in MINIMUM_SDK_VERSION)
    for package, version in versions.items():
        if _parse_version(version) < MINIMUM_SDK_VERSION:
            raise UnsupportedSdkError(
                f"{package} {minimum} or newer is required for "
                f'Search(Resource="HubContent"); found {version}'
            )


def normalize_constraints(constraints):
    """Validate and normalize a mapping of filter keys to value lists."""
    if not isinstance(constraints, Mapping):
        raise ConstraintValidationError("Constraints must be a mapping of keys to value lists")

    normalized = {}
    for key, values in constraints.items():
        if key not in SUPPORTED_CONSTRAINT_KEYS:
            valid = ", ".join(SUPPORTED_CONSTRAINT_KEYS)
            raise ConstraintValidationError(
                f"Unsupported constraint key {key!r}. Supported keys: {valid}"
            )
        if isinstance(values, str) or not isinstance(values, Sequence) or not values:
            raise ConstraintValidationError(
                f"Constraint {key!r} must contain at least one value"
            )

        clean_values = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ConstraintValidationError(
                    f"Constraint {key!r} contains an empty or non-string value"
                )
            clean_values.append(value.strip().lower())
        normalized[key] = list(dict.fromkeys(clean_values))

    return normalized


def parse_constraints(raw_constraints):
    """Parse repeatable ``key:value`` CLI arguments into normalized constraints."""
    constraints: dict[str, list[str]] = {}
    for raw in raw_constraints:
        if ":" not in raw:
            raise ConstraintValidationError(
                f"Malformed constraint {raw!r}; expected key:value"
            )
        key, value = raw.split(":", 1)
        key = key.strip()
        constraints.setdefault(key, []).append(value)
    return normalize_constraints(constraints)


def _catalog_field_values(model, field):
    """Yield string values from a scalar or list-valued normalized field."""
    value = model.get(field)
    if isinstance(value, str):
        yield value
    elif isinstance(value, Sequence):
        for item in value:
            if isinstance(item, str):
                yield item


def _resolve_catalog_values(key, field, match_mode, requested_values, catalog_models):
    """Return every current catalog value the customer's request matches.

    Resolution runs against the selection-session snapshot so an unknown value
    is rejected before any service call and a substring request expands to
    every exact catalog spelling it covers. Values keep their catalog casing.
    """
    resolved: dict[str, str] = {}

    for model in catalog_models:
        for catalog_value in _catalog_field_values(model, field):
            lowered = catalog_value.lower()
            if match_mode == "exact":
                matches = lowered in requested_values
            else:
                matches = any(requested in lowered for requested in requested_values)
            if matches:
                resolved.setdefault(catalog_value, catalog_value)

    if not resolved:
        raise ConstraintValidationError(
            f"Constraint {key!r} values {requested_values!r} do not match "
            "any current public-Hub catalog value"
        )
    return sorted(resolved.values(), key=str.lower)


def _resolve_keyword_tags(key, requested_values, catalog_models):
    """Resolve model-selection values to every matching current Hub keyword tag.

    This catalog lookup is intentionally retained for licenses. Public models
    currently use inconsistent spellings such as ``Apache 2.0`` and
    ``Apache-2.0``; resolving the customer's substring against the snapshot
    keeps both exact Search tags until the underlying metadata is standardized.
    """
    field, prefix, match_mode = _KEYWORD_CONSTRAINTS[key]
    values = _resolve_catalog_values(
        key, field, match_mode, requested_values, catalog_models
    )
    return [f"{prefix}{value}" for value in values]


def _metadata_spellings(value, casing):
    """Expand a lower-cased keyword value to the document casings metadata keeps.

    See ``_METADATA_CONSTRAINTS``: keywords are the lower-cased document value,
    metadata matches the document value exactly. Enum fields have one
    upper-case spelling; free-text fields may be lower-case, capitalized, or
    upper-case depending on which Hub producer wrote the document.
    """
    lowered = value.lower()
    if casing == "enum":
        return [lowered.upper()]
    return list(dict.fromkeys([value, lowered, lowered.capitalize(), lowered.upper()]))


def _resolve_metadata_filter(key, requested_values, catalog_models):
    """Resolve a constraint to its ``Metadata.*`` filter name and exact values."""
    field, filter_name, match_mode, casing = _METADATA_CONSTRAINTS[key]
    values = _resolve_catalog_values(
        key, field, match_mode, requested_values, catalog_models
    )
    spellings: dict[str, str] = {}
    for value in values:
        for spelling in _metadata_spellings(value, casing):
            spellings.setdefault(spelling, spelling)
    return filter_name, list(spellings.values())


def _resolve_size_values(requested_values, catalog_models):
    """Expand normalized size buckets to the raw ``ModelSize`` values they contain.

    The raw labels come from the catalog snapshot, where they are the Hub's
    lower-cased keyword copies. The document keeps its own casing (``7B``),
    so each raw label is expanded to every casing before it is sent.
    """
    resolved: dict[str, str] = {}
    for model in catalog_models:
        normalized_size = model.get("size")
        raw_size = model.get("size_raw")
        if (
            isinstance(normalized_size, str)
            and normalized_size.lower() in requested_values
            and isinstance(raw_size, str)
            and raw_size
        ):
            for spelling in _metadata_spellings(raw_size, "free_text"):
                resolved.setdefault(spelling, spelling)

    if not resolved:
        raise ConstraintValidationError(
            f"Size values {requested_values!r} do not match any current "
            "public-Hub raw model-size value"
        )
    return sorted(resolved.values(), key=str.lower)


def _resolve_model_names(requested_values, catalog_models):
    """Resolve case-insensitive substrings to exact current Hub model names."""
    resolved = set()
    for model in catalog_models:
        name = model.get("name")
        if isinstance(name, str) and any(
            requested in name.lower() for requested in requested_values
        ):
            resolved.add(name)

    if not resolved:
        raise ConstraintValidationError(
            f"Model-name values {requested_values!r} do not match any current "
            "public-Hub model"
        )
    return sorted(resolved, key=lambda name: (name.lower(), name))


def _shared_name_spelling(requested_value, resolved_names):
    """Return one catalog-cased substring shared by every resolved name."""
    spellings = set()
    for name in resolved_names:
        start = name.lower().find(requested_value)
        if start < 0:
            return None
        spellings.add(name[start : start + len(requested_value)])
    return next(iter(spellings)) if len(spellings) == 1 else None


def _alternative_filters(name, values):
    """Pack exact alternatives into safe In filters and literal-comma Equals filters."""
    search_filters: list[dict] = []
    in_values: list[str] = []
    in_length = 0

    def flush_in_values():
        nonlocal in_values, in_length
        if not in_values:
            return
        if len(in_values) == 1:
            search_filters.append(
                {"Name": name, "Operator": "Equals", "Value": in_values[0]}
            )
        else:
            search_filters.append(
                {"Name": name, "Operator": "In", "Value": ",".join(in_values)}
            )
        in_values = []
        in_length = 0

    for value in values:
        if "," in value:
            flush_in_values()
            search_filters.append(
                {"Name": name, "Operator": "Equals", "Value": value}
            )
            continue

        added_length = len(value) + (1 if in_values else 0)
        if in_values and in_length + added_length > MAX_FILTER_VALUE_LENGTH:
            flush_in_values()
            added_length = len(value)
        in_values.append(value)
        in_length += added_length

    flush_in_values()
    return search_filters


def _or_expression(search_filters):
    """Build a nested OR tree whose individual lists stay within service limits."""
    if len(search_filters) <= MAX_EXPRESSION_ITEMS:
        return {"Operator": "Or", "Filters": search_filters}

    level = [
        {"Operator": "Or", "Filters": search_filters[index : index + MAX_EXPRESSION_ITEMS]}
        for index in range(0, len(search_filters), MAX_EXPRESSION_ITEMS)
    ]
    while len(level) > MAX_EXPRESSION_ITEMS:
        level = [
            {"Operator": "Or", "SubExpressions": level[index : index + MAX_EXPRESSION_ITEMS]}
            for index in range(0, len(level), MAX_EXPRESSION_ITEMS)
        ]
    return {"Operator": "Or", "SubExpressions": level}


def _append_exact_alternatives(filters, subexpressions, name, values):
    """Add exact alternatives without exceeding filter-list or value limits."""
    if len(values) == 1:
        filters.append({"Name": name, "Operator": "Equals", "Value": values[0]})
        return

    alternative_filters = _alternative_filters(name, values)
    if len(alternative_filters) == 1:
        filters.append(alternative_filters[0])
        return
    subexpressions.append(_or_expression(alternative_filters))


def validate_search_expression(expression, path="SearchExpression"):
    """Validate generated expression-list and filter-value service limits."""
    if not isinstance(expression, Mapping):
        raise ConstraintValidationError(f"{path} must be an object")

    has_condition = False
    for collection_name in ("Filters", "NestedFilters", "SubExpressions"):
        if collection_name not in expression:
            continue
        values = expression[collection_name]
        if not isinstance(values, list) or not values:
            raise ConstraintValidationError(f"{path}.{collection_name} must be a non-empty list")
        has_condition = True
        if len(values) > MAX_EXPRESSION_ITEMS:
            raise ConstraintValidationError(
                f"{path}.{collection_name} has {len(values)} elements; "
                f"the maximum is {MAX_EXPRESSION_ITEMS}"
            )

    for index, search_filter in enumerate(expression.get("Filters", [])):
        if not isinstance(search_filter, Mapping):
            raise ConstraintValidationError(f"{path}.Filters[{index}] must be an object")
        value = search_filter.get("Value")
        if not isinstance(value, str) or not value:
            raise ConstraintValidationError(
                f"{path}.Filters[{index}].Value must be a non-empty string"
            )
        if len(value) > MAX_FILTER_VALUE_LENGTH:
            raise ConstraintValidationError(
                f"{path}.Filters[{index}].Value exceeds "
                f"{MAX_FILTER_VALUE_LENGTH} characters"
            )

    for index, subexpression in enumerate(expression.get("SubExpressions", [])):
        validate_search_expression(subexpression, f"{path}.SubExpressions[{index}]")

    for index, nested_filter in enumerate(expression.get("NestedFilters", [])):
        if not isinstance(nested_filter, Mapping):
            raise ConstraintValidationError(
                f"{path}.NestedFilters[{index}] must be an object"
            )
        nested_expression = {"Filters": nested_filter.get("Filters", [])}
        validate_search_expression(
            nested_expression, f"{path}.NestedFilters[{index}]"
        )

    if not has_condition:
        raise ConstraintValidationError(f"{path} must contain at least one condition")


def build_search_expression(hub_name, constraints, catalog_models):
    """Translate confirmed model-selection constraints into a SearchExpression."""
    if hub_name != PUBLIC_HUB_NAME:
        raise ConstraintValidationError(
            "The Search adapter supports SageMakerPublicHub only; "
            "private Hubs must continue using ListHubContents"
        )

    normalized_constraints = normalize_constraints(constraints)
    filters = [
        {"Name": "HubName", "Operator": "Equals", "Value": PUBLIC_HUB_NAME},
        {"Name": "HubContentType", "Operator": "Equals", "Value": "Model"},
    ]
    subexpressions: list[dict] = []

    for key in SUPPORTED_CONSTRAINT_KEYS:
        if key not in normalized_constraints:
            continue
        values = normalized_constraints[key]

        if key in _METADATA_CONSTRAINTS:
            filter_name, spellings = _resolve_metadata_filter(
                key, values, catalog_models
            )
            _append_exact_alternatives(filters, subexpressions, filter_name, spellings)
        elif key in _KEYWORD_CONSTRAINTS:
            tags = _resolve_keyword_tags(key, values, catalog_models)
            _append_exact_alternatives(
                filters, subexpressions, "HubContentSearchKeywords", tags
            )
        elif key == "size":
            raw_sizes = _resolve_size_values(values, catalog_models)
            _append_exact_alternatives(
                filters, subexpressions, _SIZE_METADATA_FILTER, raw_sizes
            )
        elif key in _METADATA_CAPABILITIES or key in _CAPABILITY_TAGS:
            # Capabilities are positive exact values. Absence-based false
            # matching is not enabled until its Search semantics are verified.
            if values != ["true"]:
                raise ConstraintValidationError(
                    f"The Search adapter supports {key}:true only; "
                    "absence-based false matching is not yet verified"
                )
            if key in _METADATA_CAPABILITIES:
                filter_name, capability = _METADATA_CAPABILITIES[key]
                filters.append(
                    {"Name": filter_name, "Operator": "Equals", "Value": capability}
                )
            else:
                _append_exact_alternatives(
                    filters,
                    subexpressions,
                    "HubContentSearchKeywords",
                    [_CAPABILITY_TAGS[key]],
                )
        elif key == "name":
            names = _resolve_model_names(values, catalog_models)
            spelling = (
                _shared_name_spelling(values[0], names) if len(values) == 1 else None
            )
            if spelling is not None:
                filters.append(
                    {
                        "Name": "HubContentName",
                        "Operator": "Contains",
                        "Value": spelling,
                    }
                )
            else:
                # Several requested substrings or inconsistent catalog casing
                # cannot share the service's single case-sensitive Contains.
                # Exact names preserve local case-insensitive matching.
                _append_exact_alternatives(
                    filters, subexpressions, "HubContentName", names
                )

    expression = {"Operator": "And", "Filters": filters}
    if subexpressions:
        expression["SubExpressions"] = subexpressions
    validate_search_expression(expression)
    return expression


def _search_error(error):
    """Convert a ClientError into a stable adapter error."""
    code = error.response.get("Error", {}).get("Code", "Unknown")
    message = error.response.get("Error", {}).get("Message", str(error))
    return SearchServiceError(f"SageMaker Search failed ({code}): {message}")


def search_deployable_models(
    hub_name,
    constraints,
    catalog_models,
    region_name=None,
    sm_client=None,
    check_sdk=True,
):
    """Search the public Hub and return normalized candidate models."""
    expression = build_search_expression(hub_name, constraints, catalog_models)
    if check_sdk:
        validate_sdk_versions()
    try:
        client = sm_client or boto3.client("sagemaker", region_name=region_name)
    except botocore.exceptions.BotoCoreError as error:
        raise SearchServiceError(f"Could not create SageMaker client: {error}") from error

    models = []
    next_token = None
    seen_tokens = set()
    seen_names = set()

    while True:
        request = {
            "Resource": "HubContent",
            "SearchExpression": expression,
            "MaxResults": SEARCH_PAGE_SIZE,
            # Pages of an unsorted Search are not stable: identical repeated
            # runs of one multi-page query return the same record count but
            # different unique names, with some models repeated and others
            # skipped. A sort key makes the page boundaries deterministic. The
            # name is used only for paging; restore_catalog_order() applies the
            # customer-visible OriginalCreationTime order afterwards.
            "SortBy": SEARCH_SORT_BY,
            "SortOrder": "Ascending",
        }
        if next_token:
            request["NextToken"] = next_token

        try:
            # SageMaker PySDK v3 does not expose HubContent Search. Use the
            # version-gated boto3 operation so HubContent records are parsed
            # instead of silently discarded by an older client model.
            response = client.search(**request)
        except botocore.exceptions.ClientError as error:
            raise _search_error(error) from error
        except botocore.exceptions.BotoCoreError as error:
            raise SearchServiceError(f"SageMaker Search failed: {error}") from error

        records = response.get("Results", [])
        if not isinstance(records, list):
            raise SearchResponseError("Search response Results must be a list")
        for index, record in enumerate(records):
            if not isinstance(record, Mapping) or not isinstance(
                record.get("HubContent"), Mapping
            ):
                raise SearchResponseError(
                    f"Search result {index} does not contain a HubContent object"
                )
            model = normalize_hub_content(record["HubContent"])
            # A model repeated across pages means paging was not stable; keep
            # the candidate set a set rather than double-listing it.
            name = model.get("name")
            if isinstance(name, str):
                if name in seen_names:
                    continue
                seen_names.add(name)
            models.append(model)

        next_token = response.get("NextToken")
        if next_token is None or next_token == "":
            break
        if not isinstance(next_token, str):
            raise SearchResponseError("Search response NextToken must be a string")
        if next_token in seen_tokens:
            raise SearchResponseError("Search returned a repeated NextToken")
        seen_tokens.add(next_token)

    return models


def _ordering_summary(models, timestamp_source):
    """Describe timestamp coverage so missing List-only dates stay visible."""
    dated_models = sum(
        model.get("original_creation_time") is not None for model in models
    )
    return OrderingSummary(
        field="OriginalCreationTime",
        timestamp_source=timestamp_source,
        dated_models=dated_models,
        undated_models=len(models) - dated_models,
    )


def restore_catalog_order(
    search_models,
    catalog_models,
    timestamp_source="selection_session_snapshot",
):
    """Attach catalog dates to Search matches and apply current ordering.

    Search ``CreationTime`` identifies the indexed version and can move when
    ``latestSupported`` changes. This join deliberately removes any normalized
    Search timestamp and uses only ListHubContents ``OriginalCreationTime``.
    A Search-only model stays undated and sorts after dated models by name.
    """
    catalog_dates = {
        model.get("name"): model.get("original_creation_time")
        for model in catalog_models
        if isinstance(model.get("name"), str)
        and isinstance(model.get("original_creation_time"), str)
    }
    restored = []
    for model in search_models:
        candidate = dict(model)
        candidate.pop("original_creation_time", None)
        catalog_date = catalog_dates.get(candidate.get("name"))
        if catalog_date is not None:
            candidate["original_creation_time"] = catalog_date
        restored.append(candidate)

    ordered = sort_models_newest_first(restored)
    return ordered, _ordering_summary(ordered, timestamp_source)


def select_public_hub_models(
    hub_name,
    constraints,
    catalog_models,
    region_name=None,
    sm_client=None,
    catalog_source="snapshot",
):
    """Use Search for candidates, with a visible complete local fallback.

    A successful empty Search response is authoritative and does not fall back.
    Only explicit SDK, service, transport, or response failures use the complete
    ListHubContents snapshot. Constraint and snapshot validation errors remain
    visible because falling back would hide a query or workflow defect.
    """
    if catalog_source == "snapshot":
        search_timestamp_source = "selection_session_snapshot"
        fallback_timestamp_source = "list_hub_contents_snapshot"
    elif catalog_source == "live_list":
        search_timestamp_source = fallback_timestamp_source = "live_list"
    else:
        raise ConstraintValidationError(
            f"Unsupported catalog source: {catalog_source!r}"
        )

    try:
        search_models = search_deployable_models(
            hub_name,
            constraints,
            catalog_models,
            region_name=region_name,
            sm_client=sm_client,
        )
    except (UnsupportedSdkError, SearchServiceError, SearchResponseError) as error:
        fallback_models = filter_models(catalog_models, constraints)
        return PublicHubSelection(
            retrieval_backend="list_fallback",
            fallback_reason=FallbackReason(
                type=type(error).__name__,
                message=str(error),
            ),
            ordering=_ordering_summary(
                fallback_models, fallback_timestamp_source
            ),
            warnings=[
                "SageMaker Search was unavailable; used the complete "
                "ListHubContents snapshot and local filtering instead."
            ],
            models=fallback_models,
        )

    ordered_models, ordering = restore_catalog_order(
        search_models,
        catalog_models,
        timestamp_source=search_timestamp_source,
    )
    warnings = []
    if ordering.undated_models:
        warnings.append(
            f"{ordering.undated_models} of {len(ordered_models)} Search results "
            "had no cached OriginalCreationTime and were ordered after dated models."
        )
    return PublicHubSelection(
        retrieval_backend="search",
        ordering=ordering,
        warnings=warnings,
        models=ordered_models,
    )


def _parser():
    parser = argparse.ArgumentParser(
        description="Search SageMakerPublicHub models with confirmed exact constraints."
    )
    parser.add_argument("hub_name", help="Must be SageMakerPublicHub")
    parser.add_argument("constraints", nargs="*", help="Repeatable key:value constraints")
    parser.add_argument("--region", dest="region_name", help="AWS region override")
    parser.add_argument(
        "--snapshot-file",
        help="Selection-session catalog snapshot created during --list-values",
    )
    return parser


def parse_cli_args(argv=None):
    """Parse options and repeatable constraints in any documented order."""
    parser = _parser()
    # Python 3.10 does not reliably resume a ``nargs='*'`` positional after an
    # optional argument with parse_args(). parse_intermixed_args() supports the
    # documented option/constraint order on every runtime we ship.
    return parser.parse_intermixed_args(argv)


def _load_catalog_for_selection(args):
    """Load a session snapshot, or preserve direct CLI compatibility."""
    if args.snapshot_file:
        snapshot = load_catalog_snapshot(
            args.snapshot_file,
            expected_hub=args.hub_name,
            expected_region=args.region_name,
        )
        return SelectionCatalog(
            models=snapshot["catalog_models"],
            region_name=snapshot["region"],
            source="snapshot",
        )

    try:
        models = get_deployable_models(args.hub_name, args.region_name)
    except botocore.exceptions.ClientError as error:
        code = error.response.get("Error", {}).get("Code", "Unknown")
        message = error.response.get("Error", {}).get("Message", str(error))
        raise SearchServiceError(
            f"Public-Hub catalog discovery failed ({code}): {message}"
        ) from error
    except botocore.exceptions.BotoCoreError as error:
        raise SearchServiceError(
            f"Public-Hub catalog discovery failed: {error}"
        ) from error
    return SelectionCatalog(
        models=models,
        region_name=args.region_name,
        source="live_list",
    )


def main(argv=None):
    args = parse_cli_args(argv)
    try:
        constraints = parse_constraints(args.constraints)
        if args.hub_name != PUBLIC_HUB_NAME:
            raise ConstraintValidationError(
                "The public-Hub Search adapter supports SageMakerPublicHub only; "
                "private Hubs must continue using ListHubContents"
            )

        catalog = _load_catalog_for_selection(args)
        selection = select_public_hub_models(
            args.hub_name,
            constraints,
            catalog.models,
            region_name=catalog.region_name,
            catalog_source=catalog.source,
        )
        selection_output = selection.to_output_dict()
        print(
            json.dumps(
                {
                    "total_models": len(catalog.models),
                    "filters_applied": constraints,
                    "matched": len(selection.models),
                    "catalog_source": catalog.source,
                    **selection_output,
                }
            )
        )
        return 0
    except (SearchAdapterError, CatalogSnapshotError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
