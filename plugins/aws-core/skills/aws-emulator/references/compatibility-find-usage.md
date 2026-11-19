# Compatibility check: find AWS usage

A guide for step 2 of [references/compatibility-check.md](references/compatibility-check.md),
which has the `usage.json` format. It describes what AWS usage looks like, not a list to match
against: read the code and follow values to where they are built. Search the whole app (sources,
tests, scripts, CI, IaC, config), skipping dependency and build directories.

## Contents

1. [Where to start](#where-to-start)
2. [Settings vs data](#settings-vs-data)
3. [Assumptions](#assumptions)
4. [Hard cases](#hard-cases)

## Where to start

Grep for these markers, then read every hit in context. Step 5 greps a similar list and
reports any file you did not account for as unanalyzed.

| Ecosystem | Markers | A call looks like |
|---|---|---|
| JS/TS SDK v3 | `@aws-sdk/client-*`, `@aws-sdk/lib-*` | `client.send(new PutItemCommand({...}))`, `paginateScan(cfg, input)`, `waitUntilTableExists` |
| JS SDK v2 | `aws-sdk` | `new AWS.SQS().sendMessage({...}).promise()` |
| Python | `boto3`, `botocore`, `aiobotocore` | `boto3.client("sqs").send_message(QueueUrl=..)`, `table.put_item(...)` (resource API), `get_paginator("list_objects_v2")`, `get_waiter(...)` |
| Java | `software.amazon.awssdk`, `com.amazonaws` | `sqs.sendMessage(SendMessageRequest.builder()...build())` |
| Go | `github.com/aws/aws-sdk-go(-v2)` | `client.PutObject(ctx, &s3.PutObjectInput{...})` |
| .NET | `AWSSDK.*`, `using Amazon.*` | `await client.PutItemAsync(new PutItemRequest{...})` |
| Ruby | `aws-sdk-*`, `Aws::` | `Aws::S3::Client.new.put_object(bucket:, key:)` |
| Rust | `aws-sdk-*` | `client.put_object().bucket(b).send().await` |
| Shell / CLI | `aws <service> <command>` in `*.sh`, Makefiles, CI YAML, `package.json` scripts, Dockerfiles | `aws sqs send-message --queue-url "$Q" --delay-seconds 5` |
| CloudFormation / SAM | `AWS::<Service>::<Resource>`, `Transform: AWS::Serverless` | `Type: AWS::SQS::Queue` with `Properties` |
| CDK | `aws-cdk-lib`, `@aws-cdk/` | `new sqs.Queue(this, "Q", {fifo: true})`, `bucket.grantRead(fn)` |
| Terraform | `provider "aws"`, `resource "aws_*"` | `resource "aws_sqs_queue" "q" { fifo_queue = true }` |
| Serverless Framework | `serverless.yml` `provider: name: aws` | `functions.*.events: - sqs: arn:...` |

Operation names: SDK method names map to the API operation (`send_message`, `sendMessage`,
`SendMessageCommand`, `send-message` → `SendMessage`).

## Settings vs data

For each call, list each parameter once:

- `settings`: anything that changes how the service behaves — flags (`ConsistentRead`), enums
  (`ReturnValues: ALL_NEW`, `StreamViewType`), numbers (`WaitTimeSeconds: 20`, `Limit`), policies
  and attributes (`FilterPolicy`, `RedrivePolicy`, `FifoQueue`), expressions
  (`ConditionExpression`, `KeyConditionExpression`, `FilterPattern`), pagination tokens
  (`ExclusiveStartKey`, `NextToken`). Value: the literal, or `"<dynamic>"` when the code computes
  it. A value the environment supplies at run time (region, account, credentials, a policy or
  resource that lives outside the repo) is not a setting: record it as an `assumption`.
  For a JSON/policy value, give the literal object when it is a literal.
- `data`: names, ARNs, URLs, ids, keys, bodies and payloads (`QueueUrl`, `TableName`, `Item`,
  `MessageBody`). Names only, no values.

Use API parameter names, not SDK or CLI spellings (`--wait-time-seconds` → `WaitTimeSeconds`).

Ids that change ordering or deduplication (`MessageGroupId`, `MessageDeduplicationId`) are
settings. Values the service only matches against a pattern or passes through (an event's
`Source` and `DetailType`, a schedule's `Input`, a target `Arn`) are data: the pattern that
matches them (`EventPattern`, `FilterPolicy`) is the setting.

A setting nested in a map parameter is written as a dotted path (`Attributes.FilterPolicy`,
`Attributes.RawMessageDelivery`). A response field the app depends on (it reads
`Attributes.QueueArn` to wire a subscription) goes in the item's `resource` text or rationale; it
is not a setting.

## Assumptions

Some things the app relies on are not captured by any API parameter: the region, account or
credentials when the environment supplies them, IAM or resource policies that must allow or deny
a call, resource identifiers from an env var or config (a queue URL, a table name), principals in
other accounts. Record each as an item of kind `assumption`, next to the call items:

```json
{"id": "aws-region", "kind": "assumption", "subject": "DynamoDB client region from AWS_REGION",
 "evidence": {"file": "src/db.js", "line": 4, "snippet": "region: process.env.AWS_REGION,"}}
```

- `subject`: a few words naming the dependency, in the words a trace would use
  (`identity policy denies GetSecretValue`, `cross-account role trust`, `pre-existing SQS queue
  from QUEUE_URL`, `region from AWS_REGION`). Name the service when there is one.
- `evidence`: the line that shows the reliance (the env read, the test asserting the denial).
- `evidence.snippet` (for every item): if the copied line contains a credential-looking value
  (access key, secret, token, password, connection string with credentials, private key),
  replace that value with `<redacted>` and never show it in the answer. The evidence check
  compares only the part of the snippet before `<redacted>`.
- Say what kind of policy it is (identity or resource) only when the repo shows it; a policy
  document not in the repo is unknown, and the subject should say so.
- A region, account, or resource name, ARN or URL written as a literal in the code is **not** an
  assumption: the emulator serves any Region ([references/connect.md](references/connect.md#environment-variables),
  **Regions**), and a resource the app uses by a literal name without creating it is test setup,
  not emulator behavior. Record one only when the value comes from the environment at run time
  (env var, config file, CLI profile), or for policies, cross-account principals and reliance on
  state persisting (data surviving a restart, a long-lived shared environment).
- An identifier from the environment that names a resource the project's own IaC or setup
  creates (a Terraform output passed in as `QUEUE_URL`) is not an assumption either: the create
  call is already an item. Record one only for a resource the project expects to exist.
- Keep the call items too: an assumption is an extra item, not a replacement.

## Hard cases

- **Client factories and wrappers.** `getClient("sqs")`, `aws.py: def table(): ...`, a repository
  class wrapping `send`: follow the wrapper to every call site. The item's evidence is the line
  that names the operation; the settings come from what the call sites pass. Follow argument
  values the same way: a region, name or URL read from the environment in a config module and
  handed to a client through a factory comes from the environment (an assumption), however
  many files it passes through.
- **Code nothing runs.** Record usage only on paths the project runs: its entry points (a
  `main`, server, CLI command, handler, scheduled job, script, CI step, deployed IaC, and tests
  that use real clients) and the code they import or call. A module or function that no entry
  point reaches makes no items; list its file as `analyzed` with the reason it is not reached.
  For a library, its exported API is the entry point.
- **Request objects built elsewhere.** A variable, a builder, `**kwargs`, a spread: read where it
  is built and list its keys. A key added conditionally is still a setting.
- **Dynamic operation names.** `client[op](params)`, `getattr(client, name)`, a command class picked
  from a map: if the code lets you enumerate the possible operations, add one item each;
  otherwise record the call under `unresolved`, not as a guess.
- **CLI strings.** Options in shorthand (`Key=Value,..`) or JSON, values from `$(jq ...)`,
  heredocs or `file://` documents: open the source of the value and list its keys. `--query` and
  `--output` are client-side, not settings.
- **IaC-only resources.** A resource declared in CloudFormation/CDK/Terraform is created by the
  deployment tool: add the create operation (`sqs:CreateQueue` for `AWS::SQS::Queue`) with the
  properties that are settings. Wiring the service performs for you is usage too: event source
  mappings (`lambda:CreateEventSourceMapping`), SNS subscriptions (`sns:Subscribe`), S3 event
  notifications, EventBridge rules and targets.
- **Implied permissions.** `grant*()`, IAM and resource policies matter only if the app relies on
  them being enforced (a test that expects `AccessDenied`): record an item on the call that must
  be denied, with the error in `handled_errors`, plus an `assumption` for the denying policy.
- **IAM, other accounts, other regions.** `sts:AssumeRole` with a role in another account, a
  client or ARN in a second region, a region or account from the environment, a resource policy
  naming another account: record the call that depends on it and an `assumption` naming the
  dependency. Do not decide whether the emulator supports it; the traces do.
- **One SDK call, several operations.** A helper that picks operations at run time (the Go or
  Java upload manager: `PutObject` or `CreateMultipartUpload`/`UploadPart`/
  `CompleteMultipartUpload` by size) is one item with `"ops": [...]` listing every operation it
  can make, instead of `op`.
- **Distinct cases of one call.** When service behavior for the same call differs by case (a
  different response, error or effect) and the app hits more than one (a long poll that returns a waiting message, and one that blocks on an
  empty queue), record one item per case so each needs its own passing trace. A call that waits
  or polls in a loop also meets the case where nothing is available, its own item. An item
  verifies when any one direct trace passes, so one item for both cases would let the happy-path
  trace hide the untested case. A case the service answers the same way (a call that returns the
  same response whether or not the resource exists) is not a distinct case, and neither is one the app neither
  checks nor branches on.

  ```json
  {"id": "sqs-receive", "op": "sqs:ReceiveMessage", "resource": "jobs queue, message waiting",
   "settings": {"WaitTimeSeconds": 20}},
  {"id": "sqs-receive-empty", "op": "sqs:ReceiveMessage",
   "resource": "jobs queue empty: long poll blocks until WaitTimeSeconds, returns no messages",
   "settings": {"WaitTimeSeconds": 20}}
  ```

  An error the app handles is a case too: give it an item with the error in `handled_errors`,
  and keep the happy path as an item without it.
- **Test-only and cleanup calls** still count: tests run against the emulator too. A test whose
  clients are mocked or stubbed sends nothing to AWS and makes no items.
- **Not AWS.** A local file named `s3.js`, an HTTP client to a non-AWS host, docs and comments:
  list the file as `not-aws` with the reason.
