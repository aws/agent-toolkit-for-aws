# Enabling and configuring CloudWatch Omni Intelligence

This reference covers **first-time setup** of the CloudWatch Omni Intelligence
layer: getting it turned on for a Space, attaching an optional customer-managed
KMS key, and connecting the integrations that feed it. The Intelligence layer is
what produces the **context graph** (the service/resource topology) and the insights and
observations that answer "what changed" and "why".
 Reading and interpreting that data is day-to-day use and belongs to
`aws-observability`, not here: triaging insights, observations, or anomalies goes to
`aws-observability` → `references/cloudwatch-omni/intelligence.md`, which also owns the
public-versus-internal operation split and the fallback when no insight call is available;
a pure topology or blast-radius question goes to `aws-observability` →
`references/cloudwatch-omni/context-graph.md`.

Everything in this file uses the public CloudWatch Omni surface: `aws
cloudwatchomni get-intelligence-configuration`, `put-intelligence-configuration`,
and the `*-integration(s)` operations. All of them run under the `cloudwatch:`
IAM namespace (for example `cloudwatch:PutIntelligenceConfiguration`,
`cloudwatch:CreateIntegration`).

> **Every mutating step below changes account-level configuration.** Do not run
> `put-intelligence-configuration`, `create-integration`, `update-integration`,
> or `delete-integration` until the customer has explicitly confirmed it. Read
> operations (`get-intelligence-configuration`, `list-integrations`,
> `get-integration`) are safe to run to establish current state.

## Setup order

Turn the Intelligence layer on in this order. The context graph starts forming
on its own once a Space exists and telemetry flows; the KMS and integration
steps are refinements on top of that.

1. **A Space must exist first.** The Intelligence layer is scoped to a Space, and
   a Space is scoped to one account and one Region — there is no separate
   "intelligence" resource to create. If no Space exists yet, create one first:
   see `references/cloudwatch-omni/spaces-and-domains.md`. The wrong Region points
   at a different (or non-existent) Space and returns empty results, not an error.
2. **The Config recorder is set up automatically.** Creating a Space
   auto-creates a service-linked Config recorder
   (`AWSConfigurationRecorderForCloudWatch`) that supplies the resource inventory
   the context graph is built from. You do not create or manage this recorder by
   hand; it comes with the Space. (Adding **more** Config-based discovery is the
   `AWS_CONFIG_SLREC` integration below, which is a separate, opt-in step with its
   own extra IAM.)
3. **Optionally attach a customer-managed KMS key** with
   `put-intelligence-configuration` (see below). This is the only knob the public
   configuration surface exposes today. It is optional — without it, intelligence
   data is encrypted under an AWS-owned key.

**Enablement triage starts with the client.** Before interpreting any `get`/`put-intelligence-configuration`
result, verify the local AWS CLI / botocore carries the `cloudwatch-omni` model and upgrade it
if not — a too-old client fails *locally* with an invalid-choice or `UnknownServiceError`
before any request is sent, which is not evidence the service or feature is off (see
Troubleshooting).

Note on the "enabled" state: reading insights and observations (`ListInsights`,
`ListObservations`) is day-to-day use, covered in `aws-observability` →
`references/cloudwatch-omni/intelligence.md`, not part of the setup surface this file owns.
It is a different thing from the account-level configuration you set here with
`put-intelligence-configuration`. This file covers only setup: the context graph, the KMS
configuration, and the integrations.

## Configuring a customer-managed KMS key

`put-intelligence-configuration` attaches (or removes) a customer-managed KMS key
that CloudWatch Omni uses to encrypt intelligence data. `get-intelligence-configuration`
reads the current state.

| Action | CLI |
|---|---|
| Read current configuration | `aws cloudwatchomni get-intelligence-configuration` |
| Attach a customer-managed key | `aws cloudwatchomni put-intelligence-configuration --kms-key-arn <key-arn>` |
| Remove the key (revert to AWS-owned) | `aws cloudwatchomni put-intelligence-configuration --remove-kms-key` |

`get-intelligence-configuration` takes no input — the account comes from the
caller's credentials — and returns the `accountId`, the configured `kmsKeyArn`
(absent when none is set), and `createdAt`/`updatedAt`. If no configuration has
ever been written, it returns the default (no key), not an error.

`put-intelligence-configuration` rules:

- Send **exactly one** of `--kms-key-arn` or `--remove-kms-key`. Sending both is
  a `ValidationException`; the public surface requires one of them (there is no
  other public field to set).
- `--kms-key-arn` takes a **full key ARN only**, of the form
  `arn:<partition>:kms:<region>:<account-id>:key/<key-id>` (multi-Region keys use
  a `mrk-` key-id prefix). A key **alias** (`alias/...`) or a bare key ID is
  rejected by the input validation — resolve the alias to its key ARN first.
- The caller needs **`kms:Decrypt` and `kms:GenerateDataKey`** on the key, and the
  key policy must allow the CloudWatch Omni encryption context
  (`aws:cloudwatch:account=<account-id>`). CloudWatch Omni runs a KMS access check
  (a dry-run) against the key on `put` and rejects the call with
  `AccessDeniedException` when the caller lacks those permissions or the key policy
  does not allow the encryption context — so a `put` that fails on the KMS check is
  a key-policy or IAM problem on the key, not a problem with the Space. This check
  verifies caller *access*, not key *state*: a key that is disabled or pending
  deletion is not rejected here (see the destructive-action note below).
- On `--remove-kms-key` the same access check runs against the **currently
  configured** key.

> **Revoking or deleting the key makes intelligence data unrecoverable.** The key
> encrypts the stored insights, observations, and related intelligence data;
> removing the key, disabling it, or deleting it crypto-shreds that data. Before
> changing or removing a configured key, confirm with the customer that they
> understand the existing intelligence data becomes permanently unreadable. Treat
> any key change as a destructive action requiring explicit confirmation.
>
> A fresh `put-intelligence-configuration` may take a short time to take full
> effect (the enablement state is read through a cache), so an operation run
> immediately after a `put` can briefly see the previous state.

## Integrations

Integrations connect external systems to the Intelligence layer. Manage them with
`create-integration`, `get-integration`, `update-integration`, `delete-integration`,
and `list-integrations`. `list-integrations` also filters by `--integration-type`,
`--status`, and exact `--name`.

The public integration types are:

| Type | What it does | Extra setup |
|---|---|---|
| `AWS_INTEGRATION` | Grants CloudWatch Omni a role to discover AWS resources in the account for the context graph. | Pass the discovery `--role-arn`. |
| `AWS_CONFIG_SLREC` | Turns on additional AWS Config service-linked resource-configuration recording feeding the graph. | Needs extra Config + service-linked-role IAM on the **caller** — see below. |
| `SLACK` | Connects a Slack workspace (OAuth). Stays `PENDING_OAUTH` until a human completes the returned authorization URL. | See `references/cloudwatch-omni/slack-integration.md` — do not duplicate that flow here. |
| `EXTERNAL_AGENT` | Registers an external agent endpoint with the account. | Provided as a public type; confirm the customer's specifics before configuring. |

Common `create-integration` shape:

```
aws cloudwatchomni create-integration --integration-type <TYPE> --name <name> [--role-arn <arn>]
```

`--name` is unique per account. `get`, `update`, and `delete` take an
`--identifier` union — set exactly one of `integrationId=<id>`,
`integrationArn=<arn>`, or `integrationName=<name>`. `delete-integration` is
idempotent.

### AWS_CONFIG_SLREC extra IAM

`AWS_CONFIG_SLREC` needs these permissions on the **caller** (a read-only role
fails):

- `config:PutServiceLinkedConfigurationRecorder`
- `config:DeleteServiceLinkedConfigurationRecorder`
- `config:DescribeConfigurationRecorderStatus` (`Resource: *`)
- `iam:CreateServiceLinkedRole` for `config.amazonaws.com`

### SLACK

`SLACK` is an OAuth integration: `create-integration` returns
`integration.authorizationUrl` and the integration stays `PENDING_OAUTH` until a
Slack workspace admin completes that URL in a browser, after which it moves to
`ACTIVE`. CloudWatch Omni cannot approve the Slack scopes itself. The full Slack
connect-and-grant flow, scopes, and channel conditions live in
`references/cloudwatch-omni/slack-integration.md` — route there for Slack rather
than repeating it.

### Integration types NOT offered to customers

Do **not** offer or attempt to configure GitHub, PagerDuty, Microsoft Teams,
`MODEL_PROVIDER`, or `CUSTOM_MCP` as CloudWatch Omni integrations — these types are
not enabled for customer use. A custom MCP tool server in particular is refused,
not configured: see `references/cloudwatch-omni/custom-mcp-integration.md`. If a
customer asks for one of these, say plainly that CloudWatch Omni does not offer it
and stop; do not describe a setup flow or substitute one type for another.

## Verifying setup

- **KMS configuration:** `aws cloudwatchomni get-intelligence-configuration` — a
  configured customer key appears as `kmsKeyArn`; its absence means the AWS-owned
  key is in use.
- **Integrations:** `aws cloudwatchomni list-integrations` (or `get-integration
  --identifier ...` for one) — check the `status`. `ACTIVE` is connected;
  `PENDING_OAUTH` means an OAuth integration (Slack) is still waiting on the
  browser authorization; `ERROR` or `FAILED` means the connection did not complete.
- **A new Space needs warm-up time.** Even with everything configured, the context
  graph and insights do not appear instantly — the layer needs telemetry and a few
  processing cycles before the graph populates and insights form. An empty graph on
  a just-created Space is expected for a while; it is not a misconfiguration.

## Troubleshooting

- **A 404, a 403, or a local client error on these operations.** The 404 / 403 /
  too-old-client model is owned by `aws-observability` →
  `references/cloudwatch-omni/context-graph.md`; read it there rather than re-deriving it
  here. The one setup-specific consequence: a 404 on `get`/`put-intelligence-configuration`
  is about this account's access to the operation, **not** a separate "intelligence feature"
  switch you can turn on from this file.
- **`AccessDeniedException` and the KMS access check** (the setup-local half of the 403
  above). Beyond a missing `cloudwatch:<Operation>` action or access grant, a
  customer-managed key adds a second cause: the caller needs
  `kms:Decrypt`/`kms:GenerateDataKey` on the key and the key policy must allow the
  `aws:cloudwatch:account=<account-id>` encryption context. CloudWatch Omni runs this check
  both at configuration time (`put`/`remove-kms-key`) and on the context-graph read path, so
  a `put` that fails it is a key-policy or IAM problem on the key, not a problem with the
  Space. A key that is merely disabled or pending deletion does **not** trigger it — the
  access check passes key *state* through (see the destructive-action note above).
- **An empty context graph after setup** almost always means the call hit the wrong
  Region (and therefore the wrong Space, or none) — the Region selects the Space,
  and a wrong Region returns an empty result rather than an error. Confirm the
  Region matches the Space's Region, then account for warm-up time.
- **The client does not carry the CloudWatch Omni model** — a too-old **AWS CLI** rejects
  the `cloudwatchomni` command (invalid choice), or **boto3/botocore** raises
  `UnknownServiceError` for the `cloudwatch-omni` service. It is a client-version problem,
  not evidence the service or feature is missing.
  Update the AWS CLI/SDK. **Never** fall back to X-Ray `GetServiceGraph` as a
  substitute — that is a different service and a different graph, not the CloudWatch
  Omni context graph.
