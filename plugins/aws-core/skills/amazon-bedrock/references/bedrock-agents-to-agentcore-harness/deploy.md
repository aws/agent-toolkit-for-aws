# Deploy

Deploy into the **source agent's region** (mirror). If any step fails, surface the error and stop — **fail loudly**, never silently work around a failure.

## CRITICAL: set the deploy-target region right after scaffold (region trap)
`agentcore create` with no resolved region **silently writes a default region** into `agentcore/aws-targets.json` that is usually not the source agent's. Immediately after scaffold, before any `add`/`deploy`: **edit `agentcore/aws-targets.json` so the deploy-target region is the source agent's region**, and verify it before the first deploy. A wrong region is wrong on two counts: the shims invoke the **source** Lambdas / KB **by ARN**, so a harness elsewhere can't reach them; and a deploy can hit region-specific Harness CFN-type issues that surface as a stack rollback (read the CloudFormation failure; if region-specific, redeploy in the source region).

If a deploy already landed in the wrong region: `aws cloudformation delete-stack` the wrong-region stack, reset `agentcore/.cli/deployed-state.json` to `{"targets":{}}`, fix `aws-targets.json`, then redeploy.

## Source-side prerequisites — the builder grants these, never the migration (INV-1)

The AG shim invokes the **original** source Lambda by ARN, so the source Lambda's resource policy must allow the shim's execution role to call it. **This is the builder's job, not the migration's** — the skill must never mutate source-side infrastructure to unblock itself.

Expect the **first shim invocation to fail with `AccessDeniedException`** until the permission exists. When it does: **stop and hand the builder this command; do NOT run `aws lambda add-permission` on the source yourself** (that mutates the source and breaks INV-1):

```bash
aws lambda add-permission --function-name <original-fn> \
  --statement-id agentcore-shim-invoke --action lambda:InvokeFunction \
  --principal <shim-role-arn> --source-arn <shim-lambda-arn>
```

(`bedrock-agent-runtime:Retrieve` for the KB shim is granted on the shim role via its `iamPolicy`, so the KB path needs no source-side change — only the AG-shim → original-Lambda invoke does.)

## Two-phase deploy

A gateway tool can only attach once the gateway and its targets are *deployed* (`add tool --type agentcore_gateway` reads the gateway's deployed tool list). So deploy twice:

1. **Scaffold:** `agentcore create` (plain — not the `--type import`/`agentcore import` path, which builds a *code* project, not a Harness). Then `cd` in and run **every** later `add`/`deploy`/`status` from that one directory — those commands resolve the project from the cwd, so a second project or a different dir yields "No agentcore project found".
2. **Add** infra that doesn't need a deployed gateway:
   - `agentcore add gateway`, then hand-add one **`targetType: "lambda"` code target** to `agentcore.json` per action group / KB shim (see "How shims are deployed").
   - `agentcore add harness` (one command, all flags): `--model-id` (= source `foundationModel`), `--temperature`/`--top-p`/`--model-max-tokens` (only one of temperature/top-p when the model rejects both), `--system-prompt` (folded instruction + non-DEFAULT override intent, per [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)). Managed memory stays on. `--additional-params` is `lite_llm`-provider only, so a bedrock harness rejects it — which is why the source guardrail is classified **cannot migrate** (verify the current CLI surface per [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)'s guardrail section before relying on this).
   - if the source had CodeInterpreter: `agentcore add tool --harness <name> --type agentcore_code_interpreter --name <tool-name>`.
3. **First deploy:** `agentcore deploy` — creates gateway, targets, harness, memory.
4. **Attach the gateway tool** (gateway now deployed): `agentcore add tool --harness <name> --type agentcore_gateway --name <tool-name> --gateway <gateway-project-name> --outbound-auth awsIam`. `--gateway <project-name>` resolves the deployed ARN automatically. **Add it exactly once** — check `harness.json`/`agentcore status` first; a duplicate `agentcore_gateway` tool deploys fine but breaks at runtime (`Tool name '…' already exists`), silently disabling every gateway-backed tool. If already doubled, remove the extra from `harness.json` and redeploy.
5. **Second deploy:** `agentcore deploy` — applies the gateway tool. The migration isn't complete until this succeeds and `agentcore status` shows the harness at a new version with the tool.

## Inbound auth — match the source's invocation posture, never loosen it (INV-2/INV-3)

`--outbound-auth awsIam` above governs how the **harness calls the gateway**. It says nothing about **who may invoke the migrated harness/gateway** — that is *inbound* auth, and it is a separate, mandatory decision. The source Bedrock Agent is IAM-gated: only principals with `bedrock-agent-runtime:InvokeAgent` on that agent's ARN can invoke it. The migrated harness must be **no more reachable than that**.

- **Discover the source posture** (Phase 2): which principals hold `bedrock-agent-runtime:InvokeAgent` on the source, and any resource-based policy on the agent. This is the bar to match.
- **Configure inbound auth explicitly** on `add harness`/`add gateway` — check `agentcore add harness --help` and `add gateway --help` for the inbound-auth flag (SigV4 with an allowed-role list, JWT with a verified issuer, etc.) and set it to match the discovered posture. Do **not** rely on the CLI default.
- **If the CLI's inbound default is unauthenticated or broader than the source** (or you cannot determine it), **hard-stop** and have the builder confirm the intended posture before deploying — a migrated agent invokable by parties who couldn't reach the source violates both secure-by-default and preserve-posture.

## How shims are deployed — hand-author the code target, CLI builds it at deploy

`agentcore add gateway-target` **cannot create a code target non-interactively** (`--type lambda` is rejected). So this is one of the guide's explicitly sanctioned hand-edits (see "Config edits — the rule"): add the target to `agentcore.json` yourself, then `agentcore deploy` builds the Lambda from your source. Per shim:

1. Place rendered shim at `tools/<shim>/handler.py` (from `{kb_shim,lambda_shim}.py.tmpl` in `assets/`) with a `pyproject.toml` beside it.
2. Add one entry to `agentCoreGateways[<i>].targets[]` in `agentcore.json`:

   ```json
   {
     "name": "<shim-name>",
     "targetType": "lambda",
     "toolDefinitions": [ /* one per function/operation; mirror source schema exactly */ ],
     "compute": {
       "host": "Lambda",
       "implementation": { "language": "Python", "path": "tools/<shim>", "handler": "handler.lambda_handler" },
       "pythonVersion": "<PYTHON_VERSION_ENUM>",
       "timeout": 30,
       "iamPolicy": { /* full policy document, least-privilege — see below */ }
     }
   }
   ```

3. Run `agentcore validate` (must print `Valid`), then `agentcore deploy`.

**No `environment` key — all shim config is baked in at render time.** The `compute` schema is strict and has **no** environment-variable support; adding an `environment` key fails `agentcore validate`. Every `{{TOKEN}}` in the shim templates (`ORIGINAL_LAMBDA_ARN`, `SCHEMA_STYLE`, `OP_ROUTES`, `KB_ID`, …) is substituted directly into `tools/<shim>/handler.py` as a literal. An unsubstituted token causes a `SyntaxError` or wrong behavior at runtime — the post-render grep in [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md) is the gate.

**Scope `iamPolicy` to a single resource ARN — never a wildcard.** It is a full policy document (`Version` + `Statement` array are required), granting exactly one action on exactly one resource:

- AG shim — invoke only the original Lambda:

  ```json
  { "Version": "2012-10-17", "Statement": [
    { "Effect": "Allow", "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:<region>:<account>:function:<original-name>" } ] }
  ```

- KB shim — retrieve only from the source KB:

  ```json
  { "Version": "2012-10-17", "Statement": [
    { "Effect": "Allow", "Action": "bedrock-agent-runtime:Retrieve",
      "Resource": "arn:aws:bedrock:<region>:<account>:knowledge-base/<kb-id>" } ] }
  ```

**Logging & monitoring.** Give the execution role `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` scoped to the function's log group (`arn:aws:logs:<region>:<account>:log-group:/aws/lambda/<fn>:*`); recommend a CloudWatch alarm on the shim's `Errors`/`Throttles` metrics; and confirm CloudTrail captures `lambda:Invoke` for audit. The shims handle tool arguments (AG shim) and retrieval text (KB shim), which may be sensitive: **encrypt the log group with a KMS key** (`aws logs associate-kms-key --log-group-name /aws/lambda/<fn> --kms-key-id <key-arn>`) and do **not** log full request/response payloads.

**Throttling & blast radius.** Set **reserved concurrency** on each shim Lambda (`aws lambda put-function-concurrency`) so a runaway caller can't exhaust account-wide Lambda concurrency, and enable request throttling on the Gateway if the CLI/service exposes it.

**Non-negotiable details (these fail `agentcore validate` if wrong):**

- The `compute` block is **strict** — unknown keys (e.g. `environment`) are rejected, and a Python Lambda **must** set `pythonVersion`.
- `pythonVersion` is an enum (e.g. `PYTHON_3_12`), **not** a bare `"3.12"` — check the project's `agentcore.json` schema (or `agentcore validate` feedback) for the currently valid values. Prefer the source Lambda's runtime.
- `implementation` requires all three of `language`, `path`, `handler` and nothing else.
- `targetType` is the literal string `"lambda"` here (valid in the JSON schema, even though `--type lambda` is rejected on the CLI).
- `path` is relative to the project root (parent of `agentcore/`).
- `handler` is `<file>.<function>` = `handler.lambda_handler`.

Do **not** use `--type lambda-function-arn` — that wires a *pre-existing* Lambda by ARN, not a shim this skill builds.

## Config edits — the rule
Hand-edit a config file **only where this guide explicitly says to** — the region correction in `aws-targets.json`, the `targetType: "lambda"` code target in `agentcore.json`, the documented recovery edits (removing a duplicate `agentcore_gateway` tool from `harness.json`; resetting `deployed-state.json` for a wrong-region redeploy). Everything else goes through `agentcore` commands — harness and tools via `add harness`/`add tool`, gateways and other targets via `add gateway`/`add gateway-target`. Do not invent new hand-edits: when an `add` command fails, fix its flags (missing `--name`, wrong `--type`) rather than editing `harness.json`/`agentcore.json` to route around the failure.

## One action group = one target, with all its functions
A Bedrock action group can expose several functions/operations (up to three), each with its own schema. The tool-schema file is a **`ToolDefinition[]` array**, so a single Lambda target carries every function in that action group — one array entry per function/operationId. Do not split an action group into multiple targets. [tool_schema.json.tmpl](assets/tool_schema.json.tmpl) is already an array; add one entry per function, mirroring the source schema exactly ([mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).

## Verification
The migration is done when `agentcore deploy` reports success. Before treating it as complete, **prompt the user** to confirm the deploy succeeded and they're satisfied — surface the deployed harness/gateway ARNs from `agentcore status`. Deeper parity (invoking the harness, comparing against the source) is out of scope unless the user asks.

## Rendering templates into CLI inputs

- KB shim / AG shim Lambda code: adapt the `*.py.tmpl` files in `assets/` (rendering rules in [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)) and place the rendered handler at `tools/<shim>/handler.py` — see "How shims are deployed" above.
- Tool-schema files: one array per target, one entry per source function/operation, mirroring the source schema exactly ([mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).
