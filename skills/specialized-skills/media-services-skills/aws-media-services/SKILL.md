---
name: aws-media-services
description: "Designs, deploys, reviews, evaluates, audits, and troubleshoots video streaming workflows across AWS media services (MediaConnect, MediaLive, MediaConvert, MediaPackage v2, MediaTailor, CloudFront). Includes per-service validation rules, cross-service workflow patterns for live streaming, linear channels, VOD pipelines, and live-to-VOD, service-specific troubleshooting, best practices assessment, cost optimization, encoder settings, DRM, SCTE-35 ad insertion, epoch locking, CDN cache configuration, and migrating MediaPackage v1 (legacy) channels and origin endpoints to MediaPackage v2."
version: 2
---

# AWS Media Services

Use this skill when the user is doing ANY of the following with AWS
media services:

- **Building or modifying** a video workflow (ingest, encoding, packaging, ad
  insertion, CDN delivery)
- **Reviewing, evaluating, or auditing** an existing or proposed configuration
  for best practices, compliance, or correctness
- **Troubleshooting** errors, alerts, or unexpected behavior
- **Asking questions** about service constraints, compatibility rules, encoder
  settings, IAM policies, security groups, DRM, SCTE-35, caching, scaling, or
  any other AWS media topic
- **Planning** a new workflow and needs to understand requirements, dependencies,
  or the discovery checklist
- **Optimizing** cost, resilience, or performance of an existing workflow
- **Migrating** MediaPackage v1 channels and origin endpoints to MediaPackage v2
  (inventory v1, plan channel groups, translate endpoint configs, generate and
  run the migration)

If the user mentions ANY AWS media service by name (MediaConnect, MediaLive,
MediaConvert, MediaPackage, MediaTailor) or related concepts (HLS, DASH, CMAF,
ABR ladder, SCTE-35, epoch locking, origin shield, CDI, SRT, RTMP, transcode,
live streaming, VOD pipeline, ad insertion, SSAI, MediaPackage v1 / v1 to v2
migration), load this skill.

This file is the orchestrator. It tells you which reference files to load based on
the user's task. **Do not load all files at once.** Load on demand per the routing
table below.

## Overview

Every command in this skill uses AWS CLI syntax, so it works with or without the
AWS MCP server. When available, the AWS MCP server is recommended for sandboxed
execution and audit logging (see Tooling below).

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference via
  `retrieve_skill` with the `file` parameter (e.g.
  `file="references/service-rules-core.md"`). Do NOT `file_read` these paths
  locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/aws-media-services/` or
  `~/.claude/skills/aws-media-services/`): Read files from the local skill
  directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

---

## MANDATORY FIRST STEP — Read Before Doing Anything Else

**STOP. Before you make ANY API call, pull ANY resource configuration, write ANY
code, or produce ANY recommendation, you MUST load the required rule files into
context.** This applies to every task type: building, modifying, evaluating,
troubleshooting, or answering questions. The one exception is a MediaPackage
v1 → v2 migration: if the user is moving MediaPackage v1 resources to v2, or asks
what to do in v2 about a v1 channel, endpoint or setting, do NOT load
`service-rules-core.md` — go straight to the migration exception at the end of
this section.

The rule content is split across:

- `references/service-rules-core.md` — cross-service compatibility constraints,
  common agent mistakes, and security considerations. **ALWAYS loaded**, except for a MediaPackage v1 → v2 migration (see the exception below).
- `references/service-rules-encoding.md` — shared encoder settings (QVBR, GOP,
  profiles, quality tuning, deinterlacing). Loaded for any encoding task.
- `references/service-rules-mediaconnect.md`
- `references/service-rules-medialive.md`
- `references/service-rules-mediaconvert.md`
- `references/service-rules-mediapackage.md`
- `references/service-rules-mediatailor.md`
- `references/service-rules-cloudfront.md`

Per-service rule files are loaded conditionally based on which services the
query involves. Without the relevant rules loaded, you will produce
recommendations based on general knowledge that may contradict the documented
rules, flag correct configurations as problems, or miss critical constraints
entirely.

**Sequence (every time):**

1. Read `references/service-rules-core.md` — confirm it is in context before
   proceeding. ALWAYS required.
2. Determine the task type and consult the Task Routing tables below to
   identify both the workflow/troubleshooting file AND the per-service rules
   to co-load.
3. For ad-hoc questions that don't match a workflow or troubleshooting
   category: if the user names specific service(s), load those service rule
   files. If the question is symptom-based or you cannot determine which
   services are involved, load ALL per-service rule files.
4. Only then begin resource discovery, API calls, or implementation.

If you find yourself about to call `aws medialive describe-channel` or similar
and you have NOT yet read the core rules file plus the relevant per-service
rules, stop and go back to step 1.

**Exception — MediaPackage v1 → v2 migration.** This applies to any task about
moving MediaPackage v1 resources to v2: planning or running the migration,
generating its artifacts, asking how a v1 setting, secret, role or input type
carries over to v2, and any request to change or delete v2 resources a migration
created. If the user describes a specific MediaPackage v1 channel, endpoint or
setting ("my v1 endpoint has…") and asks how to reproduce it in v2, it is a
migration task even when the word "migrate" is not used. General v1-vs-v2
comparisons, design or best-practice questions, and troubleshooting a running v2
workflow are not migrations: use the normal sequence above. For migration tasks,
skip steps 1–3: do NOT
load `service-rules-core.md` or any `service-rules-*.md` file. Load
[the migration workflow](references/workflow-mediapackage-migration.md) instead
and follow it; it tells you when to load each stage file:
[discovery](references/mediapackage-migration-discovery.md),
[channel groups](references/mediapackage-migration-channel-groups.md),
[endpoint configuration](references/mediapackage-migration-endpoint-config.md), and
[plan generation, execution and validation](references/mediapackage-migration-execution.md).
The migration files are self-contained: they carry their own safety rules, field
mappings, plan-approval gate, and creation order, and they replace "Plan
Validation" below for the migration. A migration reproduces the user's v1
setup as it is; it does not apply this skill's design recommendations. If the
same conversation later moves on to something other than the migration, return
to the normal sequence above.

---

## Task Routing

### Building or modifying a workflow

Determine the workflow type. Load the matching workflow file AND the per-service
rules listed in the right column (the core rules file is already loaded from the
mandatory first step above).

| Workflow type | Workflow file | Service rules to co-load |
|---------------|---------------|--------------------------|
| Live event (ingest → encode → package → deliver) | `references/workflow-live-event.md` | mediaconnect + medialive + encoding + mediapackage + cloudfront (+ mediatailor if ads) |
| Linear channel (24/7 with schedule, ad insertion) | `references/workflow-linear-channel.md` | medialive + encoding + mediapackage + mediatailor + cloudfront |
| VOD pipeline (file-based transcode → package → deliver) | `references/workflow-vod-pipeline.md` | mediaconvert + encoding + mediapackage + cloudfront |
| Live-to-VOD (live + archive/harvest → VOD transcode) | `references/workflow-live-event.md` + `references/workflow-vod-pipeline.md` | union of live event + VOD pipeline |
| Ad insertion (SSAI/CSAI, MediaTailor scaling) | `references/workflow-ad-insertion.md` | medialive + encoding + mediapackage + mediatailor + cloudfront |
| Contribution transport (MediaConnect, SRT, DX, encoders) | `references/workflow-contribution-distribution.md` | mediaconnect + medialive + encoding |
| Router-based switching (master control, dynamic routing, playout) | `references/workflow-contribution-distribution.md` | mediaconnect + medialive + encoding |
| Resilience (dual-AZ, dual-region, epoch locking, multi-CDN, ops readiness) | `references/workflow-resilience-patterns.md` | ALL (cross-cutting) |
| Cost optimization (reserved vs on-demand, channel classes, right-sizing) | `references/workflow-cost-optimization.md` | ALL (cross-cutting) |
| Subtitles and accessibility (captions, multi-language, auto-captioning) | `references/workflow-subtitles-accessibility.md` | medialive + mediaconvert + encoding |
| MediaPackage v1 → v2 migration (inventory v1, plan channel groups, translate endpoints, generate/execute) | [`references/workflow-mediapackage-migration.md`](references/workflow-mediapackage-migration.md), which loads the stage files one at a time: [`references/mediapackage-migration-discovery.md`](references/mediapackage-migration-discovery.md), [`references/mediapackage-migration-channel-groups.md`](references/mediapackage-migration-channel-groups.md), [`references/mediapackage-migration-endpoint-config.md`](references/mediapackage-migration-endpoint-config.md), [`references/mediapackage-migration-execution.md`](references/mediapackage-migration-execution.md) | none — self-contained; see the migration exception under the mandatory first step |

### Troubleshooting

Load the relevant troubleshooting file(s) for the problem area AND the
per-service rules listed in the right column. The core rules file is already
loaded from the mandatory first step above. Load only the files needed.

| Problem area | Troubleshooting file | Service rules to co-load |
|--------------|----------------------|--------------------------|
| MediaConnect flow issues, source connectivity, VPC interfaces, MediaConnect Router | `references/troubleshooting-mediaconnect.md` | mediaconnect |
| MediaLive channel errors, alerts, encoding, pipeline failover | `references/troubleshooting-medialive.md` | medialive + encoding |
| MediaPackage ingest failures, manifest issues, access denied, issues after a completed v1→v2 migration | `references/troubleshooting-mediapackage.md` | mediapackage |
| MediaConvert job failures, codec errors, output issues, automation | `references/troubleshooting-mediaconvert.md` | mediaconvert + encoding |
| MediaTailor ad insertion, ADS issues, SSAI scaling, session management | `references/troubleshooting-mediatailor.md` | mediatailor + medialive + mediapackage + cloudfront |
| CloudFront origin errors, cache behavior, multi-CDN, Embedded POPs (ePOP) | `references/troubleshooting-cloudfront.md` | cloudfront + mediapackage |
| Cross-service signal chain (no video, latency, sync, AZ alignment, IAM, failover) | `references/troubleshooting-pipeline.md` | ALL |

### Quick reference

For a quick answer about a specific service's constraints, valid parameter
values, or compatibility rules:

1. `references/service-rules-core.md` is already loaded (mandatory first step).
2. If the user names specific service(s) in the query, load those per-service
   rule files (e.g. `references/service-rules-medialive.md`).
3. If the question crosses service boundaries (e.g., MediaPackage→MediaTailor
   compatibility), the cross-service rules are already in
   `service-rules-core.md`.
4. If you can't determine which services are involved, load ALL per-service
   rule files.

This includes the following topics:

- MediaTailor scaling patterns (multi-region, CDN origin shield, prefetch)
- MediaConnect Router (paired resilient zonal endpoints) and downstream NDI converter caveats
- Epoch locking and cross-region failover
- Contribution transport (SRT tuning, Direct Connect sizing, RTP+FEC)
- Multi-CDN architecture patterns
- CloudFront advanced patterns (Embedded POPs / ePOP, CF Functions, segment sharding)
- Operational readiness for live events (capacity planning, KPI baselines)
- DRM production patterns
- MediaPackage v1→v2 migration: field mappings, incompatibilities, and cutover
  readiness are in `references/workflow-mediapackage-migration.md` and its
  `mediapackage-migration-*.md` files, not in the service rules
- Audio, HDR, and codec configuration details

---

## Workflow Discovery Checklist

Before creating ANY resources for a new workflow, gather requirements from the
user in a fixed order (mode → cost/scale → approach → source → network → encoding →
ad insertion → packaging → IAM → VOD-specific). Do not proceed until all required
items are answered; later questions depend on earlier answers. A MediaPackage
v1 → v2 migration does not use this checklist: follow
[the migration workflow](references/workflow-mediapackage-migration.md), which has
its own onboarding and discovery steps.

**Load `references/workflow-discovery-checklist.md`** for the full ordered question
set whenever building or modifying a workflow.

## Plan Validation (before presenting to user)

Before presenting a proposed configuration to the user, cross-check against
the loaded service rules:

- Codec/container compatibility (e.g., HEVC requires fMP4, not TS)
- GOP/segment duration alignment across all ABR rungs
- Dependency ordering (downstream before upstream)
- IAM trust policy includes all required service principals + sts:TagSession
- IAM permissions scoped to specific resource ARNs (no Resource: "*")
- Security posture (CIDR scoped, OAC configured, no Principal: *)
- All prerequisite resources included (IAM roles, VPC, MediaPackage channel MUST be in the plan before resources that depend on them)

Do NOT make API calls during this step. This is a rules-based review of the
proposed plan against constraints already in context.

Agents MUST NOT skip dependency steps to save time. All prerequisites (IAM,
VPC, MediaPackage channel, etc.) MUST be created before resources that reference
them. Skipping steps and fixing errors reactively leads to circular
troubleshooting loops. Execute the plan in dependency order.

---

## Resource Creation Order

Respect dependency order — a resource must exist before anything that references
it (live chain, VOD chain, live-to-VOD addition, and the common flow patterns
table).

**Load `references/resource-creation-order.md`** for the full dependency chains and
flow-pattern table when creating resources.

## Startup and Shutdown (Live Only)

Start upstream first and poll each resource to its ready state before proceeding
(`STARTING` ≠ running); shut down in reverse (`STOPPING` ≠ stopped). Poll on a
tight ~5s cadence.

**Load `references/startup-shutdown.md`** for the ordered start/stop tables and the
polling pattern (including MediaConnect Router lifecycle) when operating a live
workflow.

## Tooling

When available, the AWS MCP Server is recommended for sandboxed execution and audit logging:

- **AWS MCP Server** (`aws-mcp-server`): AWS API access, Agent SOPs
  for guided multi-step workflows, and documentation search via
  `search_documentation` and `read_documentation`.
- **AWS IaC MCP Server** (`aws-iac-mcp-server`): CloudFormation template validation,
  CDK documentation search, CDK code samples, and IaC best practices.

**Large response warning:** MediaLive `describe-channel` and MediaPackage `list-*`
calls return very large JSON. Always use `--query` (JMESPath) to extract only the
fields you need.

```bash
# Good — extract only what you need
aws medialive describe-channel --channel-id 12345 --query "{State:State,Name:Name,Id:Id}"
aws medialive list-channels --query "Channels[].{Name:Name,Id:Id,State:State}"
aws mediapackagev2 list-origin-endpoints --channel-group-name X --channel-name Y \
  --query "Items[].{Name:OriginEndpointName,Url:HlsManifests[0].Url}"
```
