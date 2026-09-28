# OTel Collector Setup — shared reference

Use this when the user needs a **telemetry destination** as well as instrumentation: the app is
instrumented (or is being instrumented) and has nowhere to export to.

The shape is always the same on every platform:

```
app (ADOT SDK) --OTLP--> collector --OTLP/HTTP + SigV4--> destination
```

The **CloudWatch Agent is the primary collector** (Step 2); upstream `otelcol-contrib` is the
backup. The app-side wiring is identical either way.

Pick the platform guide for deployment and app wiring:

| Platform | Guide | Collector runs as | App exports to |
|---|---|---|---|
| EC2 | [collector-ec2.md](collector-ec2.md) | systemd service on the host | `http://localhost:4318` (or `:4317` for gRPC) |
| ECS | [collector-ecs.md](collector-ecs.md) | sidecar container in the same task | `http://localhost:4318` |
| EKS | [collector-eks.md](collector-eks.md) | DaemonSet/Deployment + Service in its own namespace | the collector Service's DNS name on `:4318` |

**Lambda is not here.** A Lambda execution environment has nowhere to run a collector short of a
custom extension, and it does not need one: the ADOT layer exports to the environment's own X-Ray
receiver under active tracing. See the `lambda-*.md` guides.

## Step 1: The destination — CloudWatch's own OTLP endpoints, per signal

**Omni reads CloudWatch's data; it has no store of its own.** Telemetry lands in CloudWatch first,
in OTLP form — log groups for logs, `aws/spans` for traces, and the account's CloudWatch Dataset for
metrics. A dataset integration copies logs and traces into the Dataset, and the Space reads the
Dataset.

The collector exports to CloudWatch's own OTLP endpoints — three endpoints, one per signal. This is
the standard path and what the CloudWatch Agent uses.

| Signal | Endpoint | SigV4 `service` | IAM action |
|---|---|---|---|
| Traces | `https://xray.<region>.amazonaws.com/v1/traces` | `xray` | `xray:PutTraceSegments`, `xray:PutTelemetryRecords` |
| Metrics | `https://monitoring.<region>.amazonaws.com/v1/metrics` | `monitoring` | `cloudwatch:PutMetricData` |
| Logs | `https://logs.<region>.amazonaws.com/v1/logs` | `logs` | `logs:PutLogEvents` |

`CloudWatchAgentServerPolicy` covers all three and is what AWS's own collector docs recommend.

`cloudwatch:PutMetricData` in that table is the IAM action the OTLP metrics endpoint authorizes
against — it does not mean the collector calls the `PutMetricData` API. A metric that arrives
through the OTLP endpoint stays OpenTelemetry-native, carries its resource attributes
(`"@resource.service.name"`), and is PromQL-queryable in Omni. A metric published with the
`PutMetricData` API itself, or with EMF log lines, is a CloudWatch metric and is not — see
[instrumentation.md](instrumentation.md) (§ Custom metrics).

Three things that are easy to get wrong:

- **Transaction Search must be enabled in the Region before traces work.** This is a real
  prerequisite for Omni generally, not just for this endpoint — Omni only understands
  OpenTelemetry, and Transaction Search is what routes incoming spans into the `aws/spans`
  CloudWatch Logs group that Omni reads. Without it the traces endpoint rejects spans. It is an
  account-level, per-Region change: the user enables it with
  `aws xray update-trace-segment-destination --destination CloudWatchLogs --region <region>` (which
  also requires a CloudWatch Logs resource policy letting `xray.amazonaws.com` call
  `logs:PutLogEvents` on `aws/spans`). That resource policy grants a service principal, so it
  MUST carry the confused-deputy conditions the Transaction Search documentation shows:
  `aws:SourceAccount` equal to the account and `aws:SourceArn` matched with `ArnLike` against
  `arn:aws:xray:<region>:<account-id>:*` — never a bare grant to the principal. Tell the user
  to enable it; do not enable it for them. Spans carry request attributes, so treat `aws/spans`
  (and any custom trace log group) as a log group holding application data: CloudWatch Logs
  encrypts it at rest with a service-owned key by default, and a customer who must use their
  own key associates a symmetric KMS key with `aws logs associate-kms-key`. That key policy
  grants the CloudWatch Logs service principal (`logs.<region>.amazonaws.com`) the encrypt,
  decrypt, and data-key actions, and — like every service-principal grant in this file — it
  MUST be scoped, not bare: the CloudWatch Logs documentation's statement conditions it with
  `ArnLike` on `kms:EncryptionContext:aws:logs:arn` matching
  `arn:aws:logs:<region>:<account-id>:log-group:*` (or the one log group), so the key can
  only be used for that account's log groups. Recommend it where the customer's data
  classification calls for it; do not associate a key or edit a key policy for them.
- **Each signal needs its OWN `sigv4auth` extension**, because the `service` differs
  (`xray` vs `monitoring` vs `logs`). One shared extension cannot sign for more than one.
- **The logs endpoint needs `x-aws-log-group` and `x-aws-log-stream` headers.** The log group
  must already exist.

## Step 2: Choose the collector

**The CloudWatch Agent is the primary collector.** Since **1.300070** it builds an OTLP pipeline
straight from its JSON config via a root-level `opentelemetry` section, so it needs no hand-written
collector YAML at all:

```json
{
  "agent": { "region": "<region>" },
  "opentelemetry": {
    "collect": {
      "otlp": {
        "grpc_endpoint": "0.0.0.0:4317",
        "http_endpoint": "0.0.0.0:4318"
      }
    }
  }
}
```

That is the whole configuration. The agent derives the three destination endpoints from
`agent.region` and builds the `sigv4auth` extensions, batch processors and pipelines itself. It also
adds resource detection, entity correlation (`cloud.resource_id`), log-group routing, and retry plus
sending queues — none of which the hand-written pipeline below has.

**This stays inside Omni's scope.** The `opentelemetry` section pulls in **no** Application Signals,
ServiceEvents or Dynamic Instrumentation components. Those live in the agent's separate
`logs.metrics_collected.application_signals` and `traces.traces_collected.application_signals`
sections, which you MUST NOT add. Leave `span_metrics_enabled` unset — it defaults to `false`, and
turning it on generates span metrics this reference does not cover.

`resource_attributes` sits alongside `collect` if extra resource attributes are needed, but prefer
`OTEL_RESOURCE_ATTRIBUTES` on the application so they travel with the app rather than the host.

**Verify the version first.** An agent older than 1.300070 reports `Configuration validation
succeeded`, `status: running` and `configstatus: configured` while starting **no** OTLP listener
and generating no collector YAML. The only check that catches it is
looking for listeners on 4317/4318. Note the Amazon Linux 2023 repo package is currently
1.300069.1, so install the current build from S3 rather than the distro repo.

**The host package and the container image use different version schemes.** Compare the
`1.3000NN` middle component, not a full string:

| | Form | Example |
|---|---|---|
| Host RPM / `-ctl -a status` | `1.3000NN.Pb####` | `1.300072.0b1766` |
| Container tag (`public.ecr.aws/cloudwatch-agent/cloudwatch-agent`) | `1.3000NN.Pb####`, **no `v` prefix** | `1.300072.0b1766` |

There is no `v`-prefixed tag and no `1.300070.1` tag in that repository — the nearest published tag
is `1.300070.0b1586`. Pin a real tag; do not float `:latest`. To enumerate tags, use the public-ECR
token endpoint plus `/v2/<repo>/tags/list` (`aws ecr-public describe-images` does not work against
`public.ecr.aws` without a registry id). On EKS, chart 6.6.0 already defaults `agent.image.tag` to
a build past the floor, so pinning is optional there.

**One limit decides when you cannot use it:**

1. **Batch sizes are fixed** — traces and logs 10000/30s, metrics 1000/10s. Not tunable from JSON.
   The endpoints derive from `agent.region`; the JSON schema has no endpoint, URL, token or auth
   field anywhere under `opentelemetry` — which is fine, since the per-signal CloudWatch endpoints
   are exactly what the agent targets.

### Backup: upstream OTel Collector Contrib

Use `otelcol-contrib` when batch sizing matters, or when the customer
will not run the CloudWatch Agent. `otelcol-contrib` on a host,
`otel/opentelemetry-collector-contrib:<version>` as a container.

**Contrib, not core.** `sigv4auth` is a contrib component; the core build refuses to start with
`unknown extension "sigv4auth"`. Pin a version from
[opentelemetry-collector-releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/latest)
rather than floating `latest`.

## Step 3: Write the collector config (otelcol-contrib only)

Skip this entire step if you are using the CloudWatch Agent — its JSON above is the config.

**CloudWatch's own endpoints,** traces + metrics. Each signal needs its own
exporter and its own `sigv4auth`, because the signing service differs:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    send_batch_size: 200
    timeout: 10s

exporters:
  otlphttp/traces:
    traces_endpoint: https://xray.<region>.amazonaws.com/v1/traces
    compression: gzip
    auth:
      authenticator: sigv4auth/traces
  otlphttp/metrics:
    metrics_endpoint: https://monitoring.<region>.amazonaws.com/v1/metrics
    compression: gzip
    auth:
      authenticator: sigv4auth/metrics

extensions:
  sigv4auth/traces:
    region: "<region>"
    service: "xray"
  sigv4auth/metrics:
    region: "<region>"
    service: "monitoring"

service:
  extensions: [sigv4auth/traces, sigv4auth/metrics]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/traces]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/metrics]
```

### Why the config looks like this

- **`otlphttp`, never `otlp`, on the exporter.** The CloudWatch OTLP endpoints are HTTP/1.1
  only — gRPC is not supported. The `otlp` exporter speaks gRPC.
- **Both receiver protocols are enabled — gRPC on 4317 and HTTP on 4318.** That is the OTel
  default pair, and it is what the CloudWatch Agent listens on too. It matters here because SDK
  defaults differ: the Java agent defaults to **gRPC on 4317** while the Python, Node.js and .NET
  distros default to **HTTP on 4318**. Listening on both means an app works whichever default it
  has, and `OTEL_EXPORTER_OTLP_PROTOCOL` becomes a correctness detail rather than a hard
  requirement. Dropping one protocol is a deliberate narrowing, not a simplification.
  Note this is the *inbound* side only — the exporter to CloudWatch is HTTP-only regardless.
- **`extensions` sits at `service.extensions`.** AWS's "OpenTelemetry Collector" page shows it
  nested under `service.telemetry.extensions`, which is not a real config key — the collector
  fails to start on it. AWS's CloudWatch-agent page has it in the right place. Use
  `service.extensions`.
- **`send_batch_size: 200`** keeps requests under the metrics endpoint's limits: 1 MB and
  1,000 data points per request, 500 TPS per account. Traces allow 5 MB and 10,000 spans, so
  200 is comfortable for both.
- **`compression: gzip`** — the endpoints accept `gzip` or `none` and nothing else.
- Spans older than 14 days or more than 2 hours in the future are rejected. Only matters if
  the user replays telemetry.

## Step 4: Wire the app to the collector

Set on the application, per the platform guide's mechanism (systemd `Environment=`, container
`environment`, pod `env`):

```
OTEL_EXPORTER_OTLP_ENDPOINT=<collector URL from the table above>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

**Set `OTEL_EXPORTER_OTLP_PROTOCOL` explicitly.** SDK defaults differ — the Java agent defaults
to gRPC, so pointing it at 4318 without this produces a port that is listening and telemetry
that silently never arrives. This is the single most common failure in this setup.

Nothing else about the instrumentation changes. Do not revisit the loader variables.

## IAM: the collector needs permissions, the app still does not

The instrumentation guides say instrumentation adds no IAM, and that stays true — the SDK only
talks to the collector. The **collector** is what calls AWS, so it needs credentials.

**What to grant:** `CloudWatchAgentServerPolicy`, which covers all three CloudWatch OTLP signals
(`xray`, `monitoring`, `logs`).

Where that grant attaches, per platform:

| Platform | Identity | How |
|---|---|---|
| EC2 | instance profile role | attach `CloudWatchAgentServerPolicy` |
| ECS | **task** role (not execution role) | attach `CloudWatchAgentServerPolicy` |
| EKS | service account | IRSA or EKS Pod Identity — see [collector-eks.md](collector-eks.md) |

On ECS the execution role additionally needs `ssm:GetParameters` if the config comes from
Parameter Store — a different role for a different reason. Getting these two backwards is the
usual cause of an ECS collector that starts and then 403s.

## Do NOT

- Do not use CloudWatch Agent port **4316**, and do not install the
  `amazon-cloudwatch-observability` **EKS add-on**. Both wire up Application Signals. This is not a
  ban on the CloudWatch Agent itself — Step 2 makes it the primary collector, and its
  `opentelemetry` section pulls in no Application Signals components. What is banned is the
  Application Signals *configuration*, not the agent.
- Do not enable Application Signals, ServiceEvents, or Dynamic Instrumentation in the
  collector config.
- Do not modify application source. This is all IaC and collector config.
- Do not deploy. Present the diff and let the user apply it.

## Verify (optional, and only after the user deploys)

**None of this is part of the change you present.** Every check here inspects a *running* collector,
so it belongs to the conversation after the user applies — and on EC2 the change takes effect only
when the instance is replaced, since UserData runs at first boot only.

Do not run these unprompted, and do not treat them as a gate on completing the task. Hand the
relevant few to the user, or run them if they ask you to verify after applying.

**The checks differ by collector AND by platform.** Pick the row that matches what you deployed.
Several checks that work on an EC2 host are impossible in a container, and vice versa.

### CloudWatch Agent (primary)

| Goal | EC2 (host install) | ECS Fargate | EKS |
|---|---|---|---|
| Collector running | `amazon-cloudwatch-agent-ctl -a status` → `running` / `configured` | `aws ecs describe-tasks` → the `cloudwatch-agent` container `RUNNING`, `init` `STOPPED` exit 0 | `kubectl -n amazon-cloudwatch get pods` |
| **Receiver actually listening** | `ss -lntp \| grep -E '4317\|4318'` — **the check that catches a too-old agent**, which otherwise reports `running` and `configured` while listening on nothing | the collector log stream's `Starting HTTP server` / `Starting GRPC server` lines | `kubectl -n amazon-cloudwatch logs -l app.kubernetes.io/name=cloudwatch-agent \| grep -E 'Starting (HTTP\|GRPC) server'` — **use the log, not `get endpoints`**: Endpoints come from ready pods and the Service spec, so they are populated even when a too-old agent is listening on nothing. `get endpoints cloudwatch-agent` being non-empty is still worth checking for the *selector* mismatch case |
| Per-signal export failures | `grep -E 'Exporting failed\|dropped_items' /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log` | grep the same strings in the collector's **awslogs stream** | `kubectl -n amazon-cloudwatch logs -l app.kubernetes.io/name=cloudwatch-agent \| grep -E 'Exporting failed\|dropped_items'` |

Three things about the agent's own diagnostics:

- **The log is a file only on a host install.** There, `journalctl -u amazon-cloudwatch-agent` is
  near-empty and will hide the errors, so read the file. **In a container the file is never
  populated** — the agent runs with `logtarget = "lumberjack"` and writes to stdout, so the awslogs
  stream (ECS) or `kubectl logs` (EKS) *is* the log.
- **You cannot exec into the agent container.** The image is distroless: no `ss`, no `sh`, no
  `printenv`. Read the endpoints from the API server instead of poking inside the pod.
- **There is no 8888 endpoint.** The agent generates `service.telemetry.metrics.level: None` and logs
  `Skipped telemetry setup.`. On EKS the operator still creates a `cloudwatch-agent-monitoring`
  Service on 8888 *with endpoints*, so the check looks available and then refuses the connection.

Benign noise you will see on a **healthy** collector — do not grep for `E!` or `Error`, grep for
`Exporting failed` / `dropped_items`:

- On Fargate: two `E! [EC2] Fetch hostname / identity document from EC2 metadata fail` lines against
  `169.254.169.254`, followed by `I! Detected the instance is ECS`. There is no IMDS in a task.
- `Cannot access /etc/cwagentconfig: no such file or directory` when the config comes from
  `CW_CONFIG_CONTENT`.
- `E! ... "msg":"using deprecated field \`blocking\`"` with a ~2.5 KB Go stacktrace, once per
  exporter — an upstream collector deprecation, not your problem.

### `otelcol-contrib` (backup)

| Goal | Check |
|---|---|
| Collector running | `systemctl status otelcol-contrib` (host) |
| Receiver listening | `curl -sS -o /dev/null -w '%{http_code}' http://localhost:4318/v1/traces` → **405** |
| Per-signal export failures | `curl -s http://localhost:8888/metrics \| grep -E 'receiver_accepted\|exporter_sent\|exporter_send_failed'` |

`otelcol_receiver_accepted_*` rising with `otelcol_exporter_sent_*` at zero means the destination is
rejecting; both at zero means the app never sent anything — check `OTEL_EXPORTER_OTLP_PROTOCOL`.

**On ECS Fargate neither `curl` check is reachable** — there is no host shell and no route into the
task's network namespace without `enableExecuteCommand` plus `ssmmessages:*` on the task role. Use
the collector's log stream instead: it dumps its generated pipelines at startup and logs
`Everything is ready. Begin running and processing data.`. See [collector-ecs.md](collector-ecs.md).

### Optional: confirm telemetry arrived at the destination

Everything above establishes that the collector is healthy, which is this guide's job. Confirming the
data landed is a **query** task and belongs to the **aws-observability** skill — route there rather
than reproducing query recipes here. Two facts a reader needs in order to look in the right place:

- **Traces** land in the CloudWatch Logs group **`aws/spans`** (via Transaction Search), not in the
  CloudWatch X-Ray traces view. In the console that is CloudWatch → Transaction Search.
- **Metrics** land in CloudWatch's **Metrics V2** store and are **not** visible to `list-metrics` or
  `get-metric-statistics`, which only see V1. They are queried with PromQL over
  `https://monitoring.<region>.amazonaws.com`.

Allow 1–2 minutes for either to appear. If `aws/spans` stays empty while the collector logs no export
errors, the usual cause is Transaction Search not being enabled on the account.

**One trap worth stating, because it invites an account-wide change for no reason:**
`aws xray get-indexing-rules` reports a probabilistic `DesiredSamplingPercentage` that defaults to
**1%**. It governs X-Ray-side indexing for trace-summary search — it does **not** reduce what reaches
`aws/spans`, which is unsampled. Do not raise it to debug missing spans.

**Also do not treat `traces.span.metrics.calls` / `.duration` as evidence the metrics pipeline works.**
CloudWatch derives those from ingested spans, so they appear even when metric export is failing
entirely. They carry `@instrumentation.@name="cloudwatch.aws/xray/span-metrics"`; the SDK's own
metrics carry `@instrumentation.cloudwatch.source="cloudwatch-agent"`.
