---
name: migrate-to-msk
description: >-
  Helps migrate self-managed Apache Kafka workloads to Amazon MSK Express. Inventories the
  source cluster (from IaC files, Kafka CLI output, or manual input), assesses MSK Express
  compatibility across topology, Kafka version, configs, auth, and quotas, produces a
  target Express specification (instance type, broker count, monthly cost) by filling the
  AWS-published MSK Sizing/Pricing workbook, and guides migration execution using MSK
  Replicator. Applicable when the user mentions migrating Kafka, MSK, MSK Express, Kafka
  migration, analyzing Kafka infrastructure, moving to MSK, moving streaming platform to
  MSK, streaming migration, moving streaming workloads to AWS, MSK workload compatibility,
  MSK cluster sizing, choosing an MSK cluster type, or MSK Replicator.
version: 1
---

# Migrating to MSK Express

## Overview

This skill helps customers migrate self-managed Apache Kafka workloads to Amazon MSK
Express. It provides two independent phases — **Discovery** and **Assessment** —
that can be run end-to-end or individually depending on the customer's needs.

## Scope

This skill covers migrations from **self-managed Apache Kafka** (on-premises, EC2,
Docker, Kubernetes, or other non-MSK deployments) to MSK Express. Migrations from
**MSK Standard (Provisioned) to MSK Express** are out of scope.

## Prerequisites

The AWS MCP server is recommended for documentation lookups and informational
questions, but is not required. The assessment scripts are pure file processors
with no AWS API calls.

## Intent Routing

Route the customer's request based on their intent:

### 1. Open/exploratory question ("How do I migrate to MSK?")

Explain what this skill offers:

> This skill helps you migrate to MSK Express in two phases:
>
> **Phase 1 — Discovery:** Inventory your source Kafka cluster — brokers, topics,
> partition counts, configs, authentication, and workload metrics.
> I can discover this from IaC files (Terraform, CDK, Docker Compose, Kubernetes
> manifests), provide commands for you to run on your cluster, or you can provide the
> information manually. Output: `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json`.
>
> **Phase 2 — Assessment:** Validate your cluster against MSK Express across 5
> compatibility pillars (topology, Kafka version, configs, auth, quotas) and produce
> a target Express specification using the AWS-published MSK Sizing/Pricing workbook.
> I'll flag what Express will refuse vs what Express will silently convert. Outputs:
> `compatibility.<cluster_name>.json`, the filled `MSK_Sizing_Pricing.<cluster_name>.xlsx`,
> and `msk-sizing-inputs.<cluster_name>.json`.
>
> **Data replication:** For migrating data to your Express cluster, you can use
> MSK Replicator. I can provide guidance on setup and configuration.
>
> Where would you like to start? I can begin with discovery if you point me to your
> infrastructure code or describe your cluster, or jump to assessment if you already have a
> `cluster-config.json` file.

**Guardrails for this overview response:**

- This response is an overview and a routing question only. Do NOT begin, simulate, or pre-empt any phase.
- Do NOT produce or estimate assessment output here — no verdicts, pillar findings, compatibility conclusions, broker counts, instance recommendations, or cost figures. Those values exist only after you run the Phase 2 scripts against a real `cluster-config.json`.
- Do NOT open, read, or summarize the internals of `compatibility.py`, `sizing.py`, or the reference files to explain how a phase works. Describe the phases at the level shown above; do not walk the customer through the implementation.
- When the customer chooses a phase, run that phase's scripts or flow to produce real results. Always operate the skill to answer — never answer from having read its source. For the exact commands, see "Running the assessment" in [references/assessment-compatibility.md](references/assessment-compatibility.md) for Phase 2.

### 2. Discovery intent (DEFAULT when IaC files are provided)

If the customer provides a directory path, IaC files, or says "here's our infra" —
this is discovery intent. Run ONLY Phase 1 (Discovery). Do NOT run assessment,
do NOT suggest migration steps, do NOT mention blockers or compatibility.
Produce the `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` file and stop.

### 3. Assessment intent

Customer explicitly asks to assess or has a `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` file
already produced. Run Phase 2 (Assessment) only.

### 4. Informational questions

Customer asks about Express capabilities, constraints, configuration differences,
authentication support, pricing, or compaction behavior without providing
cluster-specific data. Use AWS documentation tools (`aws___search_documentation`,
`aws___read_documentation`) if available to look up the answer from MSK Express
documentation. If MCP tools are not available, reference the
[MSK Express documentation](https://docs.aws.amazon.com/msk/latest/developerguide/msk-broker-types-express.html)
and answer based on knowledge of AWS MSK.

### 5. Migration strategy questions

Customer asks about MSK Replicator compatibility, version upgrade paths, MirrorMaker 2,
or migration strategies. MSK Replicator is the native AWS-supported solution for data
replication and works for both MSK-to-MSK and non-MSK-to-MSK migrations. Use AWS
documentation tools (`aws___search_documentation`, `aws___read_documentation`) if
available to retrieve current requirements and supported configurations. If MCP tools
are not available, reference the
[MSK Replicator documentation](https://docs.aws.amazon.com/msk/latest/developerguide/msk-replicator.html)
and answer based on knowledge of AWS MSK.

---

## Phase 1 — Discovery

**Purpose:** Inventory the source cluster to build a migration profile.

**Input:** One of:

- A directory path containing IaC files (CDK, CloudFormation, Docker Compose, Kubernetes manifests, Terraform)
- Output from Kafka CLI commands the customer runs on their cluster
- Manual information provided by the customer in conversation

**Output:** `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` — saved to the working directory.

### MANDATORY first step for discovery

Before doing ANYTHING else in discovery, you MUST read the reference file:
`references/discovery.md` (located at the skill path shown above).

Use `file_read` to read the full content of `references/discovery.md`. This file
contains the REQUIRED response template and JSON schema. You MUST follow the
template exactly — your response format, forbidden content, and JSON structure
are all defined there. Do NOT respond until you have read this file.

### Discovery methods

1. **IaC analysis** — Read infrastructure files and extract cluster metadata.

2. **Kafka CLI commands** — Display standard Kafka CLI commands for the customer to run on
   their cluster (kafka-topics.sh, kafka-configs.sh, kafka-broker-api-versions.sh).
   Do NOT generate or offer Python scripts.

3. **Runtime metrics intake** — Ingest metrics provided by the customer.

4. **Manual conversation** — Ask the customer for cluster details.

### Discovery rules

- You MUST read `references/discovery.md` before responding.
- Follow the response template from that file EXACTLY.
- ALWAYS save `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` in the working directory.
- Do NOT proceed to Phase 2 without explicit customer confirmation.

---

## Phase 2 — Assessment

**Purpose:** Assess the cluster against MSK Express requirements and produce a target
Express specification (instance type, broker count, monthly cost projection).

**Input:** `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` from Phase 1.

**Outputs:**

- `migrate-to-msk-skill-artifacts/<cluster_name>/compatibility.<cluster_name>.json` — five-pillar verdict.
- `migrate-to-msk-skill-artifacts/<cluster_name>/MSK_Sizing_Pricing.<cluster_name>.xlsx` — the AWS-published MSK Sizing/Pricing workbook (downloaded by the agent) with the six workload inputs filled into the `MSK Provisioned` sheet. Open it to read the broker count and cost recommendations.
- `migrate-to-msk-skill-artifacts/<cluster_name>/msk-sizing-inputs.<cluster_name>.json` — a record of the six input values and the cell each maps to.

Assessment is implemented as two file processors (no live AWS API calls):

- `scripts/compatibility.py` — five-pillar compatibility assessment.
- `scripts/sizing.py` — computes the six workbook inputs from the discovery contract and fills them into the AWS-published workbook the agent downloads.

Both run via `uv run` with PEP 723 inline dependencies. For the exact
invocation commands, see "Running the assessment" in
[references/assessment-compatibility.md](references/assessment-compatibility.md).

### Compatibility pillars

`compatibility.py` validates the source against MSK Express across five pillars:

1. **Topology** — AZ count, broker count, KRaft vs ZooKeeper, per-cluster broker quota.
2. **Kafka version** — source version against the Express supported set (3.6, 3.8, 3.9).
3. **Configs** — broker- and topic-level configs against Express's editable, read-only,
   range-restricted, and enforced-value sets (sourced from the Express broker configuration
   documentation on `docs.aws.amazon.com/msk`).
4. **Auth** — checks the source's authentication mechanism against those MSK Express supports and surfaces any incompatibilities.
5. **Quotas** — peak workload against absolute Express ceilings (per-broker ingress/
   egress, partition count, IAM connection cap, per-partition throughput).

See [references/assessment-compatibility.md](references/assessment-compatibility.md)
for the full pseudocode, evidence codes, and verdict mapping.

### Verdict vocabulary

Each pillar emits one of three verdicts; the overall is the worst across pillars.

| Verdict | Meaning |
|---|---|
| `INFO` | Your source cluster already lines up with MSK Express here. Surfaced for informational purposes. No action needed. |
| `ADVISORY` | Your source cluster differs from MSK Express here, but Express handles this for you at the target by adjusting or replacing the setting. Migration can proceed; review it so the resulting behavior change is expected. |
| `ACTION_REQUIRED` | Identifies a configuration or condition that MSK Express is not expected to accept in its current form. Remediation on the source prior to migration is recommended. |

### Sizing

`sizing.py` computes the six workbook inputs from the source workload (peak
in/out, total partitions, retention). The agent downloads the AWS-published
workbook by reading the Express best-practices page and following its workbook
hyperlink, then runs `sizing.py --workbook <downloaded.xlsx>`, which fills the
`MSK Provisioned` sheet and writes the filled
`MSK_Sizing_Pricing.<cluster_name>.xlsx` (plus a
`msk-sizing-inputs.<cluster_name>.json` record). Open the filled workbook to
read the per-instance broker count and monthly cost; its formulas recalculate
on open. The workbook is downloaded at assessment time, not packaged with the
skill, and the script itself performs no network access (it fills a workbook
the agent already downloaded, using the Python standard library). See
[references/assessment-sizing.md](references/assessment-sizing.md) for the cell
mapping, the download flow, and caveats.

### Assessment rules

- Run `compatibility.py` and `sizing.py` independently; neither blocks the other.
- Surface any `ACTION_REQUIRED` evidence to the user for awareness, but do not gate further phases on it. Express may still accept the workload with mitigations.
- **Do NOT pivot back into discovery.** Assessment operates on the existing
  `cluster-config.json` as-is. Partial data is fine — the scripts emit
  ADVISORY evidence (`METRICS_MISSING`, `AZ_COUNT_UNKNOWN`, etc.) for
  missing fields; surface those findings and stop. Do not propose Kafka CLI
  commands, IaC walks, scripts, or questionnaires to fill the gaps. Full
  forbidden-behavior list in
  [references/assessment-compatibility.md](references/assessment-compatibility.md).
- **Your response MUST follow the assessment response template** in
  [references/assessment-compatibility.md](references/assessment-compatibility.md)
  (section "Response Template"). One template covers both artifacts. Do
  not freestyle the post-script summary — the template defines required
  sections, mandatory vocabulary (use the verdict strings verbatim), and
  forbidden content (no scores, no narrative editorializing, no in-prose
  cost / instance recommendations — the user reads those from the filled workbook).

---

## Execution model

Scripts run on the customer's local machine via `uv run`. They declare their own
dependencies (PEP 723) and are pure file processors — no AWS API calls, no
network access, and no third-party dependencies (standard library only).

## Security Considerations

Apply these controls at every phase. For additional detail, see
[MSK Security best practices](https://docs.aws.amazon.com/msk/latest/developerguide/security.html)
and [MSK IAM access control](https://docs.aws.amazon.com/msk/latest/developerguide/iam-access-control.html).

1. **Encryption in transit (mandatory).** Enforce TLS for client-broker traffic
   on the MSK Express target (`EncryptionInTransit.ClientBroker = TLS`).

2. **Encryption at rest (mandatory).** Provision the target cluster with a
   customer-managed KMS key (or AWS-managed if your compliance posture allows).

3. **Authentication — prefer IAM over long-lived credentials.** Configure the
   MSK Express target with IAM authentication as the sole client auth method.
   This gives ephemeral, role-based credentials with full CloudTrail coverage.

4. **Credential storage — use AWS Secrets Manager.** Store SASL/SCRAM and TLS
   credentials for source cluster access in Secrets Manager. Never pass passwords
   as CLI arguments.

5. **Network isolation.** Deploy MSK clusters in private subnets. Use security
   groups scoped to specific CIDR ranges or security group references. Do NOT use
   0.0.0.0/0 ingress rules.

6. **CloudTrail logging and CloudWatch alarms.** Ensure CloudTrail is enabled in
   the target account and covers `kafka.amazonaws.com` API calls. Configure alarms:
   - `ClientAuthenticationFailure` — surge indicates credential problems or attack
   - `ConnectionCloseCount` — abnormal spike may indicate connection-flooding
   - CloudTrail metric filters for denied `kafka-cluster:*` actions
   - Connection-rate alarms approaching the 100 conn/sec/broker IAM limit

7. **Sensitive data handling.** Discovery and assessment outputs contain broker
   addresses, auth hints, and broker config values. Treat these as sensitive — do
   not paste into public channels or ticketing systems without redaction.

## Troubleshooting

**Single-broker / single-AZ source.** Topology pillar emits `BROKER_COUNT_LT_3` /
`AZ_COUNT_NOT_3` ADVISORY — Express auto-fixes at the target by deploying across 3
AZs with ≥3 brokers regardless of source.

**Out-of-range topic configs.** `max.compaction.lag.ms < 1 day` is the only
Express-rejected topic-config bound encoded in compatibility.py. Adjust on the
source before migration.

**Workbook recommendations look blank or stale.** The recommendation and cost
cells are workbook formulas; they populate once the filled workbook is opened
in Excel / LibreOffice / Sheets and its formulas recalculate. `sizing.py` sets
`fullCalcOnLoad` so this happens automatically on open — if your spreadsheet
app has automatic recalculation disabled, trigger a manual recalculation.
