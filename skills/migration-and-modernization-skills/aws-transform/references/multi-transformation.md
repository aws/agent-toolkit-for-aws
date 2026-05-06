# Multi-Transformation

Apply TDs to multiple repositories in parallel. TD-to-repo assignments and config
are already confirmed from the match report. Do NOT re-discover TDs or re-prompt.

## Input

From the match report: repo list, TD per repo, config per TD, execution mode.

## Prerequisite Check (Once Only)

Verify AWS credentials ONCE. Do NOT repeat per repo.

```bash
aws sts get-caller-identity
```

Local mode also: `atx --version`

## Local Execution

If any repos were provided as git URLs (HTTPS or SSH), clone them locally first.
The user's local git config handles authentication — no Secrets Manager needed.

```bash
CLONE_DIR=~/.aws/atx/custom/atx-agent-session/repos/<repo-name>-$SESSION_TS
git clone <git-url> "$CLONE_DIR"
```

If repos were provided as an S3 bucket path with zips, download and extract locally:

```bash
mkdir -p ~/.aws/atx/custom/atx-agent-session/repos
aws s3 sync s3://user-bucket/repos/ ~/.aws/atx/custom/atx-agent-session/repos/ --exclude "*" --include "*.zip"
for zip in ~/.aws/atx/custom/atx-agent-session/repos/*.zip; do
  name=$(basename "$zip" .zip)
  unzip -qo "$zip" -d "$HOME/.aws/atx/custom/atx-agent-session/repos/${name}-$SESSION_TS/"
done
```

Use the cloned/extracted paths as `<repo-path>` for each repo.

For each repo, verify it's a git repo:

```bash
ls -la <repo-path>
git -C <repo-path> status
```

If not a git repo: `cd <repo-path> && git init && git add . && git commit -m "Initial commit"`

The active language runtime must match the transformation's target version so that
builds and tests run correctly. Check the current version, and if there is a
mismatch, first check whether the target version is already installed (e.g.,
`/usr/libexec/java_home -V 2>&1` (macOS) or `ls /usr/lib/jvm/` (Linux), `pyenv versions`, `nvm ls`). If found, switch
to it (e.g., `export JAVA_HOME=<path to JDK> && export PATH="$JAVA_HOME/bin:$PATH"`, `pyenv shell 3.12`, `nvm use 22`). Only if
the target version is not installed at all, ask the user for permission before installing. Suggest:

- Java: `brew install --cask corretto23` (macOS), `sudo yum install java-23-amazon-corretto-devel` (RHEL/AL2), or `sudo apt install java-23-amazon-corretto-jdk` (Debian/Ubuntu)
- Python: `pyenv install 3.15.0 && pyenv shell 3.15.0`
- Node.js: `nvm install 23 && nvm use 23`

Do NOT proceed until the correct version is active. Verify the switch succeeded
before proceeding.

### Telemetry

When running `atx custom def exec`, always include the `--telemetry` flag (see the Telemetry section in SKILL.md). Format:
`--telemetry "client=<client>,agent=<agent>,executionMode=<local|remote>"`

- `client` is the MCP client or tool hosting this session (lowercase, no spaces) — e.g., `kiro`, `vscode`, `cursor`, `windsurf`, `claudecode`. Use the real tool name, not a default.
- `agent` is the AI assistant driving this session (lowercase, no spaces) — e.g., `kiro`, `amazonq`, `claude`, `copilot`, `cline`, `codex`. Use the real assistant name, not a default.
- `executionMode` is `local` for direct CLI invocation, `remote` when submitting via Lambda

Run transformations in parallel — maximum 3 concurrent repos at a time (the user
can override this, but 3 is recommended to avoid overloading the machine). If there
are more than 3 repos, process them in batches of 3 (wait for a batch to finish
before starting the next). Maximum 9 repos total for local mode (user can override,
but recommend remote mode for more). If the total repo count exceeds 9, suggest
remote mode instead.

For each repo, use bash to create a runner script that captures the exit code, following this exact format:

```bash
mkdir -p ~/.aws/atx/custom/atx-agent-session
cat > ~/.aws/atx/custom/atx-agent-session/run-<repo-name>.sh << 'RUNNER'
#!/bin/bash
atx custom def exec -n <td-name> -p <repo-path> -x -t \
  --configuration 'additionalPlanContext=<config>' \
  --telemetry "client=<client>,agent=<agent>,executionMode=local"
echo $? > ~/.aws/atx/custom/atx-agent-session/<repo-name>.exit
RUNNER
chmod +x ~/.aws/atx/custom/atx-agent-session/run-<repo-name>.sh
nohup ~/.aws/atx/custom/atx-agent-session/run-<repo-name>.sh > ~/.aws/atx/custom/atx-agent-session/<repo-name>.log 2>&1 &
echo $! > ~/.aws/atx/custom/atx-agent-session/<repo-name>.pid
```

Omit `--configuration` if no config needed. The `--telemetry` flag is always included — see the Telemetry section above for field values. Launch each repo's script in rapid
succession — do NOT wait between launches. Each runner script is backgrounded
via nohup; the exit code is captured to `~/.aws/atx/custom/atx-agent-session/<repo-name>.exit` when ATX finishes.

After launching all repos, find each repo's conversation log by grepping its
process log (ATX outputs the path within 30-60 seconds of starting):

```bash
grep "Conversation log:" ~/.aws/atx/custom/atx-agent-session/<repo-name>.log 2>/dev/null
```

If it hasn't appeared yet, wait 15 seconds and retry. Extract the full path from
each — do NOT use `ls -t` across all conversations, as that may match a different run.

Then start monitoring. On each 60-second cycle:

1. Check each PID: `kill -0 $(cat ~/.aws/atx/custom/atx-agent-session/<repo-name>.pid) 2>/dev/null && echo "RUNNING" || echo "DONE"`
2. Tail each repo's conversation log and relay progress to the user
3. Report which repos are still running, which have completed

**You MUST continue polling without waiting for user input.** The user should see
continuous progress updates across all repos.

A repo's transformation is done ONLY when its background process exits (i.e.,
`kill -0` returns non-zero). Do NOT treat exit code 0 from any other command
(grep, cat, test, ls, etc.) as transformation completion. Do NOT treat log
messages like "TRANSFORMATION COMPLETE" as completion — ATX performs additional
steps after that (validation summary generation).

## Remote Execution

Prepare each repo's source before submitting the batch. Follow the source prep
rules from single-transformation.md: HTTPS and SSH git URLs (with credentials
configured) are passed directly; S3 zips from the user's bucket must be copied
to the managed source bucket (`atx-source-code-{account}`) first; local repos
must be zipped and uploaded to the same managed bucket.

Submit jobs via the batch Lambda in chunks of up to 128. If there are more than
128 jobs, split them into multiple `atx-trigger-batch-jobs` calls (e.g., 500 repos
= 4 calls of 128 + 128 + 128 + 116). Each call returns its own `batchId`. Track
all batch IDs for monitoring.

Include the `environment` field on each job to set the language version matching the transformation's target (e.g., `"JAVA_VERSION":"21"` for a Java upgrade targeting 21). Include `--telemetry` in each job's `command` string always (see Telemetry section):

```bash
aws lambda invoke --function-name atx-trigger-batch-jobs \
  --payload '{"batchName":"<name>-chunk-1","jobs":[{"source":"<url>","command":"atx custom def exec -n <td> -p /source/<project> -x -t --telemetry \"client=<client>,agent=<agent>,executionMode=remote\"","jobName":"<name>","environment":{"JAVA_VERSION":"<target>"}}]}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

If the total exceeds 128, repeat with the next chunk:

```bash
aws lambda invoke --function-name atx-trigger-batch-jobs \
  --payload '{"batchName":"<name>-chunk-2","jobs":[...next 128 jobs...]}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Monitor each batch by its `batchId`:

```bash
aws lambda invoke --function-name atx-get-batch-status \
  --payload '{"batchId":"<batch-id>"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Polling: every 60 seconds for the first 10 polls, then every 5 minutes after.
Report only on status change.

## Progress Reporting

```
[1/N] repo-name          TD-name                    Status
[2/N] repo-name          TD-name                    Status
```

## Result Collection

Collect per repo: success/failure, transformed code path, error details.

```
Succeeded:
- repo-name: TD-name (config)
Failed:
- repo-name: TD-name (error)
```

For remote executions, include the CloudWatch dashboard link in the final output:

```bash
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null)}}
REGION=${REGION:-us-east-1}
echo "https://${REGION}.console.aws.amazon.com/cloudwatch/home#dashboards/dashboard/ATX-Transform-CLI-Dashboard"
```

Hand off to [results-synthesis.md](results-synthesis.md) for consolidated reporting.

## Error Handling

| Scenario | Action |
|----------|--------|
| Git clone fails | Log error, continue with remaining repos |
| Transformation fails | Log repo and error, do not auto-retry |
| Partial results | Generate summary from successes, report failures |

## MANDATORY: Cleanup

Clean up session files **before starting** and **after completing** each batch:

```bash
[ -d ~/.aws/atx/custom/atx-agent-session ] && find ~/.aws/atx/custom/atx-agent-session -maxdepth 1 -type f \( -name "*.sh" -o -name "*.log" -o -name "*.pid" -o -name "*.exit" -o -name "*.zip" \) -delete 2>/dev/null || true
```

For remote mode: after presenting results, also prompt the user about infrastructure
teardown. See the Cleanup section in [remote-execution.md](remote-execution.md)
for the exact prompt and flow.

## Key Principles

1. Single prerequisite check — never repeat for parallel tasks
2. Trust the match report — do not re-discover TDs
3. Local parallel execution — maximum 3 concurrent repos (user-overridable); recommend remote for more than 9
4. Remote parallel execution — submit in chunks of up to 128 jobs per `atx-trigger-batch-jobs` call; split larger sets into multiple calls (max 512 repos per session)
5. Skip prerequisite checks in parallel task prompts
