# Set up AWS credentials for AI tools — Troubleshooting

This file contains the per-step error handling for the setup runbook. Each section corresponds to a
step in [setup.md](setup.md). When a step fails, find the matching section below, apply the
resolution, and resume the runbook at that step. Each section links back to its step.

## General error handling

Return to [setup.md](setup.md).

If any step fails with an error not covered in that step's table below, report the full error output
to the user and do not proceed to the next step. If installation fails, tell the customer to re-run
the set up file.

## Step 1: Determine operating system

Back to [Step 1 in setup.md](setup.md#step-1-determine-operating-system).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Cannot determine OS | No shell access or unknown environment | Ask the user what operating system they are using |

## Step 2 (macOS or Linux): Install the AWS CLI

Back to [Step 2 (macOS or Linux) in setup.md](setup.md#step-2-if-using-macos-or-linux).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `command not found: curl` | Download tool is not installed | Install `curl` via the system package manager, then re-run |
| curl exits with non-zero (e.g., exit code 22) | HTTP error or no internet connectivity | Verify network access to the download URL |
| `missing required dependencies: ...` | `unzip` (Linux) or `pkgutil` (macOS) not installed | Install the listed dependencies, then re-run |
| `unsupported OS` or `unsupported architecture` | Script only supports Linux (x86_64, aarch64) and macOS | Cannot proceed on this system |
| `musl-based Linux detected` | Alpine or similar musl distro | Cannot use prebuilt binaries; direct user to source install |
| `--system requires root` | User passed `--system` without sudo | Re-run with `sudo` or omit `--system` for user-local install |
| `post-install check failed` | `aws --version` didn't succeed after install | Check that `$HOME/.local/bin` is on PATH; re-run the script |
| `aws --version` returns an older version than just installed | A previous AWS CLI installation exists in a different location (e.g., `/usr/local/bin/aws` or Homebrew) and takes precedence on PATH | Run `which -a aws` to show all install locations. Inform the user which locations were found and offer two options: (1) remove the old installation, or (2) reorder PATH so the new install takes precedence. Ask which they prefer before proceeding |
| PATH warning in output | `$HOME/.local/bin` not first on PATH | Add it to shell rc file as the script suggests, then open a new shell |
| `Permission denied` when writing to rc file | File or directory permissions prevent writing | Check file permissions with `ls -la "$SHELL_RC"` and fix with `chmod u+w "$SHELL_RC"` |
| RC file does not exist | File hasn't been created yet (fresh system) | Create it first with `touch "$SHELL_RC"`, then re-run the echo command |
| Duplicate PATH entries in rc file | Step was run multiple times | Not harmful, but user can manually remove duplicate lines from their shell rc file |

## Step 2 (Windows): Install the AWS CLI

Back to [Step 2 (Windows) in setup.md](setup.md#step-2-if-using-windows).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `irm` or `iex` not recognized | Running in cmd.exe instead of PowerShell | Re-run from a PowerShell session |
| Download/network failure | No internet connectivity or firewall blocking the URL | Verify network access to the download URL |
| `-System requires admin privileges` | User passed `-System` without elevation | Re-run from an elevated PowerShell, or omit `-System` for user-local install |
| `msiexec failed with exit code ...` | MSI installation failed | Check Windows Event Log for MSI errors; ensure no other AWS CLI installer is running |
| `post-install check failed` | `aws --version` didn't succeed after install | Restart the shell so PATH changes from the MSI take effect, then retry |
| `aws --version` returns an older version than just installed | A previous AWS CLI installation exists in a different location (e.g., `C:\Program Files\Amazon\AWSCLIV2\`) and takes precedence on PATH | Run `Get-Command aws -All` to show all install locations. Inform the user which locations were found and offer two options: (1) uninstall the old version via Apps & Features, or (2) reorder PATH so the new install takes precedence. Ask which they prefer before proceeding |
| `LOCALAPPDATA is not set` | Rare environment issue | Set the variable or use `-System` for a Program Files install |

## Step 3: Log in to AWS

Back to [Step 3 in setup.md](setup.md#step-3-log-in-to-aws).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Region not provided in prompt | User pasted the prompt without region context | Ask the user the relevant follow up question depending on their AWS experience parameter. Then, set it with `aws configure set region <value> --profile <profile_name>` |
| command not found: `aws` | PATH not set correctly after install | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |
| `Profile '<profile_name>' is already configured with Access Key credentials` | User previously configured static access keys for this profile via `aws configure` | Offer the user two options: (1) Use a different profile name and re-run `aws login --profile <new_name>`, or (2) Remove the `aws_access_key_id` and `aws_secret_access_key` lines from `~/.aws/credentials` (under the `[<profile_name>]` section), then re-run `aws login --profile <profile_name>` |
| aws login exits with non-zero | User closed the browser without completing auth, or timed out | Re-run `aws login --profile <profile_name>` and instruct the user to complete authentication in the browser |
| Browser did not open | Headless environment or no default browser configured | Run `aws login --region <region from prompt> --profile <profile_name> --remote`. Then let the human user finish the process. |

## Step 4: Verify access

Back to [Step 4 in setup.md](setup.md#step-4-verify-access).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Unable to locate credentials` or `ExpiredToken` | `aws login` did not complete successfully | Re-run Step 3 |
| `command not found: aws` | PATH not set correctly | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |

## Step 5: Set up the Agent Toolkit

Back to [Step 5 in setup.md](setup.md#step-5-set-up-the-agent-toolkit).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `--yes` not recognized or `invalid choice` | CLI version doesn't support this flag yet | Remove the flag and retry: `aws configure agent-toolkit --region us-east-1 --profile <profile_name>` |
| Exit code 253 or "requires interactive terminal" | Agent's bash tool runs in a non-interactive subshell; wizard cannot prompt for input | Inform the user: "Almost done! Run this command in your terminal to finish setup: `aws configure agent-toolkit --region us-east-1 --profile <profile_name>`. It's a one-time interactive wizard (~30 seconds). Once complete, come back here and I'll verify everything is working." Then proceed to Step 6 only after the user confirms completion. |
| `Unable to locate credentials` or `ExpiredToken` | Session expired during setup | Re-run Step 3, then retry Step 5 |
| `command not found: aws` | PATH not set correctly | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |

## Step 6: Verify Agent Toolkit installation

Back to [Step 6 in setup.md](setup.md#step-6-verify-agent-toolkit-installation).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Unable to locate credentials` or `ExpiredToken` | Session expired | Re-run Step 3, then retry Step 6 |
| `Invalid choice` or `argument not recognized` | AWS CLI version doesn't include agent-toolkit commands | Re-run Step 2 to update to the latest version, then retry |

## Step 7: Get AWS experience rule

Back to [Step 7 in setup.md](setup.md#step-7-get-aws-experience-rule).

| Symptom | Cause | Resolution |
|---------|-------|------------|
| HTTP 404 or download failure | URL changed or no internet connectivity | Verify network access; check if the URL is still valid at the GitHub repository |
| Permission denied when saving file | No write access to the target directory | Create the directory with mkdir -p or run with appropriate permissions |
| Cannot determine AI tool configuration directory | Unknown or unsupported AI coding tool | Ask the user which AI tool they are using and where its configuration directory is |
| File saved but tool doesn't recognize it | Incorrect file path or naming convention | Verify the path matches the tool's expected location per the Agent Toolkit documentation |
