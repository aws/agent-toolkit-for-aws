# Omni Programmatic Access Reference

## Identifiers and rules at a glance

The sections below carry the detail behind each line.

- **Regional endpoint** `cloudwatch-omni.<region>.api.aws`, Region substituted. Never `.amazonaws.com`, and never the bare prefix — neither is a reachable host.
- **CLI / SDK client name** `cloudwatchomni`, no hyphen: `aws cloudwatchomni <operation>`, `boto3.client("cloudwatchomni")`. The hyphenated `cloudwatch-omni` is the endpoint prefix and is not a client name.
- **SigV4 signing name** `cloudwatch` — different from both of the above.
- **Authorization has two caller classes, and an answer gives both.** A grant-mediated caller (Access Profile, IAM Identity Center, console) needs a matching grant on the Space or is denied. A direct IAM caller signing with its own credentials is not denied by the Space when no grant matches — its own IAM policy alone decides — and reaches only Spaces its own account owns.
- **Request members** come from the per-resource reference for that resource, never from inference off an operation name.
- **All four paths exist** — public API, CLI/SDKs, CloudFormation, Agent Toolkit. Name all four when asked broadly how to call Omni, and never answer that Omni has no API, SDK, CLI, or endpoint.

CloudWatch Omni is not console-only. A script, a service, a CI job, an infrastructure-as-code template, or an AI coding agent can all drive it. There are four programmatic paths — the public API, the AWS CLI and SDKs, AWS CloudFormation, and the Agent Toolkit for AWS — and this file covers each, so an answer never wrongly denies that Omni can be used from code. Asked broadly how to call Omni from code, **name all four** before going deep on the one the reader needs: an omitted path reads as a path that does not exist, and dropping CloudFormation sends an IaC team off to write a script.

## 1. The Public API

CloudWatch Omni exposes a standard **SigV4-signed AWS API**. No console session is required. Its service model declares **Smithy RPC v2 CBOR** (`rpcv2Cbor`) — a POST to `/service/CloudWatchOmniFrontend/operation/<Op>` carrying a CBOR body — and the generated SDK/CLI projection additionally declares AWS JSON 1.0, which dispatches on an `X-Amz-Target: CloudWatchOmniFrontend.<Op>` header. Which of the two a given endpoint accepts is a service-team question, not something to assert from the model, so the answer to "how do I call it" is to **use an AWS SDK or the CLI carrying the `cloudwatchomni` model**: it selects and encodes the protocol for you.

| Property | Value |
|---|---|
| CLI / SDK service name (the client name) | `cloudwatchomni` — no hyphen |
| Endpoint prefix | `cloudwatch-omni` — hyphenated, and never a client name |
| SigV4 signing name | `cloudwatch` |
| Regional endpoint | `cloudwatch-omni.<region>.api.aws` |
| Protocol | Smithy RPC v2 CBOR (`rpcv2Cbor`); path `/service/CloudWatchOmniFrontend/operation/<Op>` |

Quote the regional endpoint in full, with the caller's Region substituted — the bare prefix is not a reachable host, so an answer that stops at it leaves the caller without an address, and `.amazonaws.com` is the wrong suffix for this service.

The signing name differs from that prefix: requests are signed for `cloudwatch` while being sent to the `cloudwatch-omni` host. An SDK/CLI with the model sets this for you; a client that derives the signing name from the hostname gets it wrong.

**A caller who does not want the SDK gets a real answer, not a redirect back to it.** Signing a request directly is a legitimate choice — some callers cannot add a dependency, and the API is a standard SigV4 API — so answer the question that was asked: give the signing name, the host, the protocol shapes above, and the operation's members from its per-resource reference. Then state the trade-off plainly, once, so the choice is informed rather than steered: the caller takes on encoding the body for each operation they add, and on whichever of the two declared protocols their endpoint accepts, both of which an SDK or the CLI handles from the model. If they want the lower-effort path after hearing that, it is the SDK; if they still want to sign it themselves, help them do it correctly. Repeating the recommendation after they have declined it is not an answer.

**An operation's request members come from its per-resource reference, never from inference off the operation name.** Asked what body a given operation takes — usually by a reader who wants to call Omni from `requests` or `curl` rather than add an SDK — give the signing name, the host, and the declared protocol shapes above, then the members from the reference that documents them. Members those references do document can be named: [alerts.md](alerts.md), for instance, carries `ListAlerts`'s required `spaceId` and the fields of its `AlertFilterCriteria`. A member that appears in none of them is an invention, arriving at the exact point the reader pastes it into a client and trusts it. Omni is also not a REST/JSON service with per-operation URL paths and bodies — that shape is wrong for both declared protocols.

### Authorization — state this on every programmatic answer

A programmatic caller is authorized by **two layers**: the caller's IAM policy, and the Space's access grants. Which one decides depends on the caller's class, and an answer gives both classes — which one the reader is in determines whether a grant is something they must go and obtain.

| Caller class | Who | What decides access, and what a denial means |
|---|---|---|
| **Grant-mediated** | A workload that has assumed an Access Profile; a person through IAM Identity Center or the console | A matching grant on the Space is **required**: with none, the Space denies the call whatever IAM allows. A denial means no grant matches it, so broadening IAM changes nothing |
| **Direct IAM** | A principal signing the API with its own credentials: CI role, SDK client, CloudFormation deployment role, coding agent | A grant is **optional**: a matching grant is enforced (row and column scopes apply, an explicit deny wins), but with none **the Space raises no denial of its own** and the caller's **IAM policy alone decides**, with no row restriction. A denial means its IAM policy lacks the action — or the Space belongs to another account (rule 2) |

Two independent rules govern a direct IAM caller, and they answer different questions:

1. **A grant is optional for it, not required** — the fallthrough in the table above. This is the reverse of the grant-mediated case, where a missing grant *is* the denial.
2. **Its reach stops at its own account's Spaces.** Another account's Space is out of reach no matter how broad its IAM policy is. That is a reachability limit, not a grant decision, and it never replaces rule 1 in an explanation — give both.

Explaining a denial means saying which layer denied it, and naming what authorized the calls that **did** work: for a direct caller holding no grant, that was rule 1 — its own IAM policy, not a grant. Put it in words ("no grant names that role, so the Space denied nothing; its own IAM policy decided"), because an answer that shows only the rule's consequences reads identically to one where grants were required all along. Establish the layer **before changing either one**: `AccessDenied` comes from both, so read the IAM policy on the calling role — whether it allows the specific `cloudwatch:<Operation>` actions this call needs, on the Omni resources it targets — *and* check whether any grant names the caller. Check for the actions the call actually makes; a policy written as `cloudwatch:*` is not the shape to recommend, and reading it as the expected one hides that the missing action may be a single operation. Two denials of the same principal are usually two different causes: the same role can be inside its rights on a Space its account owns, out of reach on another account's, and separately ungranted under an Access Profile. Attribute each denial to the layer that produced it, because a single shared explanation sends the reader to change the wrong one. Full detail is in the `setting-up-cloudwatch-observability` skill's `references/cloudwatch-omni/access-grants.md`.

**Operations** are grouped by the same resources documented elsewhere in this skill — read those files rather than guessing an operation name:

| Resource | Reference |
|---|---|
| Alerts | [alerts.md](alerts.md) |
| Views | [views.md](query/views.md) |
| Dashboards | [dashboards.md](dashboards.md) |
| Log and trace queries | [sql-logs-traces.md](query/sql-logs-traces.md) — the three operations that execute a statement are in its [Running a Query](query/sql-logs-traces.md#0-running-a-query) section |

## 2. AWS CLI and AWS SDKs

CloudWatch Omni is supported by the **AWS CLI** and the **AWS SDKs**, under the `cloudwatchomni` service name: `aws cloudwatchomni <operation>`, and the corresponding client in each SDK — `boto3.client("cloudwatchomni")` and its equivalent elsewhere.

**The client name has no hyphen.** `cloudwatchomni` is the CLI and SDK service name; `cloudwatch-omni` is the endpoint prefix from section 1 and is not a client name. A hyphenated `boto3.client("cloudwatch-omni")` (or `aws cloudwatch-omni`) raises an unknown-service error even on a client new enough to carry the model, which then reads as the version problem below when it is only a misspelling. Every SDK example starts from this client:

```python
import boto3

client = boto3.client("cloudwatchomni", region_name="us-east-1")  # cloudwatchomni, not cloudwatch-omni
```

Two things to know when a call does not work:

- **`aws cloudwatchomni …` reporting that the service is not supported means the local CLI predates Omni's service model.** The AWS CLI and each SDK ship a snapshot of service models, so a version older than Omni's release has no `cloudwatchomni` client. This is a client-version issue and says nothing about whether Omni is enabled on the account — the failure happens during argument parsing, before any request is sent. Upgrade to a version that carries it:
  - **AWS CLI v2** — check `aws --version`, then reinstall/upgrade per <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>: macOS `brew upgrade awscli` or the `.pkg` installer; Linux re-run the zip installer with `--update`; Windows the MSI.
  - **boto3** — `pip install -U boto3 botocore`.
  - **Other SDKs** — upgrade to the latest release.

  Give the customer that command; do **not** run `brew`, `pip install -U`, or an installer on the host yourself — a package-manager upgrade mutates their machine beyond the request (a Homebrew upgrade, for example, can replace the system Python other tools depend on). **Nor should you confirm the diagnosis by running the command in your own shell.** The client that failed is on the customer's machine and yours is a different installation, so `aws cloudwatchomni list-domains` succeeding for you proves nothing about theirs and does not mean the problem is solved; reporting it as fixed or verified, or pasting your own output as evidence, hands them a false resolution. Have them re-run `aws cloudwatchomni list-domains` after upgrading. If the command is still unknown then, the CLI build is older than the service launch — tell the customer that rather than substituting a CloudWatch or X-Ray command.
- **`aws cloudwatch <omni-operation>` will always fail**, at any version. Omni is a distinct service that shares only the `cloudwatch` signing name, so CloudWatch and X-Ray clients cannot reach Spaces, Omni alerts, views, dashboards, or Omni SQL. They are not a substitute, and must never be offered as one.

Any SDK or CLI that carries the `cloudwatchomni` model signs and encodes the request per section 1. Hand-rolling instead means reproducing that encoding yourself, and supplying each operation's members from the per-resource reference that documents them — they are written out in those files (see `ListAlerts` in [alerts.md](alerts.md)), but there is no public machine-readable model to generate a client from, so the work is per operation and by hand.

**Do not invent operation names, CLI subcommands, or SDK method names.** Naming the service is enough to answer "can I use the CLI or an SDK" — the operations themselves live in the per-resource references this file points to ([alerts.md](alerts.md), [views.md](query/views.md), [dashboards.md](dashboards.md), [sql-logs-traces.md](query/sql-logs-traces.md)). A fabricated subcommand or method that does not exist is worse than telling the reader where to look it up, because it fails at the point the reader trusts it most. When an example would help, show the SDK/CLI call shape from section 1 (SigV4 + `rpcv2Cbor` via the `cloudwatchomni` model) with the operation left as a placeholder rather than guessing a real one.

## 3. Infrastructure as Code

Omni resources can be declared with **AWS CloudFormation**, and therefore through CDK over the same resource types.

Consult the CloudFormation resource-type reference for the exact type names and their properties rather than guessing them — a type name assembled from a resource's display name will not resolve. Where a needed resource has no type, the API in section 1 driven from a script or a custom resource covers the gap.

**Terraform.** CloudFormation and CDK are the documented infrastructure-as-code paths; Terraform is not one of them. Say so plainly when asked, rather than either claiming Terraform support or refusing to address it — the question is a fair one and the honest answer is short. Name the supported path in the same breath: an answer that only reports Terraform as unsupported leaves the reader with nothing. A team that needs Terraform can reach Omni the same way they reach any resource their provider does not model: drive the API from an external data source or a provisioner. Present that as a workaround, never as documented support.

## 4. AI Coding Agents

Omni is usable from an AI coding agent through the **Agent Toolkit for AWS**, which distributes **agent skills** — structured, progressive-disclosure knowledge files like this one — that a coding agent loads to work with a product. Omni's skills are published there, so an agent that has them installed can operate Omni without the user having to explain the product to it first.

The same skills back the in-product Omni agent. Customers can also author their own skills for their Space, so an agent in their environment follows their runbooks and conventions rather than only the built-in guidance — that is the supported way to extend what an agent knows about a Space.

## 5. What NOT to Say

These are the specific wrong answers this reference exists to prevent:

- **Never say Omni has no API, no SDK, no CLI, no endpoint, or no programmatic access.** All four paths above are supported. This is the most damaging error available here, because it tells a customer a supported capability does not exist.
- **Never answer an Omni programmatic question with the CloudWatch or X-Ray CLI or SDK.** Those are different services and cannot reach Omni resources, at any client version.
- **Never treat a failed `aws cloudwatchomni` call as proof the API does not exist, or that Omni is not enabled.** An unsupported-service error means the local client predates Omni's service model — the fix is a client upgrade, and the call never reached AWS.
- **Never invent** an endpoint hostname, a service or signing name, an SDK client name, an operation name, or a CloudFormation type name. Say the path exists, then point at the reference that carries the exact identifiers. A plausible-looking name that does not resolve is worse than sending the reader to look it up.
