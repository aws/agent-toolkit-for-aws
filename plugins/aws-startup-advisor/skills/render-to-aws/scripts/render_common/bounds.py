"""Strict and bounded YAML loading for Render Blueprints."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import yaml

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 40
MAX_NODES = 50_000
MAX_CONTAINER_ITEMS = 10_000
MAX_SCALAR_BYTES = 128 * 1024
MAX_RESOURCES = 1_000


class BlueprintInputError(ValueError):
    pass


class StrictSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise BlueprintInputError("unhashable_mapping_key") from exc
        if duplicate:
            raise BlueprintInputError("duplicate_key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_bounded_yaml(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_SOURCE_BYTES:
        raise BlueprintInputError("source_too_large")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BlueprintInputError("invalid_utf8") from exc

    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.events.AliasEvent):
                raise BlueprintInputError("yaml_alias_forbidden")
            if getattr(event, "anchor", None) is not None:
                raise BlueprintInputError("yaml_anchor_forbidden")
            tag = getattr(event, "tag", None)
            if tag is not None and not tag.startswith("tag:yaml.org,2002:"):
                raise BlueprintInputError("yaml_custom_tag_forbidden")
        loaded = yaml.load(text, Loader=StrictSafeLoader)  # noqa: S506 -- SafeLoader subclass rejects duplicates
    except BlueprintInputError:
        raise
    except yaml.YAMLError as exc:
        raise BlueprintInputError("invalid_yaml") from exc

    if not isinstance(loaded, dict):
        raise BlueprintInputError("root_not_mapping")
    _validate_bounds(loaded)
    return loaded


def _validate_bounds(root: Any) -> None:
    node_count = 0
    resource_count = 0
    stack: list[tuple[Any, int, str]] = [(root, 0, "")]
    while stack:
        value, depth, parent_key = stack.pop()
        node_count += 1
        if node_count > MAX_NODES:
            raise BlueprintInputError("node_limit_exceeded")
        if depth > MAX_DEPTH:
            raise BlueprintInputError("depth_limit_exceeded")
        if isinstance(value, Mapping):
            if len(value) > MAX_CONTAINER_ITEMS:
                raise BlueprintInputError("container_limit_exceeded")
            for key, item in value.items():
                if not isinstance(key, str):
                    raise BlueprintInputError("non_string_key")
                if len(key.encode("utf-8")) > MAX_SCALAR_BYTES:
                    raise BlueprintInputError("scalar_limit_exceeded")
                if key in {"services", "databases", "envVarGroups", "buildSources"} and isinstance(item, list):
                    resource_count += len(item)
                stack.append((item, depth + 1, key))
        elif isinstance(value, list):
            if len(value) > MAX_CONTAINER_ITEMS:
                raise BlueprintInputError("container_limit_exceeded")
            stack.extend((item, depth + 1, parent_key) for item in value)
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_SCALAR_BYTES:
                raise BlueprintInputError("scalar_limit_exceeded")
        elif isinstance(value, float) and not math.isfinite(value):
            raise BlueprintInputError("non_finite_number")
    if resource_count > MAX_RESOURCES:
        raise BlueprintInputError("resource_limit_exceeded")
