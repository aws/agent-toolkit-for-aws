# Instrument a Java Application on Amazon EC2 with ADOT

Download the ADOT Java agent jar onto an EC2 instance and attach it with `JAVA_TOOL_OPTIONS`, by editing the instance's UserData (or the systemd unit that starts the app).

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-ec2.md](collector-ec2.md).

Java is the least invasive of the four languages here: the agent is a single jar and the JVM attaches it from an environment variable, so nothing is installed into the application's own dependencies and no image rebuild is needed on either the host or the Docker path.

## Critical Requirements

**Do NOT:**

- Install or configure the CloudWatch Agent, or any collector, on the instance — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), where the CloudWatch Agent is the primary collector
- Set `OTEL_TRACES_SAMPLER=xray`, or any `localhost:4316` / `localhost:2000` endpoint — these stay forbidden in all cases
- Set `OTEL_EXPORTER_OTLP_*` — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Set `OTEL_AWS_APPLICATION_SIGNALS_*`, `OTEL_AWS_SERVICE_EVENTS_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the instance role — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which requires `CloudWatchAgentServerPolicy` on the instance role
- Run `cdk deploy` / `terraform apply`, or modify a running instance in place
- Remove or reorder existing UserData commands — append in sequence
- Modify the application's `.java` files or its build configuration

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The instance may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ec2.md](collector-ec2.md)), the collector is what gets the IAM — the workload still gets none.

## Before you start: gather these values

If you cannot determine a value from the IaC, ask the user. Do not guess.

- **Deployment type** — read the UserData and find the command that starts the application. `docker run` / `docker start` → Docker. `java -jar`, `./gradlew bootRun`, a `catalina.sh`/Tomcat script → runs directly on the instance. If it is unclear, ask.
- **`<APP_DIR>`** and the exact startup command.
- **`<SERVICE_NAME>`** — the application or stack name; becomes `OTEL_SERVICE_NAME`.
- **Whether `JAVA_TOOL_OPTIONS` is already set** anywhere — UserData, the systemd unit, the Dockerfile, or the `docker run`. If it is, the `-javaagent` flag must be appended to the existing value, not written over it.
- **Instance OS** — Amazon Linux 2 uses `yum`, Amazon Linux 2023 uses `dnf`, Ubuntu/Debian uses `apt`.

**Terraform heredoc warning:** when adding lines to a `user_data` heredoc, match the exact leading whitespace of the existing lines. `<<-EOF` only strips indentation when it is consistent; inconsistent indentation leaves spaces before `#!/bin/bash` and cloud-init fails.

## The application runs directly on the instance

### Step 1: Download the agent jar

```typescript
instance.userData.addCommands(
  '# Download the ADOT Java agent (latest release)',
  // -f: without it an HTTP error body is written into the .jar and curl still exits 0, so the
  //     failure surfaces later as a JVM that will not start on a corrupt agent jar.
  // --retry: this download runs early in UserData; a transient failure under `set -e` aborts every
  //     later command. See the placement note in collector-ec2.md.
  'curl -fsSLo /opt/aws-opentelemetry-agent.jar \\',
  '  --retry 5 --retry-delay 5 --retry-connrefused \\',
  '  https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest/download/aws-opentelemetry-agent.jar',
);
```

Place this before the application starts. To pin a version instead of tracking latest, see the source-of-truth links in [instrumentation.md](instrumentation.md).

### Step 2: Attach the agent at startup

The startup command itself does not change — the JVM picks the agent up from the environment:

```typescript
instance.userData.addCommands(
  'export JAVA_TOOL_OPTIONS=-javaagent:/opt/aws-opentelemetry-agent.jar',
  'export OTEL_SERVICE_NAME=<SERVICE_NAME>',
  '',
  '# Existing startup command remains unchanged',
  'cd <APP_DIR>',
  'java -jar <APP_JAR>',
);
```

If `JAVA_TOOL_OPTIONS` is already set, append rather than replace — dropping existing JVM flags (heap settings, GC options, other agents) will change how the application runs:

```bash
export JAVA_TOOL_OPTIONS="$JAVA_TOOL_OPTIONS -javaagent:/opt/aws-opentelemetry-agent.jar"
```

### If the application runs as a systemd service

An `export` in UserData does **not** reach a process started by a `.service` unit — `ExecStart` is a fresh process that does not inherit the UserData shell's environment. Put the variables on the unit:

```ini
# /etc/systemd/system/<SERVICE_NAME>.service  (add to the [Service] section)
[Service]
Environment=JAVA_TOOL_OPTIONS=-javaagent:/opt/aws-opentelemetry-agent.jar
Environment=OTEL_SERVICE_NAME=<SERVICE_NAME>
```

`ExecStart` does not need to change. Then add `systemctl daemon-reload` and `systemctl restart <SERVICE_NAME>` to UserData.

**If the unit already has a `JAVA_TOOL_OPTIONS=` line, edit that line — and QUOTE the whole assignment.** Do not add a second `Environment=` for the same variable; the later assignment overrides the earlier one. Quoting is load-bearing, not style: systemd treats space-separated tokens on one `Environment=` line as *separate* assignments, so an unquoted append silently drops the `-javaagent` flag.

```ini
# WRONG -- systemd logs `Invalid environment assignment, ignoring: -javaagent:...` and the
# process receives only `-Xmx256m`. The app starts normally, serves traffic, and emits nothing.
Environment=JAVA_TOOL_OPTIONS=-Xmx256m -javaagent:/opt/aws-opentelemetry-agent.jar

# RIGHT -- the process receives both flags
Environment="JAVA_TOOL_OPTIONS=-Xmx256m -javaagent:/opt/aws-opentelemetry-agent.jar"
```

Note also that systemd does **no** shell expansion here: the `export JAVA_TOOL_OPTIONS="$JAVA_TOOL_OPTIONS -javaagent:..."` idiom shown above for the shell case does not work in a unit file — it would pass the literal string `$JAVA_TOOL_OPTIONS` to the JVM. Write the existing flags out explicitly.

Confirm with `systemctl show <SERVICE_NAME> --property=Environment`, then check the JVM echoed **the flag itself**, not just the line: `journalctl -u <SERVICE_NAME> | grep 'Picked up JAVA_TOOL_OPTIONS.*javaagent'`. Grepping only for `Picked up JAVA_TOOL_OPTIONS` matches the broken unquoted case above too, where the JVM prints the line with the pre-existing flags and no `-javaagent`.

## The application runs in a Docker container on the instance

The agent jar has to be visible inside the container. Bind-mount it from the host — no image rebuild:

```typescript
instance.userData.addCommands(
  '# Download the agent jar on the host',
  // -f: without it an HTTP error body is written into the .jar and curl still exits 0, so the
  //     failure surfaces later as a JVM that will not start on a corrupt agent jar.
  // --retry: this download runs early in UserData; a transient failure under `set -e` aborts every
  //     later command. See the placement note in collector-ec2.md.
  'curl -fsSLo /opt/aws-opentelemetry-agent.jar \\',
  '  --retry 5 --retry-delay 5 --retry-connrefused \\',
  '  https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest/download/aws-opentelemetry-agent.jar',
  '',
  '# Mount it into the container and attach it via JAVA_TOOL_OPTIONS',
  `docker run -d --name <APP_NAME> \\`,
  `  -v /opt/aws-opentelemetry-agent.jar:/opt/aws-opentelemetry-agent.jar:ro \\`,
  `  -e JAVA_TOOL_OPTIONS=-javaagent:/opt/aws-opentelemetry-agent.jar \\`,
  `  -e OTEL_SERVICE_NAME=<SERVICE_NAME> \\`,
  `  <IMAGE_URI>`,
);
```

Keep every flag the existing `docker run` already had — ports, networks, volumes, restart policy. The application image and its `Dockerfile` are untouched.

If the user prefers the agent baked into the image, the alternative is a `Dockerfile` line — `RUN curl -Lo /opt/aws-opentelemetry-agent.jar <release-url>` — plus the same `JAVA_TOOL_OPTIONS`; mention that it requires rebuilding and republishing the image.

## Verify

After the user deploys and the instance boots, look for the JVM's `Picked up JAVA_TOOL_OPTIONS:` line listing the `-javaagent` flag — that confirms the agent attached.

- Non-Docker: the application's log destination, or `journalctl -u <SERVICE_NAME>` for a systemd service. `/var/log/cloud-init-output.log` shows whether the `curl` succeeded.
- Docker: `docker logs <APP_NAME>`.

Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired the ADOT Java auto-instrumentation agent into your EC2 deployment.

**Changes:**

- UserData: downloaded `aws-opentelemetry-agent.jar` to `/opt`
- Startup: set `JAVA_TOOL_OPTIONS` (appended to any existing value) and `OTEL_SERVICE_NAME` — your startup command is unchanged
- systemd unit, if the app runs as a service: added `Environment=` lines (an `export` in UserData would not reach it)
- Docker path: bind-mounted the jar into the container, so your image and `Dockerfile` are unchanged

**Not changed:** your application source and build config, the instance role's IAM policies, and the instance's software — no CloudWatch Agent or collector was installed.

**Next steps:**

1. Review the diff — confirm `JAVA_TOOL_OPTIONS` preserves any JVM flags already in use.
2. Deploy and replace the instance (UserData runs at first boot only). Look for the `Picked up JAVA_TOOL_OPTIONS:` line.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the agent is using its default (`localhost:4317`, gRPC — the Java agent's default, not 4318). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ec2.md](collector-ec2.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
