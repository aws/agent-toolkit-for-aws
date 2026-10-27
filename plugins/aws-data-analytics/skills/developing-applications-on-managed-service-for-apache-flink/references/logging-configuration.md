# Logging Configuration Guide

## Overview

This guide covers logging best practices for Amazon Managed Service for Apache Flink applications, including Managed Service for Apache Flink service-level vs. application-level logging, local development logging, production log level guidance, querying in CloudWatch Logs Insights, and rate-limited logging patterns for high-throughput operators. Use it when setting up logging for a new application, tuning log levels for production, or adding custom logging within Flink operators without flooding CloudWatch Logs.

### 1. Managed Service for Apache Flink Service-Level Monitoring Log Level

This is the log level configured through the Managed Service for Apache Flink API or console. It controls the application's log level.

- Set via the `MonitoringConfiguration.LogLevel` parameter in `CreateApplication` or `MonitoringConfigurationUpdate.LogLevelUpdate` in `UpdateApplication`.
- Also configurable in the console under the "Monitoring log level" section of the application configuration page.
- Valid values: `ERROR`, `WARN`, `INFO`, `DEBUG`.
- AWS recommends `INFO` because Apache Flink logs some errors at the INFO level rather than ERROR. Using ERROR alone may cause you to miss important failure information.
- `DEBUG` should only be used temporarily for troubleshooting — it significantly impacts application performance.

### 2. Application-Level Log4j2 Configuration

This is the Log4j2 configuration bundled inside your application JAR at `src/main/resources/log4j2.properties` (or `log4j2.xml`). **In Managed Service for Apache Flink, the service-level `MonitoringConfiguration.LogLevel` is the only log level control — it sets the application-wide log level. MSF does not support per-package or per-logger log level configuration through bundled Log4j2 config files.** Your bundled Log4j2 configuration is only used for local development. For per-package verbosity control in MSF, you can programmatically adjust log levels in your code using Log4j2's `Configurator.setLevel()` API, or use a separate DataStream with a sink (e.g., S3 or CloudWatch) for detailed debug output.

## Enabling CloudWatch Logging for an Managed Service for Apache Flink Application

To configure logging, you need:

1. **Create the CloudWatch log group AND a log stream inside it.** MSF does not auto-create either resource. If the log group exists but the log stream does not, MSF silently drops application logs — this is the most common cause of "logs configured but nothing shows up." Verify both with explicit CLI calls before changing log levels or redeploying:

   ```bash
   # Required: create the log group
   aws logs create-log-group --log-group-name /aws/kinesis-analytics/<app-name>

   # Required: create at least one log stream inside it (MSF needs this to exist)
   aws logs create-log-stream \
       --log-group-name /aws/kinesis-analytics/<app-name> \
       --log-stream-name kinesis-analytics-log-stream

   # Strongly recommended: set an explicit retention policy. CloudWatch defaults
   # to "never expire", which inflates storage cost over time. 30 days is a
   # reasonable production starting point; align with your audit requirements.
   aws logs put-retention-policy \
       --log-group-name /aws/kinesis-analytics/<app-name> \
       --retention-in-days 30
   ```

   Verify both resources exist:

   ```bash
   aws logs describe-log-groups --log-group-name-prefix /aws/kinesis-analytics/<app-name>
   aws logs describe-log-streams --log-group-name /aws/kinesis-analytics/<app-name>
   ```

2. Add the logging option to your application using `CreateApplication` (with `CloudWatchLoggingOptions`) or `AddApplicationCloudWatchLoggingOption` for an existing application. The `LogStreamARN` must point at the existing log stream from step 1, not just the log group.
3. Add the required IAM permissions to your application's service execution role:
   - `logs:PutLogEvents`
   - `logs:DescribeLogGroups`
   - `logs:DescribeLogStreams`

### Diagnosing "App is RUNNING but no logs in CloudWatch"

When an application is processing records but no logs appear, work this checklist in order — do **not** start by changing log level or redeploying, since the most common cause is a missing resource, not a verbosity issue.

1. **Confirm the logging option is attached.** Run `describe-application` and check `CloudWatchLoggingOptionDescriptions`. If empty or missing, that is the problem — re-run step 2 above.
2. **Confirm the log stream exists** (not just the log group). Run the `describe-log-streams` call above. A log group alone is not enough; without an existing stream, logs are silently dropped.
3. **Confirm IAM permissions on the execution role** include the three `logs:*` actions listed above. Missing permissions also cause silent log loss.
4. Only after the resource and permission checks pass should you investigate `MonitoringConfiguration.LogLevel` — and only then to confirm it is `INFO` (the AWS-recommended level), not as a fix for missing logs.

## Local Development Logging vs Managed Service for Apache Flink Logging

### Local Development (IDE / Docker / Flink Mini-Cluster)

When running locally, logging behaves differently from Managed Service for Apache Flink in several ways:

- Logs go to local stdout/stderr (your terminal or IDE console). There is no CloudWatch Logs integration.
- The Managed Service for Apache Flink service-level `MonitoringConfiguration` does not exist locally. Only your Log4j2 configuration applies.
- You can change log levels by editing `log4j2.properties` and restarting the application without redeploying a JAR.

### Managed Service for Apache Flink (Production / Staging)

- All stdout/stderr output from TaskManagers and JobManager is captured and forwarded to CloudWatch Logs automatically.
- The service-level monitoring log level is the only log level control. MSF does not apply bundled Log4j2 log level configurations — per-package or per-logger levels set in `log4j2.properties` are ignored.
- CloudWatch Logs charges $0.50/GB ingested and $0.03/GB stored per month — verbose logging has direct cost impact.
- The Managed Service for Apache Flink service-level log level can be changed via `UpdateApplication` without redeploying the JAR.
- For per-package verbosity control, programmatically adjust log levels in your code (e.g., `Configurator.setLevel("com.mypackage", Level.DEBUG)`), or use a separate DataStream with a sink for detailed debug output.

## Writing Custom Log Messages to CloudWatch Logs

You can write custom messages from your application code using either Log4j2 directly or SLF4J (which delegates to Log4j2 under the hood in Flink).

### Using SLF4J (Recommended)

SLF4J is the standard logging facade used throughout Flink's own codebase. Using it keeps your code consistent with Flink internals and avoids direct Log4j2 API coupling.

```java
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class MyFlinkJob {
    private static final Logger LOG = LoggerFactory.getLogger(MyFlinkJob.class);

    public static void main(String[] args) {
        LOG.info("Application starting with configuration: {}", config);
        // NOTE: If config contains user-controlled values, sanitize to prevent log injection:
        // String sanitized = config.toString().replaceAll("[\\r\\n]", "");
    }
}
```

No additional Maven dependencies are needed — SLF4J and the Log4j2 binding are included in the Flink runtime.

### Using Log4j2 Directly

If you prefer the Log4j2 API directly, add these dependencies to your `pom.xml`:

```xml
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-api</artifactId>
    <version>2.23.1</version>
</dependency>
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-core</artifactId>
    <version>2.23.1</version>
</dependency>
```

```java
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class MyFlinkJob {
    private static final Logger LOG = LogManager.getLogger(MyFlinkJob.class);

    public static void main(String[] args) {
        LOG.info("This message will appear in CloudWatch Logs");
    }
}
```

In Managed Service for Apache Flink, custom log messages appear in CloudWatch Logs as structured JSON entries containing fields like `locationInformation`, `logger`, `message`, `threadName`, `applicationARN`, `applicationVersionId`, and `messageType`.

AWS recommends using the `INFO` level for custom messages because the application log contains a large volume of entries — INFO-level messages are easier to filter.

## Managed Service for Apache Flink-Specific CloudWatch Logs Insights Queries

These queries target the structured log format that Managed Service for Apache Flink produces natively (with `applicationARN`, `messageType`, etc.) and are useful for operational analysis beyond application-level logging.

```
# Distribution of tasks across TaskManagers (set time range to a single job run)
fields @timestamp, message
| filter message like /Deploying/
| parse message " to flink-taskmanager-*" as @tmid
| stats count(*) by @tmid
| sort @timestamp desc
| limit 2000

# Subtasks assigned to each TaskManager
fields @timestamp, @tmid, @subtask
| filter message like /Deploying/
| parse message "Deploying * to flink-taskmanager-*" as @subtask, @tmid
| sort @timestamp desc
| limit 2000

# Detect parallelism changes (auto-scaling or manual)
fields @timestamp, @parallelism
| filter message like /property: parallelism.default, /
| parse message "default, *" as @parallelism
| sort @timestamp asc

# Access denied errors
fields @timestamp, @message, @messageType
| filter @message like /AccessDenied/
| sort @timestamp desc

# Source or sink not found (Kinesis stream/resource missing)
fields @timestamp, @message
| filter @message like /ResourceNotFoundException/
| sort @timestamp desc

# Task failures — application switching from RUNNING to RESTARTING
fields @timestamp, @message
| filter @message like /switched from RUNNING to RESTARTING/
| sort @timestamp desc
```
