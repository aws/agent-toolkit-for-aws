# OTel Collector on EC2

Read [collector.md](collector.md) first — it holds the destination choice, the config, and the
endpoint limits. This guide covers only how the collector gets onto an EC2 instance and how the
application finds it.

**The CloudWatch Agent is the primary collector here** (Step 2). It needs no hand-written collector
YAML — a small `opentelemetry` section in its JSON config is the whole configuration. Upstream
`otelcol-contrib` is the backup, for the cases [collector.md](collector.md#step-2-choose-the-collector)
lists; its install and config live under *Backup* in Step 2, not here.

## Step 1: Grant the instance permissions

Do this **before** configuring the agent, not after. The agent's own config validation calls AWS,
so without the policy in place it fails outright with `configuration validation first phase failed`
— the agent never reaches a working state, and the error does not obviously point at IAM.

`CloudWatchAgentServerPolicy` grants everything the agent needs for this setup. Attach it and do
not hand-assemble a narrower policy: the OTLP pipeline calls more APIs than the three export
actions suggest, and a partial policy fails at config-validation time rather than at export time.

The collector calls AWS, so the **instance profile role** needs permissions. The application
does not.

```hcl
resource "aws_iam_role_policy_attachment" "otel_collector" {
  role       = aws_iam_role.instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# REQUIRED, not optional. The instance references the instance *profile*, not this attachment, so
# Terraform sees no dependency between them and may create both concurrently — UserData then runs
# the agent's config validation before the policy exists. This edge is the only thing that actually
# delivers the ordering the paragraph above demands.
resource "aws_instance" "main" {
  # ...
  depends_on = [aws_iam_role_policy_attachment.otel_collector]
}
```

`CloudWatchAgentServerPolicy` covers all three CloudWatch OTLP signals — the collector exports to
CloudWatch's own per-signal OTLP endpoints.

## Step 2: Install and configure the collector in UserData

### Primary: the CloudWatch Agent

```bash
# The OTLP pipeline needs CloudWatch Agent 1.300070 or later.
#
# Do NOT use `dnf install -y amazon-cloudwatch-agent`: the Amazon Linux 2023 repo currently ships
# 1.300069.1, one release too old, and an older agent accepts the `opentelemetry` section without
# complaint (see the version check below). Download the current build instead.
#
# Install with `dnf install <file>`, never `rpm -Uvh` -- rpm takes the rpm DB lock, and if an
# earlier `dnf install` in this UserData still holds it, rpm exits non-zero, which under `set -e`
# aborts the REST of UserData so neither the agent nor the application starts. dnf waits.
#
# The --retry flags are REQUIRED, not defensive. This object is ~70 MB and the download runs seconds
# after boot, while networking is still settling. A bare `curl -fsSL` here can fail with
# `curl: (56) Recv failure: Connection reset by peer`, and under `set -e` that aborts the rest of
# UserData -- so a previously healthy application never starts.
#
# `--retry-all-errors` is deliberately absent: it needs curl 7.71+, and Amazon Linux 2 ships 7.61,
# where an unrecognised option makes curl exit non-zero -- triggering the very `set -e` abort these
# flags exist to prevent, and on the first run rather than a transient one. If you know the host has
# curl 7.71+, adding it also covers mid-transfer resets, which plain `--retry` does not.
curl -fsSL --retry 5 --retry-delay 5 --retry-connrefused \
  -o /tmp/amazon-cloudwatch-agent.rpm \
  https://amazoncloudwatch-agent.s3.amazonaws.com/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
dnf install -y /tmp/amazon-cloudwatch-agent.rpm   # arm64 path for Graviton; .deb for Debian/Ubuntu

cat > /opt/aws/amazon-cloudwatch-agent/etc/otlp.json << 'EOF'
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
EOF

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/otlp.json
```

**Check the version before trusting anything else** — this is load-bearing, not a nicety:

```bash
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status   # want the 1.3000NN part >= 1.300070
# S3 builds report e.g. 1.300072.0b1766 -- compare the middle component, not the whole string
ss -lntp | grep -E '4317|4318'                                              # want BOTH listening
```

An agent older than 1.300070 does not merely ignore the section quietly — it reports success.
An older agent reports `I! Valid Json input schema.`, `Configuration validation succeeded`,
`"status": "running"`, `"configstatus": "configured"` — and yet **nothing listening on 4317/4318**
and no `amazon-cloudwatch-agent.yaml` generated at all. Every check a reader would think to run
passes while the agent collects nothing. The listener check is the one that catches it.

Do **not** add `traces.traces_collected.application_signals` or
`logs.metrics_collected.application_signals` — that turns on Application Signals, which is out of
scope here.

### Backup: upstream otelcol-contrib

```bash
# Install the upstream OTel Collector Contrib. Use `dnf install`, not `rpm -Uvh`:
# rpm takes the rpm DB lock, and if a `dnf install` earlier in this UserData still holds it,
# rpm exits non-zero -- which under `set -e` aborts the REST of UserData, so neither the
# collector nor the application starts. dnf waits for the lock instead.
OTELCOL_VERSION=<pin from the releases page>   # e.g. 0.137.0
ARCH=amd64                                     # arm64 on Graviton
curl -fsSL --retry 5 --retry-delay 5 --retry-connrefused -o /tmp/otelcol-contrib.rpm \
  "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_VERSION}/otelcol-contrib_${OTELCOL_VERSION}_linux_${ARCH}.rpm"
dnf install -y /tmp/otelcol-contrib.rpm        # apt install ./otelcol-contrib_*.deb on Debian/Ubuntu

# Write the pipeline config (see collector.md for the full file)
cat > /etc/otelcol-contrib/config.yaml << 'EOF'
receivers:
  otlp:
    protocols:
      grpc:                     # both protocols: Java defaults to gRPC/4317
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
EOF

# Start it
# The rpm installs and enables an `otelcol-contrib` systemd unit that reads
# /etc/otelcol-contrib/config.yaml, so a restart is all that is needed.
systemctl enable --now otelcol-contrib
systemctl restart otelcol-contrib
```

**Placement in UserData — put the collector install AFTER the application is installed and
started.** This overrides the ordering the Application Signals guides use.

Most UserData scripts run under `set -e`. Placing a large download first makes the collector a hard
dependency of application startup: if the download fails, every later command is skipped and the
application never starts at all — a transient failure of the ~70 MB agent download seconds after
boot takes the whole application down with it. Instrumenting a service must not be able to stop it.

Ordering costs nothing, because **the app tolerates the collector arriving late**: the SDK retries,
so a few seconds of connection refusals at boot are harmless. There is no corresponding tolerance in
the other direction.

Two further protections worth applying:

- Keep the retry flags on every download in this guide.
- If you must place the collector block early — for instance because the app's own installer is what
  needs the agent present — wrap it so its failure cannot abort the rest:

  ```bash
  install_collector() {
    # ... download, dnf install, write otlp.json, fetch-config ...
  }
  install_collector || echo "WARNING: collector install failed; application startup continues" >&2
  ```

The rpm-lock hazard described above is a separate reason to prefer `dnf install <file>`; it is not a
reason to move the block earlier.

**Other distributions.** The commands above are Amazon Linux 2023 (`dnf`). On Amazon Linux 2 use
`yum` in place of `dnf`; on Debian/Ubuntu fetch the `.deb` and `apt-get install ./<file>.deb`. For
anything else the agent may not be packaged for the OS package manager at all — see the
[CloudWatch Agent manual installation docs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/manual-installation.html).

The app retries if the receiver is not listening yet, so the collector arriving after the app is
fine — see the placement note above, which is why that is the recommended order.

`0.0.0.0:4318` rather than `127.0.0.1:4318` only matters if the app runs in a container on the
instance and reaches the collector over the docker bridge. For a process on the host, either
works; keep `0.0.0.0` and let the security group be the boundary. Do not open 4318 in the
security group — nothing outside the instance should reach it.

**Terraform heredoc indentation.** When adding these lines to an existing `user_data`
heredoc, match the leading whitespace of the surrounding lines exactly. `<<-EOF` strips
indentation only when it is consistent; mixed indentation leaves spaces before `#!/bin/bash`
and cloud-init silently refuses to run the script.

## Step 3: Point the application at the collector

The application runs as a **systemd service**, so this goes on the unit — an `export` in
UserData never reaches the `ExecStart` process. Same mechanism the `ec2-*.md` instrumentation
guides use for the loader variable; add these two alongside it:

```ini
[Service]
Environment=OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
Environment=OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Then `systemctl daemon-reload && systemctl restart <service>` (or rely on instance replacement
if `user_data_replace_on_change = true`).

`OTEL_EXPORTER_OTLP_PROTOCOL` is not optional — see [collector.md](collector.md#step-4-wire-the-app-to-the-collector).
The Java agent defaults to gRPC and will quietly send nothing to 4318 without it.

## Verify

**On the CloudWatch Agent (primary):**

```bash
# Agent running and holding a config
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status

# THE decisive check. An agent older than 1.300070 reports "running" and "configured" while
# listening on nothing, so status alone is not evidence. Both listeners must appear:
ss -lntp | grep -E '4317|4318'

# Receiver answering? 405 = yes (it rejects GET). Connection refused = no.
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/traces

# Per-signal export failures. The agent logs to a FILE -- `journalctl -u amazon-cloudwatch-agent`
# is near-empty and will hide these. Each line names the endpoint and a dropped_items count, so one
# dead pipeline is visible while the others are healthy.
grep -E 'Exporting failed|dropped_items' /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log

# Did the variables reach the app's unit?
systemctl show <service> --property=Environment
```

There is **no `localhost:8888`** on the CloudWatch Agent — it generates
`service.telemetry.metrics.level: None`. Use the log grep above instead.

**On `otelcol-contrib` (backup):**

```bash
systemctl status otelcol-contrib
# Read the WHOLE unit journal, not the tail: the last 50 lines are startup noise and will look
# clean while an exporter fails every batch. Filter for what matters instead.
journalctl -u otelcol-contrib --no-pager | grep -iE 'error|denied|refused|deprecat' | tail -30

# Separates "the app is not sending" from "the collector cannot export":
curl -s http://localhost:8888/metrics | grep -E 'receiver_accepted|exporter_sent|exporter_send_failed'

curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/traces
systemctl show <service> --property=Environment
```

If the user asks you to confirm telemetry arrived at the destination, see
[collector.md](collector.md#verify-optional-and-only-after-the-user-deploys).

Common failures, in the order they usually happen:

| Symptom | Cause |
|---|---|
| **Agent reports `running` / `configured`, nothing on 4317/4318, no generated YAML** | Agent older than 1.300070 — it accepts the `opentelemetry` section and silently ignores it. The AL2023 repo package is one release too old; install from S3 |
| Agent won't start, `configuration validation first phase failed` | `CloudWatchAgentServerPolicy` not attached yet — validation calls AWS. Check the `depends_on` in Step 1 |
| Collector won't start, `unknown extension "sigv4auth"` | Core `otelcol` instead of `otelcol-contrib` (backup path only) |
| `rpm -Uvh` fails with `can't create transaction lock` and the rest of UserData never runs | An earlier `dnf install` still holds the rpm DB lock. Use `dnf install -y <rpm>`, which waits |
| Collector logs `403` / `AccessDenied` on export | **Read the 403's `Message=` body before touching IAM.** An IAM denial names the principal and action (`User: arn:... is not authorized to perform: cloudwatch:PutMetricData`) — that one means the policy is missing from the instance profile. A 403 that instead describes account enablement is not an IAM problem and no policy change will fix it |
| Receiver up, nothing exported, app logs clean | `OTEL_EXPORTER_OTLP_PROTOCOL` unset and the SDK defaulted to gRPC |
| Spans absent, metrics present | Transaction Search not enabled on the account |
| `Environment` empty in `systemctl show` | Variables added to UserData instead of the unit |

## Completion

Tell the user which files changed (UserData, the systemd unit, the IAM attachment), that the
collector listens on `localhost:4318` and exports to the destination they chose, and that the
application source and Dockerfile were not touched. Present the diff; do not deploy.
