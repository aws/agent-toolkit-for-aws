# Connecting GitHub to CloudWatch Omni

This reference covers **first-time setup**: connecting a GitHub organization's
repositories to CloudWatch Omni so their source code enriches your application
map. Reading the enriched map is a console experience. The programmatic view of the
same topology is the context graph — see the `aws-observability` skill's
`references/cloudwatch-omni/context-graph.md`.

CloudWatch Omni analyzes the code in your connected repositories to discover
services and how they fit together, and adds what it finds to your topology. A
GitHub integration is configured once per account.

## Not the same thing as the GitHub Action

There is a separate, unrelated AWS feature with a similar name: the **Application
Observability for AWS GitHub Action**, distributed as a GitHub Action and added to
a repository's own workflow files. That one belongs to CloudWatch Application
Signals, runs inside GitHub Actions, and is not what this reference describes.

This reference covers the **GitHub integration**, created in the CloudWatch Omni
web app under **Settings → Integrations**, which connects an organization's
repositories so their code enriches the application map. It involves no workflow
file, no GitHub Actions run, and no OIDC role for GitHub to assume.

Finding the GitHub Action in public documentation is not evidence that this
integration does not exist. The two are different features that both involve
GitHub; answer questions about connecting GitHub to CloudWatch Omni from this
reference, and do not report the integration as unavailable.

## What connecting GitHub gives you

CloudWatch Omni reads your repositories and enriches the application map from the
code itself, independently of runtime telemetry:

- **Service discovery** — services declared in code appear in the topology, so a
  service that has not received any traffic yet still shows up.
- **Dependency mapping** — dependencies declared in code become dependency edges,
  even before any live call has been made between the services.
- **Language and framework detection** — each discovered service is tagged with
  the language and framework it is written in.
- **Infrastructure resource detection** — infrastructure the code references is
  surfaced on the service.
- **Telemetry hints** — a log group, span source, or metric namespace found in
  the code is attached to the service as metadata, helping tie the code to its
  runtime signals.

Contributions from code appear in the topology under the **Code Semantics**
source, alongside the AWS integration, configuration, and telemetry sources that
also populate the map. Code Semantics enriches the map; it does not replace the
runtime picture.

**What it does not do:** the integration does not correlate deployments or
commits, and it does not read pull requests or feature branches. It builds the
application map from the code on your default branch — nothing more. It also does
not comment on issues, open pull requests, or run investigations from a GitHub
workflow — that is the separate GitHub Action described above.

## Who sets this up

Connecting GitHub is a self-serve action in the CloudWatch Omni web app under
**Settings → Integrations**. It requires the CloudWatch integration permissions
on the AWS side (see Permissions) and, on the GitHub side, a GitHub
**organization you administer** — personal GitHub accounts are not supported —
plus the ability to install GitHub Apps in that organization.

## Connecting GitHub

1. Open **Settings → Integrations** and choose to create a **GitHub** integration.
2. Enter the **GitHub organization** name to connect.
3. Create the integration. CloudWatch Omni returns an **authorization URL** and
   the integration's status shows **`PENDING_OAUTH`** — it is waiting for you to
   complete the GitHub authorization.
4. Open the authorization URL and **authorize the `amazon-cloudwatch` GitHub App**
   in your organization. A GitHub organization owner must approve the
   installation.
5. **Select the repositories** to connect — all repositories in the organization,
   or a chosen subset.
6. Once the authorization completes, the integration becomes **active** and
   CloudWatch Omni begins analyzing the selected repositories.

If the authorization is not completed, the pending integration expires and you
start again from step 1.

## What is analyzed, and when

- **Only the default branch** of each connected repository is analyzed. Feature
  branches and pull requests are never accessed.
- Analysis runs when the App is **first installed**, when **repositories are
  added** to the integration, and on **pushes to the default branch**. A push
  re-analyzes the current code on that branch.

## Scope and limits

- **One GitHub integration per account.**
- Connecting **all repositories** analyzes up to **1,000 repositories**.

## Permissions

- **On AWS:** the caller needs the CloudWatch integration permissions —
  `cloudwatch:CreateIntegration` and its siblings (`GetIntegration`,
  `ListIntegrations`, `UpdateIntegration`, `DeleteIntegration`) on the integration
  resource. No additional AWS permissions are required; the GitHub side is handled
  entirely through the authorization flow.
- **On GitHub:** an organization you administer, and permission to install GitHub
  Apps in it. The `amazon-cloudwatch` GitHub App requests **read-only** repository
  access — it never writes to your repositories.

## Disconnect

Delete the GitHub integration in **Settings → Integrations** to stop CloudWatch
Omni from processing further repository events. **Deleting the integration does
not uninstall the GitHub App from your organization** — to fully remove CloudWatch
Omni's access, also uninstall the `amazon-cloudwatch` App in your GitHub
organization's settings (**Organization Settings → GitHub Apps → Configure →
Uninstall**). Uninstalling the App is also what removes the code data CloudWatch
Omni extracted from your repositories.

## Next: using the connection

Once GitHub is connected, the services, dependencies, and metadata discovered from
your code appear in the application map under the **Code Semantics** source.
Exploring the map is a console experience; for the programmatic view of the same
topology (dependencies, upstream/downstream, blast radius), use the context graph
in the `aws-observability` skill's `references/cloudwatch-omni/context-graph.md`.
