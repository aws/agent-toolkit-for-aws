# Set up AWS credentials for AI tools

## Overview

This set up file sets up AWS credentials for an AI coding tool by installing the AWS CLI, authenticating the user, and configuring the Agent Toolkit.

The workflow includes:

- Detecting the user's operating system (macOS, Linux, or Windows)
- Installing the AWS CLI v2 via the appropriate platform installer
- Authenticating the user via `aws login` with browser-based sign-in
- Verifying credentials with `aws sts get-caller-identity`
- Installing the Agent Toolkit which bundles AWS MCP server configuration and agent skills
- Verifying the Agent Toolkit installation

## Parameters

- operating_system (optional): macOS, Linux, or Windows. If not provided, Step 1 detects it automatically
- Region (required): The default AWS Region for the user's account. If not provided in the prompt, you MUST ask the user for it before proceeding

Constraints for parameter acquisition:

- You MUST detect the OS automatically before asking the user
- The user MUST either provide the AWS Region in the prompt or you MUST ask for it
- You MUST NOT ask the user for AWS credentials, access keys, or secret keys — authentication is handled entirely through `aws login` browser flow
- You MUST inform the user that credentials are valid for 12 hours and can be renewed for 90 days without re-authenticating in the browser

## Dependencies

Constraints:

- You MUST verify the following tools are available: curl (macOS/Linux) or PowerShell (Windows)
- You MUST verify internet connectivity to `https://awscli.amazonaws.com`
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed despite missing tools
- You MUST respect the customer's decision to abort at any point
- You MUST explain to the customer what step is being executed, why, and which tool is being called
- You MUST NOT require node, python3, or any other runtime beyond the shell — the installer handles all dependencies

## General error handling

If any step fails with an error not covered in that step's error handling table, report the full error output to the user and do not proceed to the next step. If installation fails, tell the customer to re-run the set up file.

## Steps

### Step 1 : Determine operating system

Determine the operating system. Check session context first; if it's not there, run a detection command:

- On Unix-like shell: `uname -s`
- On Powershell: `$env:OS`

**Success:** OS identified as macOS, Linux, or Windows

**Error handling**:

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Cannot determine OS | No shell access or unknown environment | Ask the user what operating system they are using |

Then:

- **macOS or Linux** → Proceed to Step 2 (macOS/Linux)
- **Windows** → Proceed to Step 2 (Windows)

### Step 2 (if using macOS or Linux):

Download and run the shell installer:

```bash
curl -fsSL 'https://awscli.amazonaws.com/v2/install.sh' | bash
```

After the installer completes successfully, ensure `aws` is available in the current session and future sessions:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then persist the PATH update to the user's shell configuration so it applies to new terminal sessions:

```bash
SHELL_RC="$HOME/.bashrc"
if [ "$(basename "$SHELL")" = "zsh" ]; then
  SHELL_RC="$HOME/.zshrc"
fi
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC" && source "$SHELL_RC"
```

**Success**: Installer exits with code 0 and prints the installed version.

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `command not found: curl` | Download tool is not installed | Install `curl` via the system package manager, then re-run |
| curl exits with non-zero (e.g., exit code 22) | HTTP error or no internet connectivity | Verify network access to the download URL |
| `missing required dependencies: ...` | `unzip` (Linux) or `pkgutil` (macOS) not installed | Install the listed dependencies, then re-run |
| `unsupported OS` or `unsupported architecture` | Script only supports Linux (x86_64, aarch64) and macOS | Cannot proceed on this system |
| `musl-based Linux detected` | Alpine or similar musl distro | Cannot use prebuilt binaries; direct user to source install |
| `--system requires root` | User passed `--system` without sudo | Re-run with `sudo` or omit `--system` for user-local install |
| `post-install check failed` | `aws --version` didn't succeed after install | Check that `$HOME/.local/bin` is on PATH; re-run the script |
| PATH warning in output | `$HOME/.local/bin` not first on PATH | Add it to shell rc file as the script suggests, then open a new shell |
| `Permission denied` when writing to rc file | File or directory permissions prevent writing | Check file permissions with `ls -la "$SHELL_RC"` and fix with `chmod u+w "$SHELL_RC"` |
| RC file does not exist | File hasn't been created yet (fresh system) | Create it first with `touch "$SHELL_RC"`, then re-run the echo command |
| Duplicate PATH entries in rc file | Step was run multiple times | Not harmful, but user can manually remove duplicate lines from their shell rc file |

### Step 2 (if using Windows):

Download and run the PowerShell installer:

```powershell
irm 'https://awscli.amazonaws.com/v2/install.ps1' | iex
```

**Success**: Installer exits successfully and prints the installed version.

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `irm` or `iex` not recognized | Running in cmd.exe instead of PowerShell | Re-run from a PowerShell session |
| Download/network failure | No internet connectivity or firewall blocking the URL | Verify network access to the download URL |
| `-System requires admin privileges` | User passed `-System` without elevation | Re-run from an elevated PowerShell, or omit `-System` for user-local install |
| `msiexec failed with exit code ...` | MSI installation failed | Check Windows Event Log for MSI errors; ensure no other AWS CLI installer is running |
| `post-install check failed` | `aws --version` didn't succeed after install | Restart the shell so PATH changes from the MSI take effect, then retry |
| `LOCALAPPDATA is not set` | Rare environment issue | Set the variable or use `-System` for a Program Files install |

### **Step 3: Log in to AWS**

Check if the user's prompt includes their AWS Region (e.g., "Your AWS Region is: us-east-2"). If not provided, ask the user: "What AWS Region do you want to use as your default Region?" Then configure it before logging in:

```bash
aws configure set region <region from prompt>
```

Then sign in to the AWS CLI, passing the Region explicitly:

```bash
aws login --region <region from prompt>
```

A browser window will open for authentication. The human user will authenticate.

Wait for the command to exit before proceeding to Step 4.

**Success**: `aws login` exits with code 0.

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Region not provided in prompt | User pasted the prompt without region context | Ask the user: "What AWS Region do you want to use as your default Region?" and set it with `aws configure set region <value>` |
| command not found: `aws` | PATH not set correctly after install | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |
| aws login exits with non-zero | User closed the browser without completing auth, or timed out | Re-run `aws login` and instruct the user to complete authentication in the browser |
| Browser did not open | Headless environment or no default browser configured | Look for a URL in the command output and ask the user to open it manually |

### Step 4: Verify access

Verify AWS CLI access:

```bash
aws sts get-caller-identity
```

**Success**: Returns AccountId, Arn, and UserId. Confirm to the user that credentials are working.

**Error handling**:

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Unable to locate credentials` or `ExpiredToken` | `aws login` did not complete successfully | Re-run Step 3 |
| `command not found: aws` | PATH not set correctly | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |

### Step 5: Set up the Agent Toolkit

Run the following command to install AI coding agents, install default AWS skills, and configure the AWS MCP Server connection.

```bash
aws configure agent-toolkit --yes --region us-east-1
```

**Note:** The Agent Toolkit service is currently only available in `us-east-1`, regardless of your Region. Use `us-east-1` here and in Step 6 — do not substitute the user's current Region.

**Success:** Command exits with code 0.

**Error handling**:

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `--yes` not recognized or `invalid choice` | CLI version doesn't support this flag yet | Remove the flag and retry: `aws configure agent-toolkit --region us-east-1` |
| Exit code 253 or "requires interactive terminal" | Agent's bash tool runs in a non-interactive subshell; wizard cannot prompt for input | Inform the user: "Almost done! Run this command in your terminal to finish setup: `aws configure agent-toolkit --region us-east-1`. It's a one-time interactive wizard (~30 seconds). Once complete, come back here and I'll verify everything is working." Then proceed to Step 6 only after the user confirms completion.|
| `Unable to locate credentials` or `ExpiredToken` | Session expired during setup | Re-run Step 3, then retry Step 5 |
| `command not found: aws` | PATH not set correctly | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |

### Step 6: Verify Agent Toolkit installation

Run the following command to list all available skills in the remote catalog.

```bash
aws agent-toolkit list-available-skills --region us-east-1
```

**Success:** Returns a JSON of skills with name, description, skillVersion, and categories values.

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Unable to locate credentials` or `ExpiredToken` | Session expired | Re-run Step 3, then retry Step 6 |
| `Invalid choice` or `argument not recognized` | AWS CLI version doesn't include agent-toolkit commands | Re-run Step 2 to update to the latest version, then retry |

### Step 7: Get AWS experience rule

First, identify which AI coding tool is in use and its rules files per this table:

| Agent       | Project rules        | Location                  |
| ----------- | -------------------- | ------------------------- |
| Claude Code | CLAUDE.md            | Project root              |
| Codex       | AGENTS.md            | Project root              |
| Cursor      | .cursor/rules/\*.mdc | .cursor/rules/ directory  |
| Kiro        | .kiro/steering/\*.md | .kiro/steering/ directory |

Then retrieve the AWS experience rules file, read its full contents, and
save them to that tool's rules file (creating the directory if needed):

https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-agent-rules.md

**Success**: Rule file is saved to the correct location for each AI tool. End the skill by telling the user: "The steps to get set up have all been completed. Start a new session to create new AWS resources"

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| HTTP 404 or download failure | URL changed or no internet connectivity | Verify network access; check if the URL is still valid at the GitHub repository |
| Permission denied when saving file | No write access to the target directory | Create the directory with mkdir -p or run with appropriate permissions |
| Cannot determine AI tool configuration directory | Unknown or unsupported AI coding tool | Ask the user which AI tool they are using and where its configuration directory is |
| File saved but tool doesn't recognize it | Incorrect file path or naming convention | Verify the path matches the tool's expected location per the Agent Toolkit documentation |
