# Processing Engine

## When to Activate

User asks about data processing plugins, triggers, downsampling, data transformation, alerting, or the Processing Engine feature of InfluxDB 3.

**Prerequisite:** Processing Engine is InfluxDB 3 only. If the user is on V2, inform them and offer to route to `migration`.

## Overview

The Processing Engine is an embedded Python virtual machine inside InfluxDB 3 that extends database functionality with plugins. **Only InfluxData certified plugins are supported** — custom user-written plugins are not supported.

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

## Trigger Types

| Trigger | Specification | When It Fires |
|---------|--------------|---------------|
| Data write | `table:<name>` or `all_tables` | When data is written to tables |
| Scheduled | `every:<interval>` or `cron:<expression>` | At specified intervals |
| HTTP request | `request:<endpoint>` | When HTTP requests hit the plugin endpoint |

## Creating Triggers

```bash
# Downsampler — aggregate CPU metrics hourly
influxdb3 create trigger \
  --database metrics \
  --plugin-filename "downsampler/downsampler.py" \
  --trigger-spec "every:1h" \
  --trigger-arguments 'source_measurement=cpu_detailed,target_measurement=cpu_hourly,interval=1h,window=6h,calculations="usage:avg.max_usage:max"' \
  cpu_downsampler

# MAD Anomaly Detection — real-time outlier detection on sensor data
# Fetch the Slack webhook from Secrets Manager — never hardcode secrets in trigger arguments
SLACK_WEBHOOK=$(aws secretsmanager get-secret-value --secret-id influxdb3/slack-webhook --query SecretString --output text)
influxdb3 create trigger \
  --database sensors \
  --plugin-filename "mad_check/mad_check_plugin.py" \
  --trigger-spec "all_tables" \
  --trigger-arguments "measurement=temperature_sensors,mad_thresholds=\"temp:2.5:20:5\",senders=slack,slack_webhook_url=\"$SLACK_WEBHOOK\"" \
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
```

## Managing Triggers

```bash
# List triggers
influxdb3 show system summary --database <db> --token <token>

# Disable a trigger
influxdb3 disable trigger --database <db> --trigger-name <name>

# Delete a trigger
influxdb3 delete trigger --database <db> --trigger-name <name>
```

## Configuration Options

**Trigger arguments:** Pass key=value pairs to configure plugin behavior:

```bash
--trigger-arguments 'threshold=90,notify_email=admin@example.com'
```

**Secrets in plugin arguments:** Do not hardcode webhook URLs, API keys, or other credentials directly in scripts or source control. Store them in AWS Secrets Manager and retrieve them at trigger-creation time (e.g., `aws secretsmanager get-secret-value` into an environment variable, as shown in the MAD anomaly-detection example above). **Limitation:** the resolved value is still written into the trigger spec and is visible in plaintext in `system.processing_engine_triggers` — this approach keeps secrets out of source control but does not protect them at rest inside InfluxDB. Restrict access to the database/system tables accordingly, and rotate any secret that is exposed this way.

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

## What's NOT Supported

- **Custom user-written plugins** — only InfluxData certified plugins are available. Custom user-written plugins are not supported.
- **Custom Python package installation** — plugins run with the packages bundled in the certified plugin set
- **Arbitrary filesystem or network access** — plugins operate within a constrained sandbox
