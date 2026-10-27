# Instrument a Node.js Application on Amazon EC2 with ADOT

Install the ADOT Node.js auto-instrumentation SDK on an EC2 instance and load it at application startup, by editing the instance's UserData (or the systemd unit that starts the app).

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-ec2.md](collector-ec2.md).

## Critical Requirements

**Do NOT:**

- Install or configure the CloudWatch Agent, or any collector, on the instance — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), where the CloudWatch Agent is the primary collector
- Set `OTEL_TRACES_SAMPLER=xray`, or any `localhost:4316` / `localhost:2000` endpoint — these stay forbidden in all cases
- Set `OTEL_EXPORTER_OTLP_*` — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Set `OTEL_AWS_APPLICATION_SIGNALS_*`, `OTEL_AWS_SERVICE_EVENTS_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the instance role — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which requires `CloudWatchAgentServerPolicy` on the instance role
- Run `cdk deploy` / `terraform apply`, or modify a running instance in place
- Remove or reorder existing UserData commands — append in sequence
- Modify `server.js` or any other application source file

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The instance may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ec2.md](collector-ec2.md)), the collector is what gets the IAM — the workload still gets none.

## Before you start: gather these values

If you cannot determine a value from the IaC, ask the user. Do not guess.

- **Deployment type** — read the UserData and find the command that starts the application. `docker run` / `docker start` → Docker. `node`, `npm start`, `yarn start` → runs directly on the instance. If it is unclear, ask.
- **Module format** — check `package.json`: `"type": "module"` → ESM; `"type": "commonjs"` or no `type` field → CommonJS.
- **`<APP_DIR>`** — where the application code lives on the instance (look for `cd`, `git clone`, or file copy commands). Needed for the non-Docker path, because the SDK must land in `<APP_DIR>/node_modules` for Node's module resolution to find it.
- **`<ENTRY_POINT>`** — the JavaScript file that starts the app (`server.js`, `index.js`, `app.js`).
- **`<SERVICE_NAME>`** — the application or stack name; becomes `OTEL_SERVICE_NAME`.
- **Instance OS** — Amazon Linux 2 uses `yum`, Amazon Linux 2023 uses `dnf`, Ubuntu/Debian uses `apt`. Look at the existing package commands in UserData or the AMI reference.

**Terraform heredoc warning:** when adding lines to a `user_data` heredoc, match the exact leading whitespace of the existing lines. `<<-EOF` only strips indentation when it is consistent; inconsistent indentation leaves spaces before `#!/bin/bash` and cloud-init fails.

## The application runs directly on the instance

### Step 1: Install the SDK into the application's directory

**CommonJS:**

```typescript
instance.userData.addCommands(
  '# Install ADOT Node.js auto-instrumentation. Must run in the app directory so the',
  '# package lands in <APP_DIR>/node_modules where Node module resolution finds it.',
  'cd <APP_DIR> && npm install @aws/aws-distro-opentelemetry-node-autoinstrumentation',
);
```

**ESM** — also install the instrumentation package, whose ESM hook is referenced by the loader flag:

```typescript
instance.userData.addCommands(
  'cd <APP_DIR> && npm install @aws/aws-distro-opentelemetry-node-autoinstrumentation @opentelemetry/instrumentation',
);
```

Place this after the application's own dependency install.

### Step 2: Load the SDK at startup

Find the existing `node` command and add the flags plus `OTEL_SERVICE_NAME`.

**CommonJS:**

```typescript
instance.userData.addCommands(
  'export OTEL_SERVICE_NAME=<SERVICE_NAME>',
  '',
  'cd <APP_DIR>',
  'node --require "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register" <ENTRY_POINT>',
);
```

**ESM:**

```typescript
instance.userData.addCommands(
  'export OTEL_SERVICE_NAME=<SERVICE_NAME>',
  '',
  'cd <APP_DIR>',
  'node --import "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register" \\',
  '  --experimental-loader=@opentelemetry/instrumentation/hook.mjs \\',
  '  <ENTRY_POINT>',
);
```

### If the application runs as a systemd service

An `export` in UserData does **not** reach a process started by a `.service` unit — `ExecStart` is a fresh process that does not inherit the UserData shell's environment. Put the variables on the unit instead:

```ini
# /etc/systemd/system/<SERVICE_NAME>.service  (add to the [Service] section)
[Service]
WorkingDirectory=<APP_DIR>
Environment=OTEL_SERVICE_NAME=<SERVICE_NAME>
ExecStart=/usr/bin/node --require "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register" <ENTRY_POINT>
```

Then add `systemctl daemon-reload` and `systemctl restart <SERVICE_NAME>` to UserData. (Equivalently, write the `KEY=VALUE` pairs to a file and reference it with `EnvironmentFile=`.)

## The application runs in a Docker container on the instance

The SDK has to be present *inside* the container — `npm install` in UserData installs on the host, where the containerized process cannot see it. There are two ways to get it there.

### Option A (preferred): bind-mount the SDK from the host — no image rebuild

Copy the SDK out of the ADOT image into a host directory, then mount that directory into the application container:

```typescript
instance.userData.addCommands(
  '# Stage the ADOT Node.js SDK on the host (look up the latest tag — see instrumentation.md)',
  'mkdir -p /opt/otel-auto-instrumentation-node',
  'docker run --rm \\',
  '  -v /opt/otel-auto-instrumentation-node:/dest \\',
  '  public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0 \\',
  '  cp -a /autoinstrumentation/. /dest',
);
```

Then add the mount and the environment variables to the existing `docker run`:

```typescript
instance.userData.addCommands(
  `docker run -d --name <APP_NAME> \\`,
  `  -v /opt/otel-auto-instrumentation-node:/otel-auto-instrumentation-node:ro \\`,
  `  -e NODE_OPTIONS=--require\\ /otel-auto-instrumentation-node/autoinstrumentation.js \\`,
  `  -e OTEL_SERVICE_NAME=<SERVICE_NAME> \\`,
  `  <IMAGE_URI>`,
);
```

For **ESM**, use:

```
NODE_OPTIONS=--import /otel-auto-instrumentation-node/autoinstrumentation.js --experimental-loader=/otel-auto-instrumentation-node/node_modules/@opentelemetry/instrumentation/hook.mjs
```

Keep every flag the existing `docker run` already had — ports, networks, volumes, restart policy. This option leaves the application image untouched.

### Option B: install the SDK in the image

If the user prefers the SDK baked into the image, add it to the `Dockerfile` after the existing dependency install and change `CMD`:

```dockerfile
RUN npm install @aws/aws-distro-opentelemetry-node-autoinstrumentation
# ESM also needs: @opentelemetry/instrumentation

# CommonJS
CMD ["node", "--require", "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register", "app.js"]
# ESM
# CMD ["node", "--import", "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register", "--experimental-loader=@opentelemetry/instrumentation/hook.mjs", "app.js"]
```

Add `-e OTEL_SERVICE_NAME=<SERVICE_NAME>` to the `docker run` either way. This option requires rebuilding and republishing the image, so mention that trade-off when you propose it.

## Verify

After the user deploys and the instance boots:

- Non-Docker: check the application's own log destination, or `journalctl -u <SERVICE_NAME>` for a systemd service. Grep the literal success string, `AWS Distro of OpenTelemetry automatic instrumentation started successfully` — **not** a bare `-i opentelemetry`, which also matches the benign `@aws/aws-distro-opentelemetry-instrumentation-vercel-ai Failed to register VercelAISpanProcessor` line that a healthy start always emits. `/var/log/cloud-init-output.log` shows whether the `npm install` succeeded.
- Docker: `docker logs <APP_NAME>`.

Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT Node.js auto-instrumentation into your EC2 deployment.

**Changes:**

- UserData: installed the ADOT Node.js SDK (or staged it on the host for a bind mount, for the Docker path)
- Startup: added the `node` loader flags — or `NODE_OPTIONS` for the container — and `OTEL_SERVICE_NAME`
- systemd unit, if the app runs as a service: added `Environment=` and updated `ExecStart` (an `export` in UserData would not reach it)

**Not changed:** your application source, the instance role's IAM policies, and the instance's software — no CloudWatch Agent or collector was installed.

**Next steps:**

1. Review the diff.
2. Deploy and replace the instance (UserData runs at first boot only).
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ec2.md](collector-ec2.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
