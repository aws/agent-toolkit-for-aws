# OTel Collector on EKS

Read [collector.md](collector.md) first — it holds the destination choice, the config, and the
endpoint limits. This guide covers the in-cluster deployment and, the part that trips people up,
how the application pod finds the collector pod.

The app addresses the collector by Kubernetes DNS. Its shape depends on which collector you deploy:
the **primary** CloudWatch Agent runs as a **DaemonSet with `hostNetwork: true`** in the
`amazon-cloudwatch` namespace, while the **backup** `otelcol-contrib` runs as a **Deployment fronted
by a ClusterIP Service** in its own namespace.

## How the app pod reaches the collector pod

This is the same mechanism the CloudWatch Agent operator uses. With the
`amazon-cloudwatch-observability` add-on installed, instrumented pods export to:

```
http://cloudwatch-agent.amazon-cloudwatch:4316
```

That is `http://<service-name>.<namespace>:<port>` — a Service DNS name, resolvable from any
pod in the cluster because kube-dns is in every pod's resolver search path. Nothing about it is
CloudWatch-specific except the names and the port.

Our equivalent, with our own Service and the standard OTLP/HTTP port:

```
http://otel-collector.opentelemetry.svc.cluster.local:4318
```

Two deliberate differences from the add-on's form:

- **4318, not 4316.** 4316 is the CloudWatch Agent's Application Signals port. 4318 is the OTLP
  standard for HTTP.
- **The fully-qualified name.** `otel-collector.opentelemetry` resolves too, via the search
  suffixes in `/etc/resolv.conf`. The FQDN skips the search list and resolves in one query — use
  it, but either works.

We deploy the Service ourselves rather than installing the add-on, because the add-on brings an
operator and hardcodes CloudWatch Agent endpoints and Application Signals.

## Step 1: Give the collector an AWS identity

The collector calls AWS; the app does not. Two ways, pick based on what the cluster already has:

**IRSA** (preferred; scopes permissions to this one workload). Requires an IAM OIDC provider on
the cluster — check with
`aws eks describe-cluster --name <cluster> --query 'cluster.identity.oidc.issuer'` and
`aws iam list-open-id-connect-providers`. If there is no provider, creating one is a
prerequisite, not part of this change.

If the cluster is built with the common `terraform-aws-modules/eks` module and `enable_irsa = true`,
the OIDC provider already exists and the module exports what you need — use
`module.eks.oidc_provider_arn` and `module.eks.oidc_provider` rather than declaring your own
provider resource:

```hcl
resource "aws_iam_role" "otel_collector" {
  # IAM role names are GLOBAL. Include cluster and region, or a second cluster with the same
  # name in another region collides on apply.
  name = "${var.cluster_name}-${var.region}-otel-collector"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          # CloudWatch Agent (primary). For the otelcol-contrib backup below this is instead
          # "system:serviceaccount:opentelemetry:otel-collector".
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:amazon-cloudwatch:cloudwatch-agent"
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "otel_collector" {
  role       = aws_iam_role.otel_collector.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}
```

`CloudWatchAgentServerPolicy` is the grant for the destination — CloudWatch's own per-signal OTLP
endpoints.

The `sub` condition must match `system:serviceaccount:<namespace>:<serviceaccount>` exactly. A
typo here produces `AccessDenied` on `AssumeRoleWithWebIdentity` at collector startup.

**Node role** (simpler, coarser — what the Application Signals Terraform guide does): attach
`CloudWatchAgentServerPolicy` to the node group role. Every pod on the node inherits it. Say
that trade-off out loud when recommending it.

## Step 2: Deploy the collector

### Primary: the CloudWatch Agent, installed standalone

Install the agent yourself rather than through the **EKS add-on**, which turns on Application
Signals and Container Insights. Use the `amazon-cloudwatch-observability` Helm chart — the same
chart the add-on wraps — configured down to the `opentelemetry` section.

**Prefer the IaC form.** Express the release as Terraform so this step stays a reviewable diff like
every other platform in this guide set, and `terraform plan` is the review:

```hcl
# Pin the provider. Without this, `terraform init` takes the newest major version and the required
# syntax changes with it -- v3 wants `kubernetes = { ... }`, v2 wanted a `kubernetes { ... }` block.
terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
  }
}

# Helm provider v3 syntax: `kubernetes` and `exec` are ATTRIBUTES (`= {`), not blocks.
# On a stack pinned to helm v2, drop the `=` on both.
provider "helm" {
  kubernetes = {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

resource "helm_release" "cwagent" {
  name             = "cwagent"
  repository       = "https://aws-observability.github.io/helm-charts"
  chart            = "amazon-cloudwatch-observability"
  version          = "6.6.0"
  namespace        = "amazon-cloudwatch"
  create_namespace = true
  values           = [file("${path.module}/cwagent-values.yaml")]
}
```

This produces the same result as the CLI: identical resolved values, an identical
`AmazonCloudWatchAgent` config, and no restart of the agent pods. It also leaves the out-of-band
IRSA annotation alone (see below) — a `helm_release` in-place update does not clobber it. A
`helm_release` *replacement* would, since that recreates the ServiceAccount: changing `name` or
`namespace`, or a `terraform destroy` and re-apply, means re-annotating.

**If a release already exists** — for instance it was installed by the CLI first — import it rather
than uninstalling, so the collector never goes away:

```bash
terraform import helm_release.cwagent amazon-cloudwatch/cwagent   # <namespace>/<name>
```

Expect the **first plan after import to be non-empty**: the provider does not read `repository` or
`values` back off the release, and `create_namespace` reads back as `false`, so you get one in-place
update. That is a `helm upgrade` and a revision bump, not a reinstall and not an outage. The second
plan is clean.

One cosmetic difference worth knowing on a Helm 4 CLI host: taking a v4-created release over with
the Terraform provider changes its apply method from server-side to client-side apply, because the
provider embeds an older Helm SDK. It changed nothing about the rendered resources here.

**Alternative: the Helm CLI.** Use this when the stack has no Helm provider, or for a one-off. It is
imperative, so there is no diff to present — write the values file for the user to review and hand
them the commands rather than running them yourself:

```bash
helm repo add aws-observability https://aws-observability.github.io/helm-charts
helm install cwagent aws-observability/amazon-cloudwatch-observability \
  --namespace amazon-cloudwatch --create-namespace \
  --version 6.6.0 -f cwagent-values.yaml
```

Either way, one imperative step survives: the IRSA annotation cannot be set through the chart at all
(see below), so it remains a `kubectl annotate` plus a pod restart, or EKS Pod Identity.

```yaml
# values.yaml — validated against chart 6.6.0
clusterName: <cluster-name>     # REQUIRED by the chart; it will not render without this
region: <region>                # REQUIRED; agent.config.agent.region does NOT satisfy it
agent:
  config:
    agent:
      region: <region>
    opentelemetry:
      collect:
        otlp:
          grpc_endpoint: 0.0.0.0:4317
          http_endpoint: 0.0.0.0:4318
# These default to TRUE and deploy machinery unrelated to an OTLP collector. (`kubeStateMetrics`
# and `nodeExporter` also default TRUE, and the chart's `agents` list has a second entry,
# `cloudwatch-agent-cluster-scraper` -- all three render only when `otelContainerInsights` is on,
# so leaving that false keeps them dormant and they need no entry here.)
containerLogs:
  enabled: false                # fluent-bit DaemonSets shipping ALL container logs to CW Logs
dcgmExporter:
  enabled: false
neuronMonitor:
  enabled: false
otelContainerInsights:
  enabled: false               # already the chart default; set it to pin the behaviour
containerInsights:
  enabled: false
applicationSignals:
  enabled: false
```

**The operator comes with this chart and cannot be turned off.** There is no `manager.enabled` key
— setting one is silently ignored. More importantly the agent ships as an `AmazonCloudWatchAgent`
**custom resource** that only the operator reconciles into the DaemonSet and Services, so disabling
it would leave nothing running. That is acceptable here: with `applicationSignals.enabled: false`
the operator creates no `Instrumentation` CR and annotates nothing, and its admission webhooks are
`failurePolicy: Ignore`, so a sick operator cannot wedge pod creation. If you need a genuinely
operator-free collector, use a plain manifest (mount the JSON at
`/etc/cwagentconfig/cwagentconfig.json` or pass it via `CW_CONFIG_CONTENT`, and give the
ServiceAccount a ClusterRole allowing `list`/`watch` on `replicasets` — without it the agent floods
its own log with RBAC denials).

**The chart also renders two Windows agents you cannot switch off, and one of them carries
Application Signals.** `cloudwatch-agent-windows` and `cloudwatch-agent-windows-container-insights`
are gated only on `agent.enabled`, and their configs are hardcoded in the chart — the Windows one
contains `logs.metrics_collected.application_signals` and `traces.traces_collected.application_signals`,
and the operator gives it a Service exposing **4316**. No values setting suppresses them; there is no
`windows` key at all. On a Linux-only cluster they are inert (`nodeSelector: kubernetes.io/os=windows`,
0 desired, no endpoints) and can be left alone — but expect to find 4316 in the namespace, and on a
cluster **with Windows nodes** delete both CRs after install or Application Signals will run there.

**The agent's Service does not exist at template time**, because the operator creates it. Do not try
to read it from `helm template` — the only Service there is the operator's webhook on 443. The name
is deterministic from `agents[].name`; after install confirm with `kubectl -n amazon-cloudwatch get
svc`. The app endpoint is:

```
http://cloudwatch-agent.amazon-cloudwatch.svc.cluster.local:4318
```

Note this is the same host the add-on exposes — the difference is the **port**: 4318 (OTLP), never
the Application Signals port 4316.

**The agent runs as a DaemonSet with `hostNetwork: true`**, not the Deployment-plus-ClusterIP shape
described for the backup below. 4317/4318 are therefore bound on **every node IP** — worth saying out
loud to the customer, for the same reason the guide
forbids a `LoadBalancer`.

**IRSA cannot be set through the chart.** The agent ServiceAccount template accepts no annotations
(`agent.serviceAccount` exposes only `name`; the chart's `roleArn` value is AKS-only), so Step 1's
annotation mechanism does **not** apply unchanged. Either annotate out of band — noting a later
`helm upgrade` does not revert it, but a ServiceAccount recreation would —

```bash
kubectl -n amazon-cloudwatch annotate serviceaccount cloudwatch-agent \
  eks.amazonaws.com/role-arn=<role-arn> --overwrite
kubectl -n amazon-cloudwatch delete pod -l app.kubernetes.io/name=cloudwatch-agent
```

— or use EKS Pod Identity, which needs no annotation. Either way the trust policy's `sub` is
`system:serviceaccount:amazon-cloudwatch:cloudwatch-agent`, **not** the
`opentelemetry:otel-collector` value used by the backup path below.

### Backup: upstream otelcol-contrib

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: opentelemetry
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: otel-collector
  namespace: opentelemetry
  annotations:
    # IRSA only; omit if using the node role
    eks.amazonaws.com/role-arn: arn:aws:iam::<account>:role/otel-collector-irsa
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: opentelemetry
data:
  config.yaml: |
    receivers:
      otlp:
        protocols:
          # Both protocols, matching collector.md: the Java agent defaults to gRPC on 4317 while
          # Python/Node/.NET default to HTTP on 4318. Expose both ports on the Service below too.
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
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  replicas: 1
  selector:
    matchLabels: { app: otel-collector }
  template:
    metadata:
      labels: { app: otel-collector }
    spec:
      serviceAccountName: otel-collector
      containers:
        - name: otel-collector
          # upstream CONTRIB (sigv4auth is a contrib component); pin a real version, never :latest
          image: otel/opentelemetry-collector-contrib:<version>
          args: ["--config=/conf/config.yaml"]
          ports:
            - containerPort: 4318
              name: otlp-http
          volumeMounts:
            - name: config
              mountPath: /conf
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits:   { memory: 512Mi }
      volumes:
        - name: config
          configMap:
            name: otel-collector-config
---
apiVersion: v1
kind: Service
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  type: ClusterIP
  selector:
    app: otel-collector
  ports:
    - name: otlp-http
      port: 4318
      targetPort: 4318
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
```

`type: ClusterIP` — in-cluster only. Never `LoadBalancer`; that publishes an unauthenticated
OTLP receiver to the internet.

The Service `selector` must match the pod template `labels`. When they disagree the Service
exists, DNS resolves, and every connection is refused because the Service has no endpoints.

## Step 3: Point the application at the collector

On the **application** container in its Deployment, alongside the loader variable and
`volumeMounts` the `eks-*.md` instrumentation guides add:

```yaml
env:
  # ... existing, including the language's loader variable ...
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    # CloudWatch Agent (primary). For the otelcol-contrib backup this is instead
    # http://otel-collector.opentelemetry.svc.cluster.local:4318
    value: "http://cloudwatch-agent.amazon-cloudwatch.svc.cluster.local:4318"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"
```

A stale value here fails loudly and unmistakably — `UnknownHostException` on the collector name — so
if you see that, check which of the two paths you actually deployed.

**The Service DNS name is not node-local, despite the agent being a DaemonSet.** A ClusterIP Service
is load-balanced by kube-proxy across every ready endpoint, so an app pod may well send to the agent
on a different node — and in a multi-AZ cluster, across an AZ boundary. That is correct and works;
it is simply not node-local, and the DaemonSet does not make it so.

If node-local delivery matters — for cross-AZ data-transfer cost, or to keep the failure domain on
one node — pick one of:

- **Target the node IP.** Use the downward-API pattern from the DaemonSet alternative below
  (`status.hostIP` into `NODE_IP`, then `http://$(NODE_IP):4318`). This works with the primary agent
  as-is, because `hostNetwork: true` already binds 4318 on the node.
- **Keep the Service and add `internalTrafficPolicy: Local`**, which tells kube-proxy to route only
  to endpoints on the calling node. Simpler to reason about, but traffic fails rather than falls back
  if the local agent pod is unhealthy.

Otherwise leave the Service name and drop the node-local expectation.

`OTEL_EXPORTER_OTLP_PROTOCOL` is not optional — see
[collector.md](collector.md#step-4-wire-the-app-to-the-collector).

## Alternative: DaemonSet

A DaemonSet keeps telemetry node-local, which avoids cross-AZ traffic charges and removes the
single collector as a bottleneck. The app then addresses the node it is running on:

```yaml
env:
  - name: NODE_IP
    valueFrom:
      fieldRef: { fieldPath: status.hostIP }
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://$(NODE_IP):4318"
```

This needs `hostPort: 4318` on the DaemonSet container, and the `$(NODE_IP)` interpolation only
works because `NODE_IP` is declared earlier in the same `env` list — Kubernetes substitutes in
order. Start with the Deployment; move to a DaemonSet when volume or cost justifies it.

## Verify

These inspect a running collector, so they belong to the conversation **after** the user applies.

**Primary — the CloudWatch Agent.** Note the namespace, workload kind and Service name all differ
from the backup path below:

```bash
kubectl -n amazon-cloudwatch get pods,svc
kubectl -n amazon-cloudwatch get daemonset cloudwatch-agent

# THE receiver-listening check, and the EKS substitute for `ss -lntp` -- you cannot exec into the
# agent container to run that: the image is distroless (no ss, no sh, no printenv). This also carries
# per-signal export health. Read it from stdout; there is no log FILE in a container.
kubectl -n amazon-cloudwatch logs -l app.kubernetes.io/name=cloudwatch-agent \
  | grep -E 'Starting HTTP server|Starting GRPC server|Everything is ready|Exporting failed|dropped_items'

# NOT a listening check, despite appearances. Endpoints are populated from ready pods and the
# Service's port spec, so a too-old agent listening on nothing still shows 4317/4318 here. Run it
# only for the *selector* mismatch case: empty output means the Service selects no agent pods at all.
kubectl -n amazon-cloudwatch get endpoints cloudwatch-agent

# IRSA actually injected? Read it from the API server, not from inside the pod
kubectl -n amazon-cloudwatch get pod -l app.kubernetes.io/name=cloudwatch-agent \
  -o jsonpath='{range .items[0].spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' \
  | grep -E 'AWS_ROLE_ARN|AWS_WEB_IDENTITY_TOKEN_FILE'

# DNS and the receiver, from the app's own namespace
kubectl -n <app-ns> exec deploy/<app> -- \
  curl -sS -o /dev/null -w '%{http_code}\n' \
  http://cloudwatch-agent.amazon-cloudwatch.svc.cluster.local:4318/v1/traces   # 405 = listening
```

Two caveats on that last check: many slim app images have no `curl` (`python:3.12-slim`,
`mcr.microsoft.com/dotnet/aspnet:*`), so prefer the agent-side listener log lines, or run a throwaway
`kubectl run --rm --image=curlimages/curl` pod in the app's namespace. And `kubectl get svc` will
show an `otlp-grpc` port on 4317 even when `grpc_endpoint` is not configured — only the agent log's
`Starting GRPC server` line tells the truth.

**Backup — `otelcol-contrib`:**

```bash
kubectl -n opentelemetry get pods,svc
kubectl -n opentelemetry logs deploy/otel-collector

# Service actually has endpoints (empty = selector/label mismatch)
kubectl -n opentelemetry get endpoints otel-collector

# DNS and the receiver, from the app's own namespace
kubectl -n <app-ns> exec deploy/<app> -- \
  curl -sS -o /dev/null -w '%{http_code}\n' \
  http://otel-collector.opentelemetry.svc.cluster.local:4318/v1/traces   # 405 = listening
```

| Symptom | Cause |
|---|---|
| `no such host` from the app | Wrong namespace in the DNS name, or Service not created |
| DNS resolves, connection refused | Service selector doesn't match pod labels — check `get endpoints` |
| Collector logs `AccessDenied` on `AssumeRoleWithWebIdentity` | Four causes, in order of likelihood: **the ServiceAccount was never annotated** (on the primary path the chart cannot do it — see Step 2, and remember the pod delete); the IRSA `sub` condition doesn't match — it is `system:serviceaccount:amazon-cloudwatch:cloudwatch-agent` on the primary path and `system:serviceaccount:opentelemetry:otel-collector` on the backup; the role was created seconds ago and IAM has not propagated (retry); or the manifest was applied to a **different cluster**, so the token is signed by another OIDC issuer — check `kubectl config current-context` |
| Collector logs `403` on export | **Read the 403's `Message=` body first.** A denial naming the principal and action means the role lacks `CloudWatchAgentServerPolicy`; one describing account enablement is not IAM and no policy change will fix it |
| Receiver reachable, nothing exported | `OTEL_EXPORTER_OTLP_PROTOCOL` unset, SDK defaulted to gRPC |
| Metrics arrive, spans do not | Transaction Search not enabled on the account |
| Spans arrive, metrics do not | The metrics endpoint rejected the publish. Read the 403 body — this is the inverse case and has nothing to do with Transaction Search |

## Completion

Tell the user what was added. On the **primary** path that is a Helm release in
`amazon-cloudwatch` (which brings the operator, an `AmazonCloudWatchAgent` custom resource, the
agent DaemonSet and its Services, plus two inert Windows agents), an IRSA role, and the
out-of-band ServiceAccount annotation plus pod restart. On the **backup** path it is a namespace,
ServiceAccount, ConfigMap, Deployment and Service, and the IAM role or node-role attachment.
Either way: the app now exports to the collector's DNS name, an OIDC provider may still be a
prerequisite they need, and no application source or image changed.

Present the values file plus whichever install form you used — the `helm_release` resource as part
of the Terraform diff, or the `helm` commands handed over for the user to run. Either way the
IRSA annotation and pod restart are commands for them, not for you.
