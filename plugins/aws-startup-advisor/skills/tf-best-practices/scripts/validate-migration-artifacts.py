#!/usr/bin/env python3
"""Read-only checks for generated migration infrastructure and scripts.

This is a bounded static checker, not a Terraform, YAML, or Bash interpreter.
Unknown security-group expressions and unrecognised PostgreSQL scripts fail
explicitly as unverified. The PostgreSQL check accepts a narrow early-return
SELECT-only form, or the reviewed template's verification control flow and
functions (migration-only bodies may vary). It does not prove arbitrary Bash
programs safe or replace deployment validation. No generated program is
executed, no provider is contacted, and no artifact or phase state is written.

Usage: validate-migration-artifacts.py MIGRATION_DIR [--json REPORT_PATH]
Exit 0: ARTIFACTS_OK; 1: ARTIFACTS_FAIL; 2: input/dependency/IO error.
Use --json - for JSON on stdout. A report path writes only that requested report.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any


class InputError(Exception):
    """Cannot safely read the requested input or required checker dependency."""


_EXECUTION_ENVIRONMENT_KEYS = {
    "PATH", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PS4", "IFS", "CDPATH",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME",
}


@dataclass(frozen=True, order=True)
class Finding:
    file: str
    line: int
    rule: str
    summary: str


@dataclass(frozen=True)
class Resource:
    kind: str
    name: str
    body: str
    file: str
    line: int

    @property
    def address(self) -> str:
        return f"{self.kind}.{self.name}"


def _load_module(name: str, path: Path) -> Any:
    if not path.is_file():
        raise InputError(f"Required checker dependency is missing: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise InputError(f"Cannot load checker dependency: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError) as exc:
        raise InputError(f"Cannot load checker dependency {path.name}: {exc}") from exc
    return module


def _dependencies() -> tuple[Any, Any]:
    scripts = Path(__file__).resolve().parent
    policy = _load_module("_heroku_artifact_hcl", scripts / "validate-terraform-policy.py")
    windows = _load_module("_heroku_artifact_windows", scripts / "rds_windows.py")
    return policy, windows


def _read(root: Path, path: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise InputError(f"Artifact escapes migration directory: {path.relative_to(root)}")
        if not resolved.is_file():
            raise InputError(f"Artifact is not a regular file: {path.relative_to(root)}")
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise InputError(f"Cannot read {path.relative_to(root)}: {exc}") from exc


def _files(root: Path, directory: str, suffixes: tuple[str, ...]) -> list[Path]:
    base = root / directory
    if not base.exists() and not base.is_symlink():
        return []
    if not base.resolve().is_relative_to(root):
        raise InputError(f"Artifact directory escapes migration directory: {directory}")
    if not base.is_dir():
        raise InputError(f"Artifact directory is not a directory: {directory}")
    result: list[Path] = []
    # Terraform and GitHub both load immediate files from these directories.
    # Nested modules/examples are not part of the root configuration or workflow
    # set and must not supply resources, ingress rules, or deployment steps.
    for path in base.iterdir():
        if path.suffix in suffixes and (path.is_file() or path.is_symlink()):
            _read(root, path)
            result.append(path)
    return sorted(result)


def _uncomment_hcl(text: str, policy: Any) -> str:
    _, _, comments = policy._lex_hcl(text)
    return "".join(" " if comments[i] and ch != "\n" else ch for i, ch in enumerate(text))


def _attr(body: str, name: str, policy: Any) -> str | None:
    """Read one direct attribute, retaining strings but excluding comments."""
    body = _uncomment_hcl(body, policy)
    depths, codes, _ = policy._lex_hcl(body)
    base = 1 if body.lstrip().startswith("{") else 0
    pattern = rf"\b{re.escape(name)}\s*="
    matches = [
        m for m in re.finditer(pattern, body)
        if codes[m.start()] and depths[m.start()] == base
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Duplicate {name} attributes")
    start = matches[0].end()
    bracket = paren = 0
    for i in range(start, len(body)):
        ch = body[i]
        if codes[i]:
            bracket += (ch == "[") - (ch == "]")
            paren += (ch == "(") - (ch == ")")
            if ch == "}" and depths[i] == base:
                return body[start:i].strip()
            if ch == "\n" and bracket == 0 and paren == 0 and depths[i] == base:
                return body[start:i].strip()
    return body[start:].strip()


def _string(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, str) or "${" in parsed or "%{" in parsed:
        return None
    return parsed


def _number(value: str | None) -> int | None:
    raw = _string(value) if value and value.startswith('"') else value
    return int(raw) if raw and re.fullmatch(r"[0-9]+", raw) else None


def _split_items(expression: str) -> list[str]:
    pieces: list[str] = []
    start = depth = 0
    quoted = escaped = False
    for i, ch in enumerate(expression):
        if escaped:
            escaped = False
        elif ch == "\\" and quoted:
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif not quoted:
            depth += (ch in "[(") - (ch in "])")
            if ch == "," and depth == 0:
                pieces.append(expression[start:i].strip())
                start = i + 1
    pieces.append(expression[start:].strip())
    return [part for part in pieces if part]


def _sg_refs(value: str | None) -> set[str] | None:
    """Resolve only direct IDs, lists, joins, and simple interpolated ID lists."""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"aws_security_group\.[A-Za-z0-9_-]+\.id", value):
        return {value.rsplit(".", 1)[0]}
    literal = _string(value)
    if literal is not None:
        ids = [item.strip() for item in literal.split(",")]
        return set(ids) if all(re.fullmatch(r"sg-[a-zA-Z0-9]+", v) for v in ids) else None
    if value.startswith("[") and value.endswith("]"):
        groups = [_sg_refs(item) for item in _split_items(value[1:-1])]
        if any(group is None for group in groups):
            return None
        return set().union(*groups) if groups else set()
    join = re.fullmatch(r'join\(\s*","\s*,\s*(\[.*\])\s*\)', value, re.DOTALL)
    if join:
        return _sg_refs(join.group(1))
    # An interpolation may only contain group.id, with comma separators.
    if value.startswith('"') and value.endswith('"'):
        inner = value[1:-1]
        parts = [item.strip() for item in inner.split(",")]
        refs = [
            re.fullmatch(r"\$\{(aws_security_group\.[A-Za-z0-9_-]+)\.id\}", part)
            for part in parts
        ]
        if refs and all(refs):
            return {match.group(1) for match in refs if match}
    return None


def _own_blocks(body: str, kind: str, policy: Any) -> list[str]:
    depths, codes, _ = policy._lex_hcl(body)
    base = 1 if body.lstrip().startswith("{") else 0
    result = []
    for match in re.finditer(rf"\b{re.escape(kind)}\s*\{{", body):
        if codes[match.start()] and depths[match.start()] == base:
            block, _ = policy._extract_braced_block(body, match.end() - 1)
            result.append(block)
    return result


def _instances(resource: Resource, policy: Any) -> bool | None:
    """Whether a resource is definitely instantiated; never guess dynamic counts."""
    count = _attr(resource.body, "count", policy)
    each = _attr(resource.body, "for_each", policy)
    if count is not None and each is not None:
        return None
    if count is not None:
        number = _number(count)
        return number > 0 if number is not None else None
    if each is not None:
        compact = re.sub(r"\s+", "", each)
        if compact in {"{}", "[]", "toset([])", "tomap({})", "tolist([])"}:
            return False
        return None
    return True


def _resources(root: Path, policy: Any, findings: list[Finding]) -> list[Resource]:
    resources: list[Resource] = []
    paths = _files(root, "terraform", (".tf",))
    if not paths:
        findings.append(Finding("terraform", 0, "no_terraform", "No generated Terraform files found."))
    for path in paths:
        text = _read(root, path)
        relative = path.relative_to(root).as_posix()
        depths, codes, _ = policy._lex_hcl(text)
        balance = 0
        for i, char in enumerate(text):
            if codes[i] and char in "{}":
                balance += 1 if char == "{" else -1
                if balance < 0:
                    break
        if balance != 0:
            findings.append(Finding(relative, 0, "hcl_unverified", "Unbalanced Terraform block syntax."))
            continue
        for match in re.finditer(r'\bmodule\s+"[^"]+"\s*\{', text):
            if codes[match.start()] and depths[match.start()] == 0:
                findings.append(Finding(
                    relative, text.count("\n", 0, match.start()) + 1,
                    "terraform_module_unverified",
                    "Module expansion is not evaluated by this root-module checker; "
                    "verify its resources and connections separately.",
                ))
        for match in policy.RESOURCE_OPEN.finditer(text):
            if not codes[match.start()] or depths[match.start()] != 0:
                continue
            body, _ = policy._extract_braced_block(text, match.end() - 1)
            resource = Resource(
                match.group("type"), match.group("name"), body, relative,
                text.count("\n", 0, match.start()) + 1,
            )
            instances = _instances(resource, policy)
            if instances is not False:
                resources.append(resource)
    return resources


def _ungroup_hcl(expression: str, policy: Any) -> str:
    """Remove only parentheses that enclose the entire expression."""
    raw = _uncomment_hcl(expression, policy).strip()
    _, codes, _ = policy._lex_hcl(raw)
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for i, char in enumerate(raw):
        if not codes[i]:
            continue
        if char == "(":
            stack.append(i)
        elif char == ")" and stack:
            pairs[stack.pop()] = i
    start, end = 0, len(raw)
    while start < end and pairs.get(start) == end - 1:
        start += 1
        end -= 1
        while start < end and raw[start].isspace():
            start += 1
        while end > start and raw[end - 1].isspace():
            end -= 1
    return raw[start:end]


def _heredoc_parts(expression: str) -> tuple[bool, list[str], int]:
    """Locate the first heredoc terminator without consuming a later field."""
    lines = expression.splitlines(keepends=True)
    opener = re.fullmatch(r"<<(-?)\s*([A-Za-z_][A-Za-z0-9_]*)\s*", lines[0].rstrip("\r\n"))
    if opener and len(lines) >= 2:
        end = len(lines[0])
        for index, line in enumerate(lines[1:], 1):
            end += len(line)
            terminator = line.strip() if opener.group(1) else line.rstrip()
            if terminator == opener.group(2):
                return bool(opener.group(1)), lines[1:index], end
    raise ValueError("Literal ECS heredoc string could not be parsed.")


def _heredoc_string(expression: str) -> str:
    """Read a heredoc, preserving its newline and optional indentation trim."""
    indented, content, end = _heredoc_parts(expression)
    if expression[end:].strip():
        raise ValueError("Literal ECS heredoc string could not be parsed.")
    if indented:
        indentation = min(
            (len(line) - len(line.lstrip(" \t")) for line in content if line.strip()),
            default=0,
        )
        content = [line[indentation:] if line.strip() else line for line in content]
    return "".join(content)


def _quoted_hcl_string(expression: str) -> str | None:
    """Decode a quoted HCL literal, including its long Unicode escape form."""
    def unicode_escape(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("\\U"):
            return json.dumps(chr(int(token[2:], 16)))[1:-1]
        return token

    try:
        normalized = re.sub(r"\\(?:U[0-9a-fA-F]{8}|.)", unicode_escape, expression)
        value = json.loads(normalized)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _object_field(body: str, name: str, policy: Any) -> str | None:
    """Read one direct object field expression without evaluating it."""
    body = _uncomment_hcl(body, policy)
    depths, codes, _ = policy._lex_hcl(body)
    pattern = r'(?P<key>"(?:\\.|[^"\\])*"|(?<![\w-])[A-Za-z_][\w-]*)\s*(?P<delimiter>[:=])\s*'
    for match in re.finditer(pattern, body):
        delimiter = match.start("delimiter")
        if not codes[delimiter] or depths[delimiter] != 1:
            continue
        key = match.group("key")
        if key.startswith('"'):
            start = match.start("key")
            # A key's opening quote follows code. Quotes inside a string,
            # interpolation or heredoc are not object-key tokens.
            if start and not codes[start - 1]:
                continue
            key = _quoted_hcl_string(key)
        elif not codes[match.start("key")]:
            continue
        if key != name:
            continue
        start = match.end()
        if body.startswith("<<", start):
            _, _, end = _heredoc_parts(body[start:])
            return _ungroup_hcl(body[start:start + end], policy)
        bracket = paren = 0
        end = len(body)
        for i in range(start, len(body)):
            if not codes[i]:
                continue
            char = body[i]
            if depths[i] == 1 and bracket == 0 and paren == 0 and char in ",\n}":
                end = i
                break
            bracket += (char == "[") - (char == "]")
            paren += (char == "(") - (char == ")")
        return _ungroup_hcl(body[start:end], policy)
    return None


def _literal_object_string(body: str, name: str, policy: Any) -> str | None:
    expression = _object_field(body, name, policy)
    if expression is None:
        return None
    if not expression.startswith("<<"):
        return _quoted_hcl_string(expression)
    value = _heredoc_string(expression)
    # Keep literal text around interpolations, but never inspect their
    # unevaluated expressions as URL text. Template directives remain dynamic.
    output: list[str] = []
    i = 0
    while i < len(value):
        if value.startswith(("$${", "%%{"), i):
            output.append(value[i + 1:i + 3])
            i += 3
        elif value.startswith("%{", i):
            return None
        elif value.startswith("${", i):
            expression = value[i + 2:]
            depths, codes, _ = policy._lex_hcl(expression)
            end = next(
                (j for j, char in enumerate(expression) if char == "}" and codes[j] and depths[j] == 0),
                None,
            )
            if end is None:
                return None
            output.append("<interpolation>")
            i += end + 3
        else:
            output.append(value[i])
            i += 1
    return "".join(output)


def _literal_list_objects(expression: str, policy: Any) -> list[str]:
    """Read direct object items in a literal list, allowing only grouping."""
    raw = _ungroup_hcl(expression, policy)
    if not raw.startswith("[") or not raw.endswith("]"):
        return []
    depths, codes, _ = policy._lex_hcl(raw)
    start = 1
    bracket = paren = 0
    items: list[str] = []
    for i in range(1, len(raw)):
        if not codes[i]:
            continue
        char = raw[i]
        if depths[i] == 0 and bracket == 0 and paren == 0:
            if char == "]":
                if i != len(raw) - 1:
                    return []
                items.append(raw[start:i])
                break
            if char == ",":
                items.append(raw[start:i])
                start = i + 1
        bracket += (char == "[") - (char == "]")
        paren += (char == "(") - (char == ")")
    else:
        return []
    objects: list[str] = []
    for item in items:
        item = _ungroup_hcl(item, policy)
        if item.startswith("{"):
            block, end = policy._extract_braced_block(item, 0)
            if end == len(item):
                objects.append(block)
    return objects


def _inline_database_urls(expression: str, policy: Any) -> list[str]:
    """Read literal ECS environment entries; do not evaluate Terraform."""
    raw = _ungroup_hcl(expression, policy)
    encoded = re.match(r"jsonencode\s*(?=\()", raw)
    if encoded:
        argument = raw[encoded.end():].strip()
        ungrouped = _ungroup_hcl(argument, policy)
        # A call followed by another operation is not a literal definition.
        if ungrouped == argument:
            return []
        raw = ungrouped
    heredoc = raw.startswith("<<")
    if heredoc:
        raw = _heredoc_string(raw)
    literal_string = raw.startswith('"')
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, str):
            raw = decoded
            decoded = json.loads(raw)
    except (ValueError, TypeError):
        if heredoc or literal_string:
            # Entire template expressions remain dynamic. A literal JSON
            # document that cannot be inspected must not receive a pass.
            if re.fullmatch(r"\s*(?:\$\{.*\}|%\{.*)\s*", raw, re.DOTALL):
                return []
            raise ValueError("Literal ECS container definitions JSON could not be parsed.") from None
        decoded = None
    if isinstance(decoded, list):
        values = []
        for container in decoded:
            if not isinstance(container, dict):
                continue
            environment = container.get("environment", [])
            if not isinstance(environment, list):
                raise ValueError("Literal ECS environment must be an array.")
            values.extend(
                entry["value"]
                for entry in environment
                if isinstance(entry, dict) and entry.get("name") == "DATABASE_URL"
                and isinstance(entry.get("value"), str)
            )
        return values

    # The other supported form is jsonencode([{ environment = [{ name = ...,
    # value = ... }] }]). Limit scanning to direct objects in environment lists,
    # so labels, comments and nested objects cannot masquerade as credentials.
    if not encoded:
        return []
    values: list[str] = []
    for container in _literal_list_objects(raw, policy):
        environment = _object_field(container, "environment", policy)
        if environment is None:
            continue
        for entry in _literal_list_objects(environment, policy):
            if _literal_object_string(entry, "name", policy) == "DATABASE_URL":
                value = _literal_object_string(entry, "value", policy)
                if value is not None:
                    values.append(value)
    return values


def _ecs_database_credentials(
    resources: list[Resource], policy: Any, findings: list[Finding],
) -> None:
    for resource in resources:
        if resource.kind != "aws_ecs_task_definition":
            continue
        expression = _attr(resource.body, "container_definitions", policy)
        if expression is None:
            continue
        for value in _inline_database_urls(expression, policy):
            if re.search(
                r"://[^@\s]*:(?:PLACEHOLDER|REDACTED|CHANGE_ME|REPLACE_ME)@",
                value, re.IGNORECASE,
            ):
                findings.append(Finding(
                    resource.file, resource.line, "ecs_database_password_placeholder",
                    f"{resource.address}: DATABASE_URL contains a placeholder password; "
                    "wire the actual database credential through a secret reference.",
                ))


def _rds_windows(resources: list[Resource], policy: Any, windows: Any, findings: list[Finding]) -> None:
    for resource in resources:
        if resource.kind not in {"aws_db_instance", "aws_rds_cluster"}:
            continue
        prefix = "preferred_" if resource.kind == "aws_rds_cluster" else ""
        backup = _attr(resource.body, prefix + "backup_window", policy)
        maintenance = _attr(resource.body, prefix + "maintenance_window", policy)
        literals: dict[str, str] = {}
        for name, raw in (("backup", backup), ("maintenance", maintenance)):
            if raw is None:
                continue
            literal = _string(raw)
            if literal is None:
                findings.append(Finding(
                    resource.file, resource.line, "rds_windows_unverified",
                    f"{resource.address}: {name} window is not a literal string; resolve and check it before deployment.",
                ))
                continue
            try:
                # Validate each supplied window even if its counterpart is
                # AWS-selected. The comparison value only exercises the
                # helper's parser; this boolean is intentionally ignored.
                if name == "backup":
                    windows.windows_overlap(literal, "sun:00:00-sun:00:30")
                else:
                    windows.windows_overlap("00:00-00:30", literal)
            except ValueError as exc:
                findings.append(Finding(
                    resource.file, resource.line, "rds_windows_invalid",
                    f"{resource.address}: {exc}",
                ))
            else:
                literals[name] = literal
        if len(literals) == 2 and windows.windows_overlap(
            literals["backup"], literals["maintenance"]
        ):
            findings.append(Finding(
                resource.file, resource.line, "rds_windows_overlap",
                f"{resource.address}: backup and maintenance windows overlap.",
            ))


def _database_port(resource: Resource, policy: Any) -> int | None:
    explicit = _attr(resource.body, "port", policy)
    if explicit is not None:
        return _number(explicit)
    engine = _string(_attr(resource.body, "engine", policy))
    if engine in {"postgres", "aurora-postgresql"}:
        return 5432
    if engine in {"mysql", "mariadb", "aurora", "aurora-mysql"}:
        return 3306
    return None


def _allows_port(body: str, port: int, policy: Any) -> bool:
    expression = _attr(body, "protocol", policy) or _attr(body, "ip_protocol", policy)
    protocol = _string(expression) or (expression if expression in {"-1", "6"} else None)
    if protocol == "-1":
        return True
    low = _number(_attr(body, "from_port", policy))
    high = _number(_attr(body, "to_port", policy))
    return protocol in {"tcp", "6"} and low is not None and high is not None and low <= port <= high


def _eb_database_access(resources: list[Resource], policy: Any, findings: list[Finding]) -> None:
    databases = [r for r in resources if r.kind in {"aws_db_instance", "aws_rds_cluster"}]
    environments = [r for r in resources if r.kind == "aws_elastic_beanstalk_environment"]
    if not databases or not environments:
        return
    by_address = {r.address: r for r in resources if _instances(r, policy) is True}
    for environment in environments:
        if _instances(environment, policy) is None:
            findings.append(Finding(
                environment.file, environment.line, "resource_instances_unverified",
                f"{environment.address}: dynamic count/for_each cannot establish deployed network access.",
            ))
            continue
        settings = _own_blocks(environment.body, "setting", policy)
        attached: set[str] = set()
        unknown_attachment = False
        attachment_count = 0
        for setting in settings:
            if (_string(_attr(setting, "namespace", policy)) == "aws:autoscaling:launchconfiguration"
                    and _string(_attr(setting, "name", policy)) == "SecurityGroups"):
                attachment_count += 1
                refs = _sg_refs(_attr(setting, "value", policy))
                if refs is None:
                    unknown_attachment = True
                else:
                    attached |= refs
        if unknown_attachment or not attached or attachment_count > 1:
            findings.append(Finding(
                environment.file, environment.line, "eb_database_security_group",
                f"{environment.address}: explicit instance SecurityGroups are missing or cannot be resolved.",
            ))
            continue
        linked: set[str] = set()
        opaque_secret = False
        unverified_secret = False
        for setting in settings:
            name = _string(_attr(setting, "name", policy)) or ""
            if re.search(r"DATABASE|(^|_)DB(_|$)|(^|_)RDS(_|$)", name, re.IGNORECASE):
                value = _attr(setting, "value", policy) or ""
                linked.update(re.findall(r"(aws_(?:db_instance|rds_cluster)\.[A-Za-z0-9_-]+)\.", value))
                if _string(_attr(setting, "namespace", policy)) == (
                    "aws:elasticbeanstalk:application:environmentsecrets"
                ):
                    literal = _string(value)
                    reference = re.fullmatch(
                        r"(aws_(?:secretsmanager_secret|ssm_parameter)\.[A-Za-z0-9_-]+)\.arn",
                        value,
                    )
                    if reference:
                        # The secret's contents may be populated outside Terraform.
                        # Its ARN alone does not establish which database is used.
                        if reference.group(1) in by_address:
                            opaque_secret = True
                        else:
                            unverified_secret = True
                    elif literal and re.fullmatch(
                        r"arn:[a-z0-9-]+:(?:"
                        r"secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+"
                        r"|ssm:[a-z0-9-]+:[0-9]{12}:parameter/[A-Za-z0-9/_+=.@-]+)",
                        literal,
                    ):
                        opaque_secret = True
                    else:
                        unverified_secret = True
        targets = (
            databases if opaque_secret or not linked
            else [r for r in databases if r.address in linked]
        )
        if linked - {r.address for r in databases}:
            findings.append(Finding(
                environment.file, environment.line, "eb_database_mapping_unverified",
                f"{environment.address}: a referenced database resource is missing.",
            ))
        if unverified_secret:
            findings.append(Finding(
                environment.file, environment.line, "eb_database_mapping_unverified",
                f"{environment.address}: database secret ARN is missing or cannot be resolved.",
            ))
            continue
        if not linked and len(databases) > 1 and not opaque_secret:
            findings.append(Finding(
                environment.file, environment.line, "eb_database_mapping_unverified",
                f"{environment.address}: multiple databases and no explicit database link; verify access manually.",
            ))
            continue
        # Generated environmentsecrets settings expose only an opaque secret ARN.
        # Without a database association, prove access to every possible target;
        # never guess an app-to-database mapping from resource or secret names.
        for database in targets:
            if _instances(database, policy) is None:
                findings.append(Finding(
                    database.file, database.line, "resource_instances_unverified",
                    f"{database.address}: dynamic count/for_each cannot establish deployed network access.",
                ))
                continue
            groups = _sg_refs(_attr(database.body, "vpc_security_group_ids", policy))
            port = _database_port(database, policy)
            permitted = False
            if groups is not None and port is not None:
                for group in groups:
                    sg = by_address.get(group)
                    if sg:
                        for ingress in _own_blocks(sg.body, "ingress", policy):
                            sources = _sg_refs(_attr(ingress, "security_groups", policy))
                            is_self = _attr(ingress, "self", policy) == "true" and group in attached
                            if _allows_port(ingress, port, policy) and (
                                is_self or (sources is not None and bool(sources & attached))
                            ):
                                permitted = True
                    for rule in resources:
                        if rule.kind not in {
                            "aws_security_group_rule", "aws_vpc_security_group_ingress_rule",
                        }:
                            continue
                        if _instances(rule, policy) is not True:
                            continue
                        if rule.kind == "aws_security_group_rule" and _string(
                            _attr(rule.body, "type", policy)
                        ) != "ingress":
                            continue
                        target = _sg_refs(_attr(rule.body, "security_group_id", policy))
                        source_attr = (
                            "source_security_group_id" if rule.kind == "aws_security_group_rule"
                            else "referenced_security_group_id"
                        )
                        source = _sg_refs(_attr(rule.body, source_attr, policy))
                        if (target and group in target and source and source & attached
                                and _allows_port(rule.body, port, policy)):
                            permitted = True
            if not permitted:
                findings.append(Finding(
                    environment.file, environment.line, "eb_database_access_unverified",
                    f"{environment.address}: cannot prove an attached instance SG is allowed into "
                    f"{database.address} on its database port; fix or explicitly verify the mapping.",
                ))


_CONNECTION_NAMES = {
    f"{side}_DB_{field}" for side in ("SOURCE", "TARGET")
    for field in ("HOST", "PORT", "USER", "PASSWORD", "NAME")
}


def _shell_tokens(script: str, require_connections: bool = False) -> list[str]:
    """Fingerprint tokens retaining quotes, escapes and command newlines.

    POSIX shlex unquotes both "$MODE" and '$MODE' to the same token, even
    though the latter disables expansion and can bypass a verify guard.
    Preserve the original spelling instead. Only indentation, blank/comment
    lines and explicit backslash-newline continuations are normalized.
    """
    # Normalize only literals at the documented connection-parameter boundary.
    lines = []
    seen: set[str] = set()
    for line in script.splitlines():
        assignment = re.fullmatch(
            r"""\s*((?:SOURCE|TARGET)_DB_(?:HOST|PORT|USER|PASSWORD|NAME))=(["'])(.*)\2\s*(?:#.*)?""",
            line,
        )
        if assignment:
            name, quote, value = assignment.groups()
            # Single quotes allow literal $ and backticks; embedded single quotes
            # and double-quoted expansion/escaping need human review.
            if quote in value or (quote == '"' and any(c in value for c in "$`\\!")):
                raise ValueError("Connection parameters must be simple shell literals.")
            if name in seen:
                raise ValueError(f"Duplicate connection parameter: {name}")
            seen.add(name)
            line = f'{name}="__LITERAL_CONNECTION_VALUE__"'
        lines.append(line)
    if require_connections and seen != _CONNECTION_NAMES:
        raise ValueError("The reviewed connection-parameter assignments are missing or changed.")
    text = _shell_mask("\n".join(lines), comments_only=True).replace("\\\n", "")
    tokens: list[str] = []
    word: list[str] = []
    quote = ""
    escaped = False
    for char in text:
        if escaped:
            word.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            word.append(char)
            escaped = True
        elif quote:
            word.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            word.append(char)
            quote = char
        elif char.isspace():
            if word:
                tokens.append("".join(word))
                word = []
            if char == "\n" and tokens and tokens[-1] != "\n":
                tokens.append("\n")
        else:
            word.append(char)
    if quote or escaped:
        raise ValueError("Unsupported unterminated shell quote or escape.")
    if word:
        tokens.append("".join(word))
    return tokens[:-1] if tokens and tokens[-1] == "\n" else tokens


def _shell_mask(script: str, comments_only: bool = False) -> str:
    """Mask comments, quotes, escapes and parameter expansions for brace matching.

    This deliberately only locates ordinary function definitions. Syntax is also
    checked by Bash, and safety is established by the restricted checks below,
    not by assuming this scanner understands every shell construct.
    """
    # Bash removes an unquoted backslash-newline before recognising comments.
    # A physical "# ..." line can therefore be executable continuation text,
    # e.g. X=value\<newline>#; command. Reject this ambiguous shape instead of
    # deleting it as a comment or trying to implement general Bash lexing.
    if re.search(r"\\\r?\n[ \t]*#", script):
        raise ValueError("Shell continuation into a comment-shaped line requires review.")
    chars = list(script)
    i = 0
    while i < len(script):
        ch = script[i]
        is_comment = ch == "#" and (
            i == 0 or script[i - 1].isspace() or script[i - 1] in ";{}"
        )
        if is_comment:
            end = script.find("\n", i)
            end = len(script) if end < 0 else end
        elif ch in "\"'":
            quote = ch
            end = i + 1
            while end < len(script):
                if script[end] == "\\" and quote == '"':
                    end += 2
                elif script[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
        elif ch == "\\":
            end = i + 2
        elif script.startswith("${", i):
            depth = 1
            end = i + 2
            while end < len(script) and depth:
                depth += (script[end] == "{") - (script[end] == "}")
                end += 1
        elif script.startswith("<<", i):
            match = re.match(r"<<-?([A-Za-z_]\w*)", script[i:])
            if not match:
                raise ValueError("Unsupported shell heredoc form.")
            marker = match.group(1)
            body_start = script.find("\n", i)
            ending = re.search(rf"(?m)^\t*{re.escape(marker)}\s*$", script[body_start + 1:])
            if body_start < 0 or not ending:
                raise ValueError("Unterminated shell heredoc.")
            end = body_start + 1 + ending.end()
        elif ch == "`":
            raise ValueError("Backtick command substitution requires review.")
        else:
            i += 1
            continue
        if is_comment or not comments_only:
            for n in range(i, min(end, len(script))):
                if chars[n] != "\n":
                    chars[n] = " "
        i = end
    return "".join(chars)


def _shell_structure(script: str) -> tuple[str, dict[str, str]]:
    masked = _shell_mask(script)
    functions: dict[str, str] = {}
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*\([ \t]*\)[ \t]*\{", masked):
        if any(start <= match.start() < end for start, end in spans):
            continue
        name = match.group(1)
        if name in functions:
            raise ValueError(f"Duplicate shell function: {name}")
        opening = match.end() - 1
        depth = 1
        end = opening + 1
        while end < len(masked) and depth:
            depth += (masked[end] == "{") - (masked[end] == "}")
            end += 1
        if depth:
            raise ValueError("Unbalanced shell function.")
        functions[name] = script[opening + 1:end - 1]
        spans.append((match.start(), end))
    globals_only = list(script)
    for start, end in spans:
        globals_only[start:end] = " " * (end - start)
    return "".join(globals_only), functions


def _fingerprint(tokens: list[str]) -> str:
    return hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()


# These fingerprints cover only code reachable through the reviewed --verify
# branch and its top-level setup. They deliberately do not cover export_source,
# import_target, or main's migration-only tail. Keeping them beside the shared
# validator avoids a GCP validation dependency on the Heroku skill's documents.
# Tests compare the current source template with these reviewed fingerprints.
_REVIEWED_FUNCTIONS: dict[str, str] = {
    "log": "78f3834a8af3216acd06395d79cbf1a79841c36ff55e324506d192604e1684aa",
    "usage": "c7cc04fd7840f22a630f37579ce8ff197600de6826ce911b279caa499dc18078",
    "check_prerequisites": "2fb8fbedef09bf927d6b365bcc9bd624d1d3f635905ec812d3dc74e82d13ecb9",
    "test_source_connection": "1c4e570509b48a5c87c655520dc9edfd52727a58064e1b37622fb6d031986eee",
    "test_target_connection": "976beaf8dc21e29994eb77eee2c686cace875a8ff193c3a1641031f58eed5085",
    "psql_tables": "bd4d87ff288b744ee9a006dc68b73c062e54299faf85c5486706606bc60628f7",
    "verify_migration": "1658d3c9601a4b6005a5102039148e4210dc725fff5162a153a960e2e138b868",
}
_REVIEWED_GLOBALS = "e9e0116b888896dc7951d5bb4214fd6422dafc61b40eca6f5166a7a56fd3a072"
_REVIEWED_MAIN_PREFIX: tuple[int, str] = (
    73, "dd3b1ccf4ee27db2eb2ebeb056cf0fa3fa81f432cbbbf8794a5d7b6a75529bed",
)


def _reviewed_verify(script: str) -> bool:
    globals_only, functions = _shell_structure(script)
    expected_names = set(_REVIEWED_FUNCTIONS) | {"main", "export_source", "import_target"}
    if set(functions) != expected_names:
        return False
    if _fingerprint(_shell_tokens(globals_only, require_connections=True)) != _REVIEWED_GLOBALS:
        return False
    if any(
        _fingerprint(_shell_tokens(functions[name])) != digest
        for name, digest in _REVIEWED_FUNCTIONS.items()
    ):
        return False
    length, digest = _REVIEWED_MAIN_PREFIX
    return _fingerprint(_shell_tokens(functions["main"])[:length]) == digest


def _simple_verify(script: str) -> bool:
    """Accept a small, inspectable early argument guard, never arbitrary Bash."""
    globals_only, functions = _shell_structure(script)
    if functions:
        return False
    lines = globals_only.splitlines()
    guard = re.compile(
        r"""^\s*if\s+(\[\[?)\s+"?\$(?:\{1(?::?-)?\}|1)"?\s+(?:==|=)\s+"""
        r"""(?:"--verify"|'--verify'|--verify)\s+(\]\]?)\s*;\s*then\s*(?:#.*)?$"""
    )
    found = None
    for i, line in enumerate(lines):
        match = guard.fullmatch(line)
        if match and len(match.group(1)) == len(match.group(2)):
            found = i
            break
    if found is None:
        return False
    # Before the guard, only shell options and literal assignments are allowed.
    for line in lines[:found]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        tokens = shlex.split(_shell_mask(line, comments_only=True))
        if tokens == ["set", "-euo", "pipefail"] or tokens == ["set", "-eu"]:
            continue
        if len(tokens) != 1 or not re.fullmatch(r"[A-Za-z_]\w*=[^$`]*", tokens[0]):
            return False
        if any(operator in line for operator in ("$(", "<", ">", ";", "&", "|")):
            return False
        if tokens[0].split("=", 1)[0] in {
            "PATH", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PS4", "IFS", "PSQLRC",
        }:
            return False
    end = next((i for i in range(found + 1, len(lines)) if lines[i].strip() == "fi"), None)
    if end is None:
        return False
    commands = [
        shlex.split(_shell_mask(line, comments_only=True)) for line in lines[found + 1:end]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    commands = [command for command in commands if command]
    if len(commands) < 2 or commands[-1] not in (["exit", "0"], ["exit", "1"], ["exit", "$?"]):
        return False
    for line in lines[found + 1:end]:
        if re.search(r"[;&|<>]", _shell_mask(line)):
            return False  # Never discard redirects/control operators with env assignments.
        if not line.strip().startswith("exit") and "$" in _shell_mask(line):
            return False  # Unquoted expansions may introduce extra psql options.
        # Quoted expansions can execute too: Bash @E/@P transformations and
        # := assignment can synthesize and evaluate a command substitution
        # even when the original source contains no literal "$(".
        if not line.strip().startswith("exit"):
            expansions = re.findall(r"\$\{([^}]*)\}", line)
            if any(not re.fullmatch(r"[A-Za-z_]\w*", value) for value in expansions):
                return False
            if line.count("${") != len(expansions) or "$[" in line:
                return False
    queries = 0
    for command in commands[:-1]:
        while command and re.fullmatch(r"[A-Za-z_]\w*=[^`]*", command[0]):
            if not command[0].startswith("PGPASSWORD=") or "$(" in command[0]:
                return False
            command = command[1:]
        if not command or command[0] not in {"psql", "/usr/bin/psql"}:
            return False
        # Even a literal SELECT is not read-only if a psql startup file runs
        # additional commands. -X must disable both system and user psqlrc.
        if not any(option in command for option in {"-X", "--no-psqlrc"}):
            return False
        sql_args = [i for i, token in enumerate(command) if token in {"-c", "--command"}]
        if len(sql_args) != 1 or sql_args[0] + 1 >= len(command):
            return False
        if any(token in {"-f", "--file"} or token.startswith("--file=") for token in command):
            return False
        sql = command[sql_args[0] + 1]
        if any(
            re.search(r"`|\$\(|[;&|<>]", token)
            for i, token in enumerate(command[1:], 1) if i != sql_args[0] + 1
        ):
            return False
        # Do not let a second encoded -c/--command or -f/--file option bypass
        # the single literal SELECT check.
        option_values = {
            "-h", "-p", "-U", "-d", "--host", "--port", "--username", "--dbname",
        }
        no_values = {"-X", "--no-psqlrc", "-A", "-t", "-At", "--no-align", "--tuples-only"}
        i = 1
        while i < len(command):
            token = command[i]
            if i == sql_args[0]:
                i += 2
                continue
            if token in option_values:
                if i + 1 >= len(command) or command[i + 1].startswith("-"):
                    return False
                i += 2
                continue
            if token in no_values:
                i += 1
                continue
            if token == "-v" and i + 1 < len(command) and command[i + 1] == "ON_ERROR_STOP=1":
                i += 2
                continue
            if any(token.startswith(option + "=") for option in option_values if option.startswith("--")):
                i += 1
                continue
            # A positional connection string beginning with --command or -f
            # becomes another psql option after shell expansion. Require -d /
            # --dbname (or the explicit host/user/port options) instead.
            return False
        # No arbitrary SQL functions, CTEs, psql meta-commands, multiple
        # statements or interpolation. This is a read-only operation check,
        # not proof that the comparison itself is sufficient for cutover.
        if not re.fullmatch(
            r"SELECT\s+(?:1|version\(\)|count\(\*\)\s+FROM\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)",
            sql.strip().rstrip(";").strip(), re.IGNORECASE,
        ):
            return False
        queries += 1
    return queries > 0


def _bash_syntax(script: str) -> bool:
    try:
        check = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-n"],
            input=script, capture_output=True, text=True, timeout=10,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "BASH_ENV": "/dev/null"},
            check=False,
        )
        return check.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InputError(f"Cannot run read-only Bash syntax check: {exc}") from exc


def _postgres(
    root: Path, resources: list[Resource], policy: Any, findings: list[Finding],
    require_script: bool,
) -> None:
    path = root / "scripts/migrate-postgres.sh"
    if not path.exists() and not path.is_symlink():
        if require_script:
            findings.append(Finding(
                "scripts/migrate-postgres.sh", 0, "postgres_script_missing",
                "PostgreSQL is present but its migration script is missing.",
            ))
        return
    script = _read(root, path)
    relative = path.relative_to(root).as_posix()
    first_line = script.splitlines()[0] if script else ""
    if not re.fullmatch(r"#![ \t]*(?:/usr/bin/env[ \t]+bash|/bin/bash)[ \t]*", first_line):
        findings.append(Finding(
            relative, 1, "postgres_interpreter_unverified",
            "Require a supported Bash shebang without interpreter flags: "
            "#!/usr/bin/env bash or #!/bin/bash.",
        ))
        return
    if not _bash_syntax(script):
        findings.append(Finding(relative, 0, "postgres_script_syntax", "Bash syntax check failed."))
        return
    try:
        verified = _simple_verify(script) or _reviewed_verify(script)
    except ValueError as exc:
        findings.append(Finding(
            relative, 0, "postgres_verify_unverified",
            f"Cannot establish the reviewed early read-only --verify branch: {exc}",
        ))
        return
    if not verified:
        findings.append(Finding(
            relative, 0, "postgres_verify_unverified",
            "Cannot establish a supported early read-only --verify path. Use the reviewed "
            "verification functions/control flow or a simple early SELECT-only branch with "
            "an unconditional exit; alternate shell shapes require review.",
        ))


def _yaml_comment(line: str) -> str:
    single = double = escaped = False
    for i, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and double:
            escaped = True
        elif char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char == "#" and not single and not double and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def _scalar(value: str) -> str:
    value = _yaml_comment(value).strip()
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError("Expected a YAML string.")
        return parsed
    if value.startswith("'"):
        if not value.endswith("'"):
            raise ValueError("Unterminated YAML string.")
        return value[1:-1].replace("''", "'")
    return value


def _defaults_shell(lines: list[str], start: int, indent: int) -> str | None:
    """Read only block-style defaults.run.shell, without evaluating expressions."""
    shell: str | None = None
    run_indent: int | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip())
        if depth <= indent:
            break
        value = line.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:(?:\s+.*)?", value):
            raise ValueError("Noncanonical workflow run defaults keys require review.")
        if value.startswith("run:"):
            if value != "run:":
                raise ValueError("Flow-style workflow run defaults require review.")
            run_indent = depth
        elif run_indent is not None and depth > run_indent and value.startswith("shell:"):
            if shell is not None:
                raise ValueError("Duplicate workflow default shell.")
            shell = _scalar(value.partition(":")[2])
    return shell


def _environment(lines: list[str], start: int, indent: int) -> dict[str, str]:
    values: dict[str, str] = {}
    own_indent: int | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip())
        if depth <= indent:
            break
        own_indent = depth if own_indent is None else own_indent
        if depth != own_indent:
            raise ValueError("Nested workflow environment values require review.")
        match = re.fullmatch(r"([A-Za-z_]\w*):(?:\s+(.*))?", line.strip())
        if not match:
            raise ValueError("Expected a literal workflow environment mapping.")
        key, value = match.groups()
        if key in values:
            raise ValueError("Duplicate workflow environment key.")
        if key in _EXECUTION_ENVIRONMENT_KEYS:
            raise ValueError("Workflow execution-environment overrides require review.")
        values[key] = _scalar(value or "")
    return values


def _workflow_jobs(text: str) -> list[dict[str, Any]]:
    """Read the conventional block-style jobs/steps subset we generate.

    YAML anchors, noncanonical mapping keys, merge keys, flow-style jobs/steps,
    and reusable workflows require review and are not silently accepted here.
    """
    lines = text.splitlines()
    if any("\t" in line[:len(line) - len(line.lstrip())] for line in lines):
        raise ValueError("Tabs in YAML indentation are unsupported.")
    active = [_yaml_comment(line) for line in lines]
    for line in active:
        if line and not line[0].isspace() and line not in {"---", "..."}:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:(?:\s+.*)?", line):
                raise ValueError("Noncanonical workflow root keys require review.")
    root_shell: str | None = None
    root_env: dict[str, str] = {}
    env_lines = [i for i, line in enumerate(active) if line.startswith("env:")]
    if len(env_lines) > 1:
        raise ValueError("Duplicate workflow environment.")
    if env_lines:
        index = env_lines[0]
        if active[index] != "env:":
            raise ValueError("Flow-style workflow environment requires review.")
        root_env = _environment(active, index, 0)
    root_defaults = [i for i, line in enumerate(active) if line.startswith("defaults:")]
    if len(root_defaults) > 1:
        raise ValueError("Duplicate workflow defaults.")
    if root_defaults:
        index = root_defaults[0]
        if active[index] != "defaults:":
            raise ValueError("Flow-style workflow defaults require review.")
        root_shell = _defaults_shell(active, index, 0)
    jobs_line = next((i for i, line in enumerate(active) if line == "jobs:"), None)
    if jobs_line is None:
        raise ValueError("Expected block-style jobs.")
    jobs: list[dict[str, Any]] = []
    job: dict[str, Any] | None = None
    step: dict[str, Any] | None = None
    job_indent: int | None = None
    steps_indent: int | None = None
    step_indent: int | None = None
    i = jobs_line + 1
    while i < len(lines):
        line = active[i]
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            break
        if re.search(r"(^|:\s+)[&*!]|^<<:", stripped):
            raise ValueError("YAML aliases, anchors, tags, and merges are unsupported.")
        if job_indent is None:
            job_indent = indent
        if indent == job_indent:
            match = re.fullmatch(r"([A-Za-z0-9_-]+):", stripped)
            if not match:
                raise ValueError("Expected a block-style job mapping.")
            job = {
                "name": match.group(1), "steps": [], "text": [], "condition": None,
                "shell": root_shell, "runner": None, "env": dict(root_env),
                "has_dependencies": False,
            }
            if any(existing["name"] == job["name"] for existing in jobs):
                raise ValueError("Duplicate workflow job ID.")
            jobs.append(job)
            steps_indent = step_indent = None
            step = None
            i += 1
            continue
        if job is None:
            raise ValueError("Workflow content precedes a job.")
        job["text"].append(line)
        if indent == job_indent + 2:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:(?:\s+.*)?", stripped):
                raise ValueError("Noncanonical workflow job keys require review.")
            if stripped.startswith("if:"):
                job["condition"] = _scalar(stripped.partition(":")[2])
            elif stripped.startswith("needs:"):
                job["has_dependencies"] = True
            elif stripped.startswith("runs-on:"):
                job["runner"] = _scalar(stripped.partition(":")[2])
            elif stripped.startswith("defaults:"):
                if stripped != "defaults:":
                    raise ValueError("Flow-style job defaults require review.")
                job["shell"] = _defaults_shell(active, i, indent) or root_shell
            elif stripped.startswith("env:"):
                if stripped != "env:":
                    raise ValueError("Flow-style job environment requires review.")
                job["env"].update(_environment(active, i, indent))
        if stripped.startswith("steps:") and indent == job_indent + 2:
            if stripped != "steps:":
                raise ValueError("Flow-style steps are unsupported.")
            steps_indent = indent
            step = None
            i += 1
            continue
        if steps_indent is None:
            i += 1
            continue
        if indent <= steps_indent:
            steps_indent = step_indent = None
            step = None
            i += 1
            continue
        if stripped.startswith("- "):
            if step_indent is not None and indent != step_indent:
                raise ValueError("Nested step lists are unsupported.")
            step_indent = indent
            step = {"line": i + 1, "env": {}}
            job["steps"].append(step)
            stripped = stripped[2:]
        elif step is None:
            raise ValueError("Expected a step list.")
        elif indent > step_indent + 2:
            # Inputs under with/env are not the step's own id/run/uses keys.
            i += 1
            continue
        elif indent != step_indent + 2:
            raise ValueError("Unsupported step indentation.")
        key_value = re.fullmatch(r"([A-Za-z0-9_-]+):(?:\s+(.*))?", stripped)
        if not key_value:
            raise ValueError("Unsupported step property syntax.")
        key, value = key_value.groups()
        value = value or ""
        if key == "env":
            if value:
                raise ValueError("Flow-style step environment requires review.")
            property_indent = indent + (2 if line.lstrip().startswith("- ") else 0)
            step["env"] = _environment(active, i, property_indent)
        if key in {"run", "id", "uses", "if", "shell"}:
            if key in step:
                raise ValueError(f"Duplicate step property: {key}")
            if key == "run" and value in {"|", "|-", "|+"}:
                body: list[str] = []
                property_indent = indent + (2 if line.lstrip().startswith("- ") else 0)
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_line.strip() and next_indent <= property_indent:
                        break
                    body.append(next_line)
                    job["text"].append(next_line)
                    i += 1
                margin = min(
                    (len(item) - len(item.lstrip()) for item in body if item.strip()), default=0,
                )
                step["run"] = "\n".join(item[margin:] for item in body)
                continue
            if key == "run" and value.startswith((">", "|")):
                raise ValueError("Unsupported run block style.")
            step[key] = _scalar(value)
        # Nested with/env mappings need no interpretation, but their expressions
        # remain in job["text"] for output-reference validation.
        i += 1
    if not jobs:
        raise ValueError("No workflow jobs found.")
    return jobs


def _condition(value: str | None) -> bool | None:
    if value is None:
        return True
    value = value.strip().lower()
    expression = re.fullmatch(r"\$\{\{\s*(true|false)\s*\}\}", value)
    if expression:
        value = expression.group(1)
    if value in {"true", "false"}:
        return value == "true"
    return None


def _run_shell(step: dict[str, Any], job: dict[str, Any]) -> str | None:
    explicit = step["shell"] if "shell" in step else job.get("shell")
    if explicit is not None:
        return explicit
    runner = job.get("runner") or ""
    if re.fullmatch(r"(?:ubuntu|macos)(?:-[a-zA-Z0-9.]+)*", runner):
        return "bash"
    return None


def _logical_shell_lines(script: str) -> list[str]:
    """Read whole run blocks without turning quoted/heredoc text into commands."""
    if re.search(r"\\\r?\n[ \t]*#", script):
        raise ValueError("Shell continuation into a comment-shaped line requires review.")
    lines: list[str] = []
    current: list[str] = []
    quote = ""
    i = 0
    while i < len(script):
        char = script[i]
        if char == "\\" and quote != "'":
            if script[i + 1:i + 2] == "\n":
                i += 2
                continue
            if script[i + 1:i + 3] == "\r\n":
                i += 3
                continue
            current.append(script[i:i + 2])
            i += 2
            continue
        if quote:
            if char in "\r\n":
                raise ValueError("Multiline quoted shell strings require review.")
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif script[i:i + 2] == "<<":
            raise ValueError("Shell heredocs and here-strings require review.")
        elif char == "#" and (
            not current or current[-1][-1:].isspace() or current[-1][-1:] in ";{}"
        ):
            end = script.find("\n", i)
            i = len(script) if end < 0 else end
            continue
        elif char in "\r\n":
            if "".join(current).strip():
                lines.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    if quote:
        raise ValueError("Unterminated shell string.")
    if "".join(current).strip():
        lines.append("".join(current).strip())
    return lines


def _direct_commands(
    lines: list[str], environment: dict[str, str], *, allow_assignments: bool = True,
) -> list[list[str]]:
    """Only unconditional commands and finite, literal nonempty for loops.

    The source template's for loop is supported only when its environment list
    resolves to nonempty literal environment names. No arbitrary shell control
    flow is inferred from the presence of a command-shaped substring.
    """
    environment = dict(environment)
    commands: list[list[str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Shell expansions can mutate the parent execution context even in an
        # echo argument or assignment. Support plain variable interpolation and
        # the source template's one reviewed AWS lookup, not arbitrary shell
        # programs hidden inside arguments.
        bucket_lookup = (
            'BUCKET="$(aws elasticbeanstalk create-storage-location '
            '--query S3Bucket --output text)"'
        )
        if "`" in line or "$[" in line or ("$(" in line and line != bucket_lookup):
            raise ValueError("Shell command/arithmetic substitution requires review.")
        for expansion in re.finditer(r"\$\{([^}]*)\}", line):
            if not re.fullmatch(r"[A-Za-z_]\w*", expansion.group(1)):
                raise ValueError("Only plain shell variable interpolation is supported.")
        if line.count("${") != len(re.findall(r"\$\{[^}]*\}", line)):
            raise ValueError("Unresolved shell parameter expansion requires review.")
        loop = re.fullmatch(r"for\s+([A-Za-z_]\w*)\s+in(?:\s+(.*?))?\s*;\s*do", line)
        if loop:
            variable, values = loop.groups()
            if variable in _EXECUTION_ENVIRONMENT_KEYS:
                raise ValueError("Shell loop changes the execution environment.")
            values = (values or "").strip()
            reference = re.fullmatch(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))", values)
            if reference:
                values = environment.get(reference.group(1) or reference.group(2), "")
            # Only a known, nonempty list of literal EB environment names.
            if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\s+[A-Za-z0-9_-]+)*", values):
                raise ValueError("Loop iteration list is empty or unresolved; deployment is unverified.")
            try:
                end = lines.index("done", i + 1)
            except ValueError as exc:
                raise ValueError("Unsupported shell loop structure.") from exc
            if any(re.match(r"(?:for|done)\b", body) for body in lines[i + 1:end]):
                raise ValueError("Nested shell loops require review.")
            items = values.split()
            commands.extend(_direct_commands(
                lines[i + 1:end], {**environment, variable: items[0]},
                allow_assignments=False,
            ))
            environment[variable] = items[-1]
            i = end + 1
            continue
        masked = _shell_mask(line)
        if re.search(r"[&|<>{}()]", masked):
            raise ValueError("Shell grouping, conditions, pipelines, and redirections require review.")
        # Split before unquoting so literal ";" arguments remain data.
        parts: list[list[str]] = []
        start = 0
        for separator in re.finditer(";", masked):
            parts.append(shlex.split(line[start:separator.start()]))
            start = separator.end()
        parts.append(shlex.split(line[start:]))
        for command in parts:
            assignments: list[str] = []
            while command and re.fullmatch(r"[A-Za-z_]\w*\+?=.*", command[0]):
                assignments.append(command[0])
                command = command[1:]
            if assignments and not allow_assignments:
                raise ValueError("Assignments inside shell loops require review.")
            for assignment in assignments:
                name = assignment.split("=", 1)[0].rstrip("+")
                if name in _EXECUTION_ENVIRONMENT_KEYS:
                    raise ValueError("Shell execution-environment mutation requires review.")
            if not command:
                for assignment in assignments:
                    name, value = assignment.split("=", 1)
                    if name.endswith("+") or "$" in value or "`" in value:
                        environment.pop(name.rstrip("+"), None)
                    else:
                        environment[name] = value
                continue
            # This is intentionally an allowlist of direct command words,
            # including the source template's preparation/logging commands.
            # Dynamic words, wrappers and shell builtins such as hash/kill can
            # suppress or redirect a later AWS command and require review.
            if not command or command[0] not in {
                "aws", "eb", "zip", "docker", "echo", "set",
            }:
                raise ValueError("Unsupported or dynamic shell command word requires review.")
            if command[0] == "set" and command not in (
                ["set", "-euo", "pipefail"], ["set", "-eu"], ["set", "-e"],
                ["set", "-o", "pipefail"],
            ):
                raise ValueError("Unsupported shell execution options.")
            commands.append(command)
        i += 1
    return commands


def _is_deploy_command(command: list[str]) -> bool:
    if any(token in {"--help", "-h", "--generate-cli-skeleton"} for token in command):
        return False
    if len(command) >= 2 and command[0:2] == ["eb", "deploy"]:
        return True
    if not command or command[0] != "aws":
        return False
    index = 1
    global_values = {
        "--profile", "--region", "--output", "--query", "--endpoint-url",
        "--ca-bundle", "--cli-read-timeout", "--cli-connect-timeout",
    }
    global_flags = {
        "--debug", "--no-verify-ssl", "--no-paginate", "--no-sign-request",
        "--no-cli-pager", "--no-cli-auto-prompt",
    }
    while index < len(command) and command[index].startswith("--"):
        option = command[index]
        if option in global_values:
            index += 2
        elif option in global_flags or any(
            option.startswith(name + "=") for name in global_values
        ):
            index += 1
        else:
            break
    if command[index:index + 2] != ["elasticbeanstalk", "update-environment"]:
        return False
    return any(token == "--version-label" or token.startswith("--version-label=")
               for token in command[index + 2:])


def _deploy_command(script: str, environment: dict[str, str] | None = None) -> bool:
    commands = _direct_commands(_logical_shell_lines(script), environment or {})
    return any(_is_deploy_command(command) for command in commands)


def _workflows(
    root: Path, resources: list[Resource], policy: Any,
    findings: list[Finding], require_workflow: bool,
) -> None:
    has_eb = any(r.kind == "aws_elastic_beanstalk_environment" for r in resources)
    paths = _files(root, ".github/workflows", (".yml", ".yaml"))
    # CodePipeline can satisfy the default deployment check, but a retained
    # pipeline cannot replace an explicitly selected GitHub Actions workflow.
    has_pipeline = any(
        r.kind == "aws_codepipeline" and _instances(r, policy) is True for r in resources
    )
    pipeline_satisfies_requirement = has_pipeline and not require_workflow
    expect_deployment = require_workflow or (
        has_eb and any(path.stem == "deploy-eb" for path in paths)
    )
    if expect_deployment and not paths and not pipeline_satisfies_requirement:
        findings.append(Finding(
            ".github/workflows", 0, "eb_deploy_missing",
            "The selected GitHub Actions deployment requires a generated workflow."
            if require_workflow else
            "Elastic Beanstalk has neither a generated workflow nor CodePipeline.",
        ))
    found_deployment = False
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            jobs = _workflow_jobs(_read(root, path))
        except (ValueError, TypeError) as exc:
            findings.append(Finding(relative, 0, "workflow_unverified", str(exc)))
            continue
        for job in jobs:
            ids = [step["id"] for step in job["steps"] if step.get("id")]
            if len(ids) != len(set(ids)):
                findings.append(Finding(relative, 0, "workflow_duplicate_step_id", f"{job['name']}: duplicate step IDs."))
            source = "\n".join(job["text"])
            for name in sorted(set(re.findall(r"\bsteps\.([A-Za-z0-9_-]+)\.outputs\b", source))):
                if name not in ids:
                    findings.append(Finding(
                        relative, 0, "workflow_step_reference",
                        f"{job['name']}: steps.{name}.outputs references a missing step ID in this job.",
                    ))
            if re.search(r"\bsteps\s*\[", source):
                findings.append(Finding(
                    relative, 0, "workflow_reference_unverified",
                    f"{job['name']}: bracket-style step references require manual validation.",
                ))
            if _condition(job["condition"]) is False:
                continue
            for step in job["steps"]:
                if _condition(step.get("if")) is False:
                    continue
                uses = step.get("uses", "")
                script = step.get("run", "")
                deploy_action = uses.startswith("einaregilsson/beanstalk-deploy@")
                try:
                    deploy_run = bool(script) and _deploy_command(
                        script, {**job["env"], **step["env"]},
                    )
                except ValueError as exc:
                    if expect_deployment and re.search(r"elasticbeanstalk|\beb\s+deploy\b", script):
                        findings.append(Finding(
                            relative, step["line"], "workflow_run_unverified", str(exc),
                        ))
                    continue
                if not deploy_action and not deploy_run:
                    continue
                if job["has_dependencies"]:
                    findings.append(Finding(
                        relative, step["line"], "workflow_dependency_unverified",
                        "Deployment depends on other jobs; verify their execution before deployment.",
                    ))
                    continue
                if _condition(job["condition"]) is None or _condition(step.get("if")) is None:
                    findings.append(Finding(
                        relative, step["line"], "workflow_condition_unverified",
                        "Deployment has an unevaluated condition; confirm when it runs.",
                    ))
                    continue
                if deploy_action:
                    found_deployment = True
                if deploy_run:
                    if _run_shell(step, job) not in {"bash", "sh"}:
                        findings.append(Finding(
                            relative, step["line"], "workflow_shell_unverified",
                            "Deployment step uses an unsupported shell.",
                        ))
                    elif not _bash_syntax(script):
                        findings.append(Finding(
                            relative, step["line"], "workflow_run_syntax",
                            "Deployment step fails Bash syntax validation.",
                        ))
                    else:
                        found_deployment = True
    if expect_deployment and paths and not found_deployment and not pipeline_satisfies_requirement:
        findings.append(Finding(
            ".github/workflows", 0, "eb_deploy_missing",
            "No active, supported EB deploy action, `eb deploy`, or AWS update-environment "
            "--version-label command found. Comments and echo statements do not deploy.",
        ))


def validate(
    migration_dir: Path, *, require_postgres_script: bool = False,
    require_eb_workflow: bool = False,
) -> dict[str, Any]:
    root = migration_dir.resolve(strict=True)
    if not root.is_dir():
        raise InputError("Migration directory is not a directory.")
    policy, windows = _dependencies()
    findings: list[Finding] = []
    resources = _resources(root, policy, findings)
    try:
        _ecs_database_credentials(resources, policy, findings)
        _rds_windows(resources, policy, windows, findings)
        _eb_database_access(resources, policy, findings)
        _postgres(root, resources, policy, findings, require_postgres_script)
        _workflows(root, resources, policy, findings, require_eb_workflow)
    except ValueError as exc:
        findings.append(Finding("terraform", 0, "artifact_shape_unverified", str(exc)))
    status = "ARTIFACTS_FAIL" if findings else "ARTIFACTS_OK"
    return {
        "schema_version": 1,
        "producer": "validate-migration-artifacts",
        "artifact_status": status,
        "verdict": status,
        "checks_run": [
            "postgres_verify", "eb_database_access", "workflow_deploy", "rds_windows",
            "ecs_database_credentials",
        ],
        "scope": [
            "supported PostgreSQL verification control flow and Bash syntax",
            "explicit Elastic Beanstalk to RDS security-group references",
            "GitHub Actions step IDs and presence of an EB deployment operation",
            "literal RDS backup and maintenance window overlap",
            "placeholder passwords in literal ECS DATABASE_URL environment entries",
        ],
        "limitations": [
            "Static checks do not prove deployment success or arbitrary Bash safety.",
            "Dynamic container definitions and secret retrieval code are not evaluated.",
            "Unsupported shapes require review; Terraform validation and policy checks remain separate gates.",
        ],
        "findings": [asdict(finding) for finding in sorted(set(findings))],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    reserved = {
        ".phase-status.json", "preferences.json", "inventory.json", "plan.json",
        "aws-design.json", "cost-estimate.json", "generation-warnings.json",
    }
    if path.suffix != ".json" or path.name in reserved:
        raise InputError("Report destination must be a separate .json report, never phase state.")
    if path.is_symlink():
        raise InputError("Report destination must not be a symlink.")
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise InputError("Refusing to overwrite a preexisting input or unrelated report.") from exc
        if not isinstance(previous, dict) or previous.get("producer") != "validate-migration-artifacts":
            raise InputError("Refusing to overwrite a preexisting input or unrelated report.")
    try:
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Cannot write requested report: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_dir", type=Path)
    parser.add_argument(
        "--require-postgres-script", action="store_true",
        help="Require Heroku's migrate-postgres.sh when PostgreSQL is present.",
    )
    parser.add_argument(
        "--require-eb-workflow", action="store_true",
        help="Require a real EB deployment workflow when GitHub Actions is the selected deploy method.",
    )
    parser.add_argument(
        "--json", nargs="?", const="-", metavar="REPORT_PATH",
        help="Write a separate JSON report, or use '-' for JSON on stdout.",
    )
    args = parser.parse_args(argv)
    try:
        report = validate(
            args.migration_dir, require_postgres_script=args.require_postgres_script,
            require_eb_workflow=args.require_eb_workflow,
        )
    except (InputError, OSError, RuntimeError) as exc:
        report = {
            "schema_version": 1, "producer": "validate-migration-artifacts",
            "artifact_status": "ARTIFACTS_ERROR", "verdict": "ARTIFACTS_ERROR",
            "checks_run": [], "findings": [], "error": str(exc),
        }
        code = 2
    else:
        code = 1 if report["findings"] else 0
    if args.json and args.json != "-":
        try:
            _write_report(Path(args.json), report)
        except InputError as exc:
            print(f"ARTIFACTS_ERROR\n{exc}", file=sys.stderr)
            return 2
    if args.json == "-":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report["verdict"])
        if "error" in report:
            print(report["error"])
        for item in report.get("findings", []):
            print(f"{item['file']}:{item['line']}: {item['rule']}: {item['summary']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
