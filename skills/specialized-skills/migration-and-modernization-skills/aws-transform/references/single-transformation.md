# Single Transformation

Apply one TD to one repo. TD, config, and repo are already confirmed from the match report.

## Local Mode

### 1. Verify ATX (once per session, skip if already verified)

```bash
atx --version
```

### 2. Verify Language Version
The active language runtime must match the transformation's target version so that builds and tests run correctly. For example, a Java 8 → 17 upgrade needs Java 17 available locally.

Check the installed version matches the target:

```bash
java -version    # Java transformations
python3 --version # Python transformations
node --version   # Node.js transformations
```

If there is a mismatch, resolve it before proceeding:

- Look for the correct version already installed (e.g., check `/usr/lib/jvm/`, `pyenv versions`, `nvm ls`)
- If found, switch to it (e.g., `export JAVA_HOME=<path to JDK> && export PATH="$JAVA_HOME/bin:$PATH"`, `pyenv shell 3.12`, `nvm use 22`)
- If not installed, ask the user for permission before installing (e.g., `brew install --cask corretto17` (macOS), `sudo yum install java-17-amazon-corretto-devel` (RHEL/AL2), or `sudo apt install java-17-amazon-corretto-jdk` (Debian/Ubuntu), `pyenv install 3.12`, `nvm install 22`)
- Verify the switch succeeded by re-checking the version before continuing

### 3. Prepare Source

If the user provided a git URL (HTTPS or SSH) instead of a local path, clone it
locally first. The user's local git config handles authentication for private repos
— no Secrets Manager setup needed in local mode.

```bash
CLONE_DIR=~/.aws/atx/custom/atx-agent-session/repos/<repo-name>-$SESSION_TS
git clone <git-url> "$CLONE_DIR"
```

If the user provided an S3 path to a zip, download and extract it locally:

```bash
aws s3 cp s3://user-bucket/repos/<project>.zip ~/.aws/atx/custom/atx-agent-session/<project>-$SESSION_TS.zip
unzip -qo ~/.aws/atx/custom/atx-agent-session/<project>-$SESSION_TS.zip -d ~/.aws/atx/custom/atx-agent-session/repos/<project>-$SESSION_TS/
```

Use the cloned/extracted path as `<repo-path>` for all subsequent steps. If the
user provided a local path, use it directly.

### 4. Validate Repository

```bash
ls -la <repo-path>
git -C <repo-path> status
```

If not a git repo: `cd <repo-path> && git init && git add . && git commit -m "Initial commit"`

### Telemetry

When running `atx custom def exec`, always include the `--telemetry` flag (see the Telemetry section in SKILL.md). Format:
`--telemetry "client=<client>,agent=<agent>,executionMode=<local|remote>"`

- `client` is the MCP client or tool hosting this session (lowercase, no spaces) — e.g., `kiro`, `vscode`, `cursor`, `windsurf`, `claudecode`. Use the real tool name, not a default.
- `agent` is the AI assistant driving this session (lowercase, no spaces) — e.g., `kiro`, `amazonq`, `claude`, `copilot`, `cline`, `codex`. Use the real assistant name, not a default.
- `executionMode` is `local` for direct CLI invocation, `remote` when submitting via Lambda

### 5. Execute and Monitor

Launch the transformation in a way that returns control immediately. Some shell
tools block until all child processes exit, even with `&`. To avoid this, use bash to write
a launcher script and execute it, using exactly this:

```bash
mkdir -p ~/.aws/atx/custom/atx-agent-session
cat > ~/.aws/atx/custom/atx-agent-session/run.sh << 'RUNNER'
#!/bin/bash
atx custom def exec -n <td-name> -p <repo-path> -x -t \
  --configuration 'additionalPlanContext=<user-config>' \
  --telemetry "client=<client>,agent=<agent>,executionMode=local"
echo $? > ~/.aws/atx/custom/atx-agent-session/transform.exit
RUNNER
chmod +x ~/.aws/atx/custom/atx-agent-session/run.sh
nohup ~/.aws/atx/custom/atx-agent-session/run.sh > ~/.aws/atx/custom/atx-agent-session/transform.log 2>&1 &
echo $! > ~/.aws/atx/custom/atx-agent-session/transform.pid
cat ~/.aws/atx/custom/atx-agent-session/transform.pid
```

Omit `--configuration` if no config is needed. The `--telemetry` flag is always included — see the Telemetry section above for field values.

This backgrounds the runner script (not ATX directly), so the exit code is
captured to `~/.aws/atx/custom/atx-agent-session/transform.exit` when ATX finishes. The PID file tracks
the runner process.

**As soon as you have the PID, immediately run the next command** — do NOT stop
and wait for the user. The ATX CLI outputs the conversation log path within
30-60 seconds of starting. Read it from the process log:

```bash
grep "Conversation log:" ~/.aws/atx/custom/atx-agent-session/transform.log 2>/dev/null
```

If it hasn't appeared yet, wait 15 seconds and retry (up to 4 attempts). The
output looks like:

```
Conversation log: /Users/<user>/.aws/atx/custom/20260319_063712_e3479843/logs/2026-03-19T06-37-26-conversation.log
```

Extract the full path from this line — this is the conversation log for THIS
specific run. Do NOT use `ls -t` to find the most recent log across all
conversations, as that may return a log from a previous run.

Then start a monitoring loop. On each cycle:

1. Check if the process is still running: `kill -0 $(cat ~/.aws/atx/custom/atx-agent-session/transform.pid) 2>/dev/null && echo "RUNNING" || echo "DONE"`
2. Read the latest lines from the conversation log and tell the user what's happening
3. Wait 60 seconds, then repeat

**You MUST continue polling without waiting for user input.** After each poll,
immediately schedule the next one. The user should see continuous progress updates
like "ATX is planning changes...", "Applying changes to 3 files...", "Running build...".

CRITICAL rules:

1. **Extract conversation ID and log path.** After launching the process, look for
   the conversation log line in stdout:

   ```
   📝 Conversation log: /Users/<user>/.aws/atx/custom/<conversation-id>/logs/<timestamp>-conversation.log
   ```

   Extract the `<conversation-id>` (e.g., `20260311_233325_21bb5ef0`) and the full
   log file path. Report the conversation ID to the user immediately. Example:
   "Transformation started — conversation ID: `20260311_233325_21bb5ef0`"

2. **Tail the conversation log.** Once the log path is known, read new lines from
   the conversation log on each polling cycle and relay meaningful progress to the
   user. This is the primary way to keep the user informed of what ATX is doing
   (e.g., planning steps, applying changes, running builds, encountering errors).

3. **Filter out noise.** When reading the conversation log or process stdout,
   silently IGNORE any lines containing "Thinking" — these are animated spinner
   indicators that repeat dozens of times and must NOT be echoed to the user.
   Surface everything else: planning output, file changes, build results, errors,
   and completion summaries.

4. **Completion = process exit only.** The transformation is done ONLY when the
   background process exits (i.e., `kill -0` returns non-zero). Do NOT treat
   exit code 0 from any other command (grep, cat, test, etc.) as transformation
   completion. Do NOT treat log messages like "TRANSFORMATION COMPLETE" as
   completion — ATX performs additional steps after that (validation summary
   generation). Check the process exit code — do NOT parse terminal
   output or log content to determine completion. ATX prints progress messages
   and spinner animations throughout execution that do NOT indicate completion.

5. **Polling interval.** Check the background process status and tail the
   conversation log every 60 seconds. Do NOT use escalating backoff for local
   mode — a fixed 60-second interval is sufficient. Do NOT sleep in the foreground
   terminal.

6. **Exit code determines success.** Once `kill -0` confirms the process has
   exited, read the exit code: `cat ~/.aws/atx/custom/atx-agent-session/transform.exit`. Exit code 0 =
   success. Non-zero = failure. Only after reading the exit code should you
   report the transformation as complete or failed.

### 6. Present Results
Show TD, repo path, key changes. Next steps: `git diff`, run tests, deploy.

## Remote Mode

### 1. Check Infrastructure

```bash
aws cloudformation describe-stacks --stack-name AtxInfrastructureStack \
  --query 'Stacks[0].StackStatus' --output text || echo "NOT_DEPLOYED"
```

If NOT_DEPLOYED: get user consent, then deploy. See [remote-execution.md](remote-execution.md).

### 2. Prepare Source

| Source Type | Action |
|-------------|--------|
| HTTPS git URL (public) | Use directly — container clones it |
| HTTPS git URL (private) | Verify `atx/github-token` exists in Secrets Manager (see Step 1 in SKILL.md), then use directly — container fetches PAT and clones |
| SSH git URL (public or private) | Verify `atx/ssh-key` exists in Secrets Manager (see Step 1 in SKILL.md), then use directly — container fetches SSH key and clones |
| S3 bucket with zips | Copy zips from user's bucket to managed source bucket (`atx-source-code-{account}`), then use managed S3 paths |
| Local repo | Zip → upload to S3 → use S3 path |

For local sources:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
mkdir -p ~/.aws/atx/custom/atx-agent-session
cd <repo-path> && zip -qr ~/.aws/atx/custom/atx-agent-session/<project>-$SESSION_TS.zip .
aws s3 cp ~/.aws/atx/custom/atx-agent-session/<project>-$SESSION_TS.zip s3://atx-source-code-${ACCOUNT_ID}/repos/<project>.zip
```

**Important:** Only the CDK-managed source bucket (`atx-source-code-{account}`) is
accessible to the remote container. Do NOT pass arbitrary S3 bucket paths as source —
the container's IAM role cannot read from them.

### 3. Submit Job

```bash
aws lambda invoke --function-name atx-trigger-job \
  --payload '{"source":"<url-or-s3>","command":"atx custom def exec -n <td> -p /source/<project> -x -t --telemetry \"client=<client>,agent=<agent>,executionMode=remote\"","jobName":"<name>","environment":{"JAVA_VERSION":"<target>"}}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Add `--configuration \"additionalPlanContext=<config>\"` to the command string if config is needed.
The `--telemetry` flag is always included — see the Telemetry section for field values.

Set the appropriate version environment variable to match the transformation's target version:

- `JAVA_VERSION` for Java transformations (e.g., `"21"` for a Java 8 → 21 upgrade)
- `PYTHON_VERSION` for Python transformations (e.g., `"3.12"` for a Python 3.8 → 3.12 upgrade)
- `NODE_VERSION` for Node.js transformations (e.g., `"22"` for a Node.js 18 → 22 upgrade)

Only include the variable relevant to the transformation language. The Lambda whitelists these keys and passes them as Batch container overrides; the entrypoint switches the active runtime at startup.

### 4. Monitor

```bash
aws lambda invoke --function-name atx-get-job-status \
  --payload '{"jobId":"<job-id>"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Poll every 60 seconds for the first 10 polls, then every 5 minutes after.
Report only on status change.

### 5. Present Results (Remote)

Do NOT download results locally. Results stay in S3. Present the S3 path to the user:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Results: s3://atx-custom-output-${ACCOUNT_ID}/transformations/<job-name>/"
```

If the user wants to download results, first list the S3 path to discover the
conversation ID (generated at runtime inside the container). Use the actual
job name and account ID — do NOT leave placeholders in commands given to the user:

```bash
aws s3 ls s3://atx-custom-output-{account-id}/transformations/<job-name>/ --region <region>
```

Then provide the download command with the actual conversation ID:

```
aws s3 cp s3://atx-custom-output-{account-id}/transformations/<job-name>/<conversation-id>/code.zip ./code.zip
```

Include the CloudWatch dashboard link in the completion output:

```bash
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null)}}
REGION=${REGION:-us-east-1}
echo "https://${REGION}.console.aws.amazon.com/cloudwatch/home#dashboards/dashboard/ATX-Transform-CLI-Dashboard"
```

Show TD, repo, status, downloaded path, and the dashboard link for monitoring history and logs.

After presenting results, prompt the user about infrastructure teardown. See the
Cleanup section in [remote-execution.md](remote-execution.md) for the exact prompt.

## Error Handling

| Issue | Resolution |
|-------|------------|
| Dependency incompatibility | Check package compatibility, may need manual update |
| Build failure (remote) | Check build command works locally, verify registry credentials in `atx/credentials` |
| ATX timeout | Set `ATX_SHELL_TIMEOUT=1800` or break into smaller transforms |

## MANDATORY: Cleanup

Clean up session files **before starting** and **after completing** each transformation:

```bash
[ -d ~/.aws/atx/custom/atx-agent-session ] && find ~/.aws/atx/custom/atx-agent-session -maxdepth 1 -type f \( -name "*.sh" -o -name "*.log" -o -name "*.pid" -o -name "*.exit" -o -name "*.zip" \) -delete 2>/dev/null || true
```
