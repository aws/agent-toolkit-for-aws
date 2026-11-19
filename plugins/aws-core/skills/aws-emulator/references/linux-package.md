# Linux package: install and start

AWS Emulator runs natively **only on Linux**. On macOS and Windows, run it in Docker
([references/container.md](references/container.md)); that is also an option on Linux. No AWS account is needed.

Installing a package needs `sudo`; ask before running it.

## Contents

1. [Pre-check](#0-pre-check)
2. [Linux package](#linux-package)
3. [Start (Linux package)](#start-linux-package)
4. [Files it writes](#files-it-writes)
5. [Check it is up](#check-it-is-up)
6. [Stop](#stop)
7. [Smoke test with the AWS CLI](#smoke-test-with-the-aws-cli)

## 0. Pre-check

Check before installing or starting, and change nothing yet:

- `aws-emulator -v` prints the installed version (on Linux also try
  `/opt/aws-emulator/bin/aws-emulator -v`, in case it is not on `PATH`).
- On macOS and Windows, `docker info` must reach a running Docker daemon.
- The port (default 9297) must be free: `lsof -nP -iTCP:9297 -sTCP:LISTEN` prints nothing.

Tell the user what is missing and how to fix it, using the sections below and the
[AWS Emulator user guide](https://docs.aws.amazon.com/emulator/latest/userguide/).

## Linux package

Needs a 64-bit Linux (x86_64 or aarch64) that meets the system requirements in the
[user guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html).
Compare the distro's glibc (`ldd --version`) with the version the guide requires: on an older
one the package installs, but the emulator does not run; use Docker there instead.

```bash
# RPM (x86_64; use aws-emulator-aarch64.rpm on Arm)
sudo dnf install -y https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator-x86_64.rpm

# Debian (amd64; use aws-emulator_arm64.deb on Arm)
deb=$(mktemp -d)/aws-emulator.deb
curl -fsSLo "$deb" https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator_amd64.deb
sudo apt-get install -y "$deb"

export PATH=/opt/aws-emulator/bin:$PATH   # not on PATH by default; ask before adding it to ~/.bashrc
aws-emulator -v                           # Version, Release date, Commit
```

- Always install the `LTS/latest/` package, also in CI; do not pin a version. Security fixes and
  new coverage ship only in the latest release.
- **Upgrade:** stop the emulator, run the same `dnf install` or `apt-get install` command above
  (it replaces an older version), check `aws-emulator -v`, then start it again. The restart
  clears its state.
- Uninstall: stop it, `sudo dnf remove -y aws-emulator` or `sudo apt-get remove -y aws-emulator`,
  and remove the `PATH` line. `rm -rf ~/.aws/emulator` is a recursive delete of the emulator's
  settings, logs and any per-run files: ask the user and run it only after they explicitly
  confirm, never as part of a routine uninstall.

## Start (Linux package)

Run it in the background with `nohup`, so it outlives the shell call, and read its log instead
of blocking on it:

```bash
mkdir -p ~/.aws/emulator
nohup aws-emulator -p 9297 > ~/.aws/emulator/9297.log 2>&1 &   # https://127.0.0.1:9297, auth on
```

Add options to that one command: `-p 0` (the OS picks a free port; read it from the log),
`-p <port>` (0–65535), `-b <ip>` (bind address, default `127.0.0.1`; change it only inside a
container, see [references/container.md](references/container.md)), `-a off` (no signature checks,
no `emulator_credentials`; local tests only, reachable only on `127.0.0.1`), `-t off` (no telemetry),
`--idle-timeout 900` (exit after that many seconds without an API call, 1–31536000). Use one log per port.

Standard output is JSON lines (the address and port, the config, `ca.pem` and credentials file
paths); with `2>&1` the file also holds one plain-text telemetry notice from standard error. The
format is not a stable interface: use it only to read the port with `-p 0`, from the JSON line
that has it, and use the health route to check readiness. Unknown options exit with code 2. For every option: `aws-emulator -h`.

## Files it writes

Each start writes to `~/.aws/emulator/<port>/`, mode 0600, rewritten on every start:

- `config`: `[default]` profile with `region = us-east-1`, `endpoint_url`, `ca_bundle` and S3
  `signature_version = s3v4`.
- `emulator_credentials`: this run's key pair (access key IDs start with `EMULATOR`). Not written
  with `-a off`.
- `ca.pem`: this run's certificate; new on every start.

One folder per port, so emulators on different ports do not collide. A clean stop deletes the
files. `~/.aws/emulator/config.toml` is the emulator's own settings file (telemetry), not for SDKs.

## Check it is up

```bash
curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health   # 200, body "ok"
```

To wait in a script, loop on it (`curl -sf ... && break; sleep 1`, up to 30 tries) instead of
sleeping a fixed time. It is the only control route; there is no reset route.

## Stop

Ctrl+C, `SIGTERM` (`kill <pid>`), or the idle timeout stop it cleanly: it deletes its files and
all emulated resources are gone (state is in memory only). After a crash the files stay; the next
start on that port replaces them. To start with empty state, restart it.

## Smoke test with the AWS CLI

With the env file from [references/connect.md](references/connect.md), in one subshell:

```bash
( set -e; . ~/.aws/emulator/9297.env
  aws sts get-caller-identity --query Account --output text                         # 000000000000
  Q=$(aws sqs create-queue --queue-name smoke --query QueueUrl --output text)
  aws sqs send-message --queue-url "$Q" --message-body hello
  aws sqs receive-message --queue-url "$Q" --query 'Messages[0].Body' --output text   # hello
)
```

If any step fails, see [references/troubleshooting.md](references/troubleshooting.md).
