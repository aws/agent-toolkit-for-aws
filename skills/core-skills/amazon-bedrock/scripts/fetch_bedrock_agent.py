#!/usr/bin/env python3
"""
Fetch a complete manifest of a Bedrock Agent (Phase 1: Discovery).

Pulls every component the migration cares about into a single JSON document so the
rest of the skill can reason over a static snapshot instead of repeatedly calling
the Bedrock control plane.

Usage:
    python fetch_bedrock_agent.py --agent-id ABC123 --region us-east-1 --out manifest.json

By default fetches the DRAFT version. The skill should resolve a numbered version
via the production alias in Phase 0 and pass --agent-version <n>. If this script
sees DRAFT, it prints a WARNING summarizing that the production alias may point
elsewhere.

Pass --inline-s3-schemas to fetch action-group OpenAPI schemas stored in S3 and
inline them into the manifest under each action group's `apiSchema._inlinedPayload`.

Requires: boto3 with read-only credentials. Prefer ephemeral, role-based
credentials (an assumed IAM role, SSO session, or instance profile) over
long-lived IAM user access keys — `--profile` may otherwise resolve to static
keys in ~/.aws/credentials.

Minimum IAM permissions (all read-only; scope Resource as noted):
    sts:GetCallerIdentity
    bedrock-agent:GetAgent, ListAgentActionGroups,
        GetAgentActionGroup, ListAgentKnowledgeBases, GetAgentKnowledgeBase,
        GetKnowledgeBase, ListDataSources, GetDataSource, ListAgentAliases,
        GetAgentAlias, ListAgentVersions, ListAgentCollaborators (optional),
        GetAgentCollaborator (optional)
        -> scope to the specific agent/KB ARNs where possible
    iam:GetRole, ListAttachedRolePolicies, ListRolePolicies, GetRolePolicy
        -> scope to the agent's execution-role ARN
    s3:GetObject (only with --inline-s3-schemas)
        -> scope to the OpenAPI schema object(s)
No write/mutating permissions are needed; grant none.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    # boto3 is not in the stdlib. Exit with a distinct code so the caller can
    # cleanly fall back to the `aws bedrock-agent` CLI path (see
    # references/discovery.md "Fallback") instead of treating this as a crash.
    sys.stderr.write(
        "FALLBACK_REQUIRED: boto3 not available. Use the aws-CLI discovery path "
        "documented in references/discovery.md.\n"
    )
    sys.exit(3)

# Errors we tolerate per-call (record but don't crash). All other ClientErrors propagate.
TOLERATED_ERROR_CODES = {
    "AccessDeniedException",
    "ResourceNotFoundException",
    "ValidationException",
}


def _safe(call, *args, **kwargs):
    """Run a boto3 call, returning {'_error': code, '_message': str} on tolerated errors."""
    try:
        return call(*args, **kwargs)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in TOLERATED_ERROR_CODES:
            return {"_error": code, "_message": str(e)}
        raise


def _strip_response_metadata(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _strip_response_metadata(v) for k, v in d.items() if k != "ResponseMetadata"}
    if isinstance(d, list):
        return [_strip_response_metadata(x) for x in d]
    return d


def _maybe_inline_s3_schema(
    s3_client, api_schema: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """If apiSchema points to S3, fetch it and inline under _inlinedPayload."""
    if not api_schema or "s3" not in api_schema:
        return api_schema
    s3_ref = api_schema["s3"]
    bucket = s3_ref.get("s3BucketName")
    key = s3_ref.get("s3ObjectKey")
    if not (bucket and key):
        return api_schema
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return {**api_schema, "_inlinedPayload": body, "_inlinedSource": f"s3://{bucket}/{key}"}
    except ClientError as e:
        return {**api_schema, "_inlineError": str(e)}


def fetch_action_groups(
    bedrock_agent, s3_client, agent_id: str, version: str, inline_s3: bool
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    paginator = bedrock_agent.get_paginator("list_agent_action_groups")
    for page in paginator.paginate(agentId=agent_id, agentVersion=version):
        for summary in page.get("actionGroupSummaries", []):
            detail = _safe(
                bedrock_agent.get_agent_action_group,
                agentId=agent_id,
                agentVersion=version,
                actionGroupId=summary["actionGroupId"],
            )
            ag = _strip_response_metadata(detail).get("agentActionGroup", detail)
            if inline_s3 and isinstance(ag, dict) and "apiSchema" in ag:
                ag["apiSchema"] = _maybe_inline_s3_schema(s3_client, ag.get("apiSchema"))
            out.append(ag)
    return out


def fetch_knowledge_bases(bedrock_agent, agent_id: str, version: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    paginator = bedrock_agent.get_paginator("list_agent_knowledge_bases")
    for page in paginator.paginate(agentId=agent_id, agentVersion=version):
        for summary in page.get("agentKnowledgeBaseSummaries", []):
            assoc = _safe(
                bedrock_agent.get_agent_knowledge_base,
                agentId=agent_id,
                agentVersion=version,
                knowledgeBaseId=summary["knowledgeBaseId"],
            )
            kb_detail = _safe(
                bedrock_agent.get_knowledge_base, knowledgeBaseId=summary["knowledgeBaseId"]
            )
            ds_list: List[Dict[str, Any]] = []
            ds_paginator = bedrock_agent.get_paginator("list_data_sources")
            try:
                for ds_page in ds_paginator.paginate(knowledgeBaseId=summary["knowledgeBaseId"]):
                    for ds_summary in ds_page.get("dataSourceSummaries", []):
                        ds = _safe(
                            bedrock_agent.get_data_source,
                            knowledgeBaseId=summary["knowledgeBaseId"],
                            dataSourceId=ds_summary["dataSourceId"],
                        )
                        ds_list.append(_strip_response_metadata(ds))
            except ClientError as e:
                ds_list.append({"_error": str(e)})
            out.append(
                {
                    "association": _strip_response_metadata(assoc).get("agentKnowledgeBase", assoc),
                    "knowledgeBase": _strip_response_metadata(kb_detail).get(
                        "knowledgeBase", kb_detail
                    ),
                    "dataSources": ds_list,
                }
            )
    return out


def fetch_aliases_and_versions(bedrock_agent, agent_id: str) -> Dict[str, Any]:
    aliases: List[Dict[str, Any]] = []
    versions: List[Dict[str, Any]] = []
    try:
        for page in bedrock_agent.get_paginator("list_agent_aliases").paginate(agentId=agent_id):
            for s in page.get("agentAliasSummaries", []):
                detail = _safe(
                    bedrock_agent.get_agent_alias, agentId=agent_id, agentAliasId=s["agentAliasId"]
                )
                aliases.append(_strip_response_metadata(detail).get("agentAlias", detail))
    except ClientError as e:
        aliases.append({"_error": str(e)})
    try:
        for page in bedrock_agent.get_paginator("list_agent_versions").paginate(agentId=agent_id):
            for s in page.get("agentVersionSummaries", []):
                versions.append(s)
    except ClientError as e:
        versions.append({"_error": str(e)})
    return {"aliases": aliases, "versions": versions}


def fetch_collaborators(bedrock_agent, agent_id: str, version: str) -> List[Dict[str, Any]]:
    """Multi-agent collaborator agents (if collaboration is enabled on the source)."""
    out: List[Dict[str, Any]] = []
    if not hasattr(bedrock_agent, "list_agent_collaborators"):
        return out  # SDK too old; collaboration won't be in the manifest
    try:
        for page in bedrock_agent.get_paginator("list_agent_collaborators").paginate(
            agentId=agent_id, agentVersion=version
        ):
            for s in page.get("agentCollaboratorSummaries", []):
                detail = _safe(
                    bedrock_agent.get_agent_collaborator,
                    agentId=agent_id,
                    agentVersion=version,
                    collaboratorId=s["collaboratorId"],
                )
                out.append(_strip_response_metadata(detail).get("agentCollaborator", detail))
    except (ClientError, AttributeError) as e:
        out.append({"_error": str(e)})
    return out


def fetch_iam_role(iam, role_arn: Optional[str]) -> Dict[str, Any]:
    if not role_arn:
        return {}
    role_name = role_arn.split("/")[-1]
    role = _safe(iam.get_role, RoleName=role_name)
    attached = _safe(iam.list_attached_role_policies, RoleName=role_name)
    inline_names = _safe(iam.list_role_policies, RoleName=role_name)
    inline_policies: List[Dict[str, Any]] = []
    if isinstance(inline_names, dict) and "_error" not in inline_names:
        for name in inline_names.get("PolicyNames", []):
            doc = _safe(iam.get_role_policy, RoleName=role_name, PolicyName=name)
            inline_policies.append(_strip_response_metadata(doc))
    return {
        "role": _strip_response_metadata(role).get("Role", role),
        "attachedPolicies": _strip_response_metadata(attached).get("AttachedPolicies", attached),
        "inlinePolicies": inline_policies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a complete Bedrock Agent manifest for migration."
    )
    # id only — Phase 1 resolves name/ARN to a confirmed agentId before this runs
    parser.add_argument("--agent-id", required=True)
    parser.add_argument(
        "--agent-version",
        default="DRAFT",
        help="Agent version to inspect. Default DRAFT, but the skill should resolve a numbered "
        "version from the production alias before calling this.",
    )
    parser.add_argument(
        "--agent-alias-id", help="Optional alias id, included in manifest for reference"
    )
    parser.add_argument(
        "--region", required=False, help="AWS region (defaults to credential default)"
    )
    parser.add_argument("--profile", required=False, help="AWS profile")
    parser.add_argument(
        "--inline-s3-schemas",
        action="store_true",
        help="Fetch action-group OpenAPI schemas stored in S3 and inline them into the manifest.",
    )
    parser.add_argument("--out", required=True, help="Path to write the JSON manifest")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    bedrock_agent = session.client("bedrock-agent")
    iam = session.client("iam")
    sts = session.client("sts")
    s3_client = session.client("s3") if args.inline_s3_schemas else None

    identity = sts.get_caller_identity()
    region = session.region_name
    if not region:
        print(
            "ERROR: no region resolved from credentials. Pass --region or set AWS_DEFAULT_REGION.",
            file=sys.stderr,
        )
        return 2

    agent_id = args.agent_id
    # get_agent is fundamental to discovery — a tolerated error here (e.g.
    # ResourceNotFoundException) would write a broken manifest whose downstream
    # field lookups silently produce wrong defaults. So fail hard, not via _safe.
    try:
        agent = bedrock_agent.get_agent(agentId=agent_id)
    except ClientError as e:
        print(f"ERROR: failed to fetch agent {agent_id}: {e}", file=sys.stderr)
        return 1
    agent_doc = _strip_response_metadata(agent).get("agent", agent)
    role_info = fetch_iam_role(iam, agent_doc.get("agentResourceRoleArn"))

    aliases_and_versions = fetch_aliases_and_versions(bedrock_agent, agent_id)

    manifest: Dict[str, Any] = {
        "discovery": {
            "account": identity.get("Account"),
            "region": region,
            "callerArn": identity.get("Arn"),
            "fetchedAgentVersion": args.agent_version,
            "fetchedAgentAliasId": args.agent_alias_id,
            "warnings": [],
        },
        "agent": agent_doc,
        "agentCollaborationMode": agent_doc.get("agentCollaboration") or "DISABLED",
        "orchestrationType": agent_doc.get("orchestrationType") or "DEFAULT",
        "executionRole": role_info,
        "actionGroups": fetch_action_groups(
            bedrock_agent, s3_client, agent_id, args.agent_version, args.inline_s3_schemas
        ),
        "knowledgeBases": fetch_knowledge_bases(bedrock_agent, agent_id, args.agent_version),
        "collaborators": fetch_collaborators(bedrock_agent, agent_id, args.agent_version),
        "aliasesAndVersions": aliases_and_versions,
    }

    if args.agent_version == "DRAFT":
        prod_aliases = [
            a
            for a in aliases_and_versions["aliases"]
            if isinstance(a, dict) and a.get("agentAliasId") not in (None, "TSTALIASID")
        ]
        if prod_aliases:
            tag = ", ".join(
                f"{a.get('agentAliasName', '?')}->v{(a.get('routingConfiguration') or [{}])[0].get('agentVersion', '?')}"
                for a in prod_aliases
            )
            manifest["discovery"]["warnings"].append(
                f"Fetched DRAFT but non-DRAFT aliases exist ({tag}). DRAFT may diverge from production."
            )

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    # Manifest holds sensitive data (account ids, role ARNs, inline IAM policies).
    # Restrict to owner read/write; prefer writing it to an encrypted volume.
    try:
        os.chmod(args.out, 0o600)
    except OSError as e:
        print(
            f"WARNING: could not restrict permissions on {args.out} ({e}). It holds "
            "sensitive data (account ids, role ARNs, IAM policies) and may be readable "
            "by others — secure or delete it manually.",
            file=sys.stderr,
        )

    print(f"Wrote {args.out}")
    for w in manifest["discovery"]["warnings"]:
        print(f"  WARNING: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
