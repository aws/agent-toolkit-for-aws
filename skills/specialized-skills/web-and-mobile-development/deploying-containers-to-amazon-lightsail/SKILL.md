---
name: deploying-containers-to-amazon-lightsail
description: >
  Deploys, hosts, or runs a container or Docker app on Amazon Lightsail Container Service and returns a live,
  managed HTTPS URL at a flat monthly price — no cluster, VPC, load balancer, or registry to set up. Used when
  deploying a container image to Lightsail from a local Docker build, a public registry image, or a GitHub repo,
  or when a Lightsail container deployment fails or won't serve — including when the request doesn't name
  Lightsail but asks to run one always-on container behind a public URL at a flat, predictable monthly price.
  Not for running an app on a Lightsail instance (VM) or Amazon EC2 instead of the container service, and not
  for workloads needing Kubernetes, autoscaling, scale-to-zero, or per-request pricing (use Amazon ECS/EKS or
  ECS Express Mode).
version: 1
---

# Deploying containers to Amazon Lightsail

## Overview

Amazon Lightsail Container Service runs a container image behind a managed, HTTPS URL for a flat monthly price. The
URL, TLS certificate, and load balancing are included — there is no cluster, VPC, load balancer, or registry to set
up.

This skill takes a container image from any source to a live, serving Lightsail deployment, and diagnoses one that
won't serve. Creating the service requires two choices: **`power`**, the memory and vCPUs of each node, and **`scale`**,
how many nodes run, each running a full copy of the deployment. Capacity never changes on its own — there is no
autoscaling and no scale-to-zero — so you raise `power` or `scale` yourself when a service needs more.

## Prerequisites

Before creating anything:

- **Clarify** the image source, the port the app listens on, and the region.
- **Discover options at runtime** — the available powers and regions — instead of hardcoding them.
- **Confirm the plan and price.** State the flat monthly price (power × scale, charged even with no traffic) and confirm
  before creating billable resources — unless the user has already told you to proceed. Never create them silently. See
  the Pricing section below for where to read the figures.
- **Fixed caps aren't adjustable.** The nodes-per-service cap is the ceiling on `scale`; containers per deployment and
  deployment versions are capped too. Read the values in
  [Lightsail quotas](https://docs.aws.amazon.com/general/latest/gr/lightsail.html) rather than offering an increase.
  An account's actual quota may be lower than the published default if the account was recently created or is used
  minimally.
- **Permissions.** The calling identity needs the Lightsail actions in the Operations table below; a missing one
  surfaces as an access-denied error on the first call, not as a tooling or quota problem. See the Security
  considerations section below for scoping them.

Tools: the **AWS CLI** (v2) is all a public-registry-image deploy needs — and its operations run either through
the AWS MCP tools (preferred, see below) or the CLI directly. A local build or push also needs `docker` (running)
and — for the `push-container-image` shortcut — the `lightsailctl` plugin (the plugin-free push uses `docker` +
`register-container-image` instead).

Running AWS operations: prefer the AWS MCP execution tool **`aws___run_script`** when it is available, and keep each
call **short** — one operation that returns right away, not a long-running one (a call still running after ~30
seconds is cut off and drops the session). It isn't required: the same operations run through the local **`aws` CLI**,
which is the fallback when no MCP tool is available. Note the build and push of a **local** image are
Docker/`lightsailctl` operations that run on your machine, never through the MCP tools.

Installing `lightsailctl`: needed only for the `push-container-image` shortcut, and it needs AWS CLI v2 plus a
running Docker:

- **macOS:** `brew install aws/tap/lightsailctl`
- **Linux:** `curl "https://s3.us-west-2.amazonaws.com/lightsailctl/latest/linux-amd64/lightsailctl" -o /usr/local/bin/lightsailctl && chmod +x /usr/local/bin/lightsailctl`
- **Windows:** download `https://s3.us-west-2.amazonaws.com/lightsailctl/latest/windows-amd64/lightsailctl.exe` and add it to `PATH`.

If an install is blocked or the plugin still isn't found, see the troubleshooting reference — or skip the plugin
entirely with the plugin-free push in [references/local-image.md](references/local-image.md).

## References

The step-by-step detail lives in reference files bundled with this skill. **You MUST read the reference matching your
image source, or the step you're about to do, before doing it** — each carries the exact sequence and requirements
(ports, image architecture, push method) that are easy to get wrong.

To open one: on the AWS MCP server, retrieve it with the skill's content-retrieval tool; otherwise read it from this
skill's own directory (its location was shown to you when the skill loaded), e.g. `<skill-dir>/references/NAME.md`.
**DON'T read from a bare `references/NAME.md`** — it resolves against your working directory, not the skill, and
fails with "No files found"; if you hit that, prepend the skill directory and retry.

- [references/public-image.md](references/public-image.md) — a public registry image (no build, no push).
- [references/local-image.md](references/local-image.md) — build a local image and push it into the service's
  registry (`docker`; `push-container-image` or the plugin-free sequence).
- [references/github-source.md](references/github-source.md) — clone and build from a GitHub repo, then follow the
  local-image path.
- [references/deployment.md](references/deployment.md) — the deployment shape (`containers` + `publicEndpoint` + health
  check), how to poll to `ACTIVE`, roll back, and tear down.
- [references/troubleshooting.md](references/troubleshooting.md) — `lightsailctl` not found, a `FAILED` deployment,
  502/503, and `exec format error` (a CPU-architecture mismatch).

## Service, deployment, containers

- **Container service** — the long-lived resource you create first. It owns the capacity (`power` × `scale`), the
  public HTTPS URL, the private domain, and its own image registry. Billing runs from creation to deletion.
- **Deployment** — an immutable, versioned spec of what to run on that service. One is active at a time, and creating
  another replaces the spec entirely.
- **Containers** — entries inside a deployment (the per-deployment cap is in the Lightsail quotas linked above).
  Each has a name, an image, and ports; exactly one can be
  the public endpoint and the rest are reachable only by their siblings, over `localhost`.

## Pricing

Price is set by capacity under a transfer quota. The monthly cost is the power's price × the scale, charged from
creation until deletion whether or not any requests arrive. Each service includes one monthly data-transfer quota —
the quota does not change regardless of the power and scale that you choose for your service — and egress above it is
charged per GB at a rate that varies by Region. Inbound counts toward the quota but isn't charged when exceeded.

State a price only if you have just read it from one of the sources below — never from memory, and never a placeholder
such as `$0.00` for a rate you did not look up. Capacity cost is exact (power price × scale). Egress cost is not,
because it depends on traffic you cannot know, so give the per-GB rate rather than a total.

- **Power prices** — `get-container-service-powers` is the single source. It returns each power's monthly price per
  node, so quote that figure directly.
- **Transfer quota** — the `dataTransferQuota` attribute on `Lightsail Containers` records, from the AWS Price List
  operation `get-products` with service code `AmazonLightsail`.
- **Egress rate** — a separate `get-products` record, found with a `TERM_MATCH` filter on `overageType` =
  `ContainerSvc:Data Transfer`. Use `overageType`, not `productFamily`: `Lightsail Networking` also holds CDN, bucket,
  instance, and DNS overages. Narrow by `fromRegionCode`, not `regionCode`, since these records name the location they
  transfer out of.

## Workflow

1. **Create the service** with a chosen power and scale; poll `get-container-services` until its `state` is `READY`.
   `get-container-service-powers` returns each power's `name` (`nano`) and its `powerId` (`nano-1`) — when you create
   the service, pass the **`name`** to `--power`.
2. **Get the image in** — the one source-specific step; follow the matching reference above.
3. **Deploy** a version (its `containers` plus one `publicEndpoint` with a health check), then poll the deployment to
   `ACTIVE` — see the deployment reference.
4. **Verify and report** — only once the deployment is `ACTIVE`, read the generated URL from the service (it has a
   random id — read it, don't construct it), confirm it responds, and report the URL, the monthly price, and the
   teardown command.

**Polling:** create and deploy return immediately and finish asynchronously — expect ~5–10 min end to end, and a
still-`PENDING`/`ACTIVATING` state is normal. Poll by **repeating a short status check with a brief pause between
calls** — each check is its own quick call that returns right away, with a short `sleep` in between. Don't do the
waiting inside one long-running call (a loop inside a single `run_script`, or a long `shell` loop) — that's what
trips the execution timeouts (a single call still running after ~30 seconds can be cut off and drop the session).
Return the URL only once the deployment is `ACTIVE`.

## Do / Don't

| ✅ Do                                                                                 | ❌ Don't |
|---------------------------------------------------------------------------------------| --- |
| Confirm the monthly price before creating (unless told to proceed)                    | Create billable resources silently |
| Discover powers, regions, prices, and image versions from the API                     | Hardcode power, scale, region, prices, or an image version |
| Read the image-source reference before the image step                                 | Guess the build/push sequence |
| Poll with repeated short calls + a `sleep` between; return the URL only once `ACTIVE` | Wait inside one long-running call (a `run_script` loop or a long `shell` loop); return the URL early |
| For a public image, skip the build and push entirely                                  | Require a local build when a registry image already exists |
| Read `get-container-log` to diagnose a failure                                        | Rebuild or redeploy blindly on a 502 or a `FAILED` deployment |
| Recommend ECS/EKS or ECS Express Mode for microservices/autoscaling                   | Present Lightsail as the answer to every container question |
| Always give the teardown command                                                      | Leave the user unable to stop charges |

## Operations

| Operation (`aws lightsail …`) | Purpose | Note |
| --- | --- | --- |
| `get-container-service-powers` | list the available powers with their specs and prices | read these instead of quoting remembered sizes or prices |
| `create-container-service` | create the service | flat price = power × scale |
| `update-container-service` | change capacity (power/scale) on a running service | re-deploys the current deployment automatically, with no downtime and keeps the same deployment version |
| `get-container-services` | check state | `READY` before deploying; `RUNNING` after a deployment is active |
| `push-container-image` | push a local image | needs the `lightsailctl` plugin and a running local Docker |
| `create-container-service-registry-login` | get temporary registry credentials | first step of the plugin-free push |
| `register-container-image` | register an already-pushed image by digest | the plugin-free alternative to `push-container-image` |
| `get-container-images` | list the image versions in the service's registry | Lightsail assigns the version numbers - read them here rather than assuming them |
| `create-container-service-deployment` | deploy an image | `containers{}` + `publicEndpoint{containerName, containerPort, healthCheck}` |
| `get-container-service-deployments` | deployment state and history | `ACTIVATING → ACTIVE`; roll back by redeploying a prior version |
| `get-container-log` | read container logs | first stop for diagnosing a failed deployment; don't log secrets or customer data |
| `delete-container-service` | tear down | stops charges |

## Security considerations

- **Least-privilege IAM** — scope the calling principal to the `lightsail:` actions this workflow
  actually uses (the Operations table above is the list) rather than `lightsail:*` or an
  administrator policy.
- **Secrets** — `environment` values are stored in the deployment spec and readable through
  `get-container-service-deployments`, and there is no separate secret-injection mechanism, so a credential
  the container needs has to go there; pass only what it needs. When a value is credential-shaped — a
  password, token, API key, or connection string — you MUST warn the user before deploying and leave the
  choice to them; one option is an application that decrypts the value itself, so the deployment spec holds
  ciphertext and the key ships in the image instead. NEVER print or log those values, or the
  `get-container-service-deployments` response that carries them, back to the user or into any artifact.
- **Public surface** — the endpoint is HTTPS-only with an AWS-managed certificate, Shield Standard
  covers common network-layer DDoS automatically, and only the container named in `publicEndpoint` is
  internet-reachable. There is no request throttling or WAF for a container service, and Lightsail does not
  inject security headers, so input validation, rate limiting, and CSP / HSTS / X-Content-Type-Options /
  X-Frame-Options are all the application's responsibility.
- **Private network reach** — a container has unfiltered network access to your other Lightsail resources in
  the same account and Region, and no Lightsail firewall rule narrows it. Where VPC peering is active for the
  Region, the same access extends to your own VPC. The image is therefore the only control, so you MUST warn
  the user before deploying an image they did not build.
- **Auditing** — CloudTrail records all Lightsail API calls; Event history is on by default, and a trail
  gives continuous delivery to S3.

## Troubleshooting

If anything goes wrong — a deployment fails, or the URL won't serve — read
[references/troubleshooting.md](references/troubleshooting.md); start by reading the container log to the root cause.
