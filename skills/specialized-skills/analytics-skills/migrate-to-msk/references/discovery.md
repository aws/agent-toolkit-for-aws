# Discovery Phase

Process ONE cluster at a time. If multiple clusters are found in the IaC files,
list them and ask the user which one to process first. Do NOT process all clusters
at once.

Your response MUST follow the template exactly.

FORBIDDEN content — do NOT include any of the following:

- Compatibility observations ("not supported by MSK", "should migrate smoothly")
- Blockers, warnings, or recommendations
- Migration steps or deployment commands
- Sections called "Key Observations", "Important Notes", "Next Steps", or similar
- Any assessment of whether configs will work on Express
- Python scripts

## Response Template

```
## Discovery Complete — <cluster_name>

### Kafka
- **Version:** <version>
- **Coordination Mechanism:** <KRaft | ZooKeeper | Unknown>

### Topology
- **Brokers:** <count>
- **Availability Zones:** <count or "unknown">
- **Instance Type:** <type or "not determined">

### Security
- **Authentication:** <method>
- **Encryption in transit:** <TLS | PLAINTEXT | TLS_PLAINTEXT | UNKNOWN>

### Topics Found
| Topic | Partitions | Replication | Non-default configs |
|-------|-----------|-------------|---------------------|
| <name> | <count> | <factor> | <configs or "none"> |

### Non-default Broker Configs
- `<config.key>`: `<value>`

---

### Information I Could Not Determine

The following require runtime data that isn't available in IaC:
- Topics, partitions, replication factors, and topic-level configs
- Broker-level configuration overrides
- Peak throughput (MB/s ingress/egress per broker)
- Connection count per broker

**Options to fill these gaps:**
- **A.** Run these commands on your cluster and share the output files:

  ```bash
  kafka-topics.sh --bootstrap-server <addr> --describe > kafka-topics-output.txt
  kafka-configs.sh --bootstrap-server <addr> --entity-type brokers --entity-default --describe > kafka-configs-output.txt
  kafka-broker-api-versions.sh --bootstrap-server <addr> > kafka-versions-output.txt
  ```

  Then share the files or paste their contents here.

- **B.** Proceed with partial data (assessment will be less accurate)

Would you like to proceed to assessment, or provide additional information first?

```

## Rules

- Fill in values from IaC files/commands. Remove sections where no data was found.
- Save to `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` for the selected cluster.
- Do NOT add extra sections beyond what the template shows.
- Do NOT summarize, characterize, or editorialize the findings ("solid foundation",
  "straightforward migration", etc.). Only state facts.
- Do NOT mention Express, MSK, compatibility, blockers, or migration steps.
- Do NOT offer or generate Python scripts. Only show Kafka CLI commands.
- Do NOT reference CLI commands unless you actually displayed them in the response.
- If the user provided all information manually and there are no gaps, skip the
  "Information I Could Not Determine" section entirely. Just end with:
  "Would you like to proceed to assessment, or provide additional information first?"

---

## JSON Output Schema

Save to the following path:
`migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json`

Where `<cluster_name>` is the cluster name (lowercase, hyphenated).
Create the directories if they don't exist.

ALL fields MUST be present in the output file unless marked as `(optional)`.
Fields marked `(optional)` MAY be omitted entirely. For all other fields, if the
value cannot be determined, use `null` for strings/numbers, `false` for booleans,
`[]` for arrays, and `{}` for objects.

The output file contains sensitive data (broker addresses, authentication details).
Treat it accordingly — do not commit to version control or share in public channels.
Do NOT store passwords, private keys, or secret values in this file. For
`auth_identity`, record only the username or a Secrets Manager ARN reference —
never the password or key material.

Note: `broker_configs` and `topics[].configs` carry the **full** Kafka config
dump (every config the source exposed), not just non-default values.
`compatibility.py` filters against per-Kafka-version Apache defaults internally,
so values matching the default for the source's `kafka.version` produce no
evidence — only divergences from default are evaluated against Express's
constraints.

### `security` enum values

`encryption_in_transit` is a closed enum describing how client-broker traffic
is encrypted on the source:

- `TLS` — clients connect on a TLS-only listener (port 9094 or 9096 typically).
- `PLAINTEXT` — clients connect on a plaintext listener (port 9092 typically).
- `TLS_PLAINTEXT` — the cluster exposes both; some clients use TLS, others plaintext.
- `UNKNOWN` — use when the listener configuration cannot be determined from available IaC or CLI output.

To determine the value: check the broker's `listeners` / `advertised.listeners`
config, or look at the `security.protocol` clients use (`SSL` / `SASL_SSL` →
TLS; `PLAINTEXT` / `SASL_PLAINTEXT` → PLAINTEXT; mix → TLS_PLAINTEXT).

`authentication` is a closed enum covering the mechanism the source cluster
expects from Kafka clients:

- `UNAUTHENTICATED` — no `sasl.mechanism` or `ssl.keystore` configured on clients; the broker allows anonymous connections.
- `TLS` — clients present X.509 certificates (`ssl.keystore.location` configured); broker has `ssl.client.auth=required`.
- `SASL_SCRAM` — `sasl.mechanism=SCRAM-SHA-256` or `SCRAM-SHA-512` in client config.
- `SASL_IAM` — `sasl.mechanism=AWS_MSK_IAM`, or clients use the AWS MSK IAM signer with `sasl.mechanism=OAUTHBEARER` on an existing MSK cluster.
- `SASL_OAUTHBEARER` — `sasl.mechanism=OAUTHBEARER` with a **non-AWS** token provider (e.g. Keycloak, Okta, custom OAuth server).
- `OTHER` — any mechanism not covered above (e.g. `GSSAPI`/Kerberos, `PLAIN`, custom callback handlers).
- `UNKNOWN` — use when the mechanism cannot be determined from available IaC or CLI output.

To determine the value: check the client's `sasl.mechanism` property, or the
broker's `sasl.enabled.mechanisms` / `listener.security.protocol.map` config.
If both `OAUTHBEARER` and the AWS signer library are present, use `SASL_IAM`
(it's the AWS IAM path). Use `SASL_OAUTHBEARER` only for custom providers.

For how each value is evaluated against MSK Express, see
[assessment-compatibility.md](./assessment-compatibility.md) (Pillar 4 — Auth).

Discovery MUST emit one of these exact strings. `compatibility.py`'s
`validate_input` rejects unrecognized values.

### Partition counts: leaders vs. total replicas

Two different partition numbers come up, and they are not interchangeable. Be
explicit about which one you are recording.

- **Configured (leader) partitions** — the partition count set on a topic, one
  leader per partition. This is the `PartitionCount` shown by
  `kafka-topics.sh --describe`, and the number set with `--partitions`. It does
  **not** include replicas.
- **Total partition replicas** — configured partitions multiplied by the
  replication factor (leaders + followers). This is the basis AWS uses for
  per-broker partition limits (see `peak_partitions_per_broker` below and the
  MSK Express broker partition quota).

How each contract field is counted:

- `topics[].num_partitions` — the **configured (leader)** count for that topic.
  Record the per-topic partition count, never a pre-multiplied total.
- `topics[].replication_factor` — the source topic's replication factor.
- `metrics.peak_partitions_per_broker` — **total replicas** (leaders +
  followers) hosted on the busiest broker, matching the AWS quota basis.

The skill converts when it needs the total: `sizing.py` multiplies the summed
leader count by the Express target replication factor (always 3) to populate the
workbook's "Partitions" cell. So you only ever enter leader counts in
`num_partitions` — do not pre-multiply by RF.

**If a user reports a partition number conversationally and it is ambiguous
which count they mean, ask before recording it:** "Is that the configured
partition count per topic (leaders), or the total including replicas?" If it is
a total-including-replicas figure, divide it back to the configured count (and
capture the replication factor separately) before writing `num_partitions`.

```json
{
  "cluster_name": "<string>",
  "source_type": "<string: 'self-managed' | 'cloud-hosted'>",
  "discovered_at": "<string: ISO 8601 timestamp>",

  "kafka": {
    "version": "<string>",
    "coordination_mechanism": "<string: 'KRaft' | 'ZooKeeper' | 'Unknown'>"
  },

  "topology": {
    "num_brokers": "<integer>",
    "num_azs": "<integer> (optional)",
    "broker_instance_type": "<string> (optional)"
  },

  "topics": [
    {
      "name": "<string>",
      "num_partitions": "<integer>",
      "replication_factor": "<integer>",
      "configs": {
        "<config.key>": "<string: full Kafka topic config dump>"
      }
    }
  ],

  "broker_configs": {
    "<config.key>": "<string: full Kafka broker config dump>"
  },

  "security": {
    "encryption_in_transit": "<enum: 'TLS' | 'PLAINTEXT' | 'TLS_PLAINTEXT' | 'UNKNOWN'>",
    "authentication": "<enum: 'UNAUTHENTICATED' | 'TLS' | 'SASL_SCRAM' | 'SASL_IAM' | 'SASL_OAUTHBEARER' | 'OTHER' | 'UNKNOWN'>",
    "auth_identity": "<string> (optional)"
  },

  "metrics": {
    "source": "<string: 'manual' | 'other' | null>",
    "lookback_hours": "<integer | null>",
    "peak_bytes_in_per_broker_mbps": "<number | null>",
    "peak_bytes_out_per_broker_mbps": "<number | null>",
    "avg_bytes_in_per_broker_mbps": "<number | null>",
    "avg_bytes_out_per_broker_mbps": "<number | null>",
    "peak_connections_per_broker": "<integer | null>",
    "peak_partitions_per_broker": "<integer | null>"
  },

  "iac_index": [
    {
      "iac_type": "<string: 'terraform' | 'cdk' | 'cloudformation' | 'k8s_manifest' | 'docker_compose'>",
      "iac_file": "<string: relative path>",
      "service_name": "<string>",
      "bootstrap_hints": ["<string>"]
    }
  ]
}
```

### Example

```json
{
  "cluster_name": "orders-staging",
  "source_type": "self-managed",
  "discovered_at": "2026-05-27T18:00:00Z",
  "kafka": {
    "version": "3.6.0",
    "coordination_mechanism": "KRaft"
  },
  "topology": {
    "num_brokers": 12,
    "num_azs": 3,
    "broker_instance_type": null
  },
  "topics": [
    {
      "name": "orders",
      "num_partitions": 24,
      "replication_factor": 3,
      "configs": {
        "cleanup.policy": "delete",
        "retention.ms": "604800000"
      }
    }
  ],
  "broker_configs": {
    "log.segment.bytes": "536870912",
    "min.insync.replicas": "3"
  },
  "security": {
    "encryption_in_transit": "TLS",
    "authentication": "SASL_SCRAM",
    "auth_identity": "kafka-admin"
  },
  "metrics": {
    "source": "manual",
    "lookback_hours": 24,
    "peak_bytes_in_per_broker_mbps": 142.7,
    "peak_bytes_out_per_broker_mbps": 285.3,
    "avg_bytes_in_per_broker_mbps": 78.4,
    "avg_bytes_out_per_broker_mbps": 156.8,
    "peak_connections_per_broker": 1240,
    "peak_partitions_per_broker": 380
  },
  "iac_index": [
    {
      "iac_type": "k8s_manifest",
      "iac_file": "deploy/orders.yaml",
      "service_name": "order-svc",
      "bootstrap_hints": ["kafka:9092"]
    }
  ]
}
```
