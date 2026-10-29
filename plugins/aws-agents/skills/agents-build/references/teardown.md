# Remove a project resource

Use this reference for removing one resource from an AgentCore CLI v1 project. For tearing down an entire deployed target, use the `agents-deploy` teardown workflow, which previews and scopes deletion to a named target.

## Before removing

Read `agentcore/agentcore.json` and `agentcore/aws-targets.json`. Require CLI v1.0.0 or later and project config `"version": 2`. For a v0 project, commit, review `agentcore migrate`, and apply the reviewed plan with `agentcore migrate --yes` first. Identify the resource name, its parent if any, and each target where it is deployed. Confirm the intended deletion with the user when it will remove durable data such as Memory.

`agentcore remove` changes the local project declaration. `agentcore deploy --target <target>` applies the change in AWS for that target. `agentcore status --target <target> --json` reports deployed project resources; it has no `--state` or `--type` filter in v1.

## Remove a resource

```bash
agentcore remove memory --name MyMemory
agentcore remove gateway-target --gateway MyGateway --name WeatherTools
agentcore remove gateway --name MyGateway
agentcore remove credential --name MyAPIKey
agentcore remove runtime --name MyRuntime
agentcore remove harness --name MyHarness
agentcore remove policy --engine MyPolicyEngine --name SpendingLimit
agentcore remove policy-engine --name MyPolicyEngine
agentcore remove payment-connector --manager MyPayments --name Coinbase
agentcore remove payment-manager --name MyPayments
```

These are examples; use only the command for the resource the user selected. Remove child targets before their Gateway, policies before their engine, and connectors before their manager if project validation requires it. For an API key or OAuth provider, the resource type passed to `agentcore remove` is `credential`. Check `agentcore remove --help` for the resource types supported by the installed v1 CLI.

Before deploying, inspect the changed `agentcore/agentcore.json` and preview the target stack with `agentcore build` followed by `cd agentcore/cdk && npx cdk diff` using the project's target context. See the `agents-deploy` diff procedure for the exact target setup. Then deploy each intended target explicitly:

```bash
agentcore deploy --target <target>
agentcore status --target <target> --json
```

`--yes` on `agentcore deploy` is only the confirmation for deleting a target stack when the project declares nothing to deploy. It is not a general noninteractive deploy flag. Do not delete a CloudFormation stack by searching for a project name; a project can have several targets and other resources can survive stack deletion.
