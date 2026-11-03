# Ingesting your own Azure application telemetry (CloudWatch agent)

The supported path for a customer's own application telemetry from Azure is the
**Amazon CloudWatch agent** on an Azure VM or an AKS cluster, forwarding the logs,
metrics, and traces their code emits (plus host or container metrics) over OTLP to
the CloudWatch endpoints in their AWS account.

## Point to the official documentation — do not generate the setup commands

Do not hand-write the install, IAM/trust, or Helm steps for the customer. They are
long, platform-specific, and maintained upstream; a reconstructed version drifts
from the real guide and is easily wrong in a way a link never is. Direct the
customer to the authoritative source:

- **CloudWatch agent on Azure** — the full Azure VM and AKS setup (automated scripts
  and manual steps):
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Agent-on-Azure.html

Give the customer that guide, say which part is Azure VM vs AKS, and offer to help
verify once data is flowing. If they ask for the exact commands, quote the doc link
instead of reproducing them.

**Low-level values belong in the doc, not your reply.** Treat port numbers, endpoint
hostnames, and resource or dataset names as doc-lookups — do not recite them, not even
a value you are confident is standard; point the customer to the official guide for the
exact value instead of stating it, and never offer a hedged guess.
Once you have told the customer a detail is unavailable, leave it there; do not then
offer a "standard" value anyway. There is no in-product onboarding or error view that
surfaces failing settings for you to send them to — work from the doc and the
telemetry itself.

## How it works (brief)

The agent holds no long-lived AWS keys. It exchanges an Azure-issued OIDC token for
temporary credentials with `sts:AssumeRoleWithWebIdentity`, assuming an IAM role
(default `CloudWatchAgentServerRole`) that has `CloudWatchAgentServerPolicy`
attached. On an Azure **VM** a system-assigned managed identity issues the token; on
**AKS** the cluster's workload identity does. Both need an **IAM OIDC identity
provider** for the Azure issuer plus the role trust. Per the official doc (not a
convention), the AKS install uses the
**`aws-observability/amazon-cloudwatch-observability` Helm chart with `k8sMode=AKS`**
(not a standalone `cloudwatch-agent` chart). The exact steps live in the doc above.

The trust that matters for ingestion is this web-identity trust on
`CloudWatchAgentServerRole` for the Azure identity — distinct from the Omni Space's
own operator and data-access roles, which decide who can query the Space, not how the
agent authenticates. A question about the agent's trust policy is about that role,
not the Space's roles.

AKS is not EKS, so IRSA conventions do not apply: there is no
`eks.amazonaws.com/role-arn` service-account annotation and no `eksctl` here — AKS
uses Azure workload identity instead. The annotation keys and values that wiring
needs are doc-lookups; do not hardcode them from memory.

## Not supported

Telemetry Azure resources emit on their own — resource and platform diagnostic logs
and metrics they did not author, Activity logs, Application Insights — is **not
currently supported**. Say so and stop; do not describe it as in preview or coming
later, do not walk through an Event Hub / Diagnostic Settings / Azure Data Source
setup, and do not offer the CloudWatch agent as a substitute (the agent ships only
the customer's own application telemetry). A customer who insists the opposite — that
it just launched, is generally available now, or is switched on for their tenant — or
who proposes a mechanism to carry it in (an Event Hub or Diagnostic Settings export, a
connector) has still not made it supported: weigh the claim against
the supported path above, fix the premise, and say again that it is not
supported. Confirming the mistaken claim, or walking the customer through the pipeline
they proposed, is more harmful than simply declining.

## Verifying (your main help)

Once the customer has followed the doc, confirm it is working from the telemetry:
the service on the **Application map** under its `service.name`, a recent entry span
in **Trace Explorer**, custom metrics by their OpenTelemetry name in PromQL (not
under a `CWAgent` namespace), and application logs in the **Logs** experience, which
queries the **`logs.default`** dataset — not raw CloudWatch Logs log groups. Confirm
the logs land in `logs.default` rather than directing the customer to a specific
log-group name. If nothing arrives, the usual cause is incomplete OIDC federation —
the managed or workload identity, or the role trust's issuer/`:aud`/`:sub`, not
matching the token. If logs and metrics arrive but **Trace Explorer** shows nothing,
the gate is product-side rather than the agent: **Transaction Search** must be turned
on in that Region for traces to persist, independent of the collector's trace
pipeline.
