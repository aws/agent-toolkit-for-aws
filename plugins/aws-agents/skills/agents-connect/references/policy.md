# Gateway policies in AgentCore CLI v1

Use Cedar policy engines to authorize Gateway tool calls. Policies act at the Gateway boundary; they do not replace Runtime or Harness inbound authentication, and Bedrock Guardrails are a different feature.

## Inspect the project

Read `agentcore/agentcore.json` for `agentCoreGateways`, `policyEngines`, and each Gateway's `policyEngineConfiguration`. For a v0 project (`"version": 1`), commit, review `agentcore migrate`, then apply the reviewed plan with `agentcore migrate --yes` before continuing. Require CLI v1.0.0 or later.

Choose a Gateway and list the tool names and caller identities that should be allowed. When an attached engine enforces decisions, write explicit `permit` policies for desired calls. A matching `forbid` overrides a `permit`.

## Create and attach an engine

For a new Gateway and engine, add the Gateway with an explicit inbound authorizer, then add the engine and attach in log-only mode:

```bash
agentcore add gateway --name MyGateway --authorizer-type AWS_IAM
agentcore add policy-engine \
  --name MyPolicyEngine \
  --attach-to-gateways MyGateway \
  --attach-mode log-only
agentcore build
agentcore deploy --region <region>
agentcore status --json
```

`--attach-mode` accepts `log-only` or `enforce`; the v0 `LOG_ONLY` and `ENFORCE` flag values are not the v1 spelling. For an existing Gateway with no engine, `agentcore add policy-engine --attach-to-gateways MyGateway` can attach it. To change a Gateway's existing mode, edit its `policyEngineConfiguration` in `agentcore/agentcore.json`, run `agentcore build`, then deploy. `agentcore add gateway` creates a Gateway; it does not update an existing one. Use `--policy-engine-name` and `--policy-engine-mode` when creating a new Gateway around an engine already declared in the project.

## Write a Cedar policy

A policy referencing the deployed Gateway ARN requires the first deploy. Obtain that ARN from `agentcore status --json`. Save the Cedar statement to a file, review it, and add it to the project:

```bash
agentcore add policy \
  --engine MyPolicyEngine \
  --name refund_policy \
  --statement file://policy.cedar \
  --validation-mode fail-on-any-findings \
  --enforcement-mode log-only
agentcore build
agentcore deploy
```

`--statement` accepts inline text, `file://<path>`, or `-` for stdin. The v0 `--source` and `-g` flags are gone. If the policy checks an output, set `--authorization-phase return-output`; otherwise the CLI infers the phase from the statement. Tool action names use `AgentCore::Action::"TargetName___tool_name"` (three underscores). Confirm the name from the deployed Gateway target and test the intended principal, tool, and arguments.

For natural language generation, use the Gateway resource command with its deployed ID or ARN:

```bash
agentcore gateway policy generate \
  --gateway-id <gateway-id-or-arn> \
  --policy-engine-id <engine-id-or-arn> \
  --prompt "Allow the refund tool only for approved operators"
```

Review the generated Cedar and save the chosen statement to `policy.cedar`; add it with `agentcore add policy --statement file://policy.cedar`. Generation does not create the project policy for you.

## Test and enforce

Start with the Gateway's engine in `log-only` and the policy in `log-only`. Exercise allowed and denied tool calls and inspect policy decisions in the service's policy decision logs. `agentcore logs runtime` and `agentcore logs harness` show agent application logs, not necessarily the Gateway policy decision stream.

After checking the expected decisions, set the Gateway's `policyEngineConfiguration` mode to `ENFORCE` and the desired policy's `enforcementMode` to `ACTIVE` in `agentcore/agentcore.json`, then run `agentcore build` and `agentcore deploy`. Confirm the actual enum values against the v1 project schema and CLI output before editing. Test an allowed call and a denied call against the deployed Gateway.

If a call is denied unexpectedly, check the policy's action name, Gateway ARN, principal type, authorization phase, and engine attachment. If every call is denied, check that at least one applicable `permit` is active. Do not solve a denial by changing the Gateway's inbound auth to `NONE`.
