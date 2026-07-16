# Discovery & source resolution (Phases 1–2)

## Resolving the source agent
Inputs the user may give: agent **id**, **name**, **ARN**, or nothing.

- **Name only:** list agents in the confirmed region (`bedrock-agent:ListAgents`) and disambiguate with the user.
- **Nothing:** list agents and present candidates.
- **ARN:** the agent id is the last `/` segment.

Default to the **production alias's** numbered version, not DRAFT: list aliases (`ListAgentAliases`), have the user identify the production alias, read its `routingConfiguration[0].agentVersion`. **DRAFT-only** (only the auto `TSTALIASID` alias pointing at DRAFT, with no numbered version) is a valid, eligible source — confirm and proceed. Honor an explicit "migrate DRAFT" request.

Confirm the full `(account, region, agentId, agentVersion, aliasId)` tuple before discovery.

## Two discovery paths — prefer the script, fall back to the AWS CLI
Goal: one JSON manifest, `./out/source-agent.json`, that later phases read.

**Inline agents take neither path.** An inline agent (invoked via `InvokeInlineAgent`) has no persisted `agentId`, so both Path A (the fetch script, which needs `--agent-id`) and Path B (the `aws bedrock-agent get-agent` reads) are inapplicable. Its `InvokeInlineAgent` request payload already contains the configuration — map the payload's fields into the same manifest keys (below): `instruction`, `foundationModel`, `actionGroups`, `knowledgeBases`, `guardrailConfiguration`, and prompt overrides. Fields the payload doesn't carry (execution-role policies, aliases/versions) simply don't exist for an inline agent; omit them. Then proceed to eligibility exactly as for a stored agent.

**The manifest is sensitive.** It captures account ids, IAM role ARNs, attached and inline policy documents, Lambda ARNs, and KB configuration. Do not commit it (add `out/` to `.gitignore`); store it **encrypted at rest** — an encrypted volume or a KMS-backed location, not filesystem permissions alone — readable only by the running user; and delete it after a successful migration unless it is being kept for audit.

### Path A (preferred): bundled fetcher
`fetch_bedrock_agent.py` snapshots the agent in one command (inlines S3 OpenAPI schemas with `--inline-s3-schemas`; tolerates per-call permission errors). **Requires `python3` + `boto3`** — probe in Phase 0 (`python3 -c "import boto3"`). The script exits with code **3** and prints `FALLBACK_REQUIRED` if boto3 is missing, so a failed run is a clean signal to switch to Path B. Do **not** `pip install` into the user's environment.

```bash
python3 scripts/fetch_bedrock_agent.py \
  --agent-id <id> --agent-version <resolved> --region <region> \
  --inline-s3-schemas --out ./out/source-agent.json
```

### Path B (fallback): AWS CLI read commands
The `aws` CLI is a self-contained binary already required for the migration, so it works where a bare python3 may not. Run the equivalent read sequence (`aws bedrock-agent get-agent`, `list/get-agent-action-group`, `list/get-agent-knowledge-base`, `get-knowledge-base`, `list-agent-aliases`, `list-agent-versions`, `list-agent-collaborators` when collaboration is on; `aws s3 cp` to inline S3 schemas; `aws iam get-role` for the execution role) and assemble the same manifest shape yourself. Tolerate `AccessDenied`/`NotFound`/`Validation` on individual calls; abort only on outright failure.

If discovery fails outright, stop and report. Do not partially migrate from an incomplete manifest.

## Manifest schema — the script is the source of truth
`fetch_bedrock_agent.py` defines the manifest shape; don't duplicate a schema spec here (it would drift). Top-level keys it writes: `discovery` (account/region/caller/version/warnings), `agent`, `agentCollaborationMode`, `orchestrationType`, `executionRole`, `actionGroups`, `knowledgeBases`, `collaborators`, `aliasesAndVersions`. The **Path B (AWS CLI) fallback must assemble the same keys** so downstream phases read one shape regardless of path.
