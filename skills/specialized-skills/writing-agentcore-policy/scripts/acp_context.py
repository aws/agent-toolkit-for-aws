"""Session policy context: one context per agent session, drafts, pre-existing policies.

Port of the ContextManager from the AP4ACP components design. State lives in the
working-directory state dir (see common.state_dir):

    context.json              the policy context (targets, actions, gaps, auth, engine)
    schema.cedarschema        generated Cedar schema (text)
    schema.cedarschema.json   generated Cedar schema (JSON)
    drafts.json               agent-written statements; ids are never reused
    policies.json             pre-existing policies read with the developer's consent
    validations/<sha>.json    last local validation result per statement + schema

No environment variables are read here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import acp_cedar_schema as cedar_schema
import acp_common as common
import acp_discovery as discovery
import acp_schemas as schemas
import acp_validation as validation
from acp_common import SkillError

CONTEXT_VERSION = 1
MAX_LOOKUP = 40
AUTH_TYPES = ("AWS_IAM", "CUSTOM_JWT", "NONE", "AUTHENTICATE_ONLY")
PROTOCOLS = ("MCP", "HTTP")
ROUTE_TRANSLATABLE = "translatable"
ROUTE_NON_TRANSLATABLE = "non-translatable"
ROUTES = (ROUTE_TRANSLATABLE, ROUTE_NON_TRANSLATABLE)
DRAFT_ITEM_KEYS = frozenset(
    {"name", "statement", "rule_text", "idp_claims", "route", "reason", "review_required"}
)
MAX_RECORDED_ERRORS = 20
PRINCIPALS = {
    "CUSTOM_JWT": "AgentCore::OAuthUser",
    "AWS_IAM": "AgentCore::IamEntity",
}


def principal_for(auth_type: Any) -> dict[str, Any]:
    """The context's principal block for an auth type: the same entity type and notes as the
    Gateway route (`acp_discovery.PRINCIPAL_NOTES`), so routing guidance reaches the agent on
    both routes."""
    return {
        "entity_type": PRINCIPALS.get(str(auth_type)),
        "notes": list(discovery.PRINCIPAL_NOTES.get(str(auth_type), [])),
    }


def _review_items(value: Any, problems: list[str]) -> list[str]:
    """`review_required`: one string or a list of strings, each a point the developer must
    decide before the draft may be submitted (an unconfirmed claim name or ARN, a conflict)."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
        problems.append("review_required must be a non-empty string or a list of non-empty strings")
        return []
    out: list[str] = []
    for x in items:
        if x.strip() not in out:
            out.append(x.strip())
    return out


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def split_action_ref(ref: str) -> tuple[str, str]:
    """`<target>___<action>` -> (target, action). Actions may contain ':' and '/'."""
    target, sep, action = ref.partition("___")
    if not sep or not target or not action:
        raise SkillError(
            "invalid_input",
            f"action reference {ref!r} must look like <target>___<action>, "
            "for example orders___GET:/orders/{id} or crm___lookup_customer",
            input="action",
        )
    return target, action


class ContextManager:
    def __init__(self, state: Path) -> None:
        self.state = state
        self.context_file = state / "context.json"
        self.schema_file = state / "schema.cedarschema"
        self.schema_json_file = state / "schema.cedarschema.json"
        self.drafts_file = state / "drafts.json"
        self.policies_file = state / "policies.json"
        self.validations_dir = state / "validations"
        self.exports_file = state / "exports.json"

    # ------------------------------------------------------------------ context

    def has_context(self) -> bool:
        return self.context_file.is_file()

    def get_context(self) -> dict[str, Any]:
        context = common.read_json(self.context_file)
        if not context:
            raise SkillError(
                "no_context",
                "no policy context yet; run `prepare gateway` or `prepare files` first",
            )
        return context

    def get_cedar_schema(self) -> tuple[str, dict[str, Any]]:
        self.get_context()
        if not self.schema_file.is_file():
            raise SkillError("no_context", "the Cedar schema is missing; run `prepare` again")
        return (
            self.schema_file.read_text(encoding="utf-8"),
            common.read_json(self.schema_json_file, {}),
        )

    def prepare_gateway(
        self,
        sess: Any,
        gateway_arn: str,
        *,
        client_id: str | None = None,
        login_failed: bool = False,
    ) -> dict[str, Any]:
        common.parse_gateway_arn(gateway_arn)
        result = discovery.fetch_from_gateway(
            sess, gateway_arn, client_id=client_id, login_failed=login_failed
        )
        if result.get("status") != "ready":
            # login_required / input_required: the current context and drafts stay as they are.
            return result
        context = result["context"]
        context["source"] = "gateway"
        return self._store(context)

    def prepare_files(
        self,
        files: list[dict[str, str | None]],
        *,
        auth_type: str | None,
        gateway_arn: str | None,
        region: str | None,
    ) -> dict[str, Any]:
        missing: list[dict[str, Any]] = []
        resolved: list[Path] = []
        for spec in files:
            path = spec.get("path") or ""
            # Like every agent-supplied file, a schema file must be inside the working directory.
            schema_path = common.confined_path(path, input_name="file")
            if not schema_path.is_file():
                raise SkillError("invalid_input", f"schema file not found: {path}", input="file")
            resolved.append(schema_path)
            protocol = (spec.get("protocol") or "").upper() or None
            if protocol is None:
                missing.append(
                    {
                        "input": "protocol",
                        "file": path,
                        "choices": list(PROTOCOLS),
                        "message": f"Is {path} an MCP tool schema (MCP) or an HTTP API schema (HTTP)?",
                    }
                )
            elif protocol not in PROTOCOLS:
                raise SkillError(
                    "invalid_input", f"protocol must be MCP or HTTP, got {protocol}", file=path
                )
            if not spec.get("target"):
                missing.append(
                    {
                        "input": "target_name",
                        "file": path,
                        "message": f"Which Gateway target name does {path} describe?",
                    }
                )
        if auth_type is None:
            missing.append(
                {
                    "input": "auth_type",
                    "choices": list(AUTH_TYPES),
                    "message": "What inbound auth type does the Gateway use?",
                }
            )
        elif auth_type not in AUTH_TYPES:
            raise SkillError(
                "invalid_input",
                f"auth type must be one of {', '.join(AUTH_TYPES)}",
                input="auth_type",
            )
        if missing:
            return {"status": "input_required", "missing": missing}

        arn = common.parse_gateway_arn(gateway_arn) if gateway_arn else None
        parts = [
            schemas.parse_schema_file(
                str(schema_path),
                str(spec["protocol"]).upper(),
                str(spec["target"]),
            )
            for schema_path, spec in zip(resolved, files)
        ]
        targets, gaps = schemas.merge_targets(parts)
        notes: list[dict[str, Any]] = []
        for part in parts:
            gaps.extend(part.get("gaps", []))
            notes.extend(part.get("coverage_notes", []))
        context: dict[str, Any] = {
            "source": "files",
            "region": arn.region if arn else region,
            "gateway_arn": arn.arn if arn else None,
            "gateway_url": None,
            "auth": {
                "type": auth_type,
                "discovery_url": None,
                "allowed_clients": [],
                "allowed_audience": [],
            },
            "principal": principal_for(auth_type),
            "policy_engine": {"association": "unknown", "arn": None, "mode": None},
            "targets": targets,
            "gaps": _dedupe(gaps),
            "coverage_notes": _dedupe(notes),
            "guardrail_providers": None,
        }
        return self._store(context)

    def set_confirmed_claims(self, names: Any) -> dict[str, Any]:
        """Record the exact token claim names the developer gave or confirmed (CUSTOM_JWT only).
        `validate` reports a tag read whose key is not in this list. Never read the names from
        the identity provider or a token."""
        context = self.get_context()
        found = context.get("principal")
        principal: dict[str, Any] = found if isinstance(found, dict) else {}
        if principal.get("entity_type") != PRINCIPALS["CUSTOM_JWT"]:
            raise SkillError(
                "invalid_input",
                "claim names apply only to CUSTOM_JWT contexts (OAuthUser callers); this context "
                f"has auth type {(context.get('auth') or {}).get('type')}",
            )
        if not isinstance(names, list) or not names:
            raise SkillError("invalid_input", "give at least one claim name")
        clean = []
        for name in names:
            if not isinstance(name, str) or not name.strip() or name != name.strip():
                raise SkillError("invalid_input", f"invalid claim name {name!r}")
            if name not in clean:
                clean.append(name)
        principal["confirmed_claims"] = sorted(clean)
        context["principal"] = principal
        common.write_json(self.context_file, context)
        return {"confirmed_claims": principal["confirmed_claims"]}

    def _store(self, context: dict[str, Any]) -> dict[str, Any]:
        if not context.get("guardrail_providers"):
            context["guardrail_providers"] = {"categories": validation.provider_categories()}
        generated = cedar_schema.generate(context)
        context["version"] = CONTEXT_VERSION
        context["built_at"] = _now()
        context["gaps"] = _dedupe(list(context.get("gaps", [])) + list(generated.get("gaps", [])))
        context["cedar_schema"] = {
            "file": self.schema_file.name,
            "json_file": self.schema_json_file.name,
            "placeholder_gateway_arn": bool(generated.get("placeholder_gateway_arn")),
        }
        updated = self.has_context()
        previous = common.read_json(self.context_file) if updated else None
        if previous and _source_key(previous) == _source_key(context):
            kept = (previous.get("principal") or {}).get("confirmed_claims")
            if isinstance(kept, list) and isinstance(context.get("principal"), dict):
                context["principal"]["confirmed_claims"] = kept
        drafts_report = self._revalidate_drafts(
            generated["schema_text"], generated["schema_json"], context
        )
        common.write_text(self.schema_file, generated["schema_text"])
        common.write_json(self.schema_json_file, generated["schema_json"])
        common.write_json(self.context_file, context)
        if updated and previous and _source_key(previous) != _source_key(context):
            # Pre-existing policies belong to the previous Gateway's engine.
            self.policies_file.unlink(missing_ok=True)
        summary = summarize(context)
        summary["updated"] = updated
        summary["drafts"] = drafts_report
        return summary

    # ------------------------------------------------------------------ describe

    def describe(
        self,
        *,
        targets: list[str],
        actions: list[str],
        include_drafts: bool,
        include_policies: bool,
    ) -> dict[str, Any]:
        context = self.get_context()
        if not targets and not actions and not include_drafts and not include_policies:
            raise SkillError(
                "invalid_input",
                "name the actions (--action <target>___<action>) or targets (--target) a policy "
                "will use; the full schema set is not returned in one call",
            )
        _, schema_json = self.get_cedar_schema()
        known = context.get("targets", {})
        wanted: list[tuple[str, str]] = []
        unknown_targets: list[str] = []
        unknown_actions: list[str] = []
        for name in targets:
            if name not in known:
                unknown_targets.append(name)
                continue
            wanted.extend((name, action) for action in sorted(known[name].get("actions", {})))
        for ref in actions:
            target, action = split_action_ref(ref)
            if target not in known or action not in known[target].get("actions", {}):
                unknown_actions.append(ref)
                continue
            if (target, action) not in wanted:
                wanted.append((target, action))

        truncated = len(wanted) > MAX_LOOKUP
        result: dict[str, Any] = {
            "actions": [
                self._describe_action(context, schema_json, target, action)
                for target, action in wanted[:MAX_LOOKUP]
            ],
            "unknown_targets": unknown_targets,
            "unknown_actions": unknown_actions,
            "truncated": truncated,
        }
        if truncated:
            result["message"] = (
                f"{len(wanted)} actions matched; only the first {MAX_LOOKUP} are returned. "
                "Ask for the specific actions the policy names."
            )
        if unknown_actions or unknown_targets:
            result["unknown_note"] = (
                "names that match nothing are wrong names, not actions without input; "
                "check the target/action index from `prepare`"
            )
        if include_drafts:
            result["drafts"] = self.list_drafts()["drafts"]
        if include_policies:
            policies = common.read_json(self.policies_file)
            result["pre_existing_policies"] = policies if policies else None
            if not policies:
                result["pre_existing_policies_note"] = (
                    "not read yet; run `policies load` after the developer agrees"
                )
        return result

    def _describe_action(
        self, context: dict[str, Any], schema_json: dict[str, Any], target: str, action: str
    ) -> dict[str, Any]:
        entry = context["targets"][target]["actions"][action]
        gaps = [
            gap
            for gap in context.get("gaps", [])
            if gap.get("target") == target and gap.get("action") in (None, action)
        ]
        notes = [
            note
            for note in context.get("coverage_notes", [])
            if note.get("target") == target and note.get("action") in (None, action)
        ]
        return {
            "target": target,
            "action": action,
            "protocol": context["targets"][target].get("protocol"),
            "kind": context["targets"][target].get("kind"),
            # Policies name actions without the Gateway prefix; the service (and `validate`)
            # qualify them with the Gateway before checking against the schema.
            "cedar_action": f"AgentCore::Action::{json.dumps(f'{target}___{action}')}",
            "target_group": f"AgentCore::Action::{json.dumps(target)}",
            "method": entry.get("method"),
            "path": entry.get("path"),
            "description": entry.get("description"),
            "input_schema": entry.get("input_schema"),
            "output_schema": entry.get("output_schema"),
            "context_types": cedar_schema.context_types(schema_json, context, target, action),
            "gaps": gaps,
            "coverage_notes": notes,
        }

    # ------------------------------------------------------------------ drafts

    def _drafts(self) -> dict[str, Any]:
        return common.read_json(self.drafts_file, {"next_id": 1, "drafts": {}})

    @staticmethod
    def _draft_view(draft_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        return {"draft_id": draft_id, **draft, "route": draft.get("route", ROUTE_TRANSLATABLE)}

    @staticmethod
    def _build_draft(
        name: Any,
        statement: Any,
        rule_text: Any,
        idp_claims: Any,
        route: Any,
        reason: Any,
        review_required: Any = None,
    ) -> tuple[list[str], dict[str, Any]]:
        """Check one draft's fields; return (problems, record without updated_at)."""
        problems: list[str] = []
        review = _review_items(review_required, problems)
        try:
            validation.check_name(name)
        except SkillError as exc:
            problems.append(exc.message)
        if route is None:
            route = ROUTE_TRANSLATABLE
        if route not in ROUTES:
            problems.append(f"route must be one of {', '.join(ROUTES)}")
        if rule_text is not None and not (isinstance(rule_text, str) and rule_text.strip()):
            problems.append("rule_text must be a non-empty string")
        if idp_claims is not None and not isinstance(idp_claims, dict):
            problems.append("idp_claims must be a JSON object")
        record: dict[str, Any] = {"name": name, "route": route}
        if route == ROUTE_NON_TRANSLATABLE:
            if statement is not None:
                problems.append("a non-translatable draft has no statement")
            if not (isinstance(reason, str) and reason.strip()):
                problems.append("a non-translatable draft needs a reason")
            if rule_text is None:
                problems.append("a non-translatable draft needs rule_text")
            record["reason"] = reason
        elif route == ROUTE_TRANSLATABLE:
            if reason is not None:
                problems.append("reason applies only to the non-translatable route")
            if not (isinstance(statement, str) and statement.strip()):
                problems.append("a translatable draft needs a statement")
            else:
                text, joins = validation.join_sensitive_aggregation(statement.strip())
                record["statement"] = text + "\n"
                if joins:
                    record["_normalized"] = [
                        {
                            "rule": "sensitive_aggregation_join",
                            "count": joins,
                            "message": validation.SENSITIVE_JOIN_MESSAGE,
                        }
                    ]
        if review:
            if route != ROUTE_TRANSLATABLE:
                problems.append("review_required applies only to translatable drafts")
            record["review_required"] = review
        if rule_text is not None:
            record["rule_text"] = rule_text
        if idp_claims is not None:
            record["idp_claims"] = idp_claims
        return problems, record

    @staticmethod
    def _keep_review(record: dict[str, Any], old: dict[str, Any] | None) -> dict[str, Any]:
        """A replaced draft keeps its open review items and resolutions: only `draft resolve`
        clears an item, so a repair round never drops one."""
        if not old or record.get("route", ROUTE_TRANSLATABLE) != ROUTE_TRANSLATABLE:
            return record
        items = list(old.get("review_required") or [])
        for item in record.get("review_required") or []:
            if item not in items:
                items.append(item)
        if items:
            record["review_required"] = items
        if old.get("review_resolved"):
            record["review_resolved"] = old["review_resolved"]
        return record

    @staticmethod
    def _find_draft(data: dict[str, Any], name: str) -> str | None:
        return next((draft_id for draft_id, d in data["drafts"].items() if d["name"] == name), None)

    def put_draft(
        self,
        name: str,
        statement: str | None = None,
        *,
        rule_text: str | None = None,
        idp_claims: dict[str, Any] | None = None,
        route: str | None = None,
        reason: str | None = None,
        review_required: list[str] | str | None = None,
    ) -> dict[str, Any]:
        self.get_context()
        problems, record = self._build_draft(
            name, statement, rule_text, idp_claims, route, reason, review_required
        )
        if problems:
            raise SkillError("invalid_input", "; ".join(problems))
        data = self._drafts()
        existing = self._find_draft(data, name)
        draft_id = existing or f"draft-{data['next_id']}"
        if existing is None:
            data["next_id"] += 1
        normalized = record.pop("_normalized", None)
        record = self._keep_review(record, data["drafts"].get(existing) if existing else None)
        data["drafts"][draft_id] = {**record, "updated_at": _now()}
        common.write_json(self.drafts_file, data)
        result = {"draft_id": draft_id, "name": name, "replaced": existing is not None}
        if record.get("review_required"):
            result["review_required"] = record["review_required"]
        if normalized:
            result["normalized"] = normalized
        return result

    def put_drafts(self, items: Any) -> dict[str, Any]:
        """All-or-nothing batch of `put_draft`: any bad item writes nothing."""
        self.get_context()
        if not isinstance(items, list) or not items:
            raise SkillError("invalid_input", "the file must hold a non-empty JSON list of drafts")
        bad: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        first_seen: dict[str, int] = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                bad.append({"index": index, "problems": ["item must be a JSON object"]})
                continue
            unknown = sorted(set(item) - DRAFT_ITEM_KEYS)
            problems, record = self._build_draft(
                item.get("name"),
                item.get("statement"),
                item.get("rule_text"),
                item.get("idp_claims"),
                item.get("route"),
                item.get("reason"),
                item.get("review_required"),
            )
            if unknown:
                problems.append(f"unknown fields: {', '.join(unknown)}")
            name = item.get("name")
            if isinstance(name, str) and name:
                if name in first_seen:
                    problems.append(f"duplicate name {name!r} (also item {first_seen[name]})")
                else:
                    first_seen[name] = index
            if problems:
                entry: dict[str, Any] = {"index": index, "problems": problems}
                if isinstance(name, str):
                    entry["name"] = name
                bad.append(entry)
            else:
                records.append(record)
        if bad:
            raise SkillError(
                "invalid_input",
                f"{len(bad)} of {len(items)} drafts are invalid; nothing was written",
                items=bad,
            )
        data = self._drafts()
        stamp = _now()
        results = []
        for record in records:
            existing = self._find_draft(data, record["name"])
            draft_id = existing or f"draft-{data['next_id']}"
            if existing is None:
                data["next_id"] += 1
            normalized = record.pop("_normalized", None)
            record = self._keep_review(record, data["drafts"].get(existing) if existing else None)
            data["drafts"][draft_id] = {**record, "updated_at": stamp}
            entry = {"draft_id": draft_id, "name": record["name"], "replaced": existing is not None}
            if record.get("review_required"):
                entry["review_required"] = record["review_required"]
            if normalized:
                entry["normalized"] = normalized
            results.append(entry)
        common.write_json(self.drafts_file, data)
        return {"drafts": results, "count": len(results)}

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self._drafts()["drafts"].get(draft_id)
        if draft is None:
            raise SkillError(
                "not_found", f"no draft {draft_id}; see `draft list`", draft_id=draft_id
            )
        return self._draft_view(draft_id, draft)

    def get_translatable_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if draft["route"] != ROUTE_TRANSLATABLE:
            raise SkillError(
                "not_translatable",
                f"{draft_id} is marked non-translatable and has no statement to validate or "
                "submit; replace it with `draft put --statement-file` if it can be expressed",
                draft_id=draft_id,
                reason=draft.get("reason"),
            )
        return draft

    def list_drafts(self) -> dict[str, Any]:
        drafts = self._drafts()["drafts"]
        return {
            "drafts": [
                self._draft_view(draft_id, draft) for draft_id, draft in sorted(drafts.items())
            ]
        }

    def resolve_review(self, draft_id: str, resolution: str) -> dict[str, Any]:
        """Close every open review item of a draft with the developer's decision."""
        if not (isinstance(resolution, str) and resolution.strip()):
            raise SkillError("invalid_input", "--resolution must state the developer's decision")
        data = self._drafts()
        draft = data["drafts"].get(draft_id)
        if draft is None:
            raise SkillError(
                "not_found", f"no draft {draft_id}; see `draft list`", draft_id=draft_id
            )
        items = draft.pop("review_required", None) or []
        if not items:
            raise SkillError(
                "invalid_input", f"{draft_id} has no open review item", draft_id=draft_id
            )
        stamp = _now()
        draft.setdefault("review_resolved", []).extend(
            {"item": item, "resolution": resolution.strip(), "resolved_at": stamp} for item in items
        )
        draft["updated_at"] = stamp
        common.write_json(self.drafts_file, data)
        return {"draft_id": draft_id, "resolved": items, "resolution": resolution.strip()}

    def review_blockers(self, statement: str) -> list[dict[str, Any]]:
        """Drafts with open review items whose statement is this statement (layout ignored)."""
        target = validation.canonical_statement(statement)
        blockers = []
        for draft_id, draft in sorted(self._drafts()["drafts"].items()):
            items = draft.get("review_required") or []
            text = draft.get("statement")
            if items and isinstance(text, str) and validation.canonical_statement(text) == target:
                blockers.append(
                    {"draft_id": draft_id, "name": draft["name"], "review_required": items}
                )
        return blockers

    def remove_draft(self, draft_id: str) -> dict[str, Any]:
        data = self._drafts()
        if data["drafts"].pop(draft_id, None) is None:
            raise SkillError("not_found", f"no draft {draft_id}", draft_id=draft_id)
        common.write_json(self.drafts_file, data)
        return {"removed": draft_id}

    def _revalidate_drafts(
        self, schema_text: str, schema_json: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-check translatable drafts against a new context. Drafts it rejects are kept,
        marked `invalid` with their errors, so the developer's work is never lost."""
        data = self._drafts()
        kept: list[str] = []
        invalid: list[dict[str, Any]] = []
        changed = False
        for draft_id, draft in data["drafts"].items():
            if draft.get("route", ROUTE_TRANSLATABLE) != ROUTE_TRANSLATABLE:
                kept.append(draft_id)
                continue
            report = validation.validate(
                draft["statement"],
                schema_text=schema_text,
                schema_json=schema_json,
                context=context,
                name=draft["name"],
            )
            if report["status"] == "rejected":
                errors = _report_errors(report)
                if not draft.get("invalid") or draft.get("invalid_errors") != errors:
                    draft["invalid"] = True
                    draft["invalid_errors"] = errors
                    changed = True
                invalid.append({"draft_id": draft_id, "name": draft["name"], "errors": errors})
            else:
                if draft.pop("invalid", None) is not None:
                    changed = True
                draft.pop("invalid_errors", None)
                kept.append(draft_id)
        if changed:
            common.write_json(self.drafts_file, data)
        return {"kept": kept, "invalid": invalid}

    def _set_draft_invalid(self, draft_id: str, report: dict[str, Any]) -> None:
        """After validating a draft: a rejected one that was invalid keeps its errors current;
        any other result clears the mark."""
        data = self._drafts()
        draft = data["drafts"].get(draft_id)
        if draft is None or not draft.get("invalid"):
            return
        if report["status"] == "rejected":
            draft["invalid_errors"] = _report_errors(report)
        else:
            del draft["invalid"]
            draft.pop("invalid_errors", None)
        common.write_json(self.drafts_file, data)

    # ------------------------------------------------------------------ validation

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.get_translatable_draft(draft_id)
        report = self.validate(draft["statement"], name=draft["name"])
        self._set_draft_invalid(draft_id, report)
        return report

    def validate_drafts(self, draft_ids: list[str] | None) -> dict[str, Any]:
        """Validate many drafts (all when `draft_ids` is None); one compact entry per draft."""
        drafts = self._drafts()["drafts"]
        ids = sorted(drafts) if draft_ids is None else draft_ids
        for draft_id in ids:
            if draft_id not in drafts:
                raise SkillError(
                    "not_found", f"no draft {draft_id}; see `draft list`", draft_id=draft_id
                )
        summary = {"passed": 0, "rejected": 0, "incomplete": 0, "skipped": 0}
        results: list[dict[str, Any]] = []
        candidates: list[str] = []
        for draft_id in ids:
            draft = drafts[draft_id]
            entry: dict[str, Any] = {"draft_id": draft_id, "name": draft["name"]}
            if draft.get("route", ROUTE_TRANSLATABLE) != ROUTE_TRANSLATABLE:
                entry.update(status="skipped", reason="non-translatable")
                summary["skipped"] += 1
            else:
                report = self.validate(draft["statement"], name=draft["name"])
                self._set_draft_invalid(draft_id, report)
                entry["status"] = report["status"]
                summary[report["status"]] += 1
                errors = _report_errors(report)
                if errors:
                    entry["errors"] = errors
                if report["status"] == "incomplete":
                    entry["not_checked"] = report["coverage"]["not_checked"]
                    if report.get("service_check"):
                        candidates.append(draft_id)
            results.append(entry)
        return {"results": results, "summary": summary, "service_check_candidates": candidates}

    def validate(self, statement: str, *, name: str | None = None) -> dict[str, Any]:
        context = self.get_context()
        schema_text, schema_json = self.get_cedar_schema()
        report = validation.validate(
            statement,
            schema_text=schema_text,
            schema_json=schema_json,
            context=context,
            name=name,
        )
        offer = _service_check_offer(report, context)
        if offer:
            report["service_check"] = offer
        path = self.validations_dir / f"{self._validation_key(statement, schema_text)}.json"
        record = {
            "status": report["status"],
            "validated_at": _now(),
            "built_at": context["built_at"],
            "errors": _report_errors(report),
        }
        previous = common.read_json(path, {}) or {}
        if previous.get("service"):
            record["service"] = previous["service"]
        common.write_json(path, record)
        return report

    # ------------------------------------------------------------------ export

    def export_drafts(self, output: str) -> dict[str, Any]:
        """Write every draft, its rule text and its latest validation verdict to one file."""
        schema_text = self.get_cedar_schema()[0]
        translatable: dict[str, Any] = {}
        non_translatable: dict[str, Any] = {}
        for draft in self._drafts()["drafts"].values():
            if draft.get("route", ROUTE_TRANSLATABLE) != ROUTE_TRANSLATABLE:
                non_translatable[draft["name"]] = {
                    "natural_language_policy": draft.get("rule_text"),
                    "IdP": draft.get("idp_claims"),
                    "reason": draft.get("reason"),
                }
                continue
            record = (
                common.read_json(
                    self.validations_dir
                    / f"{self._validation_key(draft['statement'], schema_text)}.json"
                )
                or {}
            )
            status, passed, errors = _export_verdict(draft, record)
            translatable[draft["name"]] = {
                "natural_language_policy": draft.get("rule_text"),
                "IdP": draft.get("idp_claims"),
                "dogwood_policy": draft["statement"],
                "validation_passed": passed,
                "validation_errors": errors,
                "validation_status": status,
            }
            if draft.get("review_required"):
                translatable[draft["name"]]["review_required"] = draft["review_required"]
        target = self._export_target(output)
        # Record ownership first: a crash after the write must not leave a file that later
        # exports refuse to replace.
        exports = common.read_json(self.exports_file, []) or []
        if str(target) not in exports:
            common.write_json(self.exports_file, [*exports, str(target)])
        common.write_json(
            target,
            {"dogwood_translatable": translatable, "non_translatable": non_translatable},
        )
        return {
            "output": output,
            "counts": {
                "dogwood_translatable": len(translatable),
                "validation_passed": sum(
                    1 for e in translatable.values() if e["validation_passed"]
                ),
                "non_translatable": len(non_translatable),
            },
        }

    def _export_target(self, output: str) -> Path:
        """The export path: a .json file in the working directory that is new or ours.

        It must not be a symlink, and an existing file is overwritten only when an earlier
        `draft export` wrote it (recorded in exports.json), never a file the skill did not create.
        """
        target = common.confined_path(output, input_name="output")
        if target.suffix.lower() != ".json":
            raise SkillError("invalid_input", "the export file must end in .json", input="output")
        literal = Path.cwd() / output
        if literal.is_symlink() or target.is_symlink():
            raise SkillError(
                "invalid_input", "the export path must not be a symlink", input="output"
            )
        if target.exists():
            if not target.is_file() or str(target) not in (
                common.read_json(self.exports_file, []) or []
            ):
                raise SkillError(
                    "invalid_input",
                    f"{output} already exists and was not written by `draft export`; "
                    "choose a new file name",
                    input="output",
                )
        return target

    def record_service_validation(self, statement: str, result: dict[str, Any]) -> None:
        """Attach the service's verdict to the local validation record of this statement."""
        schema_text = self.get_cedar_schema()[0]
        path = self.validations_dir / f"{self._validation_key(statement, schema_text)}.json"
        record = common.read_json(path, {}) or {}
        record["service"] = {
            "service_validation": result.get("service_validation"),
            "status": result.get("status"),
            "statusReasons": result.get("statusReasons", []),
            "checked_at": _now(),
        }
        if result.get("service_validation") == "rejected":
            record["status"] = "rejected"
        common.write_json(path, record)

    def last_validation(self, statement: str) -> dict[str, Any] | None:
        if not self.has_context() or not self.schema_file.is_file():
            return None
        schema_text = self.schema_file.read_text(encoding="utf-8")
        return common.read_json(
            self.validations_dir / f"{self._validation_key(statement, schema_text)}.json"
        )

    @staticmethod
    def _validation_key(statement: str, schema_text: str) -> str:
        # Layout-only edits (spacing, line breaks, comments) keep the same record, so a service
        # rejection cannot be escaped by reformatting the statement.
        canonical = validation.canonical_statement(statement)
        return common.sha256_hex(canonical + "\0" + schema_text)

    # ------------------------------------------------------------------ policies

    def set_pre_existing_policies(self, engine_arn: str, policies: list[dict[str, Any]]) -> dict:
        record = {"policy_engine_arn": engine_arn, "fetched_at": _now(), "policies": policies}
        common.write_json(self.policies_file, record)
        return record

    def get_pre_existing_policies(self) -> dict[str, Any] | None:
        return common.read_json(self.policies_file)


def summarize(context: dict[str, Any]) -> dict[str, Any]:
    """The index returned by `prepare`: no schemas, only names, gaps and auth facts."""
    return {
        "status": "ready",
        "source": context.get("source"),
        "gateway_arn": context.get("gateway_arn"),
        "region": context.get("region"),
        "auth": {"type": context.get("auth", {}).get("type")},
        "principal": context.get("principal"),
        "policy_engine": context.get("policy_engine"),
        "targets": [
            {
                "name": name,
                "protocol": target.get("protocol"),
                "kind": target.get("kind"),
                "actions": sorted(target.get("actions", {})),
            }
            for name, target in sorted(context.get("targets", {}).items())
        ],
        "gaps": context.get("gaps", []),
        "coverage_notes": context.get("coverage_notes", []),
        "guardrail_providers": context.get("guardrail_providers"),
        "placeholder_gateway_arn": context.get("cedar_schema", {}).get("placeholder_gateway_arn"),
        "complete": not context.get("gaps"),
    }


def _source_key(context: dict[str, Any]) -> tuple[Any, ...]:
    return (context.get("source"), context.get("gateway_arn"))


def _report_errors(report: dict[str, Any]) -> list[str]:
    """Short list of error messages from a validation report (local errors, stage errors)."""
    errors = [str(e["message"]) for e in report.get("local_errors") or []]
    for stage in (report.get("stages") or {}).values():
        errors.extend(
            str(d["message"])
            for d in stage.get("diagnostics") or []
            if d.get("severity") == "error"
        )
    return list(dict.fromkeys(errors))[:MAX_RECORDED_ERRORS]


def _export_verdict(draft: dict[str, Any], record: dict[str, Any]) -> tuple[str, bool, list[str]]:
    """(validation_status, validation_passed, errors) of a translatable draft for export."""
    if draft.get("invalid"):
        return "invalid", False, list(draft.get("invalid_errors") or [])
    if not record:
        return "not_validated", False, []
    service = (record.get("service") or {}).get("service_validation")
    errors = list(record.get("errors") or [])
    status = record.get("status", "incomplete")
    if service == "rejected":
        reasons = record["service"].get("statusReasons") or []
        return "service_rejected", False, errors + [str(r) for r in reasons][:MAX_RECORDED_ERRORS]
    if status == "rejected":
        # A local rejection wins: a service pass only covers what local checks could not.
        return "rejected", False, errors
    if service == "passed":
        return "service_passed", True, errors
    return status, status == "passed", errors


def _service_check_offer(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    """Offer service-side validation when a Dogwood statement could not be checked locally.

    Only for a context prepared from a Gateway ARN: the service validates the policy against
    that Gateway, so a placeholder or schema-file context cannot be checked this way.
    """
    if report.get("dialect") != "dogwood" or report.get("status") == "rejected":
        return None
    stages = report.get("stages") or {}
    if not any(
        stages.get(s, {}).get("status") in ("skipped", "unavailable") for s in ("syntax", "schema")
    ):
        return None
    if context.get("source") != "gateway" or not context.get("gateway_arn"):
        return None
    return {
        "available": True,
        "requires_approval": True,
        "how": "validate --draft-id <id> --on-service (preview), then the same command with "
        "--approve <approval_token>",
        "what_it_does": "creates a temporary policy engine for this check, creates this policy "
        "in it, reads the service's verdict, then deletes both; existing engines are not touched",
        "ask": "Ask the developer before previewing; run it only after they approve the preview.",
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = common.canonical_json(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
