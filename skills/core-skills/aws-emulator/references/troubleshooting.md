# Troubleshooting

Start with the checks in [references/linux-package.md](references/linux-package.md) section 0 (`aws-emulator -v`, `docker info` on
macOS and Windows, the port is free), then find the symptom below. The
[AWS Emulator user guide](https://docs.aws.amazon.com/emulator/latest/userguide/) covers
the rest.

| Symptom | Cause | Fix |
|---|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED`, `self-signed certificate`, `unable to get local issuer certificate` | the client does not trust this run's `ca.pem` | `AWS_CONFIG_FILE=$HOME/.aws/emulator/<port>/config`; in Docker also `AWS_CA_BUNDLE=$HOME/.aws/emulator/<port>/ca.pem`; Node `NODE_EXTRA_CA_CERTS`, Rust/.NET `SSL_CERT_FILE`, Java a trust store ([references/connect.md](references/connect.md)). Never disable verification |
| `ca_bundle` file not found, or the path in the error starts with `/home/emulator/` | emulator runs in Docker; `config` names the container's path | keep `export AWS_CA_BUNDLE=$HOME/.aws/emulator/<port>/ca.pem` in the env file ([references/connect.md](references/connect.md)) |
| HTTP 403 `AccessDenied` "Sign the request with the emulator credentials" | unsigned, malformed signature, credential scope naming the wrong service, expired presigned URL, or signed with other keys (real AWS keys in `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` override the file), or keys from an earlier run or another port | `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE`; point `AWS_SHARED_CREDENTIALS_FILE` at this run's `emulator_credentials`; re-read it after a restart. Only for local tests, reachable only on `127.0.0.1` (in Docker: port published on `127.0.0.1`), never on a shared or CI host: start with `-a off` |
| HTTP 403 `SignatureDoesNotMatch` | right access key ID, wrong secret (stale file, copied by hand) or the body changed after signing | use this run's `emulator_credentials` unchanged |
| `aws sts get-caller-identity` shows a real account | requests go to AWS: `AWS_ENDPOINT_URL` not set for this command | run it in a subshell with the env file from [references/connect.md](references/connect.md), or set the variables in the script that runs the code |
| `The config profile (<name>) could not be found` | `AWS_PROFILE` names a profile the emulator's `config` lacks | `unset AWS_PROFILE` |
| `emulator serve failed: server I/O error: Address already in use` (exit 1) | another emulator or process holds the port | another port (`-p 9300`, or `-p 0` with the package); `lsof -nP -iTCP:<port> -sTCP:LISTEN` finds the holder |
| Exit code 2 at start | unknown option | check `aws-emulator -h` |
| Emulator does not run on an older distro (glibc errors) | the distro's glibc is older than the [user guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html) requires | a current distro, or Docker |
| macOS or Windows: no `aws-emulator` package or binary | it runs natively only on Linux | run it in Docker ([references/container.md](references/container.md)) |
| `aws-emulator: command not found` after installing the package | `/opt/aws-emulator/bin` is not on `PATH` | `export PATH=/opt/aws-emulator/bin:$PATH` (and add it to the shell profile) |
| Docker: SDK cannot read `~/.aws/emulator/...`, files owned by root | `~/.aws/emulator/<port>` did not exist, so Docker created it as root; or Linux host without `--user` | stop it; ask the user before running `sudo chown -R "$USER" ~/.aws/emulator/<port>` (only that folder), or remove and recreate it with `mkdir -p ~/.aws/emulator/<port>` if it holds nothing to keep; on Linux add `--user "$(id -u):$(id -g)"` |
| Docker: `Connection refused` or connection reset on the host port | host and container ports differ, the emulator was not bound to `0.0.0.0`, or it is still starting | same port on both sides (`-p 127.0.0.1:9300:9300 ... aws-emulator -p 9300`); keep `-b 0.0.0.0` in the `ENTRYPOINT`; wait on the health check |
| Docker build: `exec format error` or very slow start | RPM for the wrong CPU | `aws-emulator-aarch64.rpm` on Apple silicon/Arm, `-x86_64.rpm` on Intel/AMD |
| `Connection refused` (package) | not running or wrong port | read the port from the startup log; check the process is still up |
| `UnknownService: could not resolve a target service` | raw HTTP request without SigV4 scope, `X-Amz-Target` or service Host header, or a route that does not exist (e.g. `/__admin/reset`) | call through the CLI or an SDK; `/__admin/health` is the only control route |
| `NotImplemented` or HTTP 501 | operation not implemented in the installed build (coverage gap, not a misconfiguration); SDKs do not retry it | if the installed version is older than the latest release, upgrade first (SKILL.md); then offer the compatibility check ([references/compatibility-check.md](references/compatibility-check.md)) for the app or that operation |
| State disappeared | the emulator stopped or restarted | expected: state is in memory only; there is no reset route, restart for a clean state |
| Files left in `~/.aws/emulator/<port>/` | the process crashed or was killed | harmless; the next start on that port replaces them |
| `ResourceNotFoundException ... state CREATING` right after `CreateTable` | the table is still being created, as on AWS | poll `DescribeTable` until `TableStatus` is `ACTIVE` |

## Reporting issues

Issues go to https://github.com/aws/aws-emulator/issues through the forms in the repository's
`.github/ISSUE_TEMPLATE/`. List them and choose the form whose `name` and `description` fit the
problem (`config.yml` is not a form):

```sh
gh api repos/aws/aws-emulator/contents/.github/ISSUE_TEMPLATE --jq '.[].name'
gh api repos/aws/aws-emulator/contents/.github/ISSUE_TEMPLATE/<form>.yml --jq .content | base64 -d
```

Security problems are never filed as issues: point the user to
https://aws.amazon.com/security/vulnerability-reporting/ and stop. If no form fits, tell the user
so and don't file an issue.

Before drafting:

1. Search for an existing report: `gh issue list -R aws/aws-emulator --state all --search "<operation or error>"`,
   and the known gaps in the repository's `issues/things-that-do-not-work/`:
   `gh api 'repos/aws/aws-emulator/git/trees/main?recursive=1' --jq '.tree[].path' | grep -i '<operation>'`.
   If an issue matches, give the user its link (suggest a 👍 reaction on an open issue) and don't
   file. If only a file in `issues/things-that-do-not-work/` matches, give the user the link to the
   file, say the gap is already known and tracked there (files can't be upvoted), and don't file.
2. Check the latest release: for a difference from AWS, confirm it still happens there (if the
   installed version is older, offer to upgrade first (SKILL.md) and reproduce again); for a
   feature request, check its release notes don't already add it. Don't stop for this: draft the
   issue and note what still needs checking.

Then draft the body from the chosen form: each field's `label` becomes a `### <label>` heading,
in the form's order, filled as its `description` asks; tick the checkboxes with `- [x]` and
their labels. Fill every required field, and skip optional fields you have nothing for.

Remove or mask access keys, secret keys, session tokens, `Authorization` and
`X-Amz-Security-Token` headers, signatures, real AWS account IDs and personal data. Show the user
the full title and body in your reply (not only a file path), and ask whether to file it. Only after they confirm, file it and give them
the issue URL:

```sh
gh issue create -R aws/aws-emulator --title "<title>" --body-file "<draft>"
```

Don't pass `--label`: an issue filed this way gets no labels from the form, and the
maintainers label it during triage. Without a working `gh`, give the user the form link
instead, `https://github.com/aws/aws-emulator/issues/new?template=<form>.yml`, and the draft to
paste.
