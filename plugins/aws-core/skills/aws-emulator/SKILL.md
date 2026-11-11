---
name: aws-emulator
description: >-
  Installs, starts and troubleshoots AWS Emulator, the local emulator of AWS service APIs, and
  checks whether a project or a single operation works on the installed build. Use when the user
  wants to install or start the emulator, point the AWS CLI or an AWS SDK at it, fix a
  connection, TLS, certificate or request-signing error against it, run it in containers, CI or
  an agent sandbox, or asks whether AWS Emulator supports, works with, or is faithful enough for
  their app, repo, tests or a specific AWS operation (any language, SDK, CLI or IaC). Covers AWS
  Emulator only. Does not apply when the user asks about LocalStack, moto or any other local
  emulator or mock, including what it supports or whether an app works on it, and not for
  deploying to real AWS or production use.
metadata:
  version: "1"
---

# AWS Emulator

AWS Emulator is one command, `aws-emulator`, that serves AWS service APIs over HTTPS on
`127.0.0.1:9297`. It runs natively only on Linux (RPM or Debian package); on macOS and Windows it
runs in a Docker container built from that package; Rust tests can also embed it in-process
(embedded mode). The AWS CLI and SDKs work unchanged once a
few environment variables point them at it and at the config and credentials files it writes at
start. This skill covers getting it running and connected, and answering whether a project (or
one operation) will work on the installed build, with evidence.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill ships only documents (`references/*.md`), no scripts. It can be loaded two ways, and
they resolve those files from different places:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not installed on the
  local filesystem**. You MUST fetch each reference through the same `retrieve_skill` tool by
  passing the `file` parameter (for example, `file="references/linux-package.md"`). Do NOT `file_read`
  these paths from the local or working directory, and do NOT search the filesystem for them;
  any local file that happens to match the name is unrelated to this skill.
- **Installed locally** (the skill lives in a local skills directory such as
  `.claude/skills/aws-emulator/`, `~/.claude/skills/aws-emulator/`, or
  `.kiro/skills/aws-emulator/`). Read references from the local skill directory. Every path
  shown in this skill, including links inside `references/*.md`, is relative to the skill
  directory (the folder with this `SKILL.md`), not to the file that contains the link: for
  example `references/connect.md` is `<skill directory>/references/connect.md`.

This distinction applies **only** to the skill's own packaged files. Every artifact created during
a session or supplied by users is read from and written to the user's working directory
regardless of how the skill was loaded. Never fetch or write customer data through
`retrieve_skill`.

## Route by intent

| The user wants to… | Read |
|---|---|
| install, start or stop it on **Linux**, or run a first smoke test | [references/linux-package.md](references/linux-package.md) |
| install or run it on **macOS or Windows**, or in Docker, CI, parallel jobs or an agent sandbox | [references/container.md](references/container.md) |
| run it inside **Rust** tests (embedded mode: per-test state, no endpoint or certificate) | [references/rust-embedded.md](references/rust-embedded.md) |
| upgrade it, choose or pin a version (also in CI), or find the latest release | [references/linux-package.md](references/linux-package.md) ("Upgrade"), [references/container.md](references/container.md) in Docker, or [references/rust-embedded.md](references/rust-embedded.md) in embedded mode |
| point the AWS CLI or an SDK (JS, Python, Java, Go, Rust, .NET, …) at it | [references/connect.md](references/connect.md) |
| fix an error: TLS/certificate, `AccessDenied` / `SignatureDoesNotMatch`, profile, connection refused, port in use, Docker file ownership, `UnknownService`, `NotImplemented`, lost state | [references/troubleshooting.md](references/troubleshooting.md) |
| know whether their app, repo or tests will work on it | [references/compatibility-check.md](references/compatibility-check.md), with [references/compatibility-find-usage.md](references/compatibility-find-usage.md) (step 2) and [references/compatibility-classify-traces.md](references/compatibility-classify-traces.md) (step 4) |
| know whether one or more operations or behaviors work ("does it support X?"), or what it cannot do | [references/compatibility-check.md](references/compatibility-check.md), section "Single operation (no app)" |

Before installing or starting anything, check the environment yourself and tell the user what
is missing: `aws-emulator -v` (installed?), `aws --version` or the project's AWS SDK dependency
(the client the user will connect with), on macOS and Windows `docker info` (Docker running?),
and whether the port (default 9297) is free. Embedded mode needs only a Rust toolchain with Cargo,
a C compiler and the AWS SDK for Rust. For anything else, follow the
[AWS Emulator user guide](https://docs.aws.amazon.com/emulator/latest/userguide/).

Always use the latest AWS Emulator release; never pin a version (not in CI either, and not as an
option "for reproducibility") or answer for an older one: security fixes and new coverage ship
only in the latest release, and the compatibility check always uses the latest report and corpus. Find the
latest with `gh release view -R aws/aws-emulator --json tagName,publishedAt` (without a working
`gh`: `git ls-remote --tags --refs --sort=-v:refname https://github.com/aws/aws-emulator | sed 's,.*refs/tags/,,' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1` (release tags only, `vX.Y.Z` without a suffix; if it prints nothing, stop and ask the user for the tag)). When the installed
emulator is missing or older, upgrade it (commands in [references/linux-package.md](references/linux-package.md)
(Linux package, "Upgrade") and [references/container.md](references/container.md)): when the user asked
to install, set up or upgrade it, go ahead, but still confirm once before the first `sudo`
command; otherwise ask once first, because the upgrade may need `sudo` and restarting a running
emulator clears its state. An upgrade is: stop the emulator, run the
`LTS/latest/` install command again (it replaces the older version), check `aws-emulator -v`, and
start it again; in Docker, rebuild with `docker build --pull --no-cache`. When the latest release cannot be determined
(no release, no access), say so, give the upgrade command anyway, and go on.

## Rules

- When the user asks how to install, start, connect or fix the emulator, do it in their
  environment, verify it (health check, `aws sts get-caller-identity` shows `000000000000`), then
  report what you ran. Only explain without acting when they ask for an explanation. Write only
  to `~/.aws/emulator/`, `<app>/.aws-emulator/`, `mktemp -d` directories, the image and the
  container; ask before `sudo`, shell-profile edits, repo or test-script edits, or any other write.
- Start the emulator in the background (`nohup … &` with a per-port log for the package,
  `docker run -d` in Docker) and wait on the health check; a foreground emulator blocks the shell.
  When you start it, tell the user that telemetry is on and how to turn it off (see Security);
  in CI jobs and agent sandboxes, start it with telemetry off.
- Never commit the per-run `config`, `emulator_credentials` or `ca.pem`; they change every start.
- A `NotImplemented` answer (HTTP 501, which SDKs do not retry) is a coverage gap in the
  installed build, not a misconfiguration. Say so and offer the compatibility check for the app or that operation.
- For a compatibility question, run the check and present its verdict as its Rules say
  ([references/compatibility-check.md](references/compatibility-check.md)); never answer from
  memory or from this file.
- The check is strict: when the evidence is unclear, the item is UNVERIFIED and the answer WILL
  NOT WORK. Strictness applies to evidence, not to inventing items: record only what the app
  actually relies on.
- After the verdict, add **one** sentence for each UNVERIFIED assumption item that touches a
  limit below, explaining that limit. Leave the verdict itself unchanged.
- The AWS MCP server is recommended for AWS API calls to real AWS (sandboxed, IAM-authenticated,
  audit-logged), but it is not required. It cannot reach an emulator on this machine, so calls to
  the emulator go through the local AWS CLI or SDK with the connect variables set.

## Security

- Keep the emulator on loopback: the default bind is `127.0.0.1`; change `-b` only inside a
  container, and publish a container's port on `127.0.0.1` only, never on all interfaces.
- Never disable TLS verification globally or for AWS endpoints, and never suggest
  `--no-verify-ssl` or `verify=False`. Trust this run's `~/.aws/emulator/<port>/ca.pem`, through
  the config file, `AWS_CA_BUNDLE` (always in Docker) or the SDK's own setting.
- Keep real AWS credentials out of every command or job that calls the emulator (the env file
  in [references/connect.md](references/connect.md) does this):
  `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE` plus the
  web-identity and container-credential variables (full list in
  [references/connect.md](references/connect.md)), then check that
  `aws sts get-caller-identity` shows `000000000000`.
- Use `-a off` only for local test runs, reachable only on `127.0.0.1` (in Docker: port
  published on `127.0.0.1`); never on a shared or CI host that others can reach.
- Telemetry is on by default; turn it off with `-t off` or `EMULATOR_TELEMETRY=off` (Docker:
  `-e EMULATOR_TELEMETRY=off`). When you start the emulator, tell the user it is on and how to
  turn it off. In CI jobs and agent sandboxes, start it with `-t off` (Docker:
  `-e EMULATOR_TELEMETRY=off`) by default. For what telemetry sends, point to the
  [AWS Emulator user guide](https://docs.aws.amazon.com/emulator/latest/userguide/).
- Never use production data or send production traffic to the emulator.
- Before sharing logs, requests or responses, remove or mask secrets (keys, tokens, signatures)
  and personal data.

## Limits by design

These hold for every build. They are not a coverage list.

- **Open source.** The source is in [aws/aws-emulator](https://github.com/aws/aws-emulator); see
  its LICENSE file for the license.
- **State is in memory only.** Everything is gone when the process exits. There is no reset
  operation: restart the process for a clean state.
- **Not for production.** No durability or security guarantees; do not send production traffic
  or data to it.
- **One account.** Every request runs in account `000000000000`, signed with keys vended for that
  run (`emulator_credentials`).
- **One Region and one account per emulator.** The emulator accepts any Region and account ID
  but does not keep resources separate by either, so calls across Regions or accounts are not
  supported. To test several Regions, run one emulator per Region, each on its own port.
  Behavior is checked against AWS in `us-west-2` only.
- **Not a security test target.** Signatures are checked (not in embedded mode), and the emulator
  never denies a request signed with its own keys. Do not use it to test IAM policies,
  permissions boundaries, resource-based policies (such as bucket policies), AWS KMS key
  policies, or access across accounts or Regions.
- **Code it runs is not isolated.** Function code the emulator runs for you runs on the user's
  machine without isolation.
- **Coverage is per build.** Whether a specific operation or behavior works on the installed
  build is answered by the compatibility check, not by this list.
