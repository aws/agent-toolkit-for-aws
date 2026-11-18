# Ingesting telemetry your Azure resources emit (CloudWatch Connector)

This is the path for the telemetry **Azure resources emit on their own** — resource and
platform diagnostic logs and metrics, and VNet flow logs. It is a different mechanism from the
customer's own
application telemetry: no CloudWatch agent is involved. Trust between the Azure tenant and
the AWS account is held by a **CloudWatch Connector**, a **telemetry manifest** captures
which resources the customer wants telemetry from, and a **pipeline** reads from the Azure
infrastructure the setup creates and writes into a log group in the customer's account.

For the customer's own application logs, metrics, and traces from an Azure VM or AKS
cluster, this is the wrong file — use `custom-telemetry.md`.

Azure **Activity logs** are not part of this path. They are collected through the AWS Config
connector and are not written to CloudWatch Logs or queryable in a Space, so do not list
them among the telemetry types this pipeline delivers.

That **AWS Config connector is created only when topology or resource-tags enrichment is
enabled** for the connection — it is not part of a plain telemetry setup. So do not describe
it as something every customer gets, and do not reach for it to explain a telemetry-delivery
problem on a connection where neither feature is on.

## The operations, and what runs where

The pipeline and enrichment steps are AWS Observability Admin operations the customer can run
from the AWS CLI. Check the exact parameter names with `aws observabilityadmin <command> help`
before composing a command — give the customer the command form, not an invented flag list:

```bash
# Start ingestion. Configuration.Body is an opaque document naming the connector and writer role.
aws observabilityadmin create-telemetry-pipeline --name <name> --configuration <body>

# Inspect and change it
aws observabilityadmin get-telemetry-pipeline --pipeline-identifier <arn-or-name>
aws observabilityadmin list-telemetry-pipelines
aws observabilityadmin update-telemetry-pipeline --pipeline-identifier <arn> ...
aws observabilityadmin delete-telemetry-pipeline --pipeline-identifier <arn>

# Check a configuration or the pipeline itself before trusting it
aws observabilityadmin validate-telemetry-pipeline-configuration ...
aws observabilityadmin test-telemetry-pipeline ...

# Resource tags and topology — ONLY for changing them later. They are chosen in step 1,
# with the connection script; do not present these as the way to turn them on.
aws observabilityadmin get-telemetry-enrichment-status
aws observabilityadmin start-telemetry-enrichment ...   # re-enable after a stop
aws observabilityadmin stop-telemetry-enrichment ...
```

`delete-telemetry-pipeline` accepts only the pipeline **ARN**, not its name; a name returns a
bare authorization error that reads like an IAM problem but is identifier resolution. Reads
accept either form.

**The pipeline and enrichment operations are driveable from the CLI**, under
`aws observabilityadmin`, so guide the customer through those rather than sending them
elsewhere. **The Azure deployment artifact is the exception**: it is generated from the
customer's own manifest, so it comes from the generated setup scripts and the flow that
produces them — pointing the customer there is the correct answer, not a fallback. See
"Asked for the Bicep or `az` commands" below.

**Never assert that an operation does not exist.** Availability moves with the installed CLI,
so confirm against the customer's own before claiming anything about it:

```bash
aws observabilityadmin help                 # is the operation listed?
aws observabilityadmin <operation> help     # what does it take?
```

If an operation is missing there, the customer's CLI is behind — tell them to upgrade, rather
than telling them the capability is absent or routing them to the console as though no API
existed.

| Step | How |
|---|---|
| Create the tenant trust | `create-connector` — needs the Azure-returned tenant and client IDs plus the connector role ARN |
| See what is collectable | `list-resources-by-connector` — enumerates subscriptions, resource types, Regions |
| Record the collection intent | The connector telemetry-manifest operations |
| Get the generated Azure setup | The generated-setup retrieval, which returns the deployment artifact for that manifest |
| Start ingestion | `create-telemetry-pipeline` |
| Apply a later manifest change | The pipeline refresh |
| Resource tags / topology | chosen in step 1, with the connection script — not a separate step. `get-telemetry-enrichment-status` reads it; `start-`/`stop-telemetry-enrichment` change it afterwards |
| Verify the pipeline | `get-telemetry-pipeline`, `test-telemetry-pipeline` |

Confirm the exact operation name and its parameters with `help` as above before you put one in
front of a customer; do not reconstruct a full command line from this table alone.

**Do not run setup the customer did not ask for, and never report having run something you
did not.** Beyond that the two halves differ, and the difference is a capability one rather
than a prohibition:

- **The AWS side** — the trust step, `create-connector`, the manifest write,
  `create-telemetry-pipeline` — runs in the customer's own account with credentials the agent
  may already hold. If the customer asks for it to be run, confirm what will be created and
  then run it; do not refuse work they explicitly requested. Default to guiding rather than
  acting when they have only asked how it works.
- **The Azure side** cannot be run for them: it needs a session in the tenant with authority
  to create applications and assign roles at the **tenant root management group**. Say so as
  the reason, and hand over their generated artifact to run there.

An advisory ask ("what would I need to change?") is answered, not applied.

**Asked for the Bicep or `az` commands, the reason to give is that the artifact is generated
per-manifest — not that tooling is missing.** The Azure deployment artifact is generated from
the customer's **own** telemetry manifest, so which resources it creates depends on the
subscriptions, resource types, telemetry types and Regions *they* selected. There is no fixed command
sequence that is correct for every customer, and one reconstructed from another tenant's setup
will not match theirs.

**That is a reason not to invent the commands, not a reason to withhold them.** Once the
customer has a connector and a manifest, their real artifact can be fetched: the
generated-setup retrieval in the operations table above returns the deployment artifact for
that manifest, along with the permissions needed to apply it. So when a customer asks for the
exact commands, **retrieve their artifact and give them that**, rather than redirecting them.
Fall back to the console flow that generates it only when the retrieval is unavailable — no
connector or manifest exists yet, or the customer's CLI does not carry the operation. Treat
reconstructing the commands and withholding them as two different mistakes: never do the
first, and do not do the second when the artifact is one call away.

Do not explain any of this as an AWS tooling or CLI limitation — that is both wrong and
unhelpful, since the artifact would still be customer-specific even with a complete CLI.

Generated names — resource group, Event Hub namespace and hub names, SAS rule names, policy
and policy-assignment names, custom role names — are lookups from that same generated
artifact, for the same reason. Do not hand-write them, reconstruct them from another
customer's setup, or offer a hedged guess.

## Point to the official documentation — do not generate the setup commands

Do not hand-write the trust, identity, or Azure deployment steps for the customer. They are
long, generated per account and manifest, and maintained upstream; a reconstructed version
drifts from the real thing and is wrong in a way a link never is. Direct the customer to the
authoritative source:

- **Azure platform telemetry** — the authoritative guide for this path:
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/omni-send-platform-telemetry-from-microsoft-azure.html

  This page is the platform-telemetry setup only. The CloudWatch agent on **Azure VM** or
  **Azure AKS** is the other Azure path — it collects the customer's own application OTLP,
  not what resources emit — and lives on a separate page. Sending a platform-telemetry
  customer there is the common wrong turn.
- **The generated setup scripts are the authoritative source for the commands.** They are
  produced from the customer's own manifest, so they describe their deployment exactly; describe
  what each one creates, as below, and hand them the scripts rather than a reconstruction.

Give the customer that source, say which script belongs in which shell, and offer to help
verify once data is flowing. If they ask for the exact commands, fetch their generated
artifact and hand them that — never reproduce one from memory, and do not redirect them to a
guide when their own artifact is retrievable.

**Two scripts, two shells, in this order.** The **AWS trust** script runs where the customer
has IAM write access (AWS CloudShell works) and prints the issuer URL and the connector role
ARN. The **Azure deployment** script runs in a session signed in to the tenant, with authority
to assign roles at the tenant root management group (Azure Cloud Shell works), and returns the
tenant id and application client ids. AWS first, because the Azure step consumes what it
prints; the connector is created last, from what Azure returns.

**Both are safe to re-run.** The AWS trust step merges into an existing role's trust policy
rather than replacing it, so other statements survive. If a customer is unsure a step
finished, re-running it is a fine answer — reconstructing it by hand is not.

**You can explain and check the AWS half without running it**, because it uses only public
CLI calls:

```bash
aws iam get-outbound-web-identity-federation-info
aws iam get-role --role-name <connector-role-name>
aws iam list-role-policies --role-name <connector-role-name>
```

The role must trust **both** the Observability Admin and the telemetry pipeline service
principals, and its inline policy grants `sts:GetWebIdentityToken` limited to the Azure AD
token-exchange audience. Read the exact principal and audience strings from the generated
script or the role itself — they vary by Region and partition, so reciting them is a
doc-lookup you will get wrong.

### What each step actually creates

Name the resources, not just the step. A customer approving a tenant-wide change wants to know
what will exist afterwards:

1. **Establish the connection.** Enables **outbound web-identity federation** on the account;
   creates or updates the **connector (source) IAM role** with the two service-principal trust
   statements and the token-exchange inline policy; creates the **Entra application and
   federated credential** in the tenant; and creates the **connector** itself. If topology or
   resource-tags enrichment is wanted, it is selected here, and that adds the **AWS Config
   connector** and a **second Entra application** that reads resource configuration.
2. **Define the scope (the telemetry manifest).** The manifest is what the customer chooses,
   and the manifest API's selection criteria are the vocabulary: which **subscriptions**
   (all readable, or a named list), which **resource types**, which **telemetry types**, which
   **Azure Regions**, and optional **tag filters**; specific **resource IDs** can be named
   instead of a type when the scope is narrow. Separately from what is collected, the manifest
   names the **infrastructure subscription** — the subscription the Event Hubs and flow-log
   storage accounts are created in. That one is part of the immutable infrastructure block, so
   it is chosen deliberately rather than changed later.
3. **Deploy the Azure resources.** Creates, per in-scope Region, an **Event Hub namespace and
   hub**, a **storage account and Event Grid subscription** where VNet flow logs are in scope,
   a **policy assignment** with the **custom roles** its managed identity needs, and the
   **diagnostic settings** the policy applies to in-scope resources.
4. **Create the destination log group, set its retention, then create the telemetry pipeline —
   in that order.** All three are AWS-side, and the order is load-bearing:

   - **The log group must exist before the pipeline is created; creating the pipeline does not
     create it.** A pipeline only materialises its log group when telemetry **first arrives**,
     which may be long after setup or never, so nothing downstream can assume it is there.
     Create it explicitly — the caller needs `logs:CreateLogGroup`, and a denial on that
     permission is a setup failure attributable to the log group, not to the pipeline.
   - **Then set retention on it.** Retention is unbounded unless set, so treat setting it as
     part of this step rather than an afterthought. Writing retention against a group that does
     not exist yet fails with `ResourceNotFoundException` — which is the symptom of doing this
     before the create above, not of a broken pipeline.
   - **Then create the pipeline**, which also needs the **writer role** it assumes. That role's
     policy must grant writes to *this* log group: the generated writer-role script is written
     for the log group name in use, so changing the name invalidates a script already run, and a
     role that does not grant the destination surfaces as a failure from the pipeline create
     after the group and retention are already in place.

   The log group name travels inside the pipeline's configuration body, so it is chosen before
   the create, not after. Check whether **Transaction Search** is enabled in the Region; if it
   is, the setup also needs an **X-Ray resource policy** (`PutResourcePolicy`) so traces can be
   written.

## `AccessDenied` has more than one cause — diagnose before concluding

An `AccessDeniedException` from a connector, manifest, or pipeline operation is **not** a
single diagnosis. Read the error and the operation before telling the customer what it means:

- **Authorization on the operation.** The caller may simply lack the IAM permission for that
  Observability Admin action, or `iam:PassRole` on the role ARN being passed.
- **The connector role's trust policy.** Connector creation fails with `AccessDenied` when the
  connector role does not trust both the **Observability Admin** service principal and the
  **telemetry pipeline (ATP)** service principal. Both statements are required; the
  Observability Admin one carries connector source-account and source-ARN conditions in
  production. The writer role passed to `create-telemetry-pipeline` must likewise trust the
  telemetry pipeline principal.
- **The role's permission policy.** The connector role needs the outbound web-identity
  token permission it federates with; the writer role needs write access to the log group,
  metric namespace, and traces it targets.
- **Account enablement.** Only after the above are ruled out is "this account is not enabled
  for the path" the answer.

Do not assert feature gating from the exception alone, and do not tell the customer to retry
against another Region, role, or credential in the hope that one works. Check the trust and
permission policies first — that is the common, fixable cause.

## How it works (brief)

**The federation direction is the opposite of the custom-telemetry path, and this is the
common wrong guess.** For the CloudWatch agent, Azure issues an OIDC token and AWS trusts it
(inbound). Here it is **outbound**: AWS mints the token and the Azure tenant trusts the AWS
issuer. Because AWS is the token issuer, the account must have **IAM outbound third-party
federation enabled** — once, before anything else in this path works. State the direction and
that prerequisite together: they are one fact, and an answer that gets the direction right but
omits the prerequisite leaves the customer without the one thing they have to turn on. Nothing
on the Azure side holds an AWS key, and nothing on the AWS side holds an Azure secret — the
tenant identity is an Entra application with a **workload-identity federated credential**, so
there is no client secret to store or rotate.

The tenant setup creates an Entra application for telemetry. **A second Entra application is
created only when topology or resource-tags enrichment is enabled** — it is the identity that
reads Azure resource configuration for those features.

**Off unless the customer turns them on.** Being enabled by default is a property of the
console flow, not of the path, so a customer driving this themselves gets neither feature
unless they ask for it — and therefore one Entra application, not two. Tell them to enable
the features explicitly; do not assume the console's defaults apply to them, and do not
explain a missing second application as a fault.

Enable them in the **first** step, with the tenant trust: a single script establishes the
connection for both connectors, so turning them on afterwards is not the intended sequence.

The telemetry identity is granted read access at the **tenant root management group**. That
grant is what permits AWS to ingest the tenant's vended telemetry at all — it is not merely
so the console can list subscriptions for scope selection.

Keep this trust separate from the Space's own roles. The connector's federated trust is what
authorises **ingestion**; the Space's access grants decide **who can query** the telemetry
once it lands. A question about the connector's trust is not answered with the Space's
grants, and vice versa.

## Order, and why it cannot move

- **The Omni resources come first.** This is the "telemetry in" step of
  Domain → Space → grants → telemetry in, not the beginning. Say what has to exist and route
  to `spaces-and-domains.md` and `access-grants.md` rather than restating those procedures.
  Telemetry started before a Space exists appears to succeed while landing nowhere the
  customer can see, so they read a working, empty Space as a failure.
- **Three phases, and the middle one is Azure's.** AWS first surfaces the two values the
  customer carries into Azure — the IAM role ARN the tenant federates to, and the IAM OIDC
  issuer URL. The Azure identity setup then returns the tenant ID and the application client
  IDs. Only then can the connector be created, because it consumes those IDs. So the customer
  does not need their tenant ID up front, and the connector cannot be created first.
- **Scope before setup.** The artifact is generated from the manifest, so subscriptions,
  resource types, telemetry types, Regions, and any tag filters are chosen before the Azure
  deployment runs — not adjusted afterwards by editing generated files.
- **Creating the pipeline is the first apply.** It performs the initial reconcile itself.
  There is no refresh at onboarding; the pipeline refresh is for a later manifest change.
- **Topology and resource-tags enrichment are chosen in the first step, not enabled afterwards.**
  A single script establishes the connection for both connectors, in the same step as the tenant
  trust, so the customer decides there. If asked "how do I turn these on?", the answer is to
  enable them when establishing the connection — **not** to run an enrichment operation as a
  follow-up step. The enrichment operations exist for changing the choice later (and for
  re-enabling after a stop), which is a different question; do not offer one as the way to get
  the feature in the first place. **Either feature is independent of the pipeline: turning one
  on or off does not touch ingestion**, because they read Azure resource configuration through
  the second Entra application rather than through the telemetry path.

## Changing the scope afterwards

Do not state a flat "this is immutable" rule. The telemetry manifest is rewritable, and
re-reconciling applies the new scope — subscriptions, resource types, telemetry types, Regions, and
tag filters can all change.

A manifest change is applied by **refreshing the telemetry pipeline** — rewriting the manifest
alone does not move telemetry. Say so whenever you describe a scope change, or the customer
edits the scope and reads the unchanged delivery as a bug.

**Reducing or removing a scope needs work in the customer's Azure tenant too.** The AWS side
stops reading, but the Azure resources carry on emitting into the Event Hubs and storage
accounts until the customer turns that off on their side — so a scope reduction that is only
made in the manifest leaves them paying for Azure telemetry nobody collects. Tell them the
Azure-side step is required; the console's update and delete flows give the specific
instructions for their own setup, so route them there rather than composing the steps.

What cannot change is the manifest's **infrastructure block**: the infrastructure subscription the Event
Hubs are created in, and the Event Hub settings (tier and partition count). Treat the storage
account settings the same way unless the customer confirms otherwise. Everything outside that
block is editable, so never tell a customer a scope change is impossible without checking
which layer it belongs to.

## Not yet arriving is not the same as failing

Two things make a correct setup look slow, and both are expected:

- **Role assignments at the tenant root management group take time to propagate** before
  policy remediation can authorise against them. A remediation authorisation failure shortly
  after granting is expected — wait and rerun rather than re-granting.
- **Policy evaluation does not retroactively configure resources that already exist.** The
  diagnostic-settings policy applies to resources as they are created or updated. Bringing
  existing resources in requires running **remediation**, which is submitted asynchronously
  and does not wait for completion.

When telemetry genuinely is not arriving, work through these causes rather than guessing:

1. The pipeline never reached active — check `aws observabilityadmin get-telemetry-pipeline`.
2. **The destination log group was never created.** A pipeline can be active and still deliver
   nothing, because creating it does not create its log group — the group is only materialised
   when telemetry first arrives. A setup driven by hand rather than through the console flow is
   the usual way this happens, so check the group named in the pipeline's configuration exists
   (`aws logs describe-log-groups --log-group-name-prefix <name>`) before looking further.
3. Remediation was not run, so the diagnostic setting was never applied to resources that
   existed before setup.
4. Dataset integration is not enabled for the Space, so records land in the log group but do
   not appear in Omni — check the Space's dataset integration for that Region.
5. The Azure deployment partially failed and some resources were not created.
6. The writer role, or the read/federation role, has the wrong trust or permission policy — for
   the writer role, that includes not granting writes to this pipeline's log group.

## Security considerations for the destination

Everything this path collects lands in **one CloudWatch Logs log group** in the customer's
account, and the telemetry is not low-sensitivity: VNet flow logs carry source and
destination addresses and traffic patterns, and resource diagnostic logs can carry request
parameters. Raise these with the customer rather than waiting to be asked.

- **Encryption in transit.** Telemetry travels to CloudWatch over TLS-protected HTTPS
  endpoints for the whole path, so it is not exposed in the clear between the Azure tenant
  and the destination log group.
- **Encryption at rest.** CloudWatch Logs encrypts the log group under an AWS-owned key by
  default, so this telemetry is never stored unencrypted. A **customer-managed KMS key** is
  the optional control on top of that, and it is what gives the customer their own key policy
  and audit trail over decryption. Whether the setup flow lets them supply or re-key the log
  group is a doc-and-console lookup — do not assert a procedure for attaching a key, and do
  not imply the data is unprotected without one.
- **The destination log group is not the only store in this path.** The same diagnostic data
  and VNet flow logs are staged inside the Azure tenant first — in the **Event Hub namespaces
  and hubs** and the **Storage account** the setup creates — so a security answer that covers
  only the log group has missed two stores holding the same records. Both should have
  **encryption at rest** enabled and traffic to them secured in transit. Azure encrypts both
  at rest by default and a customer-managed key is the optional control on top, the same shape
  as the log group above; the exact settings belong to the generated artifact, so send the
  customer there rather than asserting a configuration. Retention on the Event Hubs is also a
  store of its own: records sit there until the pipeline reads them and the hub's retention
  expires them.
- **One log group is one blast radius.** There is no per-subscription or per-signal
  separation inside it, so whoever can read it can read every in-scope subscription's
  telemetry. **Two independent gates apply**: the Space's access grants govern reading
  through the Space, and the log group's own IAM governs reading it directly in CloudWatch
  Logs. Granting the latter bypasses the former, which is the part customers miss.
- **Retention is unbounded unless set.** A log group keeps data indefinitely by default.
  These telemetry types are high-volume and carry network detail, so an explicit retention period is
  a data-minimisation decision, not only a cost one.
- **The manifest is the real exposure control.** Scoping to named subscriptions, resource
  types, and telemetry types keeps out-of-scope telemetry out of the log group altogether, which is
  stronger than collecting broadly and restricting reads afterwards. Prefer a named
  subscription list over all subscriptions when the customer's goal does not need the whole
  tenant.
- **The Azure-side grant is a tenant-wide read.** The telemetry identity holds read access at
  the tenant root management group. It is read-only, but it is tenant-wide and it is what
  permits ingestion — say so before the customer runs it, not after.

## The Azure side never sends to CloudWatch, so it never needs AWS credentials

**Correct this premise whenever a customer asks how the Azure side will authenticate to
CloudWatch, or says it cannot obtain AWS credentials.** Nothing in Azure pushes to CloudWatch,
so the question does not arise. Say the flow in one line before anything else: **Azure writes
to Event Hubs and Storage inside the customer's own tenant, and the pipeline reads from those
using the connector's federated identity.** That sentence is the answer; an answer that
mentions federation without naming Event Hubs and Storage has not given it. In detail:

1. Azure writes its own telemetry **inside the customer's tenant** — diagnostic settings to
   **Event Hubs**, VNet flow logs to **Storage**.
2. **AWS reads from those**, using the connector's federated identity.

So there is nothing on the Azure side holding or needing an AWS credential, and consequently
no token-based, API-key or shared-key ingestion endpoint — not one that is withheld, one that
does not exist in this architecture. Do not invent one, and do not accept the premise and
start explaining how Azure could authenticate. **Specifically, do not answer this with OIDC or
workload-identity federation.** That is this path's *outbound* federation — what AWS uses to
read **from** the tenant — and it is not a way for the Azure side to obtain AWS credentials.
Offering it as one accepts the false premise instead of correcting it.

**Do not offer the CloudWatch agent as the workaround here.** It is not a fallback for a
credential problem: it ships only the customer's own application telemetry and cannot collect
what Azure resources emit. The reverse also holds — this path does not carry an application's
own OTLP. A customer proposing a mechanism to bridge the gap has not made one exist; correct
the premise and stop.

## Helping the customer verify

Verification is theirs to run; your job is to tell them what to check and what each result
means. Point them at the telemetry rather than the setup output, which can succeed while
records are still minutes away:

- Records arriving in the pipeline's log group, in the right account and Region.
- The telemetry types appearing matching the telemetry types the manifest selected. A declared Region or
  resource type with nothing arriving is the useful finding, and a Region mismatch between the
  manifest and the Azure resources is the common cause.
- The pipeline's own state from `aws observabilityadmin get-telemetry-pipeline`, and
  `test-telemetry-pipeline` for an active check. Space-side visibility is the Space's dataset
  integration for that Region.

Pipeline progress counters are not projected identically across clients, so an absent progress
field is a client-model gap and **not** evidence the pipeline is broken — do not diagnose from
its absence.
