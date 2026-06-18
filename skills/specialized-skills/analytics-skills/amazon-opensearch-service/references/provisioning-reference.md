# Provisioning capability — entry point and reference

This file is the **entry point** for the `provisioning` capability. It covers cost considerations, security, high availability, and provides a navigation index over the rest of the provisioning files. Infrastructure operations use standard **AWS CLI** commands (e.g., `aws opensearch describe-domain`, `aws opensearchserverless create-collection`); the AWS MCP server's `call_aws` is a streamlined alternative when available but is not required. Data-plane operations (queries, mappings, ISM) use `awscurl` (SigV4-authenticated HTTP requests) regardless of MCP presence.

## When to use this capability

`SKILL.md` routes here when the user is **provisioning or managing AOS domains and AOSS collections**. Concrete triggers:

- Phrases: *"create OpenSearch domain"*, *"scale to N nodes"*, *"AOSS collection"*, *"upgrade my domain"*, *"set up monitoring"*, *"FGAC master user"*, *"snapshot policy"*, *"UltraWarm"*, *"Auto-Tune"*, *"engine version"*
- Tasks: domain creation, upgrades, blue/green, storage tiers (UltraWarm, cold), monitoring (CloudWatch alarms), snapshots, FGAC, AOSS collection lifecycle, security policies

## All provisioning files (capability index)

After loading this entry, you can discover every provisioning-capability file from this list. There are NO other provisioning files outside `references/provisioning-*.md`.

| User need | File |
|---|---|
| Create AOS domain | [`provisioning-domain-provision.md`](provisioning-domain-provision.md) |
| Deploy search config to a domain | [`provisioning-domain-deploy-search.md`](provisioning-domain-deploy-search.md) |
| Create AOSS collection | [`provisioning-serverless-provision.md`](provisioning-serverless-provision.md) |
| Deploy search config to a collection | [`provisioning-serverless-deploy-search.md`](provisioning-serverless-deploy-search.md) |
| Configure agentic search on a domain | [`provisioning-agentic-setup.md`](provisioning-agentic-setup.md) |
| Upgrade domain version | [`provisioning-upgrades.md`](provisioning-upgrades.md) |
| Storage tier management (UltraWarm, cold) | [`provisioning-storage-tiers.md`](provisioning-storage-tiers.md) |
| CloudWatch alarms / monitoring | [`provisioning-monitoring.md`](provisioning-monitoring.md) |
| Troubleshoot domain or collection issues | [`provisioning-troubleshooting.md`](provisioning-troubleshooting.md) |

Cross-cutting refs you may also load: [`sizing.md`](sizing.md) (instance/storage math), [`security.md`](security.md) (FGAC, encryption, VPC), [`personas.md`](personas.md) (DevOps / SRE communication).

## Sizing-related universal rules (apply when this capability sizes a domain)

- **Current-generation instances.** Default to Graviton (`r7g`/`r8g` for memory-optimized; `m7g`/`m8g` for cluster managers). `r6g`/`r6gd` only with explicit justification (existing RIs, specific compatibility need). Full instance family list: see [supported-instance-types.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html); rule and rationale: [sizing.md §Instance family selection](sizing.md).
- **Input honesty.** When sizing on UNKNOWN inputs, lead with `[BLOCKER — need input]` OR present 2–3 tiered bands (small/medium/large workload assumption). Never present a single point estimate built on invented numbers.

## Cross-capability handoff

- For **post-provision search setup** (vector / RAG / semantic): see [`search-semantic-search-guide.md`](search-semantic-search-guide.md).
- For **post-provision log ingestion** (OSI pipelines, OpenSearch Dashboards): see [`log-analytics-guide.md`](log-analytics-guide.md).
- For **trace ingestion + queries** on the new domain: see [`trace-analytics-trace-queries.md`](trace-analytics-trace-queries.md).
- For **migrating into a freshly provisioned domain**: see [`assessment-workflow.md`](assessment-workflow.md).

## Cost: OpenSearch Serverless

- Charged per OCU (OpenSearch Compute Units) hour
- For current OCU floors, redundancy options, and Vector-Search OCU isolation rules, see [sizing.md §OCU model](sizing.md).
- Scales automatically based on workload
- Storage charged separately per GB
- Neural sparse enrichment: charged based on SemanticSearchOCU CloudWatch metric

## Cost: OpenSearch Domain

- Instance hours (varies by instance type)
- EBS storage (GB-month)
- Data transfer and snapshot storage

For monthly cost figures, plug your sizing inputs into <https://calculator.aws> — pricing changes per-region and per-account (RI / Savings Plan / EDP discount math).

Cost optimization levers (no dollar figures — see calculator.aws): Reserved Instances, right-sizing, UltraWarm for cold data, OR1 for log workloads, gp3 storage, Auto-Tune. For instance-family selection rule and rationale, see [sizing.md §Instance family selection](sizing.md); full instance family catalog at [supported-instance-types.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html).

## Security Best Practices

1. **Network**: Deploy in VPC for production, use security groups, enable VPC Flow Logs
2. **Access**: Enable fine-grained access control, use IAM roles, least-privilege policies
3. **Encryption**: At-rest encryption, node-to-node encryption, enforce HTTPS
4. **Monitoring**: Enable CloudWatch logs, set up security alerting

## High Availability (Domain)

1. Enable zone awareness, distribute across 3 AZs
2. Enable automated snapshots to S3
3. Configure standby replicas
4. Test restore procedures

## Monitoring

1. CloudWatch logs: index slow logs, search slow logs, error logs, audit logs
2. CloudWatch alarms: cluster health, CPU/memory, storage, JVM pressure
3. SNS notifications for alerts

## Troubleshooting Quick Reference

| Issue | Check |
|---|---|
| Domain creation fails | Service quotas, VPC config, IAM permissions |
| Cluster health yellow/red | Shard allocation, storage space, node health |
| Access denied | Fine-grained access control, IAM policies, data access policies |
| Model deployment fails | ML plugin enabled, memory allocation, Bedrock region availability |
| Slow queries | Slow logs, query optimization, resource utilization |
| Collection creation fails | Service quotas, region availability, encryption policy |
