# Storage Tier Management

## UltraWarm

UltraWarm provides cost-effective warm storage for infrequently accessed data using S3-backed nodes.

### Enable UltraWarm

```bash
aws opensearch update-domain-config --domain-name my-domain \
  --cluster-config WarmEnabled=true,WarmType=ultrawarm1.medium.search,WarmCount=2
```

### Migrate Indices to UltraWarm

```
POST /_ultrawarm/migration/my-old-index/_warm
```

Check migration status:

```
GET /_ultrawarm/migration/my-old-index/_status
```

### Query UltraWarm Data

UltraWarm data is fully searchable. Queries run transparently across hot and warm tiers.

## Cold Storage

Cold storage detaches data from the cluster for long-term retention at lowest cost.

### Enable Cold Storage

```bash
aws opensearch update-domain-config --domain-name my-domain \
  --cluster-config ColdStorageOptions={Enabled=true}
```

Requires UltraWarm to be enabled first.

### Migrate to Cold Storage

```
POST /_cold/migration/my-archive-index/_cold
```

### Restore from Cold Storage

Cold data must be migrated back to warm before querying:

```
POST /_cold/migration/my-archive-index/_warm
```

## ISM Policies for Automated Tiering

Use Index State Management to automate data lifecycle:

```
PUT /_plugins/_ism/policies/log-lifecycle
{
  "policy": {
    "states": [
      {"name": "hot", "actions": [], "transitions": [{"state_name": "warm", "conditions": {"min_index_age": "7d"}}]},
      {"name": "warm", "actions": [{"warm_migration": {}}], "transitions": [{"state_name": "cold", "conditions": {"min_index_age": "30d"}}]},
      {"name": "cold", "actions": [{"cold_migration": {}}], "transitions": [{"state_name": "delete", "conditions": {"min_index_age": "90d"}}]},
      {"name": "delete", "actions": [{"delete": {}}]}
    ],
    "ism_template": [{"index_patterns": ["cwl-*"], "priority": 100}]
  }
}
```

## Sizing Guidance

| Tier | Cost | Query Latency | Use Case |
|------|------|---------------|----------|
| Hot (EBS) | $$$ | Milliseconds | Active queries, recent data |
| UltraWarm | $$ | Seconds | Infrequent access, compliance retention |
| Cold | $ | Minutes (restore required) | Archive, long-term retention |
