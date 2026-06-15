# Security considerations

This skill has two operational modes: (1) **advisory** — pricing math is local and input comes from user-provided files, and (2) **mutating** — creating keyspaces/tables and modifying table settings (TTL, PITR, capacity mode) via AWS APIs after user confirmation. Security exposure comes from the capture steps (connecting to the user's Cassandra cluster, reading prepared-statement contents), from how the user eventually connects applications to Amazon Keyspaces, and from the create/modify operations the skill performs on the user's behalf.

## Risks introduced by following the skill

1. **Cluster credentials** — Mode 2 and Mode 3 rely on captures that require connecting to a running Cassandra cluster with `cqlsh` or driver credentials. If the user is already authenticating to their cluster, the skill inherits that posture. The skill never stores or transmits credentials.
2. **Sensitive query content** — `system.prepared_statements` captures literal bound values (email addresses, customer IDs, account numbers) from real application queries. These files are **sensitive** and must be handled as such.
3. **Schema disclosure** — `DESCRIBE SCHEMA` includes table names, column names, and data types. Usually not secret, but for regulated workloads the table may indicate the kind of data stored (e.g. `patient_records`, `pii_events`).
4. **Pricing data staleness** — pricing comes from snapshot JSON files. If the user is making a procurement decision, state the snapshot date and direct them to the live [Keyspaces pricing page](https://aws.amazon.com/keyspaces/pricing/) to confirm.

## Recommended controls

### Credentials (do not touch)

The skill does not create, read, write, or transmit credentials.

- You MUST NOT prompt the user to enter AWS access keys or Cassandra passwords into the chat.
- The user runs `aws configure`, `ada credentials update`, or their cluster-specific authentication flow **outside** the skill before capturing diagnostics.
- You SHOULD recommend storing service-specific credentials (username/password for Keyspaces) in AWS Secrets Manager with automatic rotation enabled, rather than in application configuration files or environment variables.
- When the target is Amazon Keyspaces itself (e.g., for a TCO self-comparison), link the user to [Keyspaces IAM authentication](https://docs.aws.amazon.com/keyspaces/latest/devguide/programmatic.credentials.html) and the [SigV4 authentication plugin](https://docs.aws.amazon.com/keyspaces/latest/devguide/programmatic.credentials.html#programmatic.credentials.SigV4) rather than walking them through it in this skill.

### IAM least-privilege for Keyspaces

When the user deploys to Keyspaces, recommend least-privilege policies. Typical actions:

- `cassandra:Select` — reads.
- `cassandra:Modify` — writes (insert, update, delete).
- `cassandra:Alter`, `cassandra:Create`, `cassandra:Drop` — DDL operations (restrict to DDL roles, not application roles).
- `cassandra:Restore` — only for backup/restore roles.

Resource ARNs follow the pattern:

```
arn:aws:cassandra:<region>:<account-id>:/keyspace/<keyspace>/table/<table>
```

- You MUST NOT recommend wildcarded `cassandra:*` on production resources, because write/drop access should be separately scoped.
- You SHOULD recommend `aws:SourceVpc` or `aws:SourceVpce` condition keys when the application connects via a VPC endpoint.
- You SHOULD prefer IAM roles (EC2 instance profiles, EKS IRSA, Lambda execution roles) over long-lived access keys.

### TLS / encryption in transit

Amazon Keyspaces requires TLS. The endpoint pattern is:

```
cassandra.<region>.amazonaws.com:9142 --ssl
```

- You MUST include `--ssl` in every `cqlsh` example that targets Keyspaces.
- You MUST recommend TLS on the source Cassandra cluster during captures when the cluster is accessible over the network.
- You SHOULD recommend VPC endpoints (AWS PrivateLink) for private connectivity to Keyspaces.

### Encryption at rest

- Keyspaces encrypts data at rest by default with AWS-owned keys.
- For customer-managed KMS (CMK), recommend it when the user needs key rotation control or access logging. See [Keyspaces encryption at rest](https://docs.aws.amazon.com/keyspaces/latest/devguide/EncryptionAtRest.html).
- PITR-protected data is also encrypted.

### Prepared-statement PII handling

When capturing `system.prepared_statements`:

- You MUST warn the user that the file may contain PII from literal bound values in queries before they copy it off the cluster or share it with the skill.
- You SHOULD recommend redacting obviously sensitive columns (tokens, secrets, raw PII) before handing the file to the skill, if the user has time.
- You MUST NOT echo the raw `query_string` of a flagged statement back in chat when it contains values that look sensitive; surface the `prepared_id` and a short abstract pattern (e.g. "SELECT … FROM users WHERE email = ?") instead.
- Treat the file as ephemeral — recommend deleting it from `/tmp` after the estimate.

### Logging

- You MUST NOT add any logging from the skill that transmits capture contents off the user's machine.
- You SHOULD recommend enabling AWS CloudTrail for Keyspaces API activity logging and Amazon CloudWatch for operational metrics monitoring once the workload is deployed. CloudTrail captures all Keyspaces management events (DDL, IAM auth attempts); CloudWatch provides `SuccessfulRequestLatency`, `ThrottledEvents`, and `SystemErrors` metrics essential for operational visibility.
- You SHOULD recommend enabling CloudTrail log file validation (`--enable-log-file-validation`) to detect tampering, and encrypting CloudTrail logs with a KMS key (`--kms-key-id <key-arn>`).
- You SHOULD recommend encrypting CloudWatch Logs groups with KMS (`aws logs associate-kms-key --log-group-name <group> --kms-key-id <key-arn>`) when logs may contain sensitive information (table names, query patterns, IAM principal identifiers).

### Operational hygiene

- You MUST NOT use `PROD`, `production`, or real customer identifiers in example keyspace or table names, because copy-paste-into-production is a real failure mode.
- You SHOULD suggest per-region isolation for regulated data (e.g., data residency requirements for EU workloads).

## Skill-specific gotchas

- **Over-broad selection.** The description is scoped to Keyspaces + Cassandra terms; do not suggest this skill when the user is working with DynamoDB, Cassandra-on-EC2 operations (not migration), or generic NoSQL modeling questions unrelated to Keyspaces.
- **Destructive actions.** The skill blocks `delete-keyspace` and `delete-table` (irreversible). It performs create/modify operations (`create-keyspace`, `create-table`, `update-table`, `tag-resource`) only after explicit user confirmation per the Safety guidance section in SKILL.md. Advisory modes (pricing, compatibility) produce only local file writes (`/tmp/*.json`, `/tmp/*.pdf`).
- **Cross-account / cross-region.** The skill does not assume cross-account access. For multi-region Keyspaces deployments, remind the user that each region has its own pricing and endpoints.
- **Privilege escalation paths.** The skill does not create IAM policies or roles. When the user asks for one, refer them to the IAM permissions reference and recommend review by their security team.
- **Sensitive output redaction.** See prepared-statement handling above. Also: compatibility output never includes bound values from schema itself, only feature names and object names, so schema-only compatibility reports are generally safe to share.

## Links

- [Amazon Keyspaces security overview](https://docs.aws.amazon.com/keyspaces/latest/devguide/security.html)
- [Keyspaces IAM authentication](https://docs.aws.amazon.com/keyspaces/latest/devguide/programmatic.credentials.html)
- [Keyspaces encryption at rest](https://docs.aws.amazon.com/keyspaces/latest/devguide/EncryptionAtRest.html)
- [SigV4 authentication plugin](https://docs.aws.amazon.com/keyspaces/latest/devguide/programmatic.credentials.html#programmatic.credentials.SigV4)
- [AWS security best practices](https://aws.amazon.com/architecture/security-identity-compliance/)
