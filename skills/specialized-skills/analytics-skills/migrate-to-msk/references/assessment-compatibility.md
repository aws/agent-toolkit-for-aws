# Assessment — Compatibility

This reference describes the compatibility assessment for migrating a
self-managed Apache Kafka cluster to MSK Express. It documents the five
pillars that `scripts/compatibility.py` evaluates — topology, Kafka version,
configs, auth, and quotas — together with the AWS-doc-anchored thresholds and
the per-finding verdicts each pillar emits.

`compatibility.py` is a pure file processor: input is the discovery contract
`migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json`; output is
`compatibility.<cluster_name>.json`. No live cluster or AWS API calls.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's **own bundled
files** — the `references/` documents and the `scripts/` files
(`compatibility.py`, `sizing.py`) — from different places. Determine how the
skill was loaded before you read a reference or run a script:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not
  installed on the local filesystem**; its reference files and scripts do not
  exist on disk. You MUST fetch each reference or script through the same
  `retrieve_skill` tool by passing the `file` parameter (for example,
  `file="references/assessment-compatibility.md"` or `file="scripts/sizing.py"`),
  and run a script from the content that tool returns. Do NOT `file_read` these
  paths from the local or working directory, and do NOT search the filesystem
  for them — they are not there, and any local file that happens to match the
  name is unrelated to this skill.
- **Installed locally** (the skill lives in a local skills directory such as
  `.claude/skills/migrate-to-msk/`, `~/.claude/skills/migrate-to-msk/`, or
  `.kiro/skills/migrate-to-msk/`). Read references and run scripts from the
  local skill directory using the relative paths shown throughout this
  documentation (`uv run scripts/compatibility.py ...`).

This distinction applies **only** to the skill's own packaged files. The
customer's data is always on the local filesystem in both modes: the input IaC
files, the discovery `cluster-config.json`, and every artifact under
`migrate-to-msk-skill-artifacts/<cluster_name>/` are read from and written to
the customer's working directory regardless of how the skill was loaded. Never
fetch or write customer data through `retrieve_skill`.

## Running the assessment

Run both scripts with `uv run`, which resolves each script's declared
dependencies automatically. Resolve the script location first per the guardrail
above — when this skill was loaded through the MCP `retrieve_skill` tool, fetch
each script via `retrieve_skill` with the `file` parameter and run that content;
when it is installed locally, run it from the local skill directory. Pass the
discovery `cluster-config.json` as input, and write the outputs into the same
per-cluster artifacts directory:

```bash
# Compatibility -> compatibility.<cluster_name>.json
uv run scripts/compatibility.py \
  migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json \
  --out-dir migrate-to-msk-skill-artifacts/<cluster_name>

# Sizing: first download the AWS workbook by following the "MSK Sizing/Pricing
# workbook" link on the Express best-practices page (resolve the URL from the
# page; do not hardcode it), then fill it. Writes the filled
# MSK_Sizing_Pricing.<cluster_name>.xlsx plus msk-sizing-inputs.<cluster_name>.json.
uv run scripts/sizing.py \
  migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json \
  --workbook <downloaded-MSK_Sizing_Pricing.xlsx> \
  --out-dir migrate-to-msk-skill-artifacts/<cluster_name>
```

The two scripts are independent: run them in either order, and a failure in one
does not block the other. `sizing.py` fills a workbook the agent has already
downloaded and performs no network access itself; without `--workbook` it emits
the JSON inputs and a cell-by-cell fill-in table only. It also accepts
`--avg-in-mbps`, `--avg-out-mbps`, and `--retention-hrs` to override the
workbook's heuristic defaults — see [assessment-sizing.md](./assessment-sizing.md)
for the full download-and-fill flow.

## Source of truth (AWS public docs)

Every threshold and rule below is anchored to one of these AWS public
documentation pages. When AWS publishes updates, refresh the constants in
`compatibility.py`.

- [Express broker overview](https://docs.aws.amazon.com/msk/latest/developerguide/msk-broker-types-express.html)
- [Express read/write broker and topic configurations](https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration-express-read-write.html)
- [Express read-only broker configurations](https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration-express-read-only.html)
- [Express broker quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-quota)
- [Express broker best practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html)

Apache Kafka per-version defaults (used to filter the full config dump):

- [Kafka broker configs](https://kafka.apache.org/documentation/#brokerconfigs)
- [Kafka topic configs](https://kafka.apache.org/documentation/#topicconfigs)

## Assessment scope — forbidden behavior

Assessment operates on the existing `cluster-config.json` produced by Phase 1
(Discovery). It is NOT discovery, and it does NOT pivot back into discovery
when the input is incomplete.

When in Assessment, you MUST NOT:

- Discuss the discovery phase, mention "Phase 1", or describe how
  `cluster-config.json` is produced.
- Propose, suggest, or display any method for gathering more cluster
  information — no Kafka CLI commands (`kafka-topics.sh`, `kafka-configs.sh`,
  `kafka-broker-api-versions.sh`, etc.), no IaC file walks, no Python
  discovery scripts, no `boto3` calls, no manual questionnaires, no
  "would you like me to fetch X from your cluster?" prompts.
- Ask the user to provide additional cluster fields, peaks, configs, or
  topics. The contract is fixed at the input file.

**Partial data is fine.** When required fields are missing or empty
(no `metrics` block, no `num_azs`, no broker configs, etc.), the scripts
already emit ADVISORY evidence describing the gap (`METRICS_MISSING`,
`AZ_COUNT_UNKNOWN`, etc.). Surface those verdicts to the user as-is and
stop. Do not offer to gather the missing data yourself. If the user wants
better assessment fidelity, they can re-run Phase 1 — but suggesting that
is a routing decision the user makes, not something Assessment proposes
mid-flow.

If the input is malformed (`compatibility.py`'s `validate_input` raises),
report the error from the script and stop. Do not improvise around it.

## Response Template

After running `compatibility.py` and `sizing.py`, your response MUST follow
the template below exactly. One template covers both artifacts in a single
response.

FORBIDDEN content — do NOT include any of the following:

- Free-form narrative summaries beyond what the template allows.
- Editorial framings ("looks good overall", "this is a clean migration",
  "you're in great shape", "minor issues only", etc.). State facts; let the
  user judge.
- Numeric scores, percentages, or "readiness scores". The skill emits
  categorical verdicts only.
- Recommendations to run discovery again, fetch more cluster data, or
  invoke any Kafka CLI / IaC walk / questionnaire (see "Assessment scope"
  above).
- MSK Replicator commands or any migration execution detail. That belongs
  to a later conversation, not the assessment response.
- "Action items", "Next steps", or "Recommendations" sections beyond the
  one mandated below.
- Per-instance broker-count recommendations or monthly cost numbers in
  prose. The user reads those from the populated xlsx; do not retype them.

### Template

```
## Assessment Complete — <cluster_name>

**How to read these results:**

- **`INFO`** — This setting already matches how MSK Express works. No action needed — it's listed so you can see it was checked.
- **`ADVISORY`** — Your cluster differs from MSK Express here, and Express adjusts or replaces this for you during migration. You can migrate as-is, but we recommend reviewing it so the change in behavior is expected; where a setting behaves differently, validate in a test environment first.
- **`ACTION_REQUIRED`** — MSK Express won't accept this configuration as-is, so it can't be migrated unchanged. We'll walk you through what to adjust before you migrate.
**Overall verdict:** <INFO | ADVISORY | ACTION_REQUIRED>

### Compatibility — by pillar

| Pillar | Verdict | Findings |
|---|---|---|
| Topology | <verdict> | <count> finding(s) |
| Kafka version | <verdict> | <count> finding(s) |
| Configs | <verdict> | <count> finding(s) |
| Auth | <verdict> | <count> finding(s) |
| Quotas | <verdict> | <count> finding(s) |

### Findings

(One bullet per evidence object emitted by compatibility.py. List only
non-INFO findings. Use the `code` and `detail` from the evidence verbatim.
Group by pillar in the same order as the table.)

- **`<EVIDENCE_CODE>`** [<severity>] — <detail string from compatibility.py>
- ...

If there are zero non-INFO findings, replace this section with:
"No advisories or action-required items. All five pillars: INFO."

### Sizing artifact

The six workload inputs have been computed from the source workload and filled
into the AWS-published MSK Sizing/Pricing workbook, saved to:

`migrate-to-msk-skill-artifacts/<cluster_name>/MSK_Sizing_Pricing.<cluster_name>.xlsx`

Open it in Excel, LibreOffice, or Google Sheets to view the per-instance broker
count and monthly cost recommendations on the `MSK Provisioned` sheet. The
workbook formulas recalculate on open. The computed inputs are also recorded in
`msk-sizing-inputs.<cluster_name>.json`.

### Choosing the right size for your cluster

Guidance for reading the workbook and picking a target:

1. Refine your inputs in column **C**. The rest of the sheet recalculates automatically as you change them.
2. Compare the monthly cost of each Express instance type in cells **I26:I32**, then choose the instance type from the matching rows in **G26:G32**. Throughput and connection quotas vary by instance type. Please review the [MSK Express broker quotas page](https://docs.aws.amazon.com/msk/latest/developerguide/MSK-Express-MSK-broker-quotas.html) to confirm the instance you choose meets your throughput, connection, and partition requirements.
3. Stay within the per-cluster broker quota when you choose: **60 brokers with KRaft, 30 with ZooKeeper**.
4. To see why the workbook recommends this broker count, review the bottleneck breakdown in cells **F149:H155**. It displays which of the ingress, egress, and partition limits determines the recommended count for each type of instance.

The workbook estimates cost using us-east-1 pricing. For pricing in other AWS Regions, or to calculate costs in detail, see the [Amazon MSK pricing page](https://aws.amazon.com/msk/pricing/).

### Artifacts produced

- `migrate-to-msk-skill-artifacts/<cluster_name>/compatibility.<cluster_name>.json`
- `migrate-to-msk-skill-artifacts/<cluster_name>/MSK_Sizing_Pricing.<cluster_name>.xlsx`
- `migrate-to-msk-skill-artifacts/<cluster_name>/msk-sizing-inputs.<cluster_name>.json`

---

Would you like to discuss data replication strategy or revisit any of the
findings above?
```

### Rules

- The response MUST start with `## Assessment Complete — <cluster_name>`
  using the `cluster_name` from the input.
- The response MUST open with the "How to read these results:" legend
  exactly as shown, then the overall verdict.
- Use the verdict strings (`INFO` / `ADVISORY` / `ACTION_REQUIRED`)
  verbatim in the legend, verdict, table, and findings. Do not translate to
  "Pass / Warn / Fail" or any other vocabulary.
- The findings list reproduces evidence `code` and `detail` strings as-is.
  Do not paraphrase the script's wording, do not drop the code, do not
  reorder severity components within a finding.
- Do NOT add a "Cost summary" or "Recommended instance" section in prose
  even if you opened the xlsx — the user reads numbers from the workbook,
  the skill response only points at it.
- Do NOT add a confidence rating, risk score, or quality bar.
- Do NOT add migration timeline estimates.
- The closing question is fixed: ask whether to discuss data replication
  strategy or revisit findings. No alternative phrasings.

## Pillars

`compatibility.py` runs five pillars; the pillar-roll-up is the worst per-finding severity.

### 1. Topology (`assess_topology`)

The 3-AZ requirement, KRaft availability, and the 3-broker minimum come from
the Express broker overview page. The target broker count is determined by the
sizing workbook, not carried over from the source, so this pillar does not
compare the source broker count against a per-cluster ceiling.

| Code | Severity | When |
|---|---|---|
| `AZ_COUNT_UNKNOWN` | ADVISORY | `topology.num_azs` missing |
| `AZ_COUNT_NOT_3` | ADVISORY | `topology.num_azs` ≠ 3 (note: Express always uses 3 AZs) |
| `BROKER_COUNT_LT_3` | ADVISORY | `topology.num_brokers` < 3 (note: Express minimum is 3; exact count comes from the sizing workbook) |
| `KRAFT_REQUIRED_FOR_VERSION` | ADVISORY | `kafka.version` is 3.9 and `kafka.coordination_mechanism` is `ZooKeeper` |

### 2. Kafka version (`assess_kafka_version`)

Per the Express broker overview page, MSK Express supports Apache Kafka versions
3.6, 3.8, and 3.9. Any version outside that set is ADVISORY: your cluster runs a
different version, so after migrating your workload will run on a new Kafka
version. Confirm your client libraries and applications are compatible with the
Express Kafka version you choose — Kafka clients are generally compatible across
minor versions, but we recommend validating in a test environment before
migrating. See the Apache Kafka upgrade notes at
https://kafka.apache.org/documentation/#upgrade for details. Sources older than
Apache Kafka
2.8.1 additionally cannot be data-migrated with MSK Replicator (which requires a
2.8.1+ source); use a MirrorMaker 2 based solution for data migration in that
case.

| Code | Severity | When |
|---|---|---|
| `VERSION_SUPPORTED` | INFO | `kafka.version` ∈ {3.6, 3.8, 3.9} |
| `VERSION_NOT_IN_EXPRESS_SET` | ADVISORY | any other version (older, newer, or a gap such as 3.7); message adds the MirrorMaker 2 note when `kafka.version` < 2.8.1 |

### 3. Configs (`assess_configs`)

Largest pillar. Covers broker-level (`broker_configs`) and topic-level (`topics[].configs`) configs.

**Default-value filtering.** Discovery passes the FULL Kafka config dump (every config the source exposed). `compatibility.py` compares each value against the Apache Kafka default for the source's `kafka.version`; values matching the default produce **no evidence**. Only divergences from default are evaluated against the rules below. See `BROKER_DEFAULTS_BY_VERSION` and `TOPIC_DEFAULTS_BY_VERSION` in the script.

**Express config buckets** (sourced from the Express read/write and read-only
broker configuration pages):

- **Editable** — configurable on Express. Your values carry over.
- **Read-only** — Express enforces a fixed value (sometimes instance-derived). Custom overrides are silently replaced.
- **Range-restricted** — editable, but with a documented bounded range; out-of-range values are rejected.
- **Forced** — read-only with a known fixed enforcement value.
- **Non-exposed** — not a configurable property on MSK Express. This value is managed internally and may differ from your current setting. We recommend validating on a test cluster to confirm the behavior meets your expectations before migrating production traffic.

The exact sets are constants in `compatibility.py` (`EXPRESS_BROKER_RW`, `EXPRESS_BROKER_RO`, `EXPRESS_BROKER_RANGES`, `EXPRESS_BROKER_FORCED`, and the topic-level equivalents).

**Decision matrix** (applied to non-default values only):

| Membership of key | Verdict |
|---|---|
| Editable and within range | INFO (no evidence emitted) |
| Editable with a range, and value out of range | **ACTION_REQUIRED** (`*_CONFIG_OUT_OF_RANGE`) |
| In forced set, value ≠ forced value | ADVISORY (`*_CONFIG_FORCED_VALUE`) |
| Read-only (not in forced) | ADVISORY (`*_CONFIG_READ_ONLY`) |
| Not in editable or read-only sets | ADVISORY (`*_CONFIG_NOT_EXPOSED`) |

Per-topic replication factor: `replication_factor ≠ 3` → ADVISORY (`TOPIC_RF_NOT_3`); Express creates topics with a replication factor of 3 regardless.

**Documented bounded ranges** (Express read/write configurations page):

| Config | Bound |
|---|---|
| `log.cleaner.max.compaction.lag.ms` | [1 day = 86_400_000 ms, +∞] |
| `max.compaction.lag.ms` (topic) | [1 day = 86_400_000 ms, +∞] |

**Forced values** (Express read-only configurations page):

| Config | Express value |
|---|---|
| `default.replication.factor` | 3 |
| `min.insync.replicas` (broker + topic) | 2 |
| `transaction.state.log.min.isr` | 2 |
| `unclean.leader.election.enable` (broker + topic) | false |

### 4. Auth (`assess_auth`)

MSK Express supports four client authentication mechanisms — unauthenticated,
TLS (AWS Private CA), SASL/SCRAM (Secrets Manager), and IAM (`SASL/AWS_MSK_IAM`
or `SASL/OAUTHBEARER`, both carrying an AWS IAM token via the AWS MSK IAM
libraries). TLS in transit is
**required** for every authenticated mechanism; plaintext is only possible with
unauthenticated access. The discovery contract carries two closed-enum fields,
`security.encryption_in_transit` and `security.authentication`; a missing field
or an explicit `UNKNOWN` is treated as undetermined and flagged ADVISORY (it is
not a hard failure). Unrecognized values are rejected at validation time.

The supported mechanisms (unauthenticated, TLS, SASL/SCRAM, IAM) carry over
as-is and emit no evidence (INFO).

| Code | Severity | When |
|---|---|---|
| `AUTH_OAUTHBEARER_NOT_SUPPORTED` | ACTION_REQUIRED | `security.authentication` = `SASL_OAUTHBEARER` (custom OAuth provider; MSK Express accepts OAUTHBEARER only as an AWS IAM token transport, not with external identity providers) |
| `AUTH_UNKNOWN` | ADVISORY | `security.authentication` = `UNKNOWN` or missing (verify it is a supported mechanism) |
| `AUTH_MECHANISM_NOT_SUPPORTED` | ACTION_REQUIRED | `security.authentication` = `OTHER` (e.g. SASL/GSSAPI/Kerberos, SASL/PLAIN — not supported by Express) |
| `ENCRYPTION_NOT_TLS` | ACTION_REQUIRED | `security.encryption_in_transit` ≠ `TLS` **and** an authenticated mechanism is in use (TLS / SASL/SCRAM / IAM) — Express requires TLS for these; update clients before migrating |
| `ENCRYPTION_UNKNOWN` | ADVISORY | `security.encryption_in_transit` = `UNKNOWN` or missing (confirm clients can use TLS) |

Unauthenticated access is `INFO` — Express supports it, and plaintext is
permitted in that case, so no encryption finding fires. Mechanism-specific
re-credentialing work (SASL/SCRAM secret prefix, IAM policies, TLS Private CA
association) is out of scope for compatibility — handled by migration planning.

### 5. Quotas (`assess_quotas`)

Compatibility checks **absolute** Express ceilings — workload can't fit *any* Express configuration. Sizing checks per-instance fit.

All values below come from the Express broker quotas page.

| Limit | Value |
|---|---|
| Max ingress / broker (max-quota at m7g.16xlarge) | 750 MBps |
| Max egress / broker (max-quota at m7g.16xlarge) | 1875 MBps |
| Max partitions / broker | 32_000 |
| Max IAM connections / broker | 3_000 |
| Max throughput / partition | 15 MB/s |

| Code | Severity | When |
|---|---|---|
| `METRICS_MISSING` | ADVISORY | `metrics` block absent |
| `INGRESS_OVER_MAX_BROKER` | ADVISORY | `peak_bytes_in_per_broker_mbps` > 750 |
| `EGRESS_OVER_MAX_BROKER` | ADVISORY | `peak_bytes_out_per_broker_mbps` > 1875 |
| `PARTITIONS_OVER_MAX_BROKER` | ADVISORY | `peak_partitions_per_broker` > 32_000 |
| `CONNECTIONS_OVER_IAM_LIMIT` | ADVISORY | `security.authentication` ∈ {`SASL_IAM`, `SASL_OAUTHBEARER`} AND `peak_connections_per_broker` > 3_000 |
| `PARTITION_THROUGHPUT_OVER_LIMIT` | ADVISORY | average per-partition throughput (`peak_in × num_brokers / total_partitions`) > 15 MB/s |

The per-partition check is approximate; hot partitions can exceed 15 MB/s while the cluster average is fine.

## Output schema

```json
{
  "cluster_name": "<from input>",
  "assessed_at": "<ISO-8601>",
  "overall": "INFO | ADVISORY | ACTION_REQUIRED",
  "pillars": {
    "topology":      {"verdict": "...", "evidence": [...]},
    "kafka_version": {"verdict": "...", "evidence": [...]},
    "configs":       {"verdict": "...", "evidence": [...]},
    "auth":          {"verdict": "...", "evidence": [...]},
    "quotas":        {"verdict": "...", "evidence": [...]}
  },
  "summary": {
    "action_required_codes": [...],
    "advisory_codes":        [...],
    "info_codes":            [...]
  }
}
```

Each evidence object carries `code`, `severity` (per-finding, used for summary bucketing), `detail`, plus optional `topic`, `config_key`, `observed`, `limit`, `enforced`.

## Refresh procedure

> **The script is the source of truth.** This reference documents the *rules*
> `scripts/compatibility.py` enforces — the AWS-doc-anchored data and the
> classification matrix. **Do not re-implement the script from this document.**
> Always invoke `scripts/compatibility.py` directly. If the script's behavior
> diverges from this reference, the script wins; update this reference instead.

When AWS publishes updates to the anchor docs:

1. Re-fetch the AWS public docs linked at the top of this file.
2. Diff against the constants at the top of `compatibility.py`.
3. Update `BROKER_DEFAULTS_BY_VERSION` / `TOPIC_DEFAULTS_BY_VERSION` if Apache Kafka adds a new supported version.

## Security considerations

- **Discovery input may contain credentials.** `cluster-config.json` is produced
  by the discovery phase. Before passing it to `compatibility.py`, verify it
  does not contain SASL passwords, API keys, TLS private keys, or other
  credential material. The discovery contract intentionally captures
  `security.authentication` (the mechanism) but never the secret itself;
  if your discovery output includes anything resembling a credential,
  redact it before processing or sharing.
- **Output files reveal cluster topology and configuration.** The
  `compatibility.<cluster_name>.json` output enumerates broker configs, topic
  configs, partition counts, and authentication mode. Treat it as sensitive:
  store with restrictive permissions (e.g., `chmod 600`), keep it inside the
  `migrate-to-msk-skill-artifacts/<cluster_name>/` directory, and do not
  paste it into public channels, ticketing systems, or shared chat without
  redaction.
- **Do not log raw config values.** The script's evidence detail strings
  include observed config values; this is intentional for human review but
  means logs containing this output should be retained under the same
  controls as the cluster-config input.
