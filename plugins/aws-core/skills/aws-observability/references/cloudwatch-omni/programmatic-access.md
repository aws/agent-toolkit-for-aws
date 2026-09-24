# Omni Programmatic Access Reference

CloudWatch Omni is not console-only. A script, a service, a CI job, an infrastructure-as-code template, or an AI coding agent can all drive it. There are four programmatic paths — the public API, the AWS CLI and SDKs, AWS CloudFormation, and the Agent Toolkit for AWS — and this file covers each, so an answer never wrongly denies that Omni can be used from code.

## 1. The Public API

CloudWatch Omni exposes a standard **SigV4-signed AWS API**. No console session is required — but the wire protocol is Smithy RPC v2 CBOR (`rpcv2Cbor`), not JSON: each call is a POST to `/service/CloudWatchOmniFrontend/operation/<Op>` with a CBOR body. So the caller needs an AWS SDK or CLI that carries the `cloudwatchomni` service model; a hand-rolled JSON-over-SigV4 client cannot call it.

| Property | Value |
|---|---|
| Endpoint prefix | `cloudwatch-omni` |
| SigV4 signing name | `cloudwatch` |
| Regional endpoint | `cloudwatch-omni.<region>.api.aws` |
| Protocol | Smithy RPC v2 CBOR (`rpcv2Cbor`); path `/service/CloudWatchOmniFrontend/operation/<Op>` |

The signing name differs from the endpoint prefix. Requests are signed for `cloudwatch` while being sent to the `cloudwatch-omni` host — an SDK/CLI with the model sets this for you; a client that derives the signing name from the hostname gets it wrong.

### Authorization — state this on every programmatic answer

A programmatic caller is authorized by **two layers**: the caller's IAM policy, and the Space's access grants. How they combine depends on how the caller presents itself. A caller that has assumed an **Access Profile**, or a person acting through IAM Identity Center or the console, must hold a matching grant on the Space — with none, the Space denies the call regardless of IAM. An IAM principal that signs the API call **directly with its own credentials** (a CI role using the CLI, an SDK client, a CloudFormation deployment role, a coding agent) is treated as a machine identity: grants that match it are enforced (their row and column scopes apply, and an explicit deny wins), but when no grant matches, the Space does not deny — the request falls through to the caller's IAM policy, which alone decides, with no row restriction. Direct IAM callers reach only Spaces owned by their own account.

So when a correctly signed call is denied, check both layers: the IAM policy on the calling role (`cloudwatch:*` actions on the `cloudwatch-omni` resources), and, if the caller runs under an Access Profile or a grant naming it exists, that grant's permission and scope. Full detail is in the `setting-up-cloudwatch-observability` skill's `references/cloudwatch-omni/access-grants.md`.

**Operations** are grouped by the same resources documented elsewhere in this skill — read those files rather than guessing an operation name:

| Resource | Reference |
|---|---|
| Alerts | [alerts.md](alerts.md) |
| Views | [views.md](query/views.md) |
| Dashboards | [dashboards.md](dashboards.md) |
| Log and trace queries | [sql-logs-traces.md](query/sql-logs-traces.md) |

## 2. AWS CLI and AWS SDKs

CloudWatch Omni is supported by the **AWS CLI** and the **AWS SDKs**, under the `cloudwatchomni` service name: `aws cloudwatchomni <operation>`, and the corresponding client in each SDK.

Two things to know when a call does not work:

- **`aws cloudwatchomni …` reporting that the service is not supported means the local CLI predates Omni's service model.** The AWS CLI and each SDK ship a snapshot of service models, so a version older than Omni's release has no `cloudwatchomni` client. This is a client-version issue and says nothing about whether Omni is enabled on the account — the failure happens during argument parsing, before any request is sent. Upgrade to a version that carries it:
  - **AWS CLI v2** — check `aws --version`, then reinstall/upgrade per <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>: macOS `brew upgrade awscli` or the `.pkg` installer; Linux re-run the zip installer with `--update`; Windows the MSI.
  - **boto3** — `pip install -U boto3 botocore`.
  - **Other SDKs** — upgrade to the latest release.

  Give the customer that command; do **not** run `brew`, `pip install -U`, or an installer on the host yourself — a package-manager upgrade mutates their machine beyond the request (a Homebrew upgrade, for example, can replace the system Python other tools depend on). Then have them re-run `aws cloudwatchomni list-domains`. If the command is still unknown after upgrading, the CLI build is older than the service launch — tell the customer that rather than substituting a CloudWatch or X-Ray command.
- **`aws cloudwatch <omni-operation>` will always fail**, at any version. Omni is a distinct service that shares only the `cloudwatch` signing name, so CloudWatch and X-Ray clients cannot reach Spaces, Omni alerts, views, dashboards, or Omni SQL. They are not a substitute, and must never be offered as one.

Any SDK or CLI that carries the `cloudwatchomni` model signs and encodes the request per section 1; there is no library-free path, because the `rpcv2Cbor` protocol needs the model to encode the body.

**Do not invent operation names, CLI subcommands, or SDK method names.** Naming the service is enough to answer "can I use the CLI or an SDK" — the operations themselves live in the per-resource references this file points to ([alerts.md](alerts.md), [views.md](query/views.md), [dashboards.md](dashboards.md), [sql-logs-traces.md](query/sql-logs-traces.md)). A fabricated subcommand or method that does not exist is worse than telling the reader where to look it up, because it fails at the point the reader trusts it most. When an example would help, show the SDK/CLI call shape from section 1 (SigV4 + `rpcv2Cbor` via the `cloudwatchomni` model) with the operation left as a placeholder rather than guessing a real one.

## 3. Infrastructure as Code

Omni resources can be declared with **AWS CloudFormation**, and therefore through CDK over the same resource types.

Consult the CloudFormation resource-type reference for the exact type names and their properties rather than guessing them — a type name assembled from a resource's display name will not resolve. Where a needed resource has no type, the API in section 1 driven from a script or a custom resource covers the gap.

**Terraform.** CloudFormation and CDK are the documented infrastructure-as-code paths; Terraform is not one of them. Say so plainly when asked, rather than either claiming Terraform support or refusing to address it — the question is a fair one and the honest answer is short. A team that needs Terraform can reach Omni the same way they reach any resource their provider does not model: drive the API from an external data source or a provisioner. Present that as a workaround, never as documented support.

## 4. AI Coding Agents

Omni is usable from an AI coding agent through the **Agent Toolkit for AWS**, which distributes **agent skills** — structured, progressive-disclosure knowledge files like this one — that a coding agent loads to work with a product. Omni's skills are published there, so an agent that has them installed can operate Omni without the user having to explain the product to it first.

The same skills back the in-product Omni agent. Customers can also author their own skills for their Space, so an agent in their environment follows their runbooks and conventions rather than only the built-in guidance — that is the supported way to extend what an agent knows about a Space.

## 5. What NOT to Say

These are the specific wrong answers this reference exists to prevent:

- **Never say Omni has no API, no SDK, no CLI, no endpoint, or no programmatic access.** All four paths above are supported. This is the most damaging error available here, because it tells a customer a supported capability does not exist.
- **Never answer an Omni programmatic question with the CloudWatch or X-Ray CLI or SDK.** Those are different services and cannot reach Omni resources, at any client version.
- **Never treat a failed `aws cloudwatchomni` call as proof the API does not exist, or that Omni is not enabled.** An unsupported-service error means the local client predates Omni's service model — the fix is a client upgrade, and the call never reached AWS.
- **Never invent** an endpoint hostname, a service or signing name, an SDK client name, an operation name, or a CloudFormation type name. Say the path exists, then point at the reference that carries the exact identifiers. A plausible-looking name that does not resolve is worse than sending the reader to look it up.
