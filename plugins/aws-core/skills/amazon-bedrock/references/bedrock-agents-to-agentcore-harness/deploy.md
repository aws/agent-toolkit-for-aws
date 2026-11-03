# Deploy a migrated Bedrock Agent as a v1 Harness

Use the approved discovery and mapping plan. Deploy in the source agent's region and preserve its inbound access posture. Do not change or delete the source Bedrock Agent as part of this migration.

## Scaffold and configure

```bash
agentcore create --name <ProjectName> --template empty
cd <ProjectName>
agentcore add harness \
  --name <HarnessName> \
  --model '{"provider":"bedrock","modelId":"<source-foundationModel>"}' \
  --authorizer-type AWS_IAM \
  --max-iterations 25 --max-tokens 4096 --timeout-seconds 300
agentcore add gateway --name <GatewayName> --authorizer-type AWS_IAM
```

Adjust invocation limits to the approved plan. A Bedrock Agent's source `foundationModel` may need an inference profile in the target region. Read `app/<HarnessName>/harness.yaml`; it uses `model.bedrockModelConfig.modelId`, not the JSON input shape used by `--model`. Put the mapped instruction in `app/<HarnessName>/system-prompt.md`. If the source idle session TTL matters, set `environment.agentCoreRuntimeEnvironment.lifecycleConfiguration.idleRuntimeSessionTimeout` in `harness.yaml` to the mapped value. Keep managed memory configured unless the assessment calls for a different mode.

For Code Interpreter, add one tool to the YAML `tools` list:

```yaml
tools:
  - type: agentcore_code_interpreter
    name: code_interpreter
    config:
      agentCoreCodeInterpreter: {}
```

The v1 CLI has no `add tool` command. Do not duplicate the YAML `tools` key. Run `agentcore build` after each configuration edit.

## Add Gateway targets

An action-group shim is a new Lambda backed Gateway target. Render the source action group into `tools/<shim>/handler.py` using the templates in this skill's `assets/`, with one `toolDefinitions` entry per source function or OpenAPI operation. The v1 CDK Python packager also requires a `pyproject.toml` in each shim's `compute.implementation.path`; the empty project and Harness scaffold do not create one under `tools/`. Place this minimal manifest beside each rendered `handler.py`, including KB shims:

```toml
# tools/<shim>/pyproject.toml
[project]
name = "agentcore-migration-shim"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["boto3"]
```

This Python requirement matches the `PYTHON_3_12` Lambda configuration below. Store the complete target object in a JSON file and add it through the CLI:

```json
{
  "name": "ActionGroupTools",
  "targetType": "lambda",
  "toolDefinitions": [
    {"name":"example_tool","description":"Describe the mapped operation","inputSchema":{"type":"object","properties":{}}}
  ],
  "compute": {
    "host": "Lambda",
    "implementation": {"language":"Python","path":"tools/action-group","handler":"handler.lambda_handler"},
    "pythonVersion": "PYTHON_3_12",
    "timeout": 30,
    "iamPolicy": {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"lambda:InvokeFunction","Resource":"<source-lambda-arn>"}]}
  }
}
```

```bash
agentcore add gateway-target --gateway <GatewayName> --target-configuration file://action-group-target.json
```

Use a scoped `bedrock:Retrieve` policy on the source Knowledge Base ARN for a KB shim. (IAM has no `bedrock-agent-runtime` service prefix; that is only the API client name.) For a Knowledge Base with default retrieval behavior that the managed connector supports, use `agentcore add gateway-connector --gateway <GatewayName> --name <TargetName> --connector bedrock-knowledge-bases --knowledge-base <KB_ID>` instead. `lambdaFunctionArn` targets point at an existing Lambda; use `lambda` with `compute` for a shim the project builds. Do not put secret values or unsupported `environment` keys into target configuration. Run `agentcore build` to catch schema errors.

## Shim security and capacity

- Give each action-group shim role only `lambda:InvokeFunction` on the exact source Lambda ARN. A KB shim needs `bedrock-agent-runtime:Retrieve` on the exact source Knowledge Base ARN; do not use resource `*`.
- Give the shim role `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` scoped to its `/aws/lambda/<shim-function>` log group. Encrypt that log group with a customer-managed KMS key and set an appropriate retention period. Avoid logging full tool inputs, responses, or retrieval passages.
- Set reserved concurrency on each shim Lambda to an approved bound so migration traffic cannot consume unlimited account concurrency. Alarm on its `Errors` and `Throttles` metrics.
- Enable CloudTrail **Lambda data events** for `lambda:Invoke` on the shim and source functions when invocation audit is required; ordinary management-event logging does not capture those calls.
- If the source Lambda is in another account or its resource policy denies the shim, give the source owner the proposed `aws lambda add-permission` change for review. The shim's own IAM policy does not modify the source Lambda policy. Do not apply a source-side permission change as part of the migration.

## First deploy and Gateway ARN

```bash
agentcore build
agentcore deploy --region <source-region>
agentcore status --json
```

The first deploy creates the default target in `agentcore/aws-targets.json` using the effective account and the explicit source region. Confirm both before proceeding. Find the deployed Gateway ARN in `agentcore status --json`. Record it in the approved migration plan. If deployment fails, inspect the CloudFormation failure and fix the project configuration; do not reset all deployed state or delete a stack by guesswork.

## Attach the Gateway to the Harness

Edit the existing `tools` list in `app/<HarnessName>/harness.yaml` once:

```yaml
tools:
  - type: agentcore_gateway
    name: migrated_tools
    config:
      agentCoreGateway:
        gatewayArn: arn:aws:bedrock-agentcore:<region>:<account>:gateway/<id>
        outboundAuth:
          awsIam: {}
```

The Gateway ARN exists only after the first deploy. The `outboundAuth` block governs the Harness to Gateway call. The Gateway's `authorizerType` and Harness's `authorizerType` govern inbound access. A classic Bedrock Agent is IAM gated; explicitly preserve at least that posture and confirm the caller roles have only the necessary new permissions. The v1 Gateway default is `NONE`, so do not omit `--authorizer-type AWS_IAM` during creation. The Harness tool name must be unique.

```bash
agentcore build
agentcore deploy
agentcore status --json
```

Confirm the second deploy succeeds and the Harness and Gateway are deployed. An optional parity check uses `agentcore invoke --harness <HarnessName> --prompt "Hello"`; compare the output with the source agent before traffic cutover.

## Clean up or roll back a dedicated migration project

If the migration should be reversed, the source Bedrock Agent remains available because this workflow does not change or delete it. Return callers to the source before removing the new Harness stack. In a project dedicated to this migration, inspect the selected target and deployed resources, then run:

```bash
agentcore status --target <target> --json
agentcore remove all --yes
agentcore deploy --yes --target <target>
```

`remove all` empties the project's resource configuration for every target, so follow the `agents-deploy` teardown procedure when the project has other targets or resources; back up `agentcore/agentcore.json` and `agentcore/.env.local` first. Delete any non-default Harness endpoints before removing the Harness. After verifying the stack is gone, delete the sensitive `./out/source-agent.json` discovery manifest unless it must be retained in encrypted audit storage.

## Source permissions and verification

The shim's role must be allowed to invoke the source Lambda ARN. If a source Lambda policy change is required, hand the exact proposed change to the source owner; keep source-side changes outside the migration automation. Give the shim role only the Lambda or KB permission it needs and verify its CloudWatch log access. Alarm on Lambda errors and throttles, and avoid logging full tool arguments or retrieval text. Do not claim successful migration until `agentcore build` and both deploys complete and the target status reports deployed resources.
