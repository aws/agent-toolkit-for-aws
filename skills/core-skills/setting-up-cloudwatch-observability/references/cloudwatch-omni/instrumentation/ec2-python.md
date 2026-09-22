# Instrument a Python Application on Amazon EC2 with ADOT

Install the ADOT Python distro on an EC2 instance and start the application through the `opentelemetry-instrument` wrapper, by editing the instance's UserData (or the systemd unit that starts the app).

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
- Modify the application's `.py` files

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The instance may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ec2.md](collector-ec2.md)), the collector is what gets the IAM — the workload still gets none.

## Before you start: gather these values

If you cannot determine a value from the IaC, ask the user. Do not guess.

- **Deployment type** — read the UserData and find the command that starts the application. `docker run` / `docker start` → Docker. `python`, `flask run`, `gunicorn`, `uwsgi`, `manage.py runserver` → runs directly on the instance. If it is unclear, ask.
- **`<APP_DIR>`** — where the application code lives on the instance.
- **`<ENTRY_POINT>`** — the module or file that starts the app, and the exact startup command (it may be a WSGI/ASGI server rather than `python`).
- **`<SERVICE_NAME>`** — the application or stack name; becomes `OTEL_SERVICE_NAME`.
- **Virtual environment** — if the app runs from a venv, install into that venv (`<VENV>/bin/pip`) so `opentelemetry-instrument` resolves on the same interpreter.
- **Instance OS** — Amazon Linux 2 uses `yum`, Amazon Linux 2023 uses `dnf`, Ubuntu/Debian uses `apt`.

**Terraform heredoc warning:** when adding lines to a `user_data` heredoc, match the exact leading whitespace of the existing lines. `<<-EOF` only strips indentation when it is consistent; inconsistent indentation leaves spaces before `#!/bin/bash` and cloud-init fails.

## The application runs directly on the instance

### Step 1: Install the ADOT Python distro

```typescript
instance.userData.addCommands(
  '# Install the ADOT Python distro (provides the opentelemetry-instrument wrapper)',
  'pip install aws-opentelemetry-distro',
);
```

If the application runs from a virtual environment, install into it instead so the wrapper and the app share an interpreter:

```typescript
instance.userData.addCommands(
  '<VENV>/bin/pip install aws-opentelemetry-distro',
);
```

Place this after the application's own dependency install.

### Step 2: Start the application through the wrapper

Find the existing startup command and prefix it with `opentelemetry-instrument`, leaving the rest of the command exactly as it was:

```typescript
instance.userData.addCommands(
  'export OTEL_SERVICE_NAME=<SERVICE_NAME>',
  '',
  'cd <APP_DIR>',
  'opentelemetry-instrument python <ENTRY_POINT>',
);
```

The wrapper goes in front of whatever the app actually uses:

```bash
opentelemetry-instrument flask run
opentelemetry-instrument gunicorn -c gunicorn.conf.py app:app
opentelemetry-instrument uwsgi --ini uwsgi.ini
opentelemetry-instrument python manage.py runserver 0.0.0.0:<PORT> --noreload
```

For Django's dev server, `--noreload` is required — the autoreloader re-executes the process and the instrumentation is lost.

### If the application runs as a systemd service

An `export` in UserData does **not** reach a process started by a `.service` unit — `ExecStart` is a fresh process that does not inherit the UserData shell's environment. Put the variable on the unit and wrap `ExecStart`:

```ini
# /etc/systemd/system/<SERVICE_NAME>.service  (add to the [Service] section)
[Service]
WorkingDirectory=<APP_DIR>
Environment=OTEL_SERVICE_NAME=<SERVICE_NAME>
ExecStart=/usr/local/bin/opentelemetry-instrument /usr/bin/python <ENTRY_POINT>
```

`ExecStart` requires an absolute path for the first argument. Confirm where `opentelemetry-instrument` was installed (`/usr/local/bin/`, or `<VENV>/bin/` for a venv install) rather than assuming. Then add `systemctl daemon-reload` and `systemctl restart <SERVICE_NAME>` to UserData.

## The application runs in a Docker container on the instance

The distro has to be installed inside the container — a `pip install` in UserData installs on the host, where the containerized interpreter cannot see it. Unlike the other languages, the ADOT Python SDK is a Python package resolved by the container's own interpreter, so **the image has to be rebuilt**.

Add the install after the existing dependency install in the `Dockerfile`, and wrap `CMD`:

```dockerfile
# After the existing pip install / pip install -r requirements.txt
RUN pip install --no-cache-dir aws-opentelemetry-distro

# Wrap the existing CMD — keep its arguments unchanged
# Before: CMD ["python", "app.py"]
CMD ["opentelemetry-instrument", "python", "app.py"]

# Other shapes:
# CMD ["opentelemetry-instrument", "flask", "run"]
# CMD ["opentelemetry-instrument", "gunicorn", "-c", "gunicorn.conf.py", "djangoapp.wsgi:application"]
```

Then add the service name to the existing `docker run`, keeping every flag it already had:

```typescript
instance.userData.addCommands(
  `docker run -d --name <APP_NAME> \\`,
  `  -e OTEL_SERVICE_NAME=<SERVICE_NAME> \\`,
  `  <IMAGE_URI>`,
);
```

Tell the user this path requires rebuilding and republishing the image.

## Note on pre-fork servers

Gunicorn with its default sync workers and no `--preload` needs no special handling — instrumentation loads and produces both server spans and nested client spans normally.

The configurations that more often need attention are `--preload` and async worker classes (gevent, eventlet). If the workload uses one of those and no telemetry appears, the usual remedy is a Gunicorn `post_fork` hook that re-initializes the SDK — flag that to the user rather than changing the server configuration silently.

## Verify

After the user deploys and the instance boots:

- Non-Docker: check the application's log destination, or `journalctl -u <SERVICE_NAME> -o cat` for a systemd service. **ADOT Python prints no line containing "opentelemetry"** — grep for the real one: `Configuration of aws_configurator not loaded, configurator already loaded`. The `-o cat` matters: under the wrapper the syslog identifier is `opentelemetry-instrument[<pid>]`, so a plain `journalctl | grep -i opentelemetry` matches *every* line. `/var/log/cloud-init-output.log` shows whether the `pip install` succeeded.
- Docker: `docker logs <APP_NAME>`.

Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT Python auto-instrumentation into your EC2 deployment.

**Changes:**

- UserData (or Dockerfile, for the container path): installed `aws-opentelemetry-distro`
- Startup: prefixed the existing startup command with `opentelemetry-instrument` and set `OTEL_SERVICE_NAME`
- systemd unit, if the app runs as a service: added `Environment=` and wrapped `ExecStart` (an `export` in UserData would not reach it)

**Not changed:** your application source, the instance role's IAM policies, and the instance's software — no CloudWatch Agent or collector was installed.

**Next steps:**

1. Review the diff. If the app runs in Docker, the image needs a rebuild.
2. Deploy and replace the instance (UserData runs at first boot only).
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ec2.md](collector-ec2.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
