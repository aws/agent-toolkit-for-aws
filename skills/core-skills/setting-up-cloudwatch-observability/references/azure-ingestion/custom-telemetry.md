# Custom telemetry: the CloudWatch agent on Azure

Use this path when the customer wants to send **their own** application metrics,
logs, and traces (plus host metrics) from compute they run in Azure. They install
the **Amazon CloudWatch agent** on an **Azure VM** or an **AKS** cluster; the
agent runs an OpenTelemetry (OTLP) receiver and forwards everything to the
CloudWatch OTLP endpoints in the customer's AWS account.

> Scope: this covers the telemetry the customer's **own application** produces —
> the logs, metrics, and traces from their code. Ingesting telemetry that Azure
> resources emit on their own (resource/platform diagnostic logs — the Azure
> equivalent of AWS VPC flow logs or Route 53 logs) is **not available today**;
> if that's what the customer wants, say so and stop rather than using this path —
> do not present the CloudWatch agent as a workaround for it (it cannot collect
> resource-emitted telemetry).

If the customer's request does not make clear which of the two they mean (for
example "get my Azure telemetry into CloudWatch"), resolve that **before** giving
any setup steps: say that this path covers the telemetry their own application
emits, that telemetry Azure resources emit themselves is not supported today, and
ask which they have if it is still unclear.

## How authentication works

The agent never stores long-lived AWS keys. It uses OIDC web-identity federation:

- **Azure VM** — a **system-assigned managed identity** on the VM issues OIDC
  tokens. The agent reads a token from the Azure Instance Metadata Service and
  calls `sts:AssumeRoleWithWebIdentity` for temporary AWS credentials.
- **AKS** — the cluster's **workload identity** issues the OIDC token through a
  projected service account token; the agent assumes the role the same way.

Either way, the customer's AWS account needs two things:

1. An **IAM OIDC identity provider** for the Azure issuer.
2. An **IAM role** that trusts that issuer and has the
   `CloudWatchAgentServerPolicy` managed policy attached (default role name
   `CloudWatchAgentServerRole`).

**The Azure step always runs first.** It produces the value the AWS trust step
consumes — the tenant ID on a VM, the OIDC issuer URL on AKS — so the AWS step
can never run first.

**Ownership split for you (the agent):** you have the customer's **AWS**
credentials, so you own the AWS-side IAM setup (Automated step 2, or the manual
AWS commands below). When the customer asks you to onboard or set this up, you
may run those AWS-side steps directly — **except where a step says to confirm first.** Touching the
trust policy of the shared `CloudWatchAgentServerRole` is the one that does: it is existing
infrastructure the whole CloudWatch-agent fleet depends on, so it needs the save-first, show-the-
merged-policy, confirm-then-write procedure regardless of how broad the onboarding request was. That
applies to the **automated** path as well as the manual commands — `aws/setup.sh` writes that trust
policy too, so check whether the role already exists before running it (see Step 2). When the customer only asks _what changes
to make_ (an advisory, read-and-recommend request), present the AWS-side steps
for them to apply — do **not** run `terraform apply`, `az`, or `aws` mutating
commands on their behalf, and do not list them as steps for the customer to run;
describe the change and let them decide how to apply it. The **Azure-side** steps
(assigning the managed identity, installing the agent onto the VM/cluster)
require the customer's Azure CLI session, which you do **not** have — hand those
commands to the customer to run in an Azure-authenticated shell (for example
Azure Cloud Shell).

**The customer's application is off limits.** Your job is to collect the
telemetry the application **already** emits — never edit the customer's
application code or its dependencies to make it emit something different. On AKS
the exporter's endpoint has to point at the agent, which is allowed; on a VM even
that is unnecessary, since the agent listens on the OTLP default. If a signal is not reaching CloudWatch, fix it in
the agent's configuration, not in their code: application logs written to a file
rather than exported over OTLP are collected by configuring the agent to read
that file (see `append-config` under Configuring what the agent collects), not by
rewriting the application to export them.

## Prerequisite: find the Azure resource ID

The onboarding scripts identify the VM or cluster by its full Azure resource ID
(`CWAGENT_AZURE_RESOURCE_ID`). The customer can find it on the resource's
Properties page in the Azure portal, or retrieve it:

```sh
# Azure VM
az vm show --resource-group <rg> --name <vm> --query id --output tsv
# AKS cluster
az aks show --resource-group <rg> --name <cluster> --query id --output tsv
```

---

## Automated setup (recommended)

Two onboarding scripts. **Run the Azure step first, then the AWS trust step.**

### Azure VM

**Step 1 — Azure side (customer runs, in an Azure-authenticated shell).** Assigns
the VM's managed identity, installs and starts the agent, and prints the Azure
tenant ID. The default OpenTelemetry config collects host metrics and starts an
OTLP receiver for the customer's app metrics, logs, and traces.

```sh
curl -fsSL https://raw.githubusercontent.com/aws/amazon-cloudwatch-agent/main/scripts/azure/setup.sh | \
  CWAGENT_PLATFORM=azure_vm \
  CWAGENT_AZURE_RESOURCE_ID=<vm-resource-id> \
  CWAGENT_AWS_ROLE_ARN=<role-arn> \
  CWAGENT_AWS_REGION=<region> \
  sh
```

**Step 2 — AWS side (you run this; needs IAM write access).** Creates the role,
attaches `CloudWatchAgentServerPolicy`, and adds the Azure web-identity trust for
the tenant ID from step 1.

> **This script writes a tenant-wide trust.** It takes only a tenant ID — no managed-identity
> object ID — so the trust is the `:aud`-only form the manual section says not to ship: any identity
> in the Azure tenant could assume a role holding `CloudWatchAgentServerPolicy`. Tell the customer
> before running it, then narrow it afterwards by adding `"<issuer-host>:sub"` to the existing
> `StringEquals` block (save-first / confirm procedure below). Or use the manual commands, which set
> both conditions on the first write.
> **STOP if `CloudWatchAgentServerRole` already exists.** It is the default name for every
> CloudWatch agent setup, so an account already running the agent has it, with trust the fleet
> depends on. This guide does not know whether `aws/setup.sh` merges into that policy or replaces it
> (unpinned `main`, undocumented), and a replace would take the fleet down. Check
> `aws iam get-role --role-name CloudWatchAgentServerRole` first: if it exists, apply the manual
> path's save-first / confirm / rollback procedure instead of running the script unattended.

```sh
curl -fsSL https://raw.githubusercontent.com/aws/amazon-cloudwatch-agent/main/scripts/aws/setup.sh | \
  CWAGENT_PLATFORM=azure_vm \
  CWAGENT_AZURE_TENANT_ID=<tenant-id> \
  CWAGENT_AWS_REGION=<region> \
  sh
```

For a VM the agent install can run before the trust exists — the agent retries
with backoff until the trust is in place, so the order of the two scripts is
forgiving. Use the role ARN that the AWS step creates (default
`arn:aws:iam::<account-id>:role/CloudWatchAgentServerRole`).

### AKS

Same two scripts with `CWAGENT_PLATFORM=azure_aks`. The Azure step enables the
OIDC issuer and workload identity on the cluster (an `az aks update` that can
take several minutes), installs the CloudWatch Observability Helm chart, and
prints the cluster's **OIDC issuer URL**. Here the AWS trust step **must run
after** the Azure step, because the issuer only exists once the Azure step
enables it. On AKS the chart's default OpenTelemetry config enables OTel
Container Insights and starts an OTLP receiver for the customer's app metrics,
logs, and traces.

```sh
# Step 1 — Azure side (customer runs)
curl -fsSL https://raw.githubusercontent.com/aws/amazon-cloudwatch-agent/main/scripts/azure/setup.sh | \
  CWAGENT_PLATFORM=azure_aks \
  CWAGENT_AZURE_RESOURCE_ID=<cluster-resource-id> \
  CWAGENT_AWS_ROLE_ARN=<role-arn> \
  CWAGENT_AWS_REGION=<region> \
  sh

# Step 2 — AWS side (you run this), take OIDC issuer URL from previous step
curl -fsSL https://raw.githubusercontent.com/aws/amazon-cloudwatch-agent/main/scripts/aws/setup.sh | \
  CWAGENT_PLATFORM=azure_aks \
  CWAGENT_AZURE_OIDC_ISSUER=<issuer-url> \
  CWAGENT_AWS_REGION=<region> \
  sh
```

## AKS vs Azure VM: what differs

| | Azure VM | AKS |
|---|---|---|
| `CWAGENT_PLATFORM` | `azure_vm` | `azure_aks` |
| Azure step produces | the tenant ID | the cluster OIDC issuer URL |
| Passed to the AWS step as | `CWAGENT_AZURE_TENANT_ID` | `CWAGENT_AZURE_OIDC_ISSUER` |
| OIDC audience | `https://management.azure.com/` | `sts.amazonaws.com` |
| Trust `:sub` condition | manual setup sets it (the VM's managed identity object ID); the onboarding script writes `:aud` only, so narrow it afterwards | required, both agent service accounts |
| Azure identity | system-assigned managed identity | cluster OIDC issuer + workload identity |
| Agent install | host package on the VM | Amazon CloudWatch Observability Helm chart |
| Default collection | host metrics | OTel Container Insights |
| The app's OTLP target | `localhost` `4317`/`4318` | `cloudwatch-agent.amazon-cloudwatch:4317` |

Ordering is stricter on AKS: the AWS trust step **must** run after the Azure step,
because the cluster's OIDC issuer URL does not exist until the Azure step enables
it. On a VM the tenant ID exists already, so only the value has to be in hand.

---

## Manual setup

Only for a customer who cannot run the onboarding scripts or when asked explicitly
to do the manual setup; otherwise the automated scripts above are the answer on
either platform.

The Azure work comes in two parts: enable the identity first, then install the
agent once the AWS role exists and you have its ARN.

### Azure side (hand these to the customer)

These `az` commands act on the subscription that is **active** in the customer's
Azure CLI. Have them confirm it with `az account show`, or switch with
`az account set --subscription <subscription-id>`, before running any of them.

**Azure VM:**

```sh
az vm identity assign --resource-group <rg> --name <vm>   # system-assigned managed identity
az account show --query tenantId --output tsv             # tenant ID for the AWS trust step
az vm identity show --resource-group <rg> --name <vm> \
  --query principalId --output tsv                        # object ID for the trust :sub condition
```

Both values come back from the customer: the tenant ID builds the issuer, and the object ID is what
the `:sub` condition pins the role to. Ask for both before writing the trust policy — the AWS side
cannot obtain them, since `az` needs the customer's Azure session.

Then install the agent on the VM (same package as an on-premises server) and
start it with the default OpenTelemetry config, which reads the role ARN from
`CWAGENT_ROLE_ARN`:

```sh
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a set-env -e AWS_REGION=<region>
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a set-env -e CWAGENT_ROLE_ARN=<role-arn>
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m auto -c default:otel -s
```

**AKS:**

```sh
az aks update --resource-group <rg> --name <cluster> --enable-oidc-issuer --enable-workload-identity
az aks show --resource-group <rg> --name <cluster> --query oidcIssuerProfile.issuerUrl --output tsv
```

Then install the agent via the Amazon CloudWatch Observability Helm chart. This is
the manual equivalent of the `CWAGENT_PLATFORM=azure_aks` Azure step above, which
runs it for the customer when `helm` and `kubectl` are available:

```sh
helm repo add aws-observability https://aws-observability.github.io/helm-charts
helm upgrade --install amazon-cloudwatch-observability \
  aws-observability/amazon-cloudwatch-observability \
  --namespace amazon-cloudwatch --create-namespace \
  --set k8sMode=AKS --set roleArn=<role-arn> --set region=<region> \
  --set clusterName=<cluster-name>
```

Set the same agent values the `azure_aks` script sets: OTel Container Insights on,
classic Container Insights and container logs off, and **both** `agents[]` entries
— `cloudwatch-agent` with `default:otel`, and `cloudwatch-agent-cluster-scraper` as
a deployment with `default`. Helm's `--set` replaces a whole list element, so
omitting the scraper entry removes it.

### AWS side (you run these — the customer has given you AWS credentials)

The OIDC audience and the trust condition differ between the two platforms — do
not reuse the VM policy for AKS. No thumbprint is needed either way (IAM
retrieves the issuer's top intermediate CA thumbprint).

**Azure VM.** Register the Microsoft Entra ID issuer, audience
`https://management.azure.com/`:

```sh
aws iam create-open-id-connect-provider \
  --url https://sts.windows.net/<tenant-id>/ \
  --client-id-list https://management.azure.com/
```

Trust policy, where `<issuer-host>` is
`sts.windows.net/<tenant-id>/`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/<issuer-host>"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "<issuer-host>:aud": "https://management.azure.com/",
          "<issuer-host>:sub": "<managed-identity-object-id>"
        }
      }
    }
  ]
}
```

Both conditions are required. The `management.azure.com` audience is shared by every identity in
the tenant, so `:aud` alone trusts the **whole Azure tenant** — omitting `:sub` would let any
identity in the tenant assume a role holding `CloudWatchAgentServerPolicy` (attached below). `:sub`
pins it to the one VM's managed identity. The value is the managed identity's principal (object) ID,
which the customer obtains with `az vm identity show --resource-group <rg> --name <vm> --query
principalId -o tsv` and hands to you — you cannot run `az` yourself. This equivalence holds for the
`sts.windows.net/<tenant-id>/` issuer registered above (Entra v1.0), where an app-only token's `sub`
equals its `oid`; a v2.0 issuer puts a pairwise pseudonymous value in `sub` instead, and the trust
would not match.

Do not ship the `:aud`-only form. If the customer wants several VMs to share the role, add one
`:sub` value per identity (`StringEquals` accepts a list) rather than dropping the condition.

**AKS.** Register the cluster's OIDC issuer, audience `sts.amazonaws.com`:

```sh
aws iam create-open-id-connect-provider \
  --url <aks-oidc-issuer-url> \
  --client-id-list sts.amazonaws.com
```

Trust policy, where `<issuer-host>` is the issuer URL without the `https://`
prefix. Both conditions are required: `:sub` scopes the role to the agents' own
service accounts, so omitting it would let **any** workload in the cluster assume
a role holding `CloudWatchAgentServerPolicy`. List both — the chart installs two
agents and the cluster-scraper has its own service account, so pinning only
`cloudwatch-agent` leaves the scraper permanently denied.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/<issuer-host>"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "<issuer-host>:sub": [
            "system:serviceaccount:amazon-cloudwatch:cloudwatch-agent",
            "system:serviceaccount:amazon-cloudwatch:cloudwatch-agent-cluster-scraper"
          ],
          "<issuer-host>:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```

If you are reusing an existing role, merge this statement into its trust policy
rather than replacing it.

Create the role and attach the managed policy, passing the policy inline:

```sh
aws iam create-role --role-name CloudWatchAgentServerRole \
  --assume-role-policy-document '<trust-policy-json>'
aws iam attach-role-policy --role-name CloudWatchAgentServerRole \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
```

`CloudWatchAgentServerRole` is the default name for every CloudWatch agent setup,
so `create-role` fails with `EntityAlreadyExists` if the account already runs the
agent anywhere. Then **merge** — read the current trust policy, append this
statement to its `Statement` array, and write the merged document back.
`update-assume-role-policy` replaces the whole policy, so passing only this
statement would revoke the existing EC2/ECS/EKS trust the running fleet depends
on.

This role is shared infrastructure the agent did not create, so treat the change the way you would
any edit to a customer-owned role: **save the current document, then confirm before writing.** Show
the customer the merged policy and get their agreement — a botched merge locks out the running fleet,
and without the saved original there is nothing to roll back to.

```sh
# 1. SAVE the current policy first — this is your only rollback source.
#    Write it outside the customer's repo with owner-only perms: it carries the AWS account id,
#    the OIDC issuer host, and the managed-identity object id. Delete it once the change is verified.
umask 077
aws iam get-role --role-name CloudWatchAgentServerRole \
  --query Role.AssumeRolePolicyDocument > "$(mktemp -t cwagent-trust-XXXXXX.json)"
# note the path it printed; that file is the rollback source

# 2. Append this statement to Statement[] in a copy, show the customer the merged
#    document, and write it only once they confirm:
aws iam update-assume-role-policy --role-name CloudWatchAgentServerRole \
  --policy-document '<merged-policy-json>'

# Rollback, if the fleet loses trust:
#   aws iam update-assume-role-policy --role-name CloudWatchAgentServerRole \
#     --policy-document file://<the saved path from step 1>
# Then delete the saved file.
```

If OTLP **traces** are needed, Transaction Search must be enabled in the target
Region before traces are sent (a per-Region account setting). The automated
`aws/setup.sh` can enable it with `CWAGENT_AWS_ENABLE_TRANSACTION_SEARCH=true`.

Confirm this one with the customer before enabling it. It is an **account-wide** setting for that
Region, not scoped to this VM or cluster, so it affects every service in the account that sends
traces — and it is billed on the spans it indexes. Say both things, and let them decide.

---

## Configuring what the agent collects (OTLP)

The default config (`default:otel`) already starts an OTLP receiver — gRPC on
`4317`, HTTP on `4318`. On a VM it also collects host metrics; on AKS the chart's
default enables OTel Container Insights instead. To customize, add an
`opentelemetry` section to the agent configuration file and enable the `otlp`
source; the agent sets the CloudWatch OTLP endpoints, Region, and request
signing for you (no endpoint URLs or `sigv4auth` to specify):

> **Restrict these ports before you ship this config.** The `0.0.0.0` endpoints below listen on every
> interface with no TLS and no authentication, so on AKS any pod that can route to the agent can
> inject spans, and on a VM anything that can reach the port can. Bind to `127.0.0.1` when the sender
> is on the same host — which is the VM case. Otherwise restrict `4317`/`4318` with an Azure NSG (VM)
> or a NetworkPolicy limiting ingress to the instrumented workloads (AKS). This guide does not apply
> those controls, so assess and configure them for your environment.

```json
{
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

The customer's application sends OTLP to the agent's `4317`/`4318` endpoint. On a
VM that is `localhost`, which is already the OTLP default, so **do not tell the
customer to set `OTEL_EXPORTER_OTLP_ENDPOINT`** — nothing on the application side
needs changing. Only on AKS does the application need an explicit endpoint,
`cloudwatch-agent.amazon-cloudwatch:4317`, because the agent is a different host.
Never hand-write the CloudWatch-side OTLP endpoints or `sigv4auth`; the agent sets
those itself. The
agent enriches it and forwards each signal to the correct CloudWatch OTLP
endpoint (`monitoring` for metrics, `logs` for logs, `xray` for traces). The
`CloudWatchAgentServerPolicy` grants the permissions to write to all three.

For pipelines the config file doesn't expose, the customer can append a raw
OpenTelemetry collector YAML with `amazon-cloudwatch-agent-ctl -a append-config`;
give each appended component a suffix (for example `otlphttp/cwagent`) to avoid
colliding with the agent's built-in pipelines.

## Verify data is flowing

1. Confirm the agent is running. On a VM the install script prints an
   "installed and running" sentinel on success; on AKS check the Helm release and
   the agent pods in the `amazon-cloudwatch` namespace.
2. In the customer's AWS account and Region, look for the telemetry in CloudWatch.
   Everything on this path arrives over OTLP, so the metrics are **not** in the
   classic metrics browser under a `CWAgent` namespace — query them in Query
   Studio (under Metrics), filtering on `@resource.host.name` for a VM or
   `@resource.k8s.cluster.name` for AKS.
3. If nothing arrives: check that the managed/workload identity is assigned, the
   IAM role trust and `CloudWatchAgentServerPolicy` are in place, and (for
   traces) that Transaction Search is enabled in the Region.
