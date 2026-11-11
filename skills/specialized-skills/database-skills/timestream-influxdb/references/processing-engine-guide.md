# Processing Engine Guide

## When to Activate

User asks about data processing plugins, triggers, downsampling, data transformation, alerting, or the Processing Engine feature of InfluxDB 3.

**Prerequisite:** Processing Engine is InfluxDB 3 only. If the user is on V2, inform them and offer to route to `migration`.

## Overview

The Processing Engine is an embedded Python virtual machine inside InfluxDB 3 that extends database functionality with plugins. It can use InfluxData certified plugins and customer-authored custom Python plugins when the selected engine edition and AWS account meet the requirements in the Timestream for InfluxDB documentation.

For every custom-plugin request, retrieve the [Timestream for InfluxDB custom-plugin documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-custom-plugins.html), inspect the installed DB parameter-group API model, and inspect `influxdb3 create trigger --help`. Reading this file is not verification. If authoritative sources cannot be retrieved, state that verification could not be completed and do not guess.

## Available Certified Plugins

| Plugin | Trigger Type | Use Case |
|--------|-------------|----------|
| **Downsampler** | Scheduled, HTTP | Aggregate high-frequency data into lower-resolution summaries |
| **Basic Transformation** | Scheduled, Data write | Field name normalization, unit conversions, data cleaning |
| **MAD Anomaly Detection** | Data write | Real-time outlier detection using Median Absolute Deviation |
| **State Change Monitor** | Scheduled, Data write | Track field value changes, alert on state transitions |
| **System Metrics Collector** | Scheduled | Collect CPU, memory, disk, network metrics from the host |
| **LiveAnalytics Migration** | HTTP | Migrate data from Timestream for LiveAnalytics (smaller migrations under 1B records) |

Source code and documentation: [InfluxData Plugins Repository](https://github.com/influxdata/influxdb3_plugins/tree/main/influxdata)

## Custom Plugins

Retrieve [Use custom plugins with the Processing Engine](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-custom-plugins.html) and inspect the installed `create-db-parameter-group` API model before answering. Confirm edition support (Core or Enterprise) and that custom plugins are enabled for the account. The documentation states these rules; apply them as stated:

- **Immutable:** Repository parameters cannot be changed on an existing parameter group, and parameter groups cannot be deleted. To change the URL or secret, create a new parameter group and apply it with `update-db-cluster`.
- **Repository URL:** `pluginRepositoryUrl` is an HTTPS base URL that serves raw file bytes, with no embedded credentials, query strings, or fragments. Set it under `InfluxDBv3Core` or `InfluxDBv3Enterprise` to match the cluster edition.
- **Repository secret:** For a private repository, `pluginRepositorySecretArn` names a Secrets Manager secret whose name begins with `InfluxDB-RepoToken-`, in the same AWS account and Region as the parameter group, whose value is the access token as a plain string (not JSON). Omit the field for a public repository.
- **Token scope:** Use a fine-grained, read-only token limited to the plugin repositories the triggers reference, with an expiration date; rotate it periodically.
- **Plugins:** `gh:<path>` resolves against the base URL and supports single-file `.py` plugins only. Plugins can use only the Python standard library and the pre-installed libraries; the package manager is disabled.

**Repository token handling:** You MUST have the user create or update the `InfluxDB-RepoToken-*` secret themselves, through the Secrets Manager console or with `--secret-string "file://<mode-600-file>"` from a file they delete immediately afterward. You MUST NOT accept a repository token pasted into the conversation, and MUST NOT place a token value in a command argument, environment variable you echo, or log — even when the retrieved documentation shows `--secret-string "<token>"`. Work only with the secret ARN.

Follow the retrieved behavior when it differs from the examples below. For a Core cluster, create a parameter group only when the API model confirms the `InfluxDBv3Core` namespace:

```bash
aws timestream-influxdb create-db-parameter-group \
  --name my-plugin-parameter-group \
  --description "InfluxDB 3 custom plugin repository" \
  --region us-west-2 \
  --parameters '{
    "InfluxDBv3Core": {
      "pluginRepositoryUrl": "https://raw.githubusercontent.com/my-org/influxdb-plugins/release",
      "pluginRepositorySecretArn": "arn:aws:secretsmanager:us-west-2:111122223333:secret:InfluxDB-RepoToken-my-plugins-AbCdEf"
    }
  }'
```

Never propose an in-place edit of a plugin parameter group; create a replacement group instead.

**Restrict the secret and key to the service:** Recommend attaching the documented resource policies so only the Timestream for InfluxDB service-linked role (`AWSServiceRoleForTimestreamInfluxDB`) can read the token. The secret policy grants that role only `secretsmanager:GetSecretValue` (`aws secretsmanager put-resource-policy --secret-id <secret-arn> --resource-policy file://<policy.json>`). For a customer-managed KMS key, the key policy keeps the account-root administration statement and grants that role only `kms:Decrypt` and `kms:DescribeKey` with `kms:ViaService` set to `secretsmanager.<region>.amazonaws.com`. To scope the key to this one secret, also add `"kms:EncryptionContext:SecretARN": "<secret-arn>"` to that statement's `StringEquals` condition. Never remove the root statement, because that can lock the account out of the key.

**Confirm before creating or applying the group:** A DB parameter group cannot be modified or deleted after creation, and applying one to a cluster runs a cluster maintenance action. Before running `create-db-parameter-group` or `update-db-cluster`, you MUST show the user the cluster ID, Region, repository URL, and secret ARN; state that the group is permanent and that applying it triggers maintenance; and obtain explicit confirmation, offering to schedule the change in a maintenance window. Treat a request that already acknowledges these impacts and the exact values as that confirmation.

Apply the returned parameter-group identifier to the cluster and wait for the documented ready state:

```bash
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --db-parameter-group-identifier <returned-parameter-group-id> \
  --region us-west-2
```

Use only repository path and trigger syntax verified from the custom-plugin documentation and installed CLI help. The following pattern applies only when those sources confirm the `gh:` path form and `INFLUXDB3_AUTH_TOKEN`:

```bash
(
  set -euo pipefail
  set +x

  INFLUXDB3_AUTH_TOKEN="$(
    aws secretsmanager get-secret-value \
      --secret-id <admin-token-secret-arn> \
      --query SecretString \
      --output text |
      python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])'
  )"
  export INFLUXDB3_AUTH_TOKEN
  trap 'unset INFLUXDB3_AUTH_TOKEN' EXIT

  influxdb3 create trigger \
    --host "https://<cluster-endpoint>:<port>" \
    --database metrics \
    --trigger-spec "table:sensor_data" \
    --path "gh:transforms/enrich.py" \
    enrich_sensor_data
)
```

Use the endpoint and `port` returned by `get-db-cluster` (the V3 default is 8181); without `--host` or `INFLUXDB3_HOST_URL`, the CLI targets localhost. `--path "gh:<path>"` loads a custom plugin from the configured repository; `--plugin-filename`, used in the examples below, loads a certified plugin.

Keep the admin token process-scoped, disable shell tracing, and unset the token immediately. Do not pass it through `--token`, even when the retrieved documentation does, because process arguments may expose it. Never persist webhook URLs, API keys, tokens, or other credentials in trigger arguments because they can be visible through `system.processing_engine_triggers`.

Treat every custom-plugin repository as executable production code. Verify repository ownership and source provenance; review and test the exact code; scan for secrets, malicious behavior, and vulnerable dependencies; protect repository writes; and retain auditable approval.

**Pin the repository scope:** Whoever can push to the configured location controls the code the cluster runs.

- You MUST use an owner-, repository-, and branch-scoped base URL (`https://raw.githubusercontent.com/<owner>/<repo>/<branch>`). A host-only base such as `https://raw.githubusercontent.com` lets the cluster load code from any repository that host serves. Propose it only when the user needs plugins from several repositories, after stating that risk, and only with their explicit opt-in.
- Point the base at a protected, review-gated release branch (as in the `release` example above), not a branch that accepts unreviewed pushes.
- For the strictest pinning, when the host serves raw content by commit SHA, use the SHA in place of the branch. Each new pin then requires a new, permanent parameter group and a cluster maintenance action to apply it. Authenticate every HTTP-trigger request, validate all request data, restrict network access, and apply request-size and rate limits.

## Trigger Types

| Trigger | Specification | When It Fires |
|---------|--------------|---------------|
| Data write | `table:<name>` or `all_tables` | When data is written to tables |
| Scheduled | `every:<interval>` or `cron:<expression>` | At specified intervals |
| HTTP request | `request:<endpoint>` | When HTTP requests hit the plugin endpoint |

## Creating Triggers

```bash
# Load V3_TOKEN from Secrets Manager as shown in the getting-started guide.
export INFLUXDB3_AUTH_TOKEN="$V3_TOKEN"
export INFLUXDB3_HOST_URL="https://<cluster-endpoint>:<port>"

# Downsampler — aggregate CPU metrics hourly
influxdb3 create trigger \
  --database metrics \
  --plugin-filename "downsampler/downsampler.py" \
  --trigger-spec "every:1h" \
  --trigger-arguments 'source_measurement=cpu_detailed,target_measurement=cpu_hourly,interval=1h,window=6h,calculations="usage:avg.max_usage:max"' \
  cpu_downsampler

# MAD Anomaly Detection — real-time outlier detection on sensor data
# Notification senders need credentials; see "Secrets in plugin arguments" below.
influxdb3 create trigger \
  --database sensors \
  --plugin-filename "mad_check/mad_check_plugin.py" \
  --trigger-spec "all_tables" \
  --trigger-arguments 'measurement=temperature_sensors,mad_thresholds="temp:2.5:20:5"' \
  temp_anomaly_detector

# Basic transformation — clean field names on incoming data
influxdb3 create trigger \
  --database iot \
  --plugin-filename "basic_transformation/basic_transformation.py" \
  --trigger-spec "all_tables" \
  --trigger-arguments 'measurement=raw_sensors,target_measurement=clean_sensors,names_transformations=.*:"snake alnum_underscore_only"' \
  sensor_cleaner

# State Change Monitor — alert on equipment status changes
influxdb3 create trigger \
  --database factory \
  --plugin-filename "state_change/state_change_check_plugin.py" \
  --trigger-spec "every:5m" \
  --trigger-arguments 'measurement=equipment,field_change_count="status:3",window=15m,senders=slack' \
  equipment_monitor

# System Metrics Collector — collect host metrics every 30s
influxdb3 create trigger \
  --database monitoring \
  --plugin-filename "system_metrics/system_metrics.py" \
  --trigger-spec "every:30s" \
  --trigger-arguments 'hostname=db-server-01,include_cpu=true,include_memory=true,include_disk=true,include_network=true' \
  system_monitor

unset INFLUXDB3_AUTH_TOKEN INFLUXDB3_HOST_URL V3_TOKEN
```

## Managing Triggers

```bash
# Load V3_TOKEN from Secrets Manager as shown in the getting-started guide.
export INFLUXDB3_AUTH_TOKEN="$V3_TOKEN"
export INFLUXDB3_HOST_URL="https://<cluster-endpoint>:<port>"

# List triggers
influxdb3 show system summary --database <db>

# Disable a trigger
influxdb3 disable trigger --database <db> --trigger-name <name>

# Delete a trigger
influxdb3 delete trigger --database <db> --trigger-name <name>

unset INFLUXDB3_AUTH_TOKEN INFLUXDB3_HOST_URL V3_TOKEN
```

## Configuration Options

**Trigger arguments:** Pass key=value pairs to configure plugin behavior:

```bash
--trigger-arguments 'threshold=90,notify_email=admin@example.com'
```

**Secrets in plugin arguments:** Never place webhook URLs, API keys, tokens, or other credentials in `--trigger-arguments`, scripts, or source control — including values resolved from Secrets Manager at trigger-creation time, because the resolved value is persisted in the trigger specification. Use a plugin's reference-based secret mechanism only when its documentation confirms one; otherwise omit credential-bearing senders and tell the user the notification cannot be configured without exposing the secret.

**Exposure limitation:** A resolved secret written into a trigger specification can be queried in plaintext through `system.processing_engine_triggers`. Restrict access to database and system tables, and rotate any value exposed this way. Require encryption at rest and follow [encryption guidance](encryption.md); verify customer-managed KMS key support and encryption scope before recommending it. At-rest encryption protects stored media but does not prevent an authorized database user from querying the plaintext trigger argument. Verify native audit coverage for reads of this system table and monitor those events only when the engine documentation confirms they exist; do not claim that CloudTrail records data-plane reads.

**Error handling:** `--error-behavior log` (default), `retry`, or `disable`

**Async execution:** `--run-asynchronous` for heavy processing tasks

**TOML config files:** For complex configurations, use `--trigger-arguments "config_file_path=config.toml"`

## Multi-Node Deployment

| Plugin Type | Run On | Reason |
|-------------|--------|--------|
| Data write plugins | Ingester nodes | Process data at ingestion point |
| HTTP request plugins | Querier nodes | Handle API traffic |
| Scheduled plugins | Any configured node | Pin to single node to avoid duplicates |

## Monitoring Plugin Execution

```sql
-- View plugin logs
SELECT * FROM system.processing_engine_logs
WHERE trigger_name = 'your_trigger_name'
  AND time > now() - INTERVAL '1 hour'
ORDER BY event_time DESC;

-- Check trigger status
SELECT * FROM system.processing_engine_triggers
WHERE database = 'your_database';
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Plugin not triggering | Verify trigger is enabled via `influxdb3 show system summary`. Check trigger spec syntax |
| High memory usage | Reduce window sizes, adjust batch processing intervals |
| Duplicate processing on multi-node | Pin scheduled triggers to a single node |
| Too many alerts | Increase trigger counts/thresholds, add debounce duration |
| Custom plugin returns 404 | Verify the resolved `pluginRepositoryUrl` plus repository path and use the raw-content URL form required by the retrieved documentation |
| Private plugin returns 401/403 | Verify the repository-token secret requirements, token expiration, and read-only repository scope without exposing the token |
| Custom plugin import fails | Use only the standard library and pre-installed libraries confirmed by the retrieved documentation |

## Custom Plugin Limitations

Verify each limitation against the custom-plugin documentation before citing it.

- **Plugin file layout:** Report the supported file count, file type, and path resolution from the retrieved documentation.
- **Custom Python package installation:** When installation is unsupported, use only the standard library and documented pre-installed libraries.
- **In-place repository changes:** Verify the mutability of every repository field before proposing an update.
