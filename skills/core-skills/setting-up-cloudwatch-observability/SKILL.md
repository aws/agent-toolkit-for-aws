---
name: setting-up-cloudwatch-observability
description: >-
  Sets up CloudWatch Application Observability (also called Omni) for the first time. Covers creating
  an Omni Space or Domain; configuring Omni access grants and access profiles; provisioning an Omni
  ingestion endpoint; wiring an application (Python, Node.js, Java, .NET on EC2, ECS, EKS, or Lambda)
  or an AI agent with the ADOT SDK so its OpenTelemetry traces reach an Omni endpoint — CloudWatch
  Omni instrumentation ONLY; NOT Application Signals auto-instrumentation, NOT X-Ray, NOT a CloudWatch
  Agent add-on — including no-image-rebuild instrumentation and CoreCLR profiler env vars for .NET;
  ingesting Azure telemetry via the CloudWatch agent; and connecting the DevOps Agent or Slack to a
  Space. Omni onboarding only. For Application Signals onboarding or auto-instrumentation (monitored
  Application Signals service, ServiceEvents, CI/CD deploy metadata), use aws-observability. For day-2
  use of an onboarded Space (queries, dashboards, alerts, debugging), also use aws-observability.
metadata:
  version: "1"
---

# Setting Up CloudWatch Application Observability

> **Scope:** First-time setup of a CloudWatch Application Observability Space — from creation through first traces flowing. For using a Space that is already set up (queries, dashboards, alerts, evaluations), route to **aws-observability**.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — enables running AWS CLI commands directly. All guidance also works with standard AWS CLI access (`aws cloudwatch-omni ...`).

## Concepts

| Term | What it is |
|---|---|
| **Domain** | The identity boundary. Carries the authorization provider (IAM or Identity Center) and owns the endpoint URL customers reach Omni through. One per account, or one shared across an AWS Organization. |
| **Space** | A workspace holding telemetry, in exactly one account and one Region. Created under a Domain. At most one per account per Region. |
| **Access grant** | Attaches a principal — person, group, IAM identity, or async workload — to one Space at a permission level. The only way anyone reaches data *through* a Space — it does not restrict the source CloudWatch log groups, which stay readable under their own IAM. |
| **Access Profile** | A named boundary for async workloads (alerts, integrations, agents) that act without a person in the loop. |
| **Dataset** | What queries run against. Telemetry arrives through the CloudWatch OTLP endpoints, or by forwarding what is already in CloudWatch log groups. |

Setup order from nothing: **Domain → Space → grants → telemetry in → instrumentation.** Access Profiles only when async workloads are involved. For the concept relationships and the full arc, see `references/cloudwatch-omni/app-basics.md`.

This is a **routing skill**. Classify the user's setup request and delegate to the correct reference. References live under `references/cloudwatch-omni/` (CloudWatch Omni); this skill has no CloudWatch setup content, so there is no `references/cloudwatch/` today — CloudWatch onboarding (Application Signals) lives in **aws-observability**.

| User intent | Reference |
|---|---|
| Understand **what Omni is**, its concepts, or **where to start** | `references/cloudwatch-omni/app-basics.md` |
| **Instrument an AI agent** (ADOT, OpenInference, framework detection, trace verification), or **deploy an agent to production** and get traces flowing to CloudWatch — env vars per platform (AgentCore, Lambda, or other platforms such as ECS/EC2/EKS), routing spans to a custom trace log group, IAM permissions needed, ADOT version requirements | `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md` (§ Production deployment for the deploy case) |
| **Per-framework OpenInference guide** (LangChain, LangGraph, Strands, CrewAI, OpenAI Agents, Vercel AI) once the agent framework is known | `references/cloudwatch-omni/omni-agents-instrumentation/openinference-framework-guide.md`, then the matching `references/cloudwatch-omni/omni-agents-instrumentation/instrument-<framework>.md` |
| **Instrument an application** (ADOT SDK on EC2/ECS/EKS/Lambda — Python, Node.js, Java, .NET) | `references/cloudwatch-omni/instrumentation/instrumentation.md` |
| Create an **account-scoped Space or Domain** | `references/cloudwatch-omni/spaces-and-domains.md` |
| Create a **Domain shared across an AWS Organization** | `references/cloudwatch-omni/org-domains.md` |
| Configure **access grants** for people or IAM identities | `references/cloudwatch-omni/access-grants.md` |
| Bound an **alert, integration, or agent** with an Access Profile | `references/cloudwatch-omni/access-profiles.md` |
| Deploy an **OTel Collector** so an instrumented app has somewhere to export to (EC2/ECS/EKS) — it exports to CloudWatch's own per-signal OTLP endpoints | `references/cloudwatch-omni/instrumentation/collector.md` |
| Enable **Transaction Search** so traces reach a Space (spans land in `aws/spans` only once it is on — per account, per Region) | `references/cloudwatch-omni/instrumentation/collector.md` (Step 1) |
| **Forward telemetry** already in CloudWatch into the Dataset | `references/cloudwatch-omni/data-forwarding-and-centralization.md` |
| **Send your application's own telemetry from Azure** (the logs/metrics/traces your service emits, via the CloudWatch agent on an Azure VM/AKS) | `references/cloudwatch-omni/azure-ingestion/azure-ingestion.md` (intent triage), then `references/cloudwatch-omni/azure-ingestion/custom-telemetry.md` (the CloudWatch-agent-on-VM/AKS procedure) |
| Connect **Slack** to a Space for the first time | `references/cloudwatch-omni/slack-integration.md` |
| Connect **GitHub** repositories to enrich the application map with code semantics | `references/cloudwatch-omni/github-integration.md` |
| Register a **custom MCP tool server** (HTTP or stdio) and choose its authentication | `references/cloudwatch-omni/custom-mcp-integration.md` |

## Routing Rules

1. If the user is asking **what Omni is**, what a Domain or Space or grant means, or **where to start** — rather than asking to perform a setup step — route to `references/cloudwatch-omni/app-basics.md`. It also carries the boundary against **aws-observability**.
2. If the request is about **instrumenting an AI agent project** (adding OTel to a framework such as LangChain, LangGraph, Strands, CrewAI, OpenAI Agents, or Vercel AI), route to `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md`.
3. If the request is about **instrumenting a general application** (a service on EC2, ECS, EKS, or Lambda in Python, Node.js, Java, or .NET — not an AI-agent framework), route to `references/cloudwatch-omni/instrumentation/instrumentation.md`.
4. If an **instrumentation, ADOT, or collector** request names neither Omni or a Space, nor Application Signals, ServiceEvents, or the `amazon-cloudwatch-observability` add-on, probe the target Region before choosing: `aws cloudwatch-omni list-spaces --region <region>`. A Space exists → this skill, `references/cloudwatch-omni/instrumentation/instrumentation.md`. No Space → the customer has not adopted Omni; route to **aws-observability**'s Application Signals onboarding reference. If the probe errors with an unknown service, that is the CLI model, not evidence Omni is absent — fall back to the customer's wording and ask only if still inconclusive.
5. If the request is about **Space/Domain creation or configuration**, route to the matching setup reference.
6. If the user asks about getting telemetry **to** a destination — telemetry not yet reaching CloudWatch — **deploy an OTel Collector** on EC2/ECS/EKS so an instrumented workload has somewhere to send OTLP, and wire the app's `OTEL_EXPORTER_OTLP_ENDPOINT` to it: `references/cloudwatch-omni/instrumentation/collector.md`. The collector exports straight to CloudWatch's own per-signal OTLP endpoints. If instead the telemetry is **already in CloudWatch log groups** and needs forwarding into the Dataset, route to `references/cloudwatch-omni/data-forwarding-and-centralization.md`.
7. If the request is about **getting Azure telemetry into CloudWatch**, route to `references/cloudwatch-omni/azure-ingestion/azure-ingestion.md` and decide by intent. If the customer wants the telemetry their own application produces (the logs/metrics/traces from their code), that is supported via the CloudWatch agent on an Azure VM or AKS cluster — follow the reference. If they want telemetry their Azure resources emit on their own (the Azure equivalent of AWS VPC flow logs / Route 53 logs), that is not available — say so and do not attempt a setup.
8. If the user asks to **connect, enable, or authorize Slack** for a Space for the first time (including granting the operator permission to use it), route to `references/cloudwatch-omni/slack-integration.md`. Using Slack after it is connected (posting findings to a channel, mentioning the assistant, or searching Slack) happens in Slack and the console and is not covered by these skills; Slack as an **alert notification target** is covered by **aws-observability**'s Omni alerts reference.
9. If the user wants **Application Signals, ServiceEvents, or Dynamic Instrumentation**, STOP and route to **aws-observability** — those are CloudWatch features and are out of scope for Omni instrumentation.
10. If the user already has a working Space and is asking about **queries/dashboards/alerts**, STOP and route to **aws-observability**.
11. If the user asks to **register their own MCP tool server**, connect a custom MCP server, set up MCP authentication, or choose an auth type for an MCP server (including an OAuth-protected one), route to `references/cloudwatch-omni/custom-mcp-integration.md`. For an OAuth-protected server the choice is one of the two OAuth2 types — client credentials for machine-to-machine, authorization code when a user must consent.
12. If the user asks to **connect GitHub**, link a GitHub organization or repositories, or enrich the application map from source code, route to `references/cloudwatch-omni/github-integration.md`. It connects an organization's repositories so code semantics — services, dependencies, and detected languages/frameworks — enrich the topology under the **Code Semantics** source; it analyzes the default branch only and does NOT correlate deployments, commits, or pull requests. Using the enriched map once it exists (querying topology) is out of scope here — route that to **aws-observability**.
13. If unclear, ask the user what they're trying to set up.
