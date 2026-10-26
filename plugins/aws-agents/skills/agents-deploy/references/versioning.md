# Agent Versioning and Rollback

Runtimes and Harnesses are versioned by AgentCore: each change you deploy creates a new immutable version, and **endpoints** (qualifiers) point callers at a version. This reference covers how versions work, how to pin to a specific version, and how to roll back when a deploy goes wrong.

## How versioning works

- **Runtime:** each `agentcore deploy` that changes a Runtime's code or configuration creates a new Runtime version. A deploy that only adds or moves an endpoint doesn't — the endpoint just points at an existing version.
- **Harness:** each change to a Harness — a deploy of an edited `harness.yaml` / `system-prompt.md`, or `agentcore harness update` — creates a new Harness version.
- The `DEFAULT` endpoint always follows the latest version. Callers that don't pass a qualifier use `DEFAULT`.
- Named endpoints (e.g. `prod`, `staging`) point at a specific version and only move when you move them. Point production callers at a named endpoint so you can roll back with a pointer swap.
- Old versions remain available for endpoints to point at.
- Local dev (`agentcore dev`) always runs the current code — no version concept.

## Finding the IDs

The `runtime` and `harness` commands take the resource ID, which is the last segment of the ARN `agentcore status` reports:

```bash
# Runtime ARN: arn:aws:bedrock-agentcore:<region>:<account>:runtime/<RUNTIME_ID>
agentcore status --json | jq -r '.resources[] | select(.resourceType=="runtime" and .name=="<RuntimeName>") | .arn | split("/")[1]'

# Harness ARN: arn:aws:bedrock-agentcore:<region>:<account>:harness/<HARNESS_ID>
agentcore status --json | jq -r '.resources[] | select(.resourceType=="harness" and .name=="<HarnessName>") | .arn | split("/")[1]'
```

Add `--target <name>` to `status` for a non-default target. `agentcore runtime list --json` and `agentcore harness list --json` also show IDs for the region. Run with no flags, the `eval`, `identity`, `runtime`, `harness`, `memory`, and `gateway` commands open the interactive TUI, which fails without a terminal (`interactive mode requires a TTY`) — pass `--json` (or the command's flags) from an agent shell.

## Inspecting versions

```bash
# Runtime versions and endpoints
agentcore runtime version list --id <RUNTIME_ID>
agentcore runtime version get --id <RUNTIME_ID> --version <VERSION>
agentcore runtime endpoint list --id <RUNTIME_ID>
agentcore runtime endpoint get --id <RUNTIME_ID> --qualifier <ENDPOINT_NAME>

# Harness versions and endpoints
agentcore harness version list --id <HARNESS_ID>
agentcore harness version get --id <HARNESS_ID> --version <VERSION>
agentcore harness endpoint list --id <HARNESS_ID>
```

`agentcore status` doesn't show which version an endpoint serves; `runtime endpoint list` / `harness endpoint list` do — use them to confirm what's live after a deploy or rollback.

Add `--json` for machine-readable output and `--region <region>` if the target isn't in your default region.

## Pinning a version with a named endpoint

**Runtime** — endpoints are part of the project, so they're declared in `agentcore.json` and deployed with everything else:

```bash
agentcore add runtime-endpoint --runtime <RuntimeName> --name prod --version 3
agentcore deploy
```

This writes `"endpoints": { "prod": { "version": 3 } }` on the Runtime in `agentcore/agentcore.json` (`--version` defaults to `1`). Endpoint names start with a letter and contain letters, digits, or underscores (max 48).

**Harness** — Harness endpoints aren't declared in `agentcore.json`; manage them with the `harness endpoint` commands against the deployed Harness:

```bash
agentcore harness endpoint create --id <HARNESS_ID> --name prod --target-version 3
```

`--target-version` defaults to the latest version. Because this endpoint lives outside the stack, you must delete it yourself before the Harness can be removed — see [Version retention](#version-retention).

## Invoking a specific version

By default, callers hit `DEFAULT` (the latest version). To pin a call, pass the endpoint name as the qualifier:

```bash
agentcore invoke --runtime <RuntimeName> --qualifier prod --payload '{"prompt": "Hello"}'
agentcore harness invoke --id <HARNESS_ID> --qualifier prod --prompt "Hello"
```

From the SDK:

```python
response = client.invoke_agent_runtime(
    agentRuntimeArn="<AGENT_RUNTIME_ARN>",
    qualifier="prod",  # endpoint name; omit for DEFAULT
    payload=payload,
    runtimeSessionId=session_id,
)
```

This is useful for:

- Canary testing — send some traffic to a `canary` endpoint before moving `prod`
- A/B comparison — run two versions in parallel and compare outputs
- Debugging — reproduce an issue against a specific version

## Rolling back

If a deploy breaks something, either move the endpoint back or redeploy known-good code.

**Option 1: point the endpoint at an older version (no rebuild).**

Runtime — edit the version in `agentcore/agentcore.json` (`runtimes[].endpoints.prod.version`) and deploy:

There's no CLI command to move a Runtime endpoint; edit the JSON by hand or with `jq`:

```bash
jq '(.runtimes[] | select(.name=="<RuntimeName>") | .endpoints.prod.version) = <OLDER_VERSION>' \
  agentcore/agentcore.json > agentcore/agentcore.json.tmp && mv agentcore/agentcore.json.tmp agentcore/agentcore.json
agentcore deploy
```

The same edit with a newer version rolls forward.

Harness:

```bash
agentcore harness endpoint update --id <HARNESS_ID> --qualifier prod --target-version <OLDER_VERSION>
```

**Option 2: redeploy the previous code or config.** `git checkout <commit> -- ...` overwrites those paths in the working tree, including uncommitted edits — commit or stash them first.

```bash
git checkout <PREVIOUS_COMMIT> -- app/ agentcore/agentcore.json
agentcore deploy
```

This creates a *new* version with the old code, and `DEFAULT` moves to it. It's the only rollback for callers that use `DEFAULT`.

Option 1 is faster — just a pointer swap. Option 2 is cleaner because your code matches what's running. Don't use `agentcore harness update` to change a Harness that a project manages: the next `agentcore deploy` re-applies `harness.yaml`. Edit the YAML and deploy instead.

## Canary deployment

A Runtime or Harness endpoint points at exactly one version — there's no weighted routing on an endpoint. Two ways to canary:

- **Two endpoints:** keep `prod` on the known-good version, add a `canary` endpoint on the new one (`agentcore add runtime-endpoint --runtime <RuntimeName> --name canary --version <NEW_VERSION>`, then deploy), and route a slice of traffic to `canary` in your caller. When it looks good, move `prod` to the new version.
- **Behind a Gateway:** `agentcore eval ab-test target-based run` (see its `--help` for the required `--name`, `--gateway`, `--control`, `--treatment` flags) splits Gateway traffic between two Gateway targets with `--treatment-weight` (1-99) and compares their online evaluations. See `agents-optimize`.

Monitor `agents-optimize` eval scores, `agentcore logs runtime --name <RuntimeName> --qualifier canary`, and error rates before moving `prod`.

## Version retention

Versions aren't deleted when you deploy new ones, and the CLI has no command to delete individual versions. Deleting a Runtime (for example `agentcore remove runtime --name <Name>` followed by `agentcore deploy`) removes it along with its versions and endpoints.

A Harness is different: endpoints made with `agentcore harness endpoint create` aren't part of the stack, and the service won't delete a Harness that still has them. Before removing a Harness or tearing down the project, delete them and wait until only `DEFAULT` remains:

```bash
agentcore harness endpoint delete --id <HARNESS_ID> --qualifier prod
agentcore harness endpoint list --id <HARNESS_ID>      # repeat until only DEFAULT is listed
```

If you skip this, the deploy that removes the Harness fails with `DELETE_FAILED` (`Harness ... has endpoints that must be deleted before the harness can be deleted`); delete the endpoints and run `agentcore deploy` again. See `agents-deploy` → Removing resources and tearing down.

## Staging targets

For teams that want separate dev/staging/prod environments, use deployment targets:

```json
// agentcore/aws-targets.json
[
  {"name": "default", "account": "<DEV_ACCOUNT>", "region": "us-east-1"},
  {"name": "staging", "account": "<STAGING_ACCOUNT>", "region": "us-east-1"},
  {"name": "production", "account": "<PROD_ACCOUNT>", "region": "us-west-2"}
]
```

```bash
agentcore deploy --target staging
agentcore deploy --target production
```

Each target gets its own stack and its own Runtimes and Harnesses — versions and endpoints are separate per target. Use `--target` on `status`, `invoke`, `logs`, and `traces` to work with a specific one.

## Cross-references

- If a rollback is needed because of a specific failure, use `agents-debug` to diagnose first
- For staging/production best practices, see `agents-harden`
- For running evals against a specific version before cutover, see [`agents-optimize/references/evals.md`](../../agents-optimize/references/evals.md)
