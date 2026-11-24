"""Target schemas -> policy-context targets (no AWS, no network).

Reads MCP tool schemas, OpenAPI 3 documents and Smithy JSON AST models, projects the
bundled Bedrock Runtime default schema for inference targets, and merges the parts that
describe the same target.  Every parser returns the same shape::

    {"target": str, "protocol": "MCP" | "HTTP", "kind": str,
     "actions": {name: {"input_schema", "output_schema", "sources", "method", "path",
                        "description"}},
     "gaps": [{"target", "action", "field", "reason", "detail"?}],
     "coverage_notes": [...]   # only when there is something to say}

OpenAPI 3 (JSON or YAML) and Smithy JSON AST files are read with fixed naming,
input/output rules, gap semantics (``unresolved_reference``, ``unsupported_schema``,
``skipped_operation``, ``conflicting_declarations``) and nesting bound
(``MAX_SCHEMA_DEPTH``, which rejects the file).  YAML needs the optional ``PyYAML==6.0.3``,
imported lazily.  The inference default schema is projected with its own rules instead
(field-specific gaps).

Reads no environment variables.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Hashable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from acp_common import SkillError, missing_dependency

MAX_SCHEMA_FILE_BYTES = 10 * 1024 * 1024
MAX_SCHEMA_DEPTH = 32
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
HIDDEN_PARAMETER = "x-amz-agent-hidden-parameter"
RUNTIME_ROUTE = "POST:/invocations"

SOURCE_TOOLS_LIST = "tools_list"
SOURCE_DECLARATION = "target_declaration"
SOURCE_FILE = "file"
SOURCE_DEFAULT = "service_default"

_INFERENCE_ASSET = Path(__file__).resolve().parent.parent / "assets" / "inference-default.json"


# --------------------------------------------------------------------------- helpers


def _gap(
    target: str, action: str | None, field: str | None, reason: str, detail: str | None = None
) -> dict[str, Any]:
    gap: dict[str, Any] = {"target": target, "action": action, "field": field, "reason": reason}
    if detail:
        gap["detail"] = detail
    return gap


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for gap in gaps:
        key = json.dumps(gap, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(gap)
    return out


def _action(
    input_schema: Any,
    output_schema: Any,
    sources: list[str],
    *,
    method: str | None = None,
    path: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "input_schema": input_schema if isinstance(input_schema, dict) else None,
        "output_schema": output_schema if isinstance(output_schema, dict) else None,
        "sources": list(sources),
        "method": method,
        "path": path,
        "description": description if isinstance(description, str) and description else None,
    }


def _part(
    target: str, protocol: str, kind: str, actions: dict, gaps: list, notes: list | None = None
) -> dict[str, Any]:
    part: dict[str, Any] = {
        "target": target,
        "protocol": protocol,
        "kind": kind,
        "actions": actions,
        "gaps": _dedupe_gaps(gaps),
    }
    if notes:
        part["coverage_notes"] = notes
    return part


def _check_target_name(target: Any) -> str:
    if not isinstance(target, str) or not target.strip():
        raise SkillError("invalid_input", "the target name must be a non-empty string")
    if "___" in target or len(target) > 100 or any(ord(c) < 32 for c in target):
        raise SkillError(
            "invalid_input",
            "the target name must be at most 100 characters, without control characters or '___'",
            target=target[:100],
        )
    return target


def exceeds_depth(schema: Any) -> bool:
    """True when a JSON Schema nests deeper than ``MAX_SCHEMA_DEPTH`` levels."""
    return _deeper_than_limit(schema, 1)


_NAMED_CHILDREN = ("properties", "patternProperties", "$defs", "definitions")
_SINGLE_CHILDREN = (
    "items",
    "additionalProperties",
    "not",
    "if",
    "then",
    "else",
    "contains",
)
_LIST_CHILDREN = ("oneOf", "anyOf", "allOf", "prefixItems", "items")


def _deeper_than_limit(schema: Any, depth: int) -> bool:
    if not isinstance(schema, dict):
        return False
    for key, value in schema.items():
        if key in _NAMED_CHILDREN and isinstance(value, dict):
            children = list(value.values())
        elif key in _SINGLE_CHILDREN and isinstance(value, dict):
            children = [value]
        elif key in _LIST_CHILDREN and isinstance(value, list):
            children = list(value)
        else:
            continue
        for child in children:
            if isinstance(child, dict) and (
                depth >= MAX_SCHEMA_DEPTH or _deeper_than_limit(child, depth + 1)
            ):
                return True
    return False


# --------------------------------------------------------------------------- MCP tools


def parse_mcp_tools(
    tools: Any,
    target: str,
    *,
    strip_prefix: bool,
    source: str | None = None,
    kind: str = "mcp",
) -> dict[str, Any]:
    """Tools (``tools/list`` ``tools`` array) -> one MCP target.

    ``strip_prefix=True`` is for a Gateway ``tools/list`` result, whose names carry the
    ``<target>___`` prefix; the default ``sources`` tag is then ``tools_list`` (otherwise
    ``target_declaration``).
    """
    _check_target_name(target)
    tag = source or (SOURCE_TOOLS_LIST if strip_prefix else SOURCE_DECLARATION)
    if isinstance(tools, dict):
        result = tools.get("result")
        tools = tools.get("tools", result.get("tools") if isinstance(result, dict) else None)
    if not isinstance(tools, list):
        raise SkillError(
            "invalid_input", "expected an array of MCP tools or an object with a 'tools' array"
        )
    actions: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    prefix = f"{target}___"
    for index, tool in enumerate(tools):
        raw = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(raw, str) or not raw:
            gaps.append(_gap(target, None, None, "skipped_operation", f"tool #{index} has no name"))
            continue
        name = raw[len(prefix) :] if strip_prefix and raw.startswith(prefix) else raw
        if not name:
            gaps.append(
                _gap(target, None, None, "skipped_operation", f"tool #{index} has an empty name")
            )
            continue
        schemas = {}
        for key, field in (("inputSchema", "input"), ("outputSchema", "output")):
            value = tool.get(key)
            if value is not None and not isinstance(value, dict):
                gaps.append(_gap(target, name, field, "invalid_schema", f"{key} is not an object"))
                value = None
            if value is not None and exceeds_depth(value):
                gaps.append(
                    _gap(
                        target,
                        name,
                        field,
                        "unsupported_schema",
                        f"{key} is nested deeper than {MAX_SCHEMA_DEPTH} levels",
                    )
                )
                value = None
            schemas[field] = value
        new = _action(
            schemas["input"], schemas["output"], [tag], description=tool.get("description")
        )
        if name in actions:
            _merge_action(target, name, actions[name], new, gaps)
        else:
            actions[name] = new
    return _part(target, "MCP", kind, actions, gaps)


# ------------------------------------------------- wire-schema projection (inference)

# The bundled Bedrock Runtime default schema is projected to the service wire schema
# (field-specific gaps).  Customer OpenAPI documents use the reader further below.


def _context_path(field: str, pointer: str) -> str:
    """Map a schema JSON pointer to the Cedar context path of the affected value."""
    out = "input" if field == "input" else "output"
    segs = [s for s in pointer.split("/") if s]
    i = 0
    if segs and segs[0] == "requestBody" and field == "input":
        i = 1
        if len(segs) > 1 and segs[1] == "items":
            out += ".items"
    elif segs and segs[0] == "responses":
        i = 2
    elif segs and segs[0] == "parameters":
        return out + (f".{segs[1]}" if len(segs) > 1 else "")
    while i < len(segs):
        seg = segs[i]
        if seg == "properties" and i + 1 < len(segs):
            out += "." + segs[i + 1]
            i += 1
        elif seg == "items":
            out += "[]"
        elif seg in ("oneOf", "anyOf", "allOf"):
            i += 1
        i += 1
    return out


def _is_null(node: dict) -> bool:
    return node.get("type") == "null"


def _merge_all_of(base: dict, branch: dict) -> list[str]:
    """Merge an ``allOf`` branch into ``base``; returns the keys that conflict."""
    conflicts: list[str] = []
    for key, value in branch.items():
        if key not in base:
            base[key] = value
        elif key == "properties" and isinstance(base[key], dict) and isinstance(value, dict):
            for name, prop in value.items():
                if name not in base[key]:
                    base[key][name] = prop
                elif base[key][name] != prop:
                    conflicts.append(f"properties/{name}")
        elif key == "required" and isinstance(base[key], list) and isinstance(value, list):
            base[key] = base[key] + [r for r in value if r not in base[key]]
        elif key in ("description", "title", "example", "examples"):
            continue
        elif base[key] != value:
            conflicts.append(key)
    return conflicts


class _Walker:
    """Resolves local ``$ref`` s and projects schema nodes to the service wire schema."""

    def __init__(self, doc: dict, target: str, gaps: list[dict[str, Any]]) -> None:
        self.doc = doc
        self.target = target
        self.gaps = gaps
        self.action: str | None = None
        self.field = "input"

    def gap(self, pointer: str, reason: str) -> None:
        self.gaps.append(
            _gap(self.target, self.action, _context_path(self.field, pointer), reason, pointer)
        )

    def deref(self, value: Any, path: str, stack: tuple[str, ...]) -> tuple[dict, tuple] | None:
        if not isinstance(value, dict):
            self.gap(path, "invalid_schema")
            return None
        if "$ref" not in value:
            return dict(value), stack
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            self.gap(path, "remote_schema_reference")
            return None
        if ref in stack:
            self.gap(path, "cyclic_schema_reference")
            return None
        node: Any = self.doc
        for part in ref[2:].split("/"):
            key = unquote(part).replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and key in node:
                node = node[key]
            elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
                node = node[int(key)]
            else:
                self.gap(path, "unresolved_schema_reference")
                return None
        if not isinstance(node, dict):
            self.gap(path, "unresolved_schema_reference")
            return None
        merged = dict(node)
        merged.update({k: v for k, v in value.items() if k != "$ref"})
        return self.deref(merged, path, stack + (ref,))

    def resolve(self, value: Any, path: str, stack: tuple[str, ...]) -> tuple[dict, tuple] | None:
        """Follow ``$ref`` chains and flatten ``allOf`` into one node."""
        got = self.deref(value, path, stack)
        if got is None:
            return None
        node, stack = got
        branches = node.pop("allOf", None)
        if isinstance(branches, list):
            for i, branch in enumerate(branches):
                inner = self.resolve(branch, f"{path}/allOf/{i}", stack)
                if inner is None:
                    return None
                conflicts = _merge_all_of(node, inner[0])
                if conflicts:
                    for conflict in conflicts:
                        self.gap(f"{path}/{conflict}", "allof_conflict")
                    return None
        return node, stack

    def schema(self, value: Any, path: str, stack: tuple[str, ...] = ()) -> dict | None:
        got = self.resolve(value, path, stack)
        return None if got is None else self.wire(got[0], path, got[1])

    def wire(self, node: dict, path: str, stack: tuple[str, ...]) -> dict | None:
        for key in ("oneOf", "anyOf"):
            branches = node.get(key)
            if not isinstance(branches, list):
                continue
            live = []
            for i, branch in enumerate(branches):
                p = f"{path}/{key}/{i}"
                got = self.resolve(branch, p, stack)
                if got is None:
                    return None
                if not _is_null(got[0]):
                    live.append((p, got[0], got[1]))
            other = "anyOf" if key == "oneOf" else "oneOf"
            if len(live) == 1 and other not in node:
                p, resolved, st = live[0]
                if "description" in node and "description" not in resolved:
                    resolved["description"] = node["description"]
                return self.wire(resolved, p, st)
            self.gap(path, "unsupported_oneof" if key == "oneOf" else "unsupported_anyof")
            return None
        kind = self._kind(node, path)
        if kind is None:
            return None
        out: dict[str, Any] = {"type": kind}
        for key in ("description", "format", "enum"):
            if key in node:
                out[key] = node[key]
        if "items" in node:
            items = self.schema(node["items"], f"{path}/items", stack)
            if items is None:
                self.gap(path, "unsupported_array_items")
                return None
            out["items"] = items
        props = node.get("properties")
        if isinstance(props, dict):
            kept: dict[str, Any] = {}
            for name, prop in props.items():
                p = f"{path}/properties/{name}"
                got = self.resolve(prop, p, stack)
                if got is None or got[0].get(HIDDEN_PARAMETER) is True:
                    continue
                wired = self.wire(got[0], p, got[1])
                if wired is not None:
                    kept[name] = wired
            required = node.get("required")
            required = (
                [r for r in required if isinstance(r, str)] if isinstance(required, list) else []
            )
            out["properties"] = kept
            kept_required = list(dict.fromkeys(r for r in required if r in kept))
            if kept_required:
                out["required"] = kept_required
        elif kind == "object":
            out["properties"] = {}
        return out

    def _kind(self, node: dict, path: str) -> str | None:
        declared = node.get("type")
        kind = None
        if isinstance(declared, str) and declared != "null":
            kind = declared
        elif isinstance(declared, list):
            live = sorted({t for t in declared if isinstance(t, str) and t != "null"})
            if len(live) > 1:
                self.gap(path, "unsupported_type_union")
                return None
            kind = live[0] if live else None
        if kind is None and "properties" in node:
            kind = "object"
        if kind is None and "items" in node:
            kind = "array"
        if kind is None:
            self.gap(path, "untyped_schema")
        return kind


def _path_template_names(path: str) -> list[str]:
    return [m for m in re.findall(r"\{([^{}]+)\}", path) if m]


def _first_content_schema(content: Any) -> Any:
    if not isinstance(content, dict) or not content:
        return None
    chosen = content.get("application/json") or next(iter(content.values()))
    return chosen.get("schema") if isinstance(chosen, dict) else None


def _input_wrapper(raw: dict | None) -> tuple[dict, list[str]]:
    """Object body spreads its properties, arrays become ``items``, scalars ``value``."""
    if not raw:
        return {}, []
    kind = raw.get("type")
    if kind == "object":
        return dict(raw.get("properties", {})), list(raw.get("required", []))
    if kind == "array":
        return {"items": raw}, []
    return {"value": raw}, ["value"]


def _inference_actions(
    doc: dict, target: str, paths: dict, source: str, gaps: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    walker = _Walker(doc, target, gaps)
    actions: dict[str, dict[str, Any]] = {}
    for path, raw_item in paths.items():
        walker.action = None
        walker.field = "input"
        got = walker.deref(raw_item, path, ())
        if got is None:
            gaps.append(_gap(target, None, None, "skipped_operation", f"path item {path}"))
            continue
        item = got[0]
        for method, raw_op in item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            name = f"{method.upper()}:{path}"
            walker.action = name
            walker.field = "input"
            got_op = walker.deref(raw_op, f"/{method}", ())
            if got_op is None:
                continue
            op = got_op[0]
            input_schema = _inference_input(walker, doc, item, op, path)
            walker.field = "output"
            output_schema = _inference_output(walker, op)
            actions[name] = _action(
                input_schema,
                output_schema,
                [source],
                method=method.upper(),
                path=path,
                description=op.get("summary") or op.get("description"),
            )
    return actions


def _inference_input(walker: _Walker, doc: dict, item: dict, op: dict, path: str) -> dict:
    props: dict[str, Any] = {}
    required: list[str] = []
    servers = op.get("servers") or item.get("servers") or doc.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        variables = servers[0].get("variables")
        for key in variables if isinstance(variables, dict) else []:
            props[key] = {"type": "string"}
            required.append(key)
    params: dict[tuple[str, str], dict] = {}
    declared = list(item.get("parameters") or []) + list(op.get("parameters") or [])
    for raw in declared:
        resolved = walker.deref(raw, "/parameters", ())
        if resolved is None:
            continue
        p = resolved[0]
        params[(str(p.get("in", "")), str(p.get("name", "")))] = p
    for bucket in ("query", "header", "path"):
        for (location, name), p in params.items():
            if location != bucket or not name:
                continue
            if bucket == "path":
                schema: dict | None = {"type": "string"}
            elif "schema" in p:
                schema = walker.schema(p["schema"], f"/parameters/{name}")
            else:
                walker.gap(f"/parameters/{name}", "parameter_without_schema")
                schema = None
            if schema is None:
                continue
            props[name] = schema
            if p.get("required") is True or bucket == "path":
                required.append(name)
    body = None
    request_body = op.get("requestBody")
    if request_body is not None:
        resolved = walker.deref(request_body, "/requestBody", ())
        if resolved is not None:
            raw_body = _first_content_schema(resolved[0].get("content"))
            if raw_body is not None:
                body = walker.schema(raw_body, "/requestBody")
    body_props, body_required = _input_wrapper(body)
    props.update(body_props)
    required.extend(body_required)
    for name in _path_template_names(path):
        props[name] = {"type": "string"}
        required.append(name)
    required = list(dict.fromkeys(r for r in required if r in props))
    schema_out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema_out["required"] = required
    return schema_out


def _inference_output(walker: _Walker, op: dict) -> dict | None:
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None
    codes = sorted(str(c) for c in responses if str(c).startswith("2"))
    if not codes:
        return None
    key = next(k for k in responses if str(k) == codes[0])
    pointer = f"/responses/{key}"
    resolved = walker.deref(responses[key], pointer, ())
    if resolved is None:
        return None
    raw = _first_content_schema(resolved[0].get("content"))
    return None if raw is None else walker.schema(raw, pointer)


# --------------------------------------------------------------------------- OpenAPI


def parse_openapi(
    doc: Any,
    target: str,
    *,
    protocol: str = "HTTP",
    source: str = SOURCE_DECLARATION,
    label: str = "schema",
) -> dict[str, Any]:
    """OpenAPI 3 document -> one target.

    * ``protocol="MCP"`` (an MCP OpenAPI target): one tool per ``operationId``; the input
      merges path, query and header parameters with the request body.  An operation without
      ``operationId`` is a ``skipped_operation`` gap.
    * ``protocol="HTTP"``: one ``METHOD:/path`` action per operation; the input is the
      request body plus the path template's parameters, which are always required strings.

    Output is the first 2xx response.  Local ``#/...`` references are resolved; any other
    reference leaves its schema open (``{}``) and is an ``unresolved_reference`` gap, as are
    cyclic references.  ``oneOf``/``anyOf``/``allOf`` in a request body is an
    ``unsupported_schema`` gap.  A schema nested deeper than ``MAX_SCHEMA_DEPTH`` raises.
    """
    _check_target_name(target)
    proto = protocol.upper()
    version = doc.get("openapi") if isinstance(doc, dict) else None
    if not (isinstance(version, str) and version.startswith("3")):
        raise SkillError("invalid_input", f"{label}: is not an OpenAPI 3 document")
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        raise SkillError("invalid_input", f"{label}: has no `paths` object")
    builder = _OpenApiBuilder(doc, target, proto, source, label)
    try:
        builder.paths(paths)
    except RecursionError:
        raise SkillError("invalid_input", f"{label}: is nested too deeply") from None
    return _part(target, proto, "openapi", builder.actions, builder.gaps)


_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_COMPOSITION = ("oneOf", "anyOf", "allOf")
_MAX_REF_NESTING = 2 * MAX_SCHEMA_DEPTH
_MISSING = object()


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _unqualify(target: str, name: str) -> str:
    prefix = f"{target}___"
    return name.removeprefix(prefix)


def _too_deep(label: str, target: str, action: str, field: str) -> SkillError:
    return SkillError(
        "invalid_input",
        f"{label}: {field} of {target}___{action} is nested deeper than {MAX_SCHEMA_DEPTH} levels",
    )


def _json_pointer(doc: Any, pointer: str) -> Any:
    """RFC 6901 lookup (``pointer`` starts with ``/``); ``_MISSING`` when absent."""
    node = doc
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif (
            isinstance(node, list)
            and key.isascii()
            and key.isdigit()
            and (key == "0" or not key.startswith("0"))
            and int(key) < len(node)
        ):
            node = node[int(key)]
        else:
            return _MISSING
    return node


class _Resolver:
    """Inlines local ``$ref`` s, bounding schema depth and reference nesting."""

    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self.unresolved: list[str] = []
        self.too_deep = False
        self.root_level = 1

    def resolve(self, value: Any, level: int) -> Any:
        self.root_level = level
        return self.walk(value, [], 0)

    def walk(self, value: Any, stack: list[str], depth: int) -> Any:
        if isinstance(value, list):
            return [self.walk(item, stack, depth) for item in value]
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                return self.follow(reference, value, stack, depth)
            return {key: self.entry(key, item, stack, depth) for key, item in value.items()}
        return value

    def entry(self, key: str, item: Any, stack: list[str], depth: int) -> Any:
        if depth == 0:
            if key == "schema":
                return self.child(item, stack, self.root_level)
            return self.walk(item, stack, 0)
        if key in ("properties", "patternProperties", "$defs", "definitions") and isinstance(
            item, dict
        ):
            return {name: self.child(schema, stack, depth + 1) for name, schema in item.items()}
        if key in (
            "items",
            "additionalProperties",
            "not",
            "if",
            "then",
            "else",
            "contains",
        ) and isinstance(item, dict):
            return self.child(item, stack, depth + 1)
        if key in ("oneOf", "anyOf", "allOf", "prefixItems", "items") and isinstance(item, list):
            return [self.child(schema, stack, depth + 1) for schema in item]
        return self.walk(item, stack, depth)

    def child(self, schema: Any, stack: list[str], depth: int) -> Any:
        if self.too_deep:
            return {}
        if depth > MAX_SCHEMA_DEPTH:
            if isinstance(schema, dict):
                self.too_deep = True
                return {}
            return schema
        return self.walk(schema, stack, depth)

    def follow(self, reference: str, node: dict, stack: list[str], depth: int) -> Any:
        if len(stack) >= _MAX_REF_NESTING:
            self.too_deep = True
            return {}
        target = self.target(reference, stack)
        if target is not _MISSING:
            stack.append(reference)
            resolved = self.walk(target, stack, depth)
            stack.pop()
        else:
            if reference not in self.unresolved:
                self.unresolved.append(reference)
            resolved = {}
        if isinstance(resolved, dict):
            for key, item in node.items():
                if key != "$ref":
                    resolved[key] = self.entry(key, item, stack, depth)
        return resolved

    def target(self, reference: str, stack: list[str]) -> Any:
        if not reference.startswith("#"):
            return _MISSING
        pointer = reference[1:]
        if not pointer.startswith("/") or reference in stack:
            return _MISSING
        return _json_pointer(self.doc, pointer)

    def path_item(self, raw: Any) -> tuple[Any, str | None]:
        """Follow a path item's ``$ref`` chain -> ``(item, None)`` or ``(None, bad_ref)``."""
        seen: list[str] = []
        current = raw
        while isinstance(_get(current, "$ref"), str):
            reference = current["$ref"]
            if len(seen) >= _MAX_REF_NESTING or reference in seen:
                return None, reference
            seen.append(reference)
            current = self.target(reference, [])
            if current is _MISSING:
                return None, reference
        return current, None


class _Body:
    def __init__(self, schema: Any, required: bool) -> None:
        self.schema = schema
        self.required = required


def _media_schema(content: Any) -> Any:
    if not isinstance(content, dict):
        return None
    if "application/json" in content:
        chosen = content["application/json"]
    else:
        chosen = next(iter(content.values()), None)
    return _get(chosen, "schema")


def _is_object_like(schema: Any) -> bool:
    return isinstance(schema, dict) and ("type" not in schema or schema["type"] == "object")


def _note_composition(schema: dict, unsupported: list[str]) -> None:
    for keyword in _COMPOSITION:
        if keyword in schema:
            unsupported.append(f"{keyword} in request body")


def _mcp_input(
    parameters: dict[tuple[str, str], Any], body: _Body | None, unsupported: list[str]
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: set[str] = set()
    for (location, name), parameter in sorted(parameters.items()):
        if location not in ("path", "query", "header"):
            continue
        properties[name] = _get(parameter, "schema") if "schema" in parameter else {}
        if location == "path" or parameter.get("required") is True:
            required.add(name)
    if body is not None:
        if _is_object_like(body.schema):
            _note_composition(body.schema, unsupported)
            fields = body.schema.get("properties")
            if isinstance(fields, dict):
                properties.update(fields)
            names = body.schema.get("required")
            if isinstance(names, list):
                required.update(n for n in names if isinstance(n, str))
        else:
            properties["body"] = body.schema
            if body.required:
                required.add("body")
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = sorted(required)
    return schema


def _template_params(template: str) -> list[str]:
    names: list[str] = []
    for fragment in template.split("{")[1:]:
        name, found, _ = fragment.partition("}")
        if found and name and name not in names:
            names.append(name)
    return names


def _http_input(template: str, body: _Body | None, unsupported: list[str]) -> Any:
    names = _template_params(template)
    if body is not None and _is_object_like(body.schema):
        _note_composition(body.schema, unsupported)
        base: Any = body.schema
    elif body is not None and not names:
        return body.schema
    elif body is not None:
        unsupported.append("non-object request body")
        base = {}
    else:
        base = None
    if not names:
        return base
    schema = base if base is not None else {}
    schema.setdefault("type", "object")
    if not isinstance(schema.get("properties"), dict):
        schema["properties"] = {}
    for name in names:
        schema["properties"][name] = {"type": "string"}
    if not isinstance(schema.get("required"), list):
        schema["required"] = []
    for name in names:
        if name not in schema["required"]:
            schema["required"].append(name)
    return schema


class _OpenApiBuilder:
    def __init__(self, doc: Any, target: str, protocol: str, source: str, label: str) -> None:
        self.target = target
        self.protocol = protocol
        self.source = source
        self.label = label
        self.resolver = _Resolver(doc)
        self.actions: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, Any]] = []

    def gap(self, action: str | None, reason: str, detail: str) -> None:
        self.gaps.append(_gap(self.target, action, None, reason, detail))

    def paths(self, paths: dict) -> None:
        for template, raw in paths.items():
            item, bad = self.resolver.path_item(raw)
            if bad is not None:
                self.gap(None, "unresolved_reference", bad)
                continue
            for method in _METHODS:
                if isinstance(item, dict) and method in item:
                    self.operation(template, method, item, item[method])

    def operation(self, template: str, method: str, item: dict, operation: Any) -> None:
        method = method.upper()
        skipped = f"{method} {template}"
        if not isinstance(operation, dict):
            self.gap(None, "skipped_operation", skipped)
            return
        if self.protocol == "HTTP":
            name = f"{method}:{template}"
        else:
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                self.gap(None, "skipped_operation", skipped)
                return
            name = _unqualify(self.target, operation_id)
        body = self.body(operation)
        unsupported: list[str] = []
        if self.protocol == "HTTP":
            input_schema = _http_input(template, body, unsupported)
        else:
            input_schema = _mcp_input(self.parameters(item, operation), body, unsupported)
        self.check_depth(name, "input")
        output_schema = self.output(operation)
        self.check_depth(name, "output")
        unresolved, self.resolver.unresolved = self.resolver.unresolved, []
        for reference in unresolved:
            self.gap(name, "unresolved_reference", reference)
        for detail in unsupported:
            self.gap(name, "unsupported_schema", detail)
        new = _action(
            input_schema,
            output_schema,
            [self.source],
            method=method,
            path=template,
            description=operation.get("summary") or operation.get("description"),
        )
        if name in self.actions:
            _merge_action(self.target, name, self.actions[name], new, self.gaps)
        else:
            self.actions[name] = new

    def check_depth(self, action: str, field: str) -> None:
        if self.resolver.too_deep:
            self.resolver.too_deep = False
            raise _too_deep(self.label, self.target, action, field)

    def parameters(self, item: dict, operation: dict) -> dict[tuple[str, str], Any]:
        merged: dict[tuple[str, str], Any] = {}
        for source in (item.get("parameters"), operation.get("parameters")):
            if source is None:
                continue
            resolved = self.resolver.resolve(source, 2)
            for parameter in resolved if isinstance(resolved, list) else []:
                location, name = _get(parameter, "in"), _get(parameter, "name")
                if isinstance(location, str) and isinstance(name, str):
                    merged[(location, name)] = parameter
        return merged

    def body(self, operation: dict) -> _Body | None:
        if "requestBody" not in operation:
            return None
        request = self.resolver.resolve(operation["requestBody"], 1)
        content = _get(request, "content")
        schema = _media_schema(content)
        if schema is None:
            return None
        return _Body(schema, _get(request, "required") is True)

    def output(self, operation: dict) -> Any:
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return None
        codes = [code for code in responses if code.startswith("2")]
        if not codes:
            return None
        response = self.resolver.resolve(responses[min(codes)], 1)
        return _media_schema(_get(response, "content"))


# --------------------------------------------------------------------------- Smithy

_DOCUMENTATION = "smithy.api#documentation"
_UNIT = "smithy.api#Unit"
_SMITHY_SCALARS: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "blob": {"type": "string"},
    "timestamp": {"type": "string"},
    "boolean": {"type": "boolean"},
    "byte": {"type": "integer"},
    "short": {"type": "integer"},
    "integer": {"type": "integer"},
    "long": {"type": "integer"},
    "bigInteger": {"type": "integer"},
    "intEnum": {"type": "integer"},
    "float": {"type": "number"},
    "double": {"type": "number"},
    "bigDecimal": {"type": "number"},
    "document": {},
}
_PRELUDE_KINDS = {
    "String": "string",
    "Blob": "blob",
    "Boolean": "boolean",
    "Byte": "byte",
    "Short": "short",
    "Integer": "integer",
    "Long": "long",
    "Float": "float",
    "Double": "double",
    "BigInteger": "bigInteger",
    "BigDecimal": "bigDecimal",
    "Timestamp": "timestamp",
    "Document": "document",
}
_SERVICE_CHILDREN = (
    "operations",
    "collectionOperations",
    "create",
    "put",
    "read",
    "update",
    "delete",
    "list",
)


def _shape_type(shape: Any) -> str | None:
    kind = _get(shape, "type")
    return kind if isinstance(kind, str) else None


def _shape_target(shape: Any, key: str) -> str | None:
    target = _get(_get(shape, key), "target")
    return target if isinstance(target, str) else None


def _shape_targets(shape: Any, key: str) -> list[str]:
    value = _get(shape, key)
    if isinstance(value, list):
        items = value
    elif value is None:
        return []
    else:
        items = [value]
    return [t for t in (_get(item, "target") for item in items) if isinstance(t, str)]


def _members_of(shape: Any) -> list[tuple[str, Any]]:
    members = _get(shape, "members")
    return list(members.items()) if isinstance(members, dict) else []


def _traits(shape: Any) -> dict:
    traits = _get(shape, "traits")
    return traits if isinstance(traits, dict) else {}


def _documentation(shape: Any) -> str | None:
    text = _traits(shape).get(_DOCUMENTATION)
    return text if isinstance(text, str) else None


def _smithy_prelude(shape_id: str) -> dict[str, Any] | None:
    name = shape_id.removeprefix("smithy.api#") if shape_id.startswith("smithy.api#") else None
    if name is None:
        return None
    name = name.removeprefix("Primitive")
    if name == "Unit":
        return {"type": "object", "properties": {}}
    kind = _PRELUDE_KINDS.get(name)
    return dict(_SMITHY_SCALARS[kind]) if kind else None


class _SmithyWalker:
    def __init__(self, shapes: dict, target: str) -> None:
        self.shapes = shapes
        self.target = target
        self.action: str | None = None
        self.stack: list[str] = []
        self.too_deep = False
        self.gaps: list[dict[str, Any]] = []

    def gap(self, reason: str, detail: str) -> None:
        gap = _gap(self.target, self.action, None, reason, detail)
        if gap not in self.gaps:
            self.gaps.append(gap)

    def operations(self) -> dict[str, Any]:
        services = [sid for sid in self.shapes if _shape_type(self.shapes[sid]) == "service"]
        if not services:
            return {
                sid: shape
                for sid, shape in sorted(self.shapes.items())
                if _shape_type(shape) == "operation"
            }
        operations: dict[str, Any] = {}
        seen: set[str] = set()
        for sid in sorted(services):
            self.collect(sid, "service", operations, seen)
        return dict(sorted(operations.items()))

    def collect(
        self, shape_id: str, expected: str, operations: dict[str, Any], seen: set[str]
    ) -> None:
        if shape_id not in self.shapes:
            self.gap("unresolved_reference", shape_id)
            return
        shape = self.shapes[shape_id]
        kind = _shape_type(shape)
        if kind is not None and kind != expected:
            self.gap("skipped_operation", f"{shape_id} is a {kind}")
        elif kind == "operation":
            operations[shape_id] = shape
        else:
            if shape_id in seen:
                return
            seen.add(shape_id)
            for key in _SERVICE_CHILDREN:
                for child in _shape_targets(shape, key):
                    self.collect(child, "operation", operations, seen)
            for child in _shape_targets(shape, "resources"):
                self.collect(child, "resource", operations, seen)

    def field_schema(self, shape_id: str, field: str, label: str) -> dict[str, Any]:
        self.too_deep = False
        schema = self.schema_of(shape_id, 1)
        if self.too_deep:
            raise _too_deep(label, self.target, self.action or "", field)
        return schema

    def schema_of(self, shape_id: str, depth: int) -> dict[str, Any]:
        if self.too_deep or depth > MAX_SCHEMA_DEPTH:
            self.too_deep = True
            return {}
        prelude = _smithy_prelude(shape_id)
        if prelude is not None:
            return prelude
        shape = self.shapes.get(shape_id)
        if shape is None:
            self.gap("unresolved_reference", shape_id)
            return {}
        if shape_id in self.stack:
            self.gap("unresolved_reference", f"{shape_id} (recursive)")
            return {}
        self.stack.append(shape_id)
        schema = self.shape_schema(shape_id, shape, depth)
        self.stack.pop()
        text = _documentation(shape)
        if text is not None:
            schema.setdefault("description", text)
        return schema

    def shape_schema(self, shape_id: str, shape: Any, depth: int) -> dict[str, Any]:
        kind = _shape_type(shape) or "untyped"
        if kind == "string":
            entries = _traits(shape).get("smithy.api#enum")
            if isinstance(entries, list):
                values = [e["value"] for e in entries if isinstance(e, dict) and "value" in e]
                return {"type": "string", "enum": values}
            return {"type": "string"}
        if kind == "enum":
            values = []
            for name, member in _members_of(shape):
                value = _traits(member).get("smithy.api#enumValue")
                values.append(value if isinstance(value, str) else name)
            return {"type": "string", "enum": values}
        if kind in ("list", "set"):
            return {"type": "array", "items": self.member(_get(shape, "member"), depth + 1)}
        if kind == "map":
            return {
                "type": "object",
                "additionalProperties": self.member(_get(shape, "value"), depth + 1),
            }
        if kind == "structure":
            properties, required = self.members(shape, depth + 1)
            schema: dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
            return schema
        if kind == "union":
            properties, _ = self.members(shape, depth + 2)
            if not properties:
                return {}
            return {
                "oneOf": [
                    {"type": "object", "properties": {name: schema}, "required": [name]}
                    for name, schema in properties.items()
                ]
            }
        scalar = _SMITHY_SCALARS.get(kind)
        if scalar is None:
            self.gap("unsupported_schema", f"{shape_id} ({kind})")
            return {}
        return dict(scalar)

    def member(self, member: Any, depth: int) -> dict[str, Any]:
        target = _get(member, "target")
        return self.schema_of(target, depth) if isinstance(target, str) else {}

    def members(self, shape: Any, depth: int) -> tuple[dict[str, Any], list[str]]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, member in _members_of(shape):
            schema = self.member(member, depth)
            text = _documentation(member)
            if text is not None:
                schema["description"] = text
            if "smithy.api#required" in _traits(member):
                required.append(name)
            properties[name] = schema
        return properties, required


def parse_smithy(
    doc: Any, target: str, *, source: str = SOURCE_DECLARATION, label: str = "schema"
) -> dict[str, Any]:
    """Smithy JSON AST -> one MCP target.

    One tool per operation, named by the operation shape's name without its namespace.
    Operations are those of every service (its ``operations`` and, recursively, the
    lifecycle and collection operations of its ``resources``); without a service, every
    operation shape.  The input/output structures become the tool's schemas (members keep
    their Smithy names).  Missing or recursive targets leave the schema open and are
    ``unresolved_reference`` gaps, unknown shape types ``unsupported_schema`` gaps, two
    operations with the same name a ``conflicting_declarations`` gap.
    """
    _check_target_name(target)
    shapes = _get(doc, "shapes")
    if not isinstance(shapes, dict):
        raise SkillError("invalid_input", f"{label}: Smithy model has no `shapes` object")
    walker = _SmithyWalker(shapes, target)
    actions: dict[str, dict[str, Any]] = {}
    try:
        by_action: dict[str, Any] = {}
        for shape_id, operation in walker.operations().items():
            name = _unqualify(target, shape_id.rsplit("#", 1)[-1])
            if name in by_action:
                walker.action = name
                walker.gap("conflicting_declarations", shape_id)
            else:
                by_action[name] = operation
        for name, operation in sorted(by_action.items()):
            walker.action = name
            input_id = _shape_target(operation, "input")
            if input_id is not None and input_id != _UNIT:
                input_schema = walker.field_schema(input_id, "input", label)
            else:
                input_schema = {"type": "object", "properties": {}}
            output_id = _shape_target(operation, "output")
            output_schema = None
            if output_id is not None and output_id != _UNIT:
                output_schema = walker.field_schema(output_id, "output", label)
            actions[name] = _action(
                input_schema,
                output_schema,
                [source],
                description=_documentation(operation),
            )
    except RecursionError:
        raise SkillError("invalid_input", f"{label}: is nested too deeply") from None
    return _part(target, "MCP", "smithy", actions, walker.gaps)


# --------------------------------------------------------------------------- inference


@functools.lru_cache(maxsize=1)
def _inference_doc() -> dict:
    try:
        return json.loads(_INFERENCE_ASSET.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillError(
            "missing_asset",
            "the bundled inference default schema cannot be read",
            asset=str(_INFERENCE_ASSET),
        ) from exc


def inference_target(target_name: str, declaration: Any) -> dict[str, Any]:
    """Project the bundled Bedrock Runtime default schema onto an inference target.

    ``declaration`` is the GetGatewayTarget ``inference.provider`` object
    (``{"operations": [{"path": ...}, ...]}``); an enclosing ``{"provider": ...}`` /
    ``{"connector": ...}`` is accepted too.  A connector declares no operations here, so it
    yields no actions and a gap.  A declared path that the default schema does not know
    becomes a ``POST:<path>`` action without schemas plus a gap.
    """
    _check_target_name(target_name)
    declaration = declaration if isinstance(declaration, dict) else {}
    gaps: list[dict[str, Any]] = []
    if isinstance(declaration.get("provider"), dict):
        declaration = declaration["provider"]
    elif isinstance(declaration.get("connector"), dict):
        gaps.append(
            _gap(
                target_name,
                None,
                None,
                "inference_connector_operations_unknown",
                "a connector target does not list its operations",
            )
        )
        return _part(target_name, "HTTP", "inference", {}, gaps)
    paths = sorted(
        {
            op["path"]
            for op in declaration.get("operations") or []
            if isinstance(op, dict) and isinstance(op.get("path"), str) and op["path"]
        }
    )
    doc = _inference_doc()
    known = doc.get("paths", {})
    actions: dict[str, dict[str, Any]] = {}
    for path in paths:
        if path in known:
            actions.update(
                _inference_actions(doc, target_name, {path: known[path]}, SOURCE_DEFAULT, gaps)
            )
        else:
            name = f"POST:{path}"
            actions[name] = _action(None, None, [SOURCE_DEFAULT], method="POST", path=path)
            gaps.append(
                _gap(
                    target_name,
                    name,
                    "input",
                    "inference_default_path_missing",
                    f"{path} is not in the default inference schema",
                )
            )
    if not paths:
        gaps.append(
            _gap(target_name, None, None, "no_operations", "no inference operations declared")
        )
    return _part(target_name, "HTTP", "inference", actions, gaps)


def runtime_default_target(target_name: str) -> dict[str, Any]:
    """The AgentCore Runtime default route (``POST:/invocations``); a coverage note, no gap."""
    _check_target_name(target_name)
    actions = {
        RUNTIME_ROUTE: _action(
            None,
            None,
            [SOURCE_DEFAULT],
            method="POST",
            path="/invocations",
            description="AgentCore Runtime default invocation route",
        )
    }
    notes = [
        {
            "target": target_name,
            "action": RUNTIME_ROUTE,
            "note": (
                "AgentCore Runtime exposes this default route with an open input and output "
                "record; no field-level schema is known, so policies can only match on "
                "principal, action, resource and the system/session context."
            ),
        }
    ]
    return _part(target_name, "HTTP", "runtime", actions, [], notes)


# --------------------------------------------------------------------------- files / YAML

_YAML_KEY_CLASH = 'has two YAML keys that are the same as JSON (e.g. 200 and "200")'
_YAML_INT = r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"
_YAML_FLOAT = (
    r"^(?:[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[-+]?[0-9]+[eE][-+]?[0-9]+"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
)
_YAML_BOOL = r"^(?:true|True|TRUE|false|False|FALSE)$"
_YAML_BUDGET = 2_000_000


class _YamlProblem(Exception):
    """A YAML document that JSON cannot hold (the message completes ``<label>: ...``)."""


@functools.lru_cache(maxsize=1)
def _yaml_loader() -> Any:
    """A ``yaml.SafeLoader`` reading YAML 1.2 core scalars."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise missing_dependency(
            "PyYAML",
            "pip install PyYAML==6.0.3",
            "only to read YAML schema files (the file is not JSON; converting it to JSON also works)",
        ) from exc

    replaced = {f"tag:yaml.org,2002:{t}" for t in ("bool", "int", "float", "timestamp")}

    def key_text(key: Any) -> str:
        if isinstance(key, str):
            return key
        if isinstance(key, bool):
            return "true" if key else "false"
        if isinstance(key, (int, float)):
            return str(key)
        raise _YamlProblem("has a YAML mapping key that is not a string or number")

    class Loader(yaml.SafeLoader):  # type: ignore[misc, name-defined]
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[Hashable, Any]:
            if isinstance(node, yaml.MappingNode):
                seen: set[str] = set()
                for key_node, _ in node.value:
                    if key_node.tag == "tag:yaml.org,2002:merge":
                        continue
                    text = key_text(self.construct_object(key_node, deep=True))
                    if text in seen:
                        raise _YamlProblem(_YAML_KEY_CLASH)
                    seen.add(text)
                self.flatten_mapping(node)
            mapping: dict[Hashable, Any] = {}
            for key_node, value_node in node.value:
                text = key_text(self.construct_object(key_node, deep=True))
                mapping[text] = self.construct_object(value_node, deep=deep)
            return mapping

    def construct_int(loader: Any, node: Any) -> int:
        text = loader.construct_scalar(node)
        sign = -1 if text.startswith("-") else 1
        digits = text.lstrip("+-")
        if digits.startswith("0o"):
            return sign * int(digits[2:], 8)
        if digits.startswith("0x"):
            return sign * int(digits[2:], 16)
        return sign * int(digits)

    def construct_float(loader: Any, node: Any) -> float:
        text = loader.construct_scalar(node)
        lowered = text.lstrip("+-").lower()
        if lowered == ".inf":
            return float("-inf") if text.startswith("-") else float("inf")
        if lowered == ".nan":
            return float("nan")
        return float(text)

    Loader.yaml_implicit_resolvers = {
        first: [(tag, rx) for tag, rx in resolvers if tag not in replaced]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(_YAML_BOOL), list("tTfF"))
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:float", re.compile(_YAML_FLOAT), list("-+0123456789.")
    )
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:int", re.compile(_YAML_INT), list("-+0123456789")
    )
    Loader.add_constructor("tag:yaml.org,2002:int", construct_int)
    Loader.add_constructor("tag:yaml.org,2002:float", construct_float)
    return yaml, Loader


def _yaml_to_json(value: Any, budget: list[int], active: set[int]) -> Any:
    budget[0] -= 1
    if budget[0] < 0:
        raise _YamlProblem("expands to too much data (YAML aliases)")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _YamlProblem("has a NaN or infinite YAML number")
        return value
    if isinstance(value, (list, dict)):
        if id(value) in active:
            raise _YamlProblem("has a recursive YAML alias")
        active.add(id(value))
        try:
            if isinstance(value, list):
                return [_yaml_to_json(v, budget, active) for v in value]
            return {k: _yaml_to_json(v, budget, active) for k, v in value.items()}
        finally:
            active.discard(id(value))
    raise _YamlProblem("has a custom YAML tag (!tag), which JSON cannot hold")


def _parse_yaml(text: str) -> Any:
    yaml, loader_class = _yaml_loader()
    loader = loader_class(text)
    try:
        value = loader.get_single_data()
    except _YamlProblem:
        raise
    except RecursionError:
        raise _YamlProblem("is nested too deeply") from None
    except yaml.constructor.ConstructorError as exc:
        message = str(exc)
        if "could not determine a constructor for the tag" in message:
            raise _YamlProblem("has a custom YAML tag (!tag), which JSON cannot hold") from None
        if "merging" in message:
            raise _YamlProblem("has an invalid YAML merge key (<<)") from None
        raise _YamlProblem("is neither valid JSON nor YAML") from None
    except yaml.YAMLError:
        raise _YamlProblem("is neither valid JSON nor YAML") from None
    finally:
        loader.dispose()
    try:
        return _yaml_to_json(value, [_YAML_BUDGET], set())
    except RecursionError:
        raise _YamlProblem("is nested too deeply") from None


def load_document(text: str, *, label: str = "schema") -> Any:
    """Parse a schema document: JSON first, else YAML (needs ``PyYAML==6.0.3``).

    YAML is read with YAML 1.2 scalars (only ``true``/``false`` are
    booleans, timestamps stay strings), merge keys applied; mapping keys must be strings,
    numbers or booleans and may not collide once written as JSON (``200`` and ``"200"``);
    custom tags and NaN/infinite numbers are refused.
    """

    def refuse(constant: str) -> Any:
        raise ValueError(constant)

    try:
        return json.loads(text, parse_constant=refuse)
    except (ValueError, RecursionError):
        pass
    try:
        return _parse_yaml(text)
    except _YamlProblem as exc:
        raise SkillError("invalid_input", f"{label}: {exc}") from None


def _read_document(path: str) -> Any:
    label = f"schema file {path}"
    p = Path(path).expanduser()
    if not p.is_file():
        raise SkillError("invalid_input", f"{label}: is not a readable regular file", path=path)
    try:
        if p.stat().st_size > MAX_SCHEMA_FILE_BYTES:
            raise SkillError("invalid_input", f"{label}: is larger than 10 MiB", path=path)
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise SkillError(
            "invalid_input", f"{label}: cannot be read as UTF-8 text", path=path
        ) from exc
    return load_document(text, label=label)


def _tool_list(doc: Any) -> list | None:
    if isinstance(doc, list):
        return doc
    tools = _get(doc, "tools")
    if tools is None:
        result = _get(doc, "result")
        tools = _get(result, "tools") if isinstance(result, dict) else None
    return tools if isinstance(tools, list) else None


def parse_schema_file(path: str, protocol: str, target: str) -> dict[str, Any]:
    """Parse one schema file (one target) for the file route.

    The format is detected from the document: an ``openapi`` key means
    OpenAPI 3 (JSON or YAML; ``protocol`` MCP or HTTP chooses how it is read), ``smithy`` plus
    ``shapes`` a Smithy JSON AST and a tool array (or ``{"tools": [...]}``) an MCP tool
    schema; the latter two are always MCP.  An MCP ``tools/list`` response
    (``{"result": {"tools": [...]}}``) is accepted too.  The returned part tags its actions
    ``file``.
    """
    proto = protocol.upper() if isinstance(protocol, str) else ""
    if proto not in ("MCP", "HTTP"):
        raise SkillError("invalid_input", "protocol must be MCP or HTTP", protocol=protocol)
    _check_target_name(target)
    label = f"schema file {path}"
    doc = _read_document(path)
    tools = _tool_list(doc)
    try:
        if _get(doc, "openapi") is not None:
            part = parse_openapi(doc, target, protocol=proto, source=SOURCE_FILE, label=label)
        elif _get(doc, "smithy") is not None and _get(doc, "shapes") is not None:
            part = parse_smithy(doc, target, source=SOURCE_FILE, label=label)
        elif tools is not None:
            for tool in tools:
                for key, field in (("inputSchema", "input"), ("outputSchema", "output")):
                    if exceeds_depth(_get(tool, key)):
                        name = _get(tool, "name")
                        raise _too_deep(label, target, _unqualify(target, str(name)), field)
            part = parse_mcp_tools(tools, target, strip_prefix=True, source=SOURCE_FILE)
        else:
            raise SkillError(
                "invalid_input",
                f"{label}: not an MCP tool schema, OpenAPI 3 document or Smithy JSON AST",
            )
    except RecursionError:
        raise SkillError("invalid_input", f"{label}: is nested too deeply") from None
    for name, act in part["actions"].items():
        for key, field in (("input_schema", "input"), ("output_schema", "output")):
            if act[key] is not None and exceeds_depth(act[key]):
                raise _too_deep(label, target, name, field)
    return part


# --------------------------------------------------------------------------- merge

_CONFLICT = object()


def _structural(value: Any) -> Any:
    if isinstance(value, list):
        return [_structural(v) for v in value]
    if isinstance(value, dict):
        return {
            k: (sorted(map(str, v)) if k == "required" and isinstance(v, list) else _structural(v))
            for k, v in value.items()
            if k not in ("description", "title", "examples", "example")
        }
    return value


def _merge_node(a: Any, b: Any, path: str, conflicts: list[tuple[str, str]]) -> Any:
    """Conservative merge of two declarations of one schema node.

    Equal nodes merge to themselves.  Objects take the union of their properties and only
    require what both require.  Anything incompatible is left out and reported.
    """
    if _structural(a) == _structural(b):
        return a
    if not (isinstance(a, dict) and isinstance(b, dict)) or a.get("type") != b.get("type"):
        conflicts.append((path, "schema_type_mismatch"))
        return _CONFLICT
    out = {k: v for k, v in a.items() if k not in ("properties", "required", "items", "enum")}
    for key in ("format",):
        if a.get(key) != b.get(key):
            conflicts.append((path, f"{key}_mismatch"))
            return _CONFLICT
    # Different value sets (or an enum on one side only) would otherwise merge to the plain,
    # wider type, allowing values one declaration forbids; report it like a format mismatch.
    if _enum_values(a) != _enum_values(b):
        conflicts.append((path, "enum_mismatch"))
        return _CONFLICT
    if "description" not in out and "description" in b:
        out["description"] = b["description"]
    if a.get("type") == "array":
        items = _merge_node(a.get("items"), b.get("items"), path + "[]", conflicts)
        if items is _CONFLICT:
            return _CONFLICT
        out["items"] = items
    if a.get("type") == "object":
        props: dict[str, Any] = {}
        pa, pb = a.get("properties") or {}, b.get("properties") or {}
        for name in list(pa) + [n for n in pb if n not in pa]:
            if name in pa and name in pb:
                merged = _merge_node(pa[name], pb[name], f"{path}.{name}", conflicts)
                if merged is not _CONFLICT:
                    props[name] = merged
            else:
                props[name] = pa[name] if name in pa else pb[name]
        out["properties"] = props
        req = [
            r for r in (a.get("required") or []) if r in (b.get("required") or []) and r in props
        ]
        if req:
            out["required"] = req
    if "enum" in a:
        out["enum"] = a["enum"]
    return out


def _enum_values(node: dict[str, Any]) -> frozenset[str] | None:
    """The node's enum as a set (order is not meaningful), or None when it declares none."""
    if "enum" not in node:
        return None
    return frozenset(json.dumps(v, sort_keys=True) for v in node.get("enum") or [])


def _merge_action(
    target: str, name: str, into: dict[str, Any], new: dict[str, Any], gaps: list[dict[str, Any]]
) -> None:
    for source in new["sources"]:
        if source not in into["sources"]:
            into["sources"].append(source)
    for key in ("method", "path", "description"):
        if into[key] is None:
            into[key] = new[key]
    for key, field in (("input_schema", "input"), ("output_schema", "output")):
        a, b = into[key], new[key]
        if b is None:
            continue
        if a is None:
            into[key] = b
            continue
        conflicts: list[tuple[str, str]] = []
        merged = _merge_node(a, b, field, conflicts)
        for path, why in conflicts:
            gaps.append(
                _gap(
                    target,
                    name,
                    path,
                    "conflicting_declarations",
                    f"{why}: the declarations from {', '.join(into['sources'])} disagree",
                )
            )
        into[key] = None if merged is _CONFLICT else merged


def merge_targets(parts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge parser parts by target name -> ``(targets, gaps)``.

    Actions merge by exact name (sources are unioned); incompatible declarations of the
    same schema node are left out of the merged schema and reported as
    ``conflicting_declarations`` gaps.  A live ``tools/list`` view of an action served over
    HTTP (a ``runtime``/``openapi`` target) is an extra view, not a conflict; any other
    protocol or kind disagreement keeps the first part and reports a gap.  The parts' own
    gaps are carried over.
    """
    targets: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    for part in parts:
        name = part["target"]
        gaps.extend(part.get("gaps", []))
        if name not in targets:
            targets[name] = {
                "protocol": part["protocol"],
                "kind": part["kind"],
                "actions": {},
            }
        held = targets[name]
        if (part["protocol"], part["kind"]) != (held["protocol"], held["kind"]):
            listing = part["kind"] == "mcp" and part["protocol"] == "MCP"
            held_is_listing = held["kind"] == "mcp" and held["protocol"] == "MCP"
            if listing and held["kind"] != "mcp":
                pass  # a tools/list view of a declared target
            elif held_is_listing:
                held["protocol"], held["kind"] = part["protocol"], part["kind"]
            else:
                gaps.append(
                    _gap(
                        name,
                        None,
                        "kind",
                        "conflicting_declarations",
                        f"declared as {held['protocol']}/{held['kind']} and as "
                        f"{part['protocol']}/{part['kind']}; the first declaration is kept",
                    )
                )
                continue
        for action, new in part["actions"].items():
            current = held["actions"].get(action)
            if current is None:
                held["actions"][action] = json.loads(json.dumps(new))
            else:
                _merge_action(name, action, current, json.loads(json.dumps(new)), gaps)
    return targets, _dedupe_gaps(gaps)
