# Deploy

Deploy into the **source agent's region** (mirror). If any step fails, surface the error and stop — **fail loudly**, never silently work around a failure.

## CRITICAL: pin the deploy region on the first deploy (region trap)
A new project has **no** deployment target (`agentcore/aws-targets.json` is `[]`). The first `agentcore project deploy` creates the `default` target from the **active credentials' account** and the CLI's **effective region** (`--region`, else `AWS_REGION`, else the shared AWS config) and writes it to `agentcore/aws-targets.json`. That region is whatever the shell happens to resolve. It is usually not the source agent's. So run the first deploy as `agentcore project deploy --region <source-region>` and confirm the "Created default deployment target" line names the source region and account. Later commands (`status`, `invoke`, `log`) read the region from the target, not from the shell. A wrong region is wrong on two counts: the shims invoke the **source** Lambdas / KB **by ARN**, so a harness elsewhere can't reach them; and the region must be one AgentCore supports (the CLI rejects others).

If a deploy already landed in the wrong region: `aws cloudformation delete-stack` the wrong-region stack, remove that target's entry from `agentcore/.cli/deployed-state.json`, fix the `region` in `agentcore/aws-targets.json`, then redeploy.

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

A harness's gateway tool is declared with the gateway's **ARN** (`agentCoreGateway.gatewayArn`). The CLI does not resolve a project gateway's name into that ARN, and the ARN exists only after the gateway is deployed. So deploy twice:

1. **Scaffold:** `agentcore project create --name <project>` with no `--template`. This creates a managed-harness project: `agentcore/agentcore.json`, `agentcore/aws-targets.json`, `agentcore/cdk/`, and `app/<project>/harness.yaml` and `system-prompt.md` (managed memory on). Do **not** use `project add runtime --type import`. It translates the Bedrock Agent into a *code* Runtime, not a Harness. Then `cd` in and run **every** later `project …` command from that directory. They resolve the project from the cwd.
2. **Configure the harness** in `app/<project>/harness.yaml` (the sanctioned edit; see "Config edits: the rule"): `model.modelId` = source `foundationModel`, `model.temperature` / `model.topP` / `model.maxTokens` (only one of temperature/topP when the model rejects both), the folded instruction in `system-prompt.md` (per [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)), `lifecycleConfig.idleRuntimeSessionTimeout` = source `idleSessionTTLInSeconds`, `authorizerType: AWS_IAM` (see "Inbound auth"). Leave `memory: { mode: managed }`. If the source had CodeInterpreter, add `- { type: agentcore_code_interpreter, name: <tool-name> }` under `tools`. `model.additionalParams` is `lite_llm`-provider only, so a bedrock harness rejects it. That is why the source guardrail is classified **cannot migrate** (verify per [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)'s guardrail section). Alternatively pass the same values as flags to `agentcore project add harness` (`--system-prompt`, `--model <json>`, `--tools <json>`, `--lifecycle-config <json>`, `--authorizer-type`), which writes the YAML for you.
3. **Add the gateway and its targets:**
   - `agentcore project add gateway --name <gw> --authorizer-type AWS_IAM`
   - one **`targetType: "lambda"` code target** per action group / KB shim: `agentcore project add gateway-target --gateway <gw> --target-configuration file://<target>.json` (see "How shims are deployed")
   - a MANAGED KB with default retrieval config: `agentcore project add gateway-connector --gateway <gw> --name <n> --connector bedrock-knowledge-bases --knowledge-base <kb-id>`
4. **First deploy:** `agentcore project build` (validates the spec, so fix errors before deploying), then `agentcore project deploy --region <source-region>`. This creates the harness, memory, gateway, targets, and the shim Lambdas.
5. **Attach the gateway tool** (gateway now deployed): read the gateway ARN from `agentcore project status --json` (it is also a `Gateway<Name>Arn` output on the project's CloudFormation stack) and add **exactly one** entry to the existing `tools` list in `harness.yaml` (edit the list in place, do not append a second `tools:` key, which is a duplicate YAML key and fails the read):

   ```yaml
   tools:
     - name: <tool-name>
       type: agentcore_gateway
       config:
         agentCoreGateway:
           gatewayArn: arn:aws:bedrock-agentcore:<region>:<account>:gateway/<gateway-id>
           outboundAuth:
             awsIam: {}
   ```

   A duplicate `agentcore_gateway` tool deploys fine but breaks at runtime (`Tool name '…' already exists`), silently disabling every gateway-backed tool. If already doubled, remove the extra entry and redeploy.
6. **Second deploy:** `agentcore project deploy`, applies the gateway tool. The migration isn't complete until this succeeds and `agentcore project status` shows the harness deployed with the tool.

## Inbound auth — match the source's invocation posture, never loosen it (INV-2/INV-3)

`outboundAuth: awsIam` above governs how the **harness calls the gateway**. It says nothing about **who may invoke the migrated harness/gateway**, that is *inbound* auth, and it is a separate, mandatory decision. The source Bedrock Agent is IAM-gated: only principals with `bedrock-agent-runtime:InvokeAgent` on that agent's ARN can invoke it. The migrated harness must be **no more reachable than that**.

- **Discover the source posture** (Phase 2): which principals hold `bedrock-agent-runtime:InvokeAgent` on the source, and any resource-based policy on the agent. This is the bar to match.
- **Gateway: the CLI default is `authorizerType: NONE` (unauthenticated).** Always pass `--authorizer-type AWS_IAM` on `project add gateway` (or `CUSTOM_JWT` with `--authorizer-configuration` if the source posture is JWT-based). Never leave the default.
- **Harness:** set `authorizerType: AWS_IAM` in `harness.yaml` (or `--authorizer-type AWS_IAM` on `project add harness`), or `CUSTOM_JWT` with an `authorizerConfiguration` to match a verified issuer. Do **not** rely on an unset value.
- **If the resulting posture is broader than the source** (or you cannot determine the source's), **hard-stop** and have the builder confirm the intended posture before deploying, a migrated agent invokable by parties who couldn't reach the source violates both secure-by-default and preserve-posture.

## How shims are deployed: a `lambda` code target the CLI builds at deploy

Each shim is a **`targetType: "lambda"` code target**: you supply the Python source, `agentcore project deploy` bundles it and creates the Lambda, its execution role, and the gateway target. Per shim:

1. Place the rendered shim at `tools/<shim>/handler.py` (from `{kb_shim,lambda_shim}.py.tmpl` in `assets/`) with a `pyproject.toml` beside it.
2. Write the target as a JSON file and add it with `agentcore project add gateway-target --gateway <gw> --target-configuration file://<shim>.json`:

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

3. Run `agentcore project build` (must succeed), then `agentcore project deploy`.

**No `environment` key, all shim config is baked in at render time.** The `compute` schema is strict and has **no** environment-variable support; an `environment` key fails validation. Every `{{TOKEN}}` in the shim templates (`ORIGINAL_LAMBDA_ARN`, `SCHEMA_STYLE`, `OP_ROUTES`, `KB_ID`, …) is substituted directly into `tools/<shim>/handler.py` as a literal. An unsubstituted token causes a `SyntaxError` or wrong behavior at runtime, the post-render grep in [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md) is the gate.

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

**Logging & monitoring.** The CLI attaches the AWS managed policy `AWSLambdaBasicExecutionRole` to every shim role. That policy grants `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` on `*`, which is broader than the single log group the shim writes to, and the `compute` block has no way to opt out of it. Keep `iamPolicy` itself scoped to the one action and one resource above so the managed policy is the only wildcard on the role. After the first deploy, as a standard step of the migration, replace that managed policy on each shim role with a log-group-scoped statement: `aws iam detach-role-policy --role-name <shim-role> --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole`, then `aws iam put-role-policy` with `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` on `arn:aws:logs:<region>:<account>:log-group:/aws/lambda/<fn>:*`. Record the change in the migration assessment so the builder knows a later `agentcore project deploy` may re-attach the managed policy and the step must be repeated. Recommend a CloudWatch alarm on the shim's `Errors`/`Throttles` metrics; and confirm CloudTrail captures `lambda:Invoke` for audit. The shims handle tool arguments (AG shim) and retrieval text (KB shim), which may be sensitive: **encrypt the log group with a KMS key** (`aws logs associate-kms-key --log-group-name /aws/lambda/<fn> --kms-key-id <key-arn>`) and do **not** log full request/response payloads.

**Throttling & blast radius.** Set **reserved concurrency** on each shim Lambda (`aws lambda put-function-concurrency`) so a runaway caller can't exhaust account-wide Lambda concurrency, and enable request throttling on the Gateway if the CLI/service exposes it.

**Non-negotiable details (these fail `agentcore project build` if wrong):**

- The `compute` block is **strict** — unknown keys (e.g. `environment`) are rejected, and a Python Lambda **must** set `pythonVersion`.
- `pythonVersion` is an enum (e.g. `PYTHON_3_12`), **not** a bare `"3.12"`, the validation error lists the currently valid values. Prefer the source Lambda's runtime.
- `implementation` requires all three of `language`, `path`, `handler` and nothing else.
- `targetType` is the literal string `"lambda"`. The `--target-configuration` help text lists other target types. `lambda` is accepted even though it is not listed.
- `path` is relative to the project root (parent of `agentcore/`).
- `handler` is `<file>.<function>` = `handler.lambda_handler`.

Do **not** use `targetType: "lambdaFunctionArn"`, that wires a *pre-existing* Lambda by ARN, not a shim this skill builds.

## Config edits — the rule
Hand-edit a config file **only where this guide explicitly says to**, `app/<harness>/harness.yaml` and `system-prompt.md` (the harness's own configuration format, meant to be edited), the `region` correction in `agentcore/aws-targets.json`, and the documented recovery edit (removing a wrong-region target from `agentcore/.cli/deployed-state.json`). Everything else goes through `agentcore project …` commands, gateways via `project add gateway`, targets via `project add gateway-target` / `project add gateway-connector`. Do not hand-edit `agentcore/agentcore.json`: when an `add` command fails, fix its flags (missing `--name`, bad JSON) rather than editing the spec to route around the failure.

## One action group = one target, with all its functions
A Bedrock action group can expose several functions/operations (up to three), each with its own schema. The target's `toolDefinitions` is an **array**, so a single Lambda target carries every function in that action group, one array entry per function/operationId. Do not split an action group into multiple targets. [tool_schema.json.tmpl](assets/tool_schema.json.tmpl) is already an array; add one entry per function, mirroring the source schema exactly ([mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).

## Verification
The migration is done when the second `agentcore project deploy` reports success. Before treating it as complete, **prompt the user** to confirm the deploy succeeded and they're satisfied, surface the deployed harness/gateway ARNs from `agentcore project status --json`. Deeper parity (`agentcore project invoke harness --name <harness> --prompt "…"`, comparing against the source) is out of scope unless the user asks.

## Rendering templates into CLI inputs

- KB shim / AG shim Lambda code: adapt the `*.py.tmpl` files in `assets/` (rendering rules in [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)) and place the rendered handler at `tools/<shim>/handler.py` — see "How shims are deployed" above.
- Tool-schema files: one `toolDefinitions` array per target, one entry per source function/operation, mirroring the source schema exactly ([mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).
