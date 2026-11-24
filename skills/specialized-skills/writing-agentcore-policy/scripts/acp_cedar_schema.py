"""AgentCore Cedar schema generation for a policy context.

``cedar-policy-mcp-schema-generator`` turns tool descriptions into Cedar actions over the
AgentCore schema stub (``assets/agentcore.cedarschema``).  The AgentCore naming and context
shaping is applied on top of it (parity with the hosted AgentCore Policy validator is not
verified):

* action and property names are base32-encoded before generation (the generator only
  accepts Cedar identifiers) and decoded after it; generated type names become
  ``ID_<sha256[:10]>_<alnum>``;
* every action is qualified with the Gateway ARN and its target,
  ``<gateway>___<target>___<action>``, and is a member of its group (``CallTool``;
  ``InvokeLLM`` for inference; ``InvokeAgent`` for Runtime) and of the target roll-up
  ``<gateway>___<target>``, which is a member of ``Mcp`` (``Http`` for inference/Runtime);
* leaves and roll-ups carry ``isOutput``, ``sessionId``, ``system`` and ``output``;
* HTTP routes get ``input``/``output`` records typed by the API mapping (``integer`` and
  ``number`` are both ``Long``), not by the generator.

Without a Gateway ARN the schema is generated for ``PLACEHOLDER_GATEWAY_ARN`` and flagged;
policies written against it name that ARN until it is replaced before submission.

``cedar-policy-mcp-schema-generator==0.6.1`` and ``cedarpy==4.12.2`` are imported lazily.
Reads no environment variables.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import acp_common
from acp_common import SkillError, parse_gateway_arn

PLACEHOLDER_GATEWAY_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/placeholder-gateway"
)
STUB_PATH = Path(__file__).resolve().parent.parent / "assets" / "agentcore.cedarschema"
GENERATOR_CONFIG = {
    "includeOutputs": True,
    "objectsAsRecords": True,
    "flattenNamespaces": True,
    "numbersAsDecimal": True,
}
NAMESPACE = "AgentCore"
MAX_IDENTIFIER = 480
MAX_SCHEMA_BYTES = 5 * 1024 * 1024

_ALPHABET = "ABCDEFGHIJKLMNPQRSTUVWXYZabcdefg"
_PAD = "z"
_ENC_PREFIX = "ENCODED_"
_ENC_SUFFIX = "_ENCODED_SUFFIX"
_ALL_PRINCIPALS = ["IamEntity", "OAuthUser", "UnauthenticatedUser"]


# --------------------------------------------------------------------------- errors


def _failed(why: str, **details: Any) -> SkillError:
    return SkillError("schema_generation", why, **details)


class _Unsupported(Exception):
    """An action schema the AgentCore reshaping cannot express."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# --------------------------------------------------------------------------- identifiers


def encode_identifier(raw: str) -> str:
    """Reversible base32-like encoding into a Cedar-safe identifier."""
    out = []
    acc = bits = 0
    for byte in raw.encode("utf-8"):
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_ALPHABET[(acc >> bits) & 31])
        acc &= (1 << bits) - 1
    if bits > 0:
        out.append(_ALPHABET[(acc << (5 - bits)) & 31])
    while len(out) % 8:
        out.append(_PAD)
    return _ENC_PREFIX + "".join(out) + _ENC_SUFFIX


def _decode_body(body: str) -> str:
    acc = bits = 0
    out = bytearray()
    for ch in body:
        if ch == _PAD:
            break
        value = _ALPHABET.find(ch)
        if value < 0:
            raise _failed("invalid encoded identifier")
        acc = (acc << 5) | value
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
            acc &= (1 << bits) - 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _failed("encoded identifier is not UTF-8") from exc


def decode_identifiers(text: str) -> str:
    """Decode every ``ENCODED_<body>_ENCODED_SUFFIX`` occurrence inside ``text``."""
    out = []
    rest = text
    while True:
        pos = rest.find(_ENC_PREFIX)
        if pos < 0:
            break
        out.append(rest[:pos])
        after = rest[pos + len(_ENC_PREFIX) :]
        letters = 0
        while letters < len(after) and after[letters].isascii() and after[letters].isalpha():
            letters += 1
        if after[letters:].startswith(_ENC_SUFFIX):
            out.append(_decode_body(after[:letters]))
            rest = after[letters + len(_ENC_SUFFIX) :]
        else:
            out.append(_ENC_PREFIX)
            rest = after
    out.append(rest)
    return "".join(out)


def sanitize_identifier(raw: str) -> str:
    """``ID_<sha256[:10]>_<alnum>`` type name, capped at 480 characters."""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    cleaned = "".join(c for c in raw if (c.isascii() and c.isalnum()) or c == "_")
    identifier = f"ID_{digest[:10]}_{cleaned}"
    if len(identifier) <= MAX_IDENTIFIER:
        return identifier
    suffix = identifier[len(identifier) - (MAX_IDENTIFIER - 166) :]
    return f"{identifier[:100]}_{digest}_{suffix}"


def _encode_schema(schema: Any) -> Any:
    """Encode property names (and ``required``) so the generator accepts them."""
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    for key in ("properties", "$defs", "definitions"):
        members = schema.get(key)
        if isinstance(members, dict):
            result[key] = {
                (encode_identifier(name) if key == "properties" else name): _encode_schema(value)
                for name, value in members.items()
            }
    required = schema.get("required")
    if isinstance(required, list):
        result["required"] = [encode_identifier(n) for n in required if isinstance(n, str)]
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            result[key] = _encode_schema(schema[key])
    for key in ("oneOf", "anyOf", "allOf", "prefixItems", "items"):
        if isinstance(schema.get(key), list):
            result[key] = [_encode_schema(v) for v in schema[key]]
    return result


# --------------------------------------------------------------------------- normalise

_INLINE_SKIP = ("enum", "const", "default", "examples", "example")


def _inline(node: Any, root: Any, stack: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_inline(item, root, stack) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        if not ref.startswith("#"):
            raise _Unsupported("remote_schema_reference", f"unsupported schema reference {ref}")
        target: Any = root
        for part in [p for p in ref[1:].split("/")][1:] if ref[1:] else []:
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(target, dict) and key in target:
                target = target[key]
            elif isinstance(target, list) and key.isdigit() and int(key) < len(target):
                target = target[int(key)]
            else:
                raise _Unsupported("unresolved_schema_reference", f"unresolved reference {ref}")
        if ref in stack:
            raise _Unsupported("cyclic_schema_reference", f"cyclic schema reference {ref}")
        return _inline(target, root, stack + (ref,))
    out = {}
    for key, value in node.items():
        if key in ("$defs", "definitions"):
            continue
        if key in _INLINE_SKIP:
            out[key] = value
        elif key in ("properties", "patternProperties") and isinstance(value, dict):
            out[key] = {name: _inline(child, root, stack) for name, child in value.items()}
        else:
            out[key] = _inline(value, root, stack)
    return out


def _admits_null(schema: Any) -> bool:
    members = schema.get("enum") if isinstance(schema, dict) else None
    return isinstance(members, list) and any(m is None for m in members)


def _reshape(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    node = dict(node)
    members = node.pop("enum", None)
    if isinstance(members, list):
        strings = [m for m in members if isinstance(m, str)]
        if strings:
            node["enum"] = strings
    if isinstance(node.get("items"), list):
        node["prefixItems"] = node.pop("items")
        if "additionalItems" in node:
            node["items"] = node.pop("additionalItems")
    props = node.pop("properties", None)
    if isinstance(props, dict):
        nullable = {name for name, schema in props.items() if _admits_null(schema)}
        node["properties"] = {name: _reshape(schema) for name, schema in props.items()}
        if isinstance(node.get("required"), list):
            node["required"] = [
                r for r in node["required"] if not (isinstance(r, str) and r in nullable)
            ]
    for key in ("items", "additionalProperties"):
        if key in node:
            node[key] = _reshape(node[key])
    for key in ("prefixItems", "oneOf", "anyOf", "allOf"):
        if isinstance(node.get(key), list):
            node[key] = [_reshape(child) for child in node[key]]
    return node


def normalise(schema: dict) -> dict:
    """Reshape an action schema the way AgentCore Policy does before generating.

    Local ``$ref`` s are inlined, the top level keeps only ``properties``/``required`` as an
    object, non-string ``enum`` members are dropped (a listed ``null`` makes the property
    optional) and tuple ``items`` become ``prefixItems``.  Raises ``_Unsupported`` for
    cyclic, remote or unresolved references.
    """
    inlined = _inline(schema, schema, ())
    top: dict[str, Any] = {"type": "object"}
    for key in ("properties", "required"):
        if key in inlined:
            top[key] = inlined[key]
    return _reshape(top)


# --------------------------------------------------------------------------- API typing


def _api_type(schema: Any) -> dict:
    kind = schema.get("type") if isinstance(schema, dict) else None
    if kind == "string":
        return {"type": "String"}
    if kind in ("integer", "number"):
        return {"type": "Long"}
    if kind == "boolean":
        return {"type": "Boolean"}
    if kind == "array":
        return {"type": "Set", "element": _api_type(schema.get("items") or {})}
    if kind == "object":
        return _api_record(schema)
    return {"type": "Record", "attributes": {}}


def _api_record(schema: Any) -> dict:
    schema = schema if isinstance(schema, dict) else {}
    required = {r for r in schema.get("required") or [] if isinstance(r, str)}
    attributes = {}
    properties = schema.get("properties")
    for name, value in (properties if isinstance(properties, dict) else {}).items():
        attribute = _api_type(value)
        if name not in required:
            attribute["required"] = False
        attributes[name] = attribute
    return {"type": "Record", "attributes": attributes}


def _path_params(action: str) -> list[str]:
    path = action.split(":", 1)[1] if ":" in action else ""
    return [m for m in re.findall(r"\{([^{}/]+)\}", path) if m]


# --------------------------------------------------------------------------- leaves


class _Leaf:
    def __init__(self, target: str, action: str, kind: str, declared: dict) -> None:
        self.target = target
        self.action = action
        self.kind = kind  # mcp | http | inference | runtime
        self.input = declared.get("input_schema")
        self.output = declared.get("output_schema")
        self.synthesized = (
            kind == "runtime"
            and not isinstance(self.input, dict)
            and not isinstance(self.output, dict)
        )

    def qualified(self, gateway: str) -> str:
        return f"{gateway}___{self.target}___{self.action}"


def _target_kind(target: dict) -> str:
    if target.get("kind") == "inference":
        return "inference"
    if target.get("kind") == "runtime":
        return "runtime"
    return "mcp" if str(target.get("protocol", "")).upper() == "MCP" else "http"


def _has_cedar_action(leaf: _Leaf) -> bool:
    return leaf.kind == "mcp" or leaf.synthesized or isinstance(leaf.input, dict)


def _all_leaves(context: dict) -> list[_Leaf]:
    leaves = []
    for target_name, target in sorted((context.get("targets") or {}).items()):
        kind = _target_kind(target)
        for action, declared in sorted((target.get("actions") or {}).items()):
            leaves.append(_Leaf(target_name, action, kind, declared or {}))
    return leaves


def _gateway(context: dict) -> tuple[str, bool]:
    arn = context.get("gateway_arn")
    if arn:
        return parse_gateway_arn(arn).arn, False
    return PLACEHOLDER_GATEWAY_ARN, True


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def qualified_action(context: dict, target: str, action: str) -> str:
    """Unquoted Cedar action id: ``<gateway>___<target>___<action>``."""
    gateway, _ = _gateway(context)
    return f"{gateway}___{target}___{action}"


def action_id(context: dict, target: str, action: str) -> str:
    """Cedar action entity used in policies: ``AgentCore::Action::"<gw>___<target>___<action>"``."""
    return f'{NAMESPACE}::Action::"{_escape(qualified_action(context, target, action))}"'


def target_group_id(context: dict, target: str) -> str:
    """Cedar action entity of a target's roll-up (all actions of the target)."""
    gateway, _ = _gateway(context)
    return f'{NAMESPACE}::Action::"{_escape(f"{gateway}___{target}")}"'


# --------------------------------------------------------------------------- rename


class _Renamer:
    def __init__(self) -> None:
        self.names: dict[str, str] = {}
        self.origins: dict[str, str] = {}

    def claim(self, name: str, origin: str) -> None:
        held = self.origins.setdefault(name, origin)
        if held != origin:
            raise _failed(f"generated type name collision: {name}")

    def type_name(self, raw: str) -> str:
        decoded = decode_identifiers(raw)
        name = raw if decoded == raw else sanitize_identifier(decoded)
        self.claim(name, decoded)
        return name

    def renamed(self, name: str) -> str:
        return self.names.get(name, name)

    def transform(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self.transform(v) for v in value]
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "attributes" and isinstance(item, dict):
                decoded: dict[str, Any] = {}
                for raw, attribute in item.items():
                    name = decode_identifiers(raw)
                    if name in decoded:
                        raise _failed(f"property name collision: {name}")
                    decoded[name] = self.transform(attribute)
                out[key] = decoded
            elif key == "type" and isinstance(item, str):
                out[key] = self.renamed(item)
            elif key == "name" and isinstance(item, str):
                prefix = f"{NAMESPACE}::" if item.startswith(f"{NAMESPACE}::") else ""
                bare = item[len(prefix) :]
                chosen = self.names.get(bare) or self.type_name(bare)
                out[key] = prefix + chosen
            elif key == "memberOfTypes" and isinstance(item, list):
                out[key] = [self.renamed(t) if isinstance(t, str) else t for t in item]
            else:
                out[key] = self.transform(item)
        return out


def _rename(namespace: dict, renamer: _Renamer) -> dict:
    sections = ("commonTypes", "entityTypes")
    for section in sections:
        for raw in list(namespace.get(section) or {}):
            renamer.names[raw] = renamer.type_name(raw)
    for section in sections:
        declared = namespace.pop(section, None)
        if isinstance(declared, dict):
            namespace[section] = {
                renamer.renamed(raw): renamer.transform(decl) for raw, decl in declared.items()
            }
    actions: dict[str, Any] = {}
    for raw, action in (namespace.pop("actions", None) or {}).items():
        name = decode_identifiers(raw)
        if name in actions:
            raise _failed(f"action name collision: {name}")
        actions[name] = renamer.transform(action)
    return actions


# --------------------------------------------------------------------------- generation


def _load_generator() -> Any:
    try:
        import cedar_mcp_schema_generator  # type: ignore[import-not-found]
    except ImportError as exc:
        raise acp_common.missing_dependency(
            "cedar-policy-mcp-schema-generator",
            "pip install cedar-policy-mcp-schema-generator==0.6.1",
            "to generate the Gateway's Cedar schema",
        ) from exc
    return cedar_mcp_schema_generator


def _load_cedarpy() -> Any:
    try:
        import cedarpy  # type: ignore[import-not-found]
    except ImportError as exc:
        raise acp_common.missing_dependency(
            "cedarpy", "pip install cedarpy==4.12.2", "to check the generated Cedar schema"
        ) from exc
    return cedarpy


def _stub() -> str:
    try:
        return STUB_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillError(
            "missing_asset",
            "the bundled AgentCore schema stub cannot be read",
            asset=str(STUB_PATH),
        ) from exc


def _generate_json(generator: Any, stub: str, tools: list[dict]) -> dict:
    result = generator.generate_schema(stub, tools, config=dict(GENERATOR_CONFIG))
    if not result.get("isOk"):
        raise _failed(str(result.get("error") or "the schema generator failed"))
    try:
        return json.loads(result["schemaJson"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _failed("the schema generator returned no JSON schema") from exc


def _run_generator(
    stub: str, tools: list[dict], by_name: dict[str, _Leaf], gaps: list[dict]
) -> dict:
    generator = _load_generator()
    try:
        return _generate_json(generator, stub, tools)
    except SkillError as first:
        # Find the offending tools one by one, open them up and report a gap.
        offenders = []
        for tool in tools:
            try:
                _generate_json(generator, stub, [tool])
            except SkillError as exc:
                offenders.append((tool["name"], str(exc.args[0] if exc.args else exc)))
        if not offenders:
            raise first
        replaced = {name for name, _ in offenders}
        for name, why in offenders:
            leaf = by_name[name]
            gaps.append(
                {
                    "target": leaf.target,
                    "action": leaf.action,
                    "field": "input",
                    "reason": "unsupported_schema",
                    "detail": f"the schema generator rejected the schema: {why[:300]}",
                }
            )
        retry = [
            {"name": t["name"], "inputSchema": {"type": "object"}} if t["name"] in replaced else t
            for t in tools
        ]
        return _generate_json(generator, stub, retry)


def _context_attributes(action: dict) -> dict:
    applies = action.setdefault("appliesTo", {})
    context = applies.setdefault("context", {"type": "Record", "attributes": {}})
    if context.get("type") != "Record":
        raise _failed("action context is not a record")
    return context.setdefault("attributes", {})


def _add_agentcore_context(attributes: dict, *, session: bool = True) -> None:
    attributes.setdefault("isOutput", {"type": "Boolean"})
    if session:
        attributes.setdefault("sessionId", {"type": "String"})
    attributes.setdefault("system", {"type": "EntityOrCommon", "name": "SystemContext"})
    attributes.setdefault("output", {"type": "Record", "attributes": {}})


def _shape_action(
    gateway: str,
    leaf: _Leaf,
    actions: dict,
    renamer: _Renamer,
    common_types: dict[str, Any],
) -> None:
    qualified = leaf.qualified(gateway)
    target_id = f"{gateway}___{leaf.target}"
    action = actions.get(qualified)
    if not isinstance(action, dict):
        raise _failed(f"no action generated for {leaf.action} of target {leaf.target}")
    attributes = _context_attributes(action)
    _add_agentcore_context(attributes, session=not leaf.synthesized)
    if leaf.kind != "mcp":
        for field, suffix, declaration in (
            ("input", "Input", leaf.input),
            ("output", "Output", leaf.output),
        ):
            origin = f"{qualified}{suffix}"
            name = sanitize_identifier(origin)
            renamer.claim(name, origin)
            declared = _api_record(declaration if isinstance(declaration, dict) else {})
            if field == "input":
                for param in _path_params(leaf.action):
                    declared["attributes"][param] = {"type": "String"}
            common_types[name] = declared
            attribute: dict[str, Any] = {"type": "EntityOrCommon", "name": name}
            if field == "output" or not isinstance(declaration, dict):
                attribute["required"] = False
            attributes[field] = attribute
    group, parent = {
        "inference": ("InvokeLLM", "Http"),
        "runtime": ("InvokeAgent", "Http"),
    }.get(leaf.kind, ("CallTool", "Mcp"))
    action["memberOf"] = [{"id": group}, {"id": target_id}]
    if target_id not in actions:
        rollup_attributes: dict[str, Any] = {}
        if leaf.synthesized:
            rollup_attributes = {
                "input": {"type": "Record", "attributes": {}, "required": False},
                "isOutput": {"type": "Boolean"},
                "output": {"type": "Record", "attributes": {}, "required": False},
                "system": {"type": "EntityOrCommon", "name": "SystemContext"},
            }
        else:
            _add_agentcore_context(rollup_attributes)
        actions[target_id] = {
            "appliesTo": {
                "principalTypes": list(_ALL_PRINCIPALS),
                "resourceTypes": ["Gateway"],
                "context": {"type": "Record", "attributes": rollup_attributes},
            },
            "memberOf": [{"id": parent}],
        }


def generate(context: dict) -> dict[str, Any]:
    """Generate the AgentCore Cedar schema of a policy context.

    Returns ``{"schema_text", "schema_json", "placeholder_gateway_arn", "gaps"}``.  An action
    whose schema cannot be expressed (unresolved/cyclic reference, rejected by the
    generator) is generated with an open input and reported as a gap; two actions that
    qualify to the same Cedar name make the whole generation fail.
    """
    gateway, placeholder = _gateway(context)
    gaps: list[dict[str, Any]] = []
    leaves = [leaf for leaf in _all_leaves(context) if _has_cedar_action(leaf)]
    for leaf in _all_leaves(context):
        if not _has_cedar_action(leaf):
            gaps.append(
                {
                    "target": leaf.target,
                    "action": leaf.action,
                    "field": "input",
                    "reason": "no_cedar_action",
                    "detail": "an HTTP action without an input schema has no Cedar action",
                }
            )
    by_name: dict[str, _Leaf] = {}
    tools: list[dict] = []
    for leaf in leaves:
        encoded = encode_identifier(leaf.qualified(gateway))
        if encoded in by_name:
            earlier = by_name[encoded]
            raise _failed(
                f"actions {earlier.action} of target {earlier.target} and {leaf.action} of "
                f"target {leaf.target} have the same Cedar name"
            )
        by_name[encoded] = leaf
        tool: dict[str, Any] = {"name": encoded}
        for key, declared, field in (
            ("inputSchema", leaf.input, "input"),
            ("outputSchema", leaf.output, "output"),
        ):
            if isinstance(declared, dict) and (declared or key == "inputSchema"):
                try:
                    tool[key] = _encode_schema(normalise(declared))
                except _Unsupported as exc:
                    gaps.append(
                        {
                            "target": leaf.target,
                            "action": leaf.action,
                            "field": field,
                            "reason": exc.reason,
                            "detail": str(exc),
                        }
                    )
        tool.setdefault("inputSchema", {"type": "object"})
        tools.append(tool)

    schema = _run_generator(_stub(), tools, by_name, gaps)
    namespace = schema.get(NAMESPACE)
    if not isinstance(namespace, dict):
        raise _failed("generated schema has no AgentCore namespace")
    renamer = _Renamer()
    actions = _rename(namespace, renamer)
    commons = namespace.setdefault("commonTypes", {})
    new_commons: dict[str, Any] = {}
    for leaf in leaves:
        _shape_action(gateway, leaf, actions, renamer, new_commons)
    commons.update(new_commons)
    namespace["actions"] = actions
    text = _render(schema)
    return {
        "schema_text": text,
        "schema_json": schema,
        "placeholder_gateway_arn": placeholder,
        "gaps": gaps,
    }


def _render(schema: dict) -> str:
    cedarpy = _load_cedarpy()
    try:
        text = str(cedarpy.Schema.from_json_str(json.dumps(schema)))
    except ValueError as exc:
        raise _failed(f"the generated schema is invalid: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise _failed(f"generated schema is over the {MAX_SCHEMA_BYTES}-byte limit", size=len(text))
    return text


# --------------------------------------------------------------------------- context types

_RESERVED = {
    "true", "false", "if", "then", "else", "in", "is", "like", "has", "principal", "action",
    "resource", "context", "permit", "forbid", "when", "unless",
}  # fmt: skip
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRIMITIVES = {
    "String": "String",
    "Long": "Long",
    "Bool": "Bool",
    "Boolean": "Bool",
    "decimal": "decimal",
    "datetime": "datetime",
    "duration": "duration",
    "ipaddr": "ipaddr",
}

_COMPARE = {
    "decimal": '{e}.greaterThan(decimal("1000.0"))',
    "Long": "{e} > 100",
    "String": '{e} == "value"',
    "Bool": "{e} == true",
    "datetime": '{e}.durationSince(datetime("2026-01-01T00:00:00Z")).toHours() > 24',
    "duration": '{e} > duration("1h")',
    "ipaddr": '{e}.isInRange(ip("10.0.0.0/8"))',
}
_HINTS = {
    "decimal": (
        "use .greaterThan/.greaterThanOrEqual/.lessThan/.lessThanOrEqual with a quoted decimal "
        'literal such as decimal("1000.0"); the bare operators (> < >= <=) are a type error on a '
        "decimal"
    ),
    "Long": (
        "use the ordinary integer operators (> < >= <= ==) with an unquoted number; the decimal "
        "methods are a type error on a Long"
    ),
}


def _accessor(base: str, name: str) -> str:
    if _IDENT.match(name) and name not in _RESERVED:
        return f"{base}.{name}"
    return f'{base}["{_escape(name)}"]'


def _has(base: str, name: str) -> str:
    if _IDENT.match(name) and name not in _RESERVED:
        return f"{base} has {name}"
    return f'{base} has "{_escape(name)}"'


def context_types(schema_json: dict, context: dict, target: str, action: str) -> dict[str, Any]:
    """Cedar type of every context field of one action, with a comparison hint.

    Keys are paths inside the context (``input.amount``, ``output.rows[].id``).  The right
    comparison syntax depends on a mapping the JSON Schema does not show: an MCP ``number``
    is a Cedar ``decimal`` (``.greaterThan(decimal("1000.0"))``), an MCP ``integer`` is a
    ``Long`` (``> 1000``), and HTTP routes map both to ``Long``.  Values:
    ``{"cedar_type", "compare_with", "optional", "hint"?, "enum_values"?}``; ``compare_with``
    is ``None`` for fields inside a set.
    """
    namespace = schema_json.get(NAMESPACE)
    if not isinstance(namespace, dict):
        return {}
    qualified = qualified_action(context, target, action)
    entry = (namespace.get("actions") or {}).get(qualified)
    if not isinstance(entry, dict):
        raise SkillError(
            "not_found",
            "the action is not in the generated Cedar schema",
            target=target,
            action=action,
        )
    commons = namespace.get("commonTypes") or {}
    entities = namespace.get("entityTypes") or {}
    out: dict[str, Any] = {}

    def record(
        path: str, expr: str | None, guards: list[str], cedar_type: str, extra: dict
    ) -> None:
        info: dict[str, Any] = {"cedar_type": cedar_type, "compare_with": None}
        template = _COMPARE.get(cedar_type)
        if template and expr is not None:
            info["compare_with"] = " && ".join(guards + [template.format(e=expr)])
        elif cedar_type.startswith("Set<") and expr is not None:
            element = cedar_type[4:-1]
            sample = '"value"' if element == "String" else "1" if element == "Long" else None
            if sample:
                info["compare_with"] = " && ".join(guards + [f"{expr}.contains({sample})"])
        if cedar_type in _HINTS:
            info["hint"] = _HINTS[cedar_type]
        info["optional"] = bool(guards)
        info.update(extra)
        if "enum_values" in extra and expr is not None and extra.get("entity_type"):
            first = json.dumps(extra["enum_values"][0]) if extra["enum_values"] else '"value"'
            info["compare_with"] = " && ".join(
                guards + [f"{expr} == {extra['entity_type']}::{first}"]
            )
        out[path] = info

    def describe(node: Any, depth: int = 0) -> str:
        kind, name = _resolve(node)
        if depth > 12:
            return "Record"
        if kind == "Record":
            return "Record"
        if kind == "Set":
            return f"Set<{describe(node.get('element') or {}, depth + 1)}>"
        if kind == "named":
            if name in commons:
                return describe(commons[name], depth + 1)
            if name in entities:
                return "enum" if "enum" in entities[name] else "entity"
            return _PRIMITIVES.get(name, name)
        return _PRIMITIVES.get(kind, kind)

    def resolve_name(name: str) -> str:
        return name.removeprefix(f"{NAMESPACE}::").removeprefix("__cedar::")

    def _resolve(node: Any) -> tuple[str, str]:
        kind = node.get("type", "") if isinstance(node, dict) else ""
        if kind in ("EntityOrCommon", "Entity", "CommonType", "Extension"):
            return "named", resolve_name(str(node.get("name", "")))
        if kind in ("Record", "Set") or kind in _PRIMITIVES:
            return kind, ""
        return "named", resolve_name(kind)

    def walk(
        node: Any,
        path: str,
        expr: str | None,
        guards: list[str],
        in_set: bool,
        depth: int,
    ) -> None:
        if depth > 12:
            return
        kind, name = _resolve(node)
        if kind == "Record":
            attributes = node.get("attributes") or {}
            if not attributes and path:
                record(path, None if in_set else expr, guards, "Record", {})
            for field, value in attributes.items():
                child_path = f"{path}.{field}" if path else field
                child_expr = None if (in_set or expr is None) else _accessor(expr, field)
                child_guards = list(guards)
                if isinstance(value, dict) and value.get("required") is False and child_expr:
                    child_guards.append(_has(expr or "", field))
                walk(value, child_path, child_expr, child_guards, in_set, depth + 1)
            return
        if kind == "Set":
            element = node.get("element") or {}
            ekind, ename = _resolve(element)
            if ekind in ("Record",) or (ename in commons and describe(element) == "Record"):
                walk(element, f"{path}[]", None, guards, True, depth + 1)
            else:
                record(path, None if in_set else expr, guards, describe(node), {})
            return
        if kind == "named" and name in commons:
            walk(commons[name], path, expr, guards, in_set, depth + 1)
            return
        if kind == "named" and name in entities:
            decl = entities[name]
            if "enum" in decl:
                record(
                    path,
                    None if in_set else expr,
                    guards,
                    "enum",
                    {
                        "enum_values": list(decl["enum"]),
                        "entity_type": f"{NAMESPACE}::{name}",
                    },
                )
            else:
                tag = decl.get("tags")
                record(
                    path,
                    None,
                    guards,
                    "entity",
                    {"entity_type": f"{NAMESPACE}::{name}", "tags": describe(tag) if tag else None},
                )
            return
        record(path, None if in_set else expr, guards, describe(node), {})

    walk(
        (entry.get("appliesTo") or {}).get("context") or {},
        "",
        "context",
        [],
        False,
        0,
    )
    return out
