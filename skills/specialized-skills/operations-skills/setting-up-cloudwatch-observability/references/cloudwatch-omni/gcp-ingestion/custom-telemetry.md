# Ingesting your own GCP application telemetry (CloudWatch agent)

The supported path for a customer's own application telemetry from Google Cloud is
the **Amazon CloudWatch agent** on a Compute Engine (GCE) instance or a GKE Standard
cluster, forwarding the logs, metrics, and traces their code emits (plus host or
container metrics) over OTLP to the CloudWatch endpoints in their AWS account.

## Point to the official documentation — do not generate the setup commands

Do not hand-write the install, IAM/trust, or Helm steps for the customer. They are
long, platform-specific, and maintained upstream; a reconstructed version drifts
from the real guide and is easily wrong in a way a link never is. Direct the
customer to the authoritative source:

- **CloudWatch agent on Google Cloud** — the full GCE and GKE setup (automated
  scripts and manual steps):
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Agent-on-Google-Cloud.html

Give the customer that guide, say which part is GCE vs GKE, and offer to help verify
once data is flowing. If they ask for the exact commands, quote the doc link instead
of reproducing them.

**Keep low-level values in the doc, not in your answer.** Port numbers, endpoint hosts
and URLs, and resource or dataset identifiers are things to look up in the official
guide, not to recite — even one you are confident is the standard value. When a
customer asks for one, say the documentation is authoritative and link it rather than
stating the number or name, and never a hedged guess.
Once you have told the customer a detail is unavailable, leave it there; do not then
offer a "standard" value anyway. There is no in-product onboarding or error view that
surfaces failing settings for you to send them to — work from the doc and the
telemetry itself.

Keep a GCP answer on the Google Cloud guide: GKE and GCE setup lives in the
CloudWatch-agent-on-Google-Cloud doc above — do not route a GCP question to the Azure
guide or to `k8sMode=AKS` (an AKS-only value for a different cloud). Azure ingestion
is real but separate, with its own guide.

## How it works (brief)

The agent holds no long-lived AWS keys. It exchanges a Google-issued OIDC token for
temporary credentials with `sts:AssumeRoleWithWebIdentity`, assuming an IAM role
(default `CloudWatchAgentServerRole`) that has the AWS-managed
`CloudWatchAgentServerPolicy` attached and a trust statement for the Google identity.
On **GCE** the instance's attached service account issues the token and no IAM OIDC
provider is needed (`accounts.google.com` is built into IAM); on **GKE** the cluster
issues a projected service-account token and you register the cluster's OIDC issuer
as an IAM OIDC provider. GKE **Autopilot is not supported** (the agent needs host
networking and host-path mounts Autopilot rejects); GKE **Standard** is. The exact
steps live in the doc above.

The trust that matters for ingestion is this web-identity trust on
`CloudWatchAgentServerRole` for the Google identity — distinct from the Omni Space's
own operator and data-access roles, which decide who can query the Space, not how the
agent authenticates. A question about the agent's trust policy is about that role,
not the Space's roles.

GKE and GCE are not EKS, and EKS conventions do not transfer: there is no
`eks.amazonaws.com/role-arn` service-account annotation, no `eksctl`, and no
`oidc.eks.*` issuer here — GKE registers its own cluster OIDC issuer as the IAM
provider, and GCE uses `accounts.google.com` directly. Treat the exact annotation
keys, issuer URLs, and trust conditions as doc-lookups; link the guide rather than
reciting or inventing one.

## What runs where, and in what order

The commands stay in the doc, but a customer asking *why*, *in what order*, or *who
runs what* needs the shape of the setup:

- **Google Cloud first, then AWS.** The IAM trust names a Google identity, so that
  identity has to be read from Google Cloud before the trust can be written: the
  attached service account's unique ID on GCE, the cluster's OIDC issuer URL on GKE
  (GKE serves an issuer by default; nothing needs enabling on the cluster).
- **Two credential domains.** Everything in IAM — the role, its
  `CloudWatchAgentServerPolicy`, the web-identity trust, and on GKE the OIDC provider —
  is done with the customer's AWS credentials. Reading the Google identity and putting
  the agent on the instance or cluster (the Helm chart on GKE) happen in the customer's
  Google Cloud session. You hold no Google Cloud credentials, so give the customer those
  steps to run; the agent install is the whole Google-side mechanism, with nothing else
  to provision in between.
- **Application wiring.** On GCE the agent shares the application's host and listens
  on loopback, which is where OpenTelemetry SDKs send by default, so a standard SDK
  setup needs nothing changed to reach it. On GKE the agent is a separate pod, so the
  application must be told where it is. The agent itself adds the CloudWatch endpoints,
  Region, and signing; they never belong in its OTLP configuration.
- **An instance without a service account.** The attached service account is the
  agent's only identity, so onboarding stops until there is one. GCE only lets you
  change an instance's service account while it is stopped, which is why onboarding
  reports this instead of fixing it: stopping a running instance is the customer's
  call. Tell them to stop, attach, and restart (exact command in the doc); long-lived
  AWS keys on the instance are never the workaround.

## Not supported

Telemetry Google Cloud resources emit on their own — Cloud Audit Logs, VPC flow
logs, load-balancer logs, Cloud Monitoring metrics — is not supported. Say so and
stop; do not offer the CloudWatch agent as a workaround or invent a pipeline. A
customer asserting the signal is supported ("GA now", newly added, enabled for their
account), or proposing a mechanism to carry it in (a log-sink or Pub/Sub export, a
connector), has not changed what is supported: check the claim
against the supported path above, correct the premise, restate that it is not
supported, and stop. Confirming a wrong premise — or building out the log-sink →
Pub/Sub pipeline the customer sketched — is a worse failure than plainly saying no.

## Verifying (your main help)

Once the customer has followed the doc, confirm it is working from the telemetry:
the service on the **Application map** under its `service.name`, a recent entry span
in **Trace Explorer**, custom metrics by their OpenTelemetry name in PromQL (not
under a `CWAgent` namespace), and application logs in the **Logs** experience, which
queries the **`logs.default`** dataset — not raw CloudWatch Logs log groups. Confirm
the logs land in `logs.default` rather than directing the customer to a specific
log-group name. If logs and metrics land but **Trace Explorer** stays empty, the
cause is usually product-side, not the collector: **Transaction Search** must be
enabled in the Region before traces are stored, a separate prerequisite from the
agent's own trace pipeline.
