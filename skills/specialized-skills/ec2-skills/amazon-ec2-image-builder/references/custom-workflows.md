# Advanced builds: custom image workflows and execution roles

Image Builder's build and test stages are themselves workflows. Unless custom workflows are attached, every AMI build uses the Amazon-managed defaults — `build-image` (BUILD) and `test-image` (TEST); container builds use `build-container`/`test-container`. Most users never need to change them: customize only when the default stages can't express the build (stage-level steps beyond components, custom orchestration around instance launch, skipping or reordering stage behavior).

## The execution role comes first

Custom workflows always require an execution role — the role Image Builder itself assumes to run the workflows. Without one, `create-image`/`create-image-pipeline` rejects the request: `An execution role is required to provide workflows`. The `EC2ImageBuilderExecutionPolicy` managed policy covers the baseline permissions:

```bash
execution_role_arn=$(aws iam create-role --role-name ${name}-execution \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"imagebuilder.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"${account_id}"}}}]}' \
  --query Role.Arn --output text)
aws iam attach-role-policy --role-name ${name}-execution --policy-arn arn:aws:iam::aws:policy/EC2ImageBuilderExecutionPolicy
```

This is not the build role from creating-images.md step 3 (that one lives on the build instance); the execution role is assumed by the Image Builder service.

## Define and attach workflows

Start from an Amazon-managed workflow document rather than writing one from scratch — `aws imagebuilder get-workflow` returns the YAML in the `data` field. The document shape (steps chain via `$.stepOutputs`):

```yaml
name: ${workflow_name}
description: Custom build workflow
schemaVersion: 1.0
steps:
  - name: LaunchBuildInstance
    action: LaunchInstance
    onFailure: Abort
    inputs:
      waitFor: "ssmAgent"
  - name: ApplyBuildComponents
    action: ExecuteComponents
    onFailure: Abort
    inputs:
      instanceId.$: "$.stepOutputs.LaunchBuildInstance.instanceId"
  - name: CreateOutputAMI
    action: CreateImage
    onFailure: Abort
    inputs:
      instanceId.$: "$.stepOutputs.LaunchBuildInstance.instanceId"
  - name: TerminateBuildInstance
    action: TerminateInstance
    onFailure: Continue
    inputs:
      instanceId.$: "$.stepOutputs.LaunchBuildInstance.instanceId"
outputs:
  - name: ImageId
    value: "$.stepOutputs.CreateOutputAMI.imageId"
```

Like components, `create-workflow` accepts `--dry-run` to validate the document without creating anything — a valid document returns `DryRunOperationException` ("Request would have succeeded"), an invalid one returns the actual validation error. Create your version, then attach it to the build along with the execution role:

```bash
custom_workflow_arn=$(aws imagebuilder create-workflow --name ${name}-build --semantic-version 1.0.0 --type BUILD \
  --data file://workflow.yaml --region ${region} \
  --query workflowBuildVersionArn --output text)
aws imagebuilder create-image --image-recipe-arn ${recipe_arn} \
  --infrastructure-configuration-arn ${infra_arn} \
  --workflows "workflowArn=${custom_workflow_arn}" "workflowArn=arn:aws:imagebuilder:${region}:aws:workflow/test/test-image/x.x.x" \
  --execution-role ${execution_role_arn} --region ${region}
```

- Workflow types are `BUILD`, `TEST`, and `DISTRIBUTION`. A distribution workflow is an optional override — without one, the attached distribution configuration still runs; the Amazon-managed `distribute-image` and `distribute-container` are the starting points. The Amazon-managed defaults are `arn:aws:imagebuilder:${region}:aws:workflow/build/build-image/x.x.x` and `.../workflow/test/test-image/x.x.x`, and Amazon-managed variants exist too (e.g. `build-image-with-update-ssm-agent`) — browse with `aws imagebuilder list-workflows --owner Amazon`.
- The same `--workflows` + `--execution-role` pair works on `create-image-pipeline`.
- Workflows can pause for approval or external automation with a `WaitForAction` step, which does its own wiring: it publishes an `EC2 Image Builder Workflow Step Waiting` event to the default EventBridge bus, and can invoke a Lambda function asynchronously (`lambdaFunctionName`, with an optional JSON `payload`). The invocation carries the waiting step's execution id, so the function can run its checks and act directly; whatever responds — automation or an operator — resumes or stops the build with `send-workflow-step-action --action RESUME|STOP` (pause default 3 days, maximum 7; the call's reason surfaces as the step's `reason` output). Lambda invocation needs `lambda:InvokeFunction` on the execution role, scoped to the invoked function's ARN.
- An `ExecuteStateMachine` step starts an AWS Step Functions state machine (`stateMachineArn`, optional JSON `input`) and waits for it to complete — the direct integration for compliance validation or certification flows. The execution role needs `states:StartExecution` and `states:DescribeExecution`, scoped to the state machine and its executions.
- A `RunCommand` step runs an SSM command document against the build instance (`documentName`, `parameters`, and `instanceId.$` chained from the launch step) — the hook for hardening, scanning, or setup logic that lives in SSM documents rather than components.
- If a custom-workflow build finishes AVAILABLE but the "output" AMI is just the parent AMI (possibly owned by another account): the build likely attached only a TEST workflow — without a BUILD workflow, no new AMI is created.
- Each step action's inputs, outputs, timeouts, and IAM requirements are in the [supported step actions documentation](https://docs.aws.amazon.com/imagebuilder/latest/userguide/wfdoc-step-actions.html); the broader document schema and workflow management are in the [image workflows documentation](https://docs.aws.amazon.com/imagebuilder/latest/userguide/manage-image-workflows.html).
