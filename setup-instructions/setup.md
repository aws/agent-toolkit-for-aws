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
- profile_name (required): The AWS CLI profile name to use for all commands. You MUST ask the user: "What profile name do you want to use for your AWS CLI credentials?"
- AWS experience (required): The user has access to either our new AWS experience or our advanced AWS experience. If not provided in the prompt, you MUST ask the user: "Did you sign up recently for AWS using a social provider like Google or GitHub, and did you create a project?" If they say yes, they are using our new AWS experience. If they say no, they are using our advanced AWS experience.
- Region (required): The default AWS Region for the user's account. If not provided in the prompt, you MUST ask the user for it before proceeding
  - If the AWS experience parameter is our advanced AWS experience, ask the user: "What AWS Region do you want to use as your default Region?"
  - If the AWS experience parameter is our new AWS experience, ask the user: "What AWS Region was your project created in?" They can find this value in the additional info tab of their project in AWS Settings.

Constraints for parameter acquisition:

- You MUST detect the OS automatically before asking the user
- The user MUST either provide the AWS Region in the prompt or you MUST ask for it
- You MUST NOT ask the user for AWS credentials, access keys, or secret keys — authentication is handled entirely through `aws login` browser flow
- You MUST inform the user that credentials are valid for 12 hours and can be renewed for 90 days without re-authenticating in the browser

## Dependencies

Constraints:

- You MUST verify the following tools are available: curl (macOS/Linux) or PowerShell (Windows), and uv (all platforms)
- If uv is not installed, install it before proceeding:
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `irm https://astral.sh/uv/install.ps1 | iex`
- You MUST verify internet connectivity to `https://awscli.amazonaws.com`
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed despite missing tools
- You MUST respect the customer's decision to abort at any point
- You MUST explain to the customer what step is being executed, why, and which tool is being called
- You MUST NOT require node, python3, or any other runtime beyond the shell and uv — the installer handles all other dependencies
- IF the AWS experience parameter is "our new AWS experience" THEN the user's account is part of a "project". Always use the term "project" when talking to the user.

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
| `aws --version` returns an older version than just installed | A previous AWS CLI installation exists in a different location (e.g., `/usr/local/bin/aws` or Homebrew) and takes precedence on PATH | Run `which -a aws` to show all install locations. Inform the user which locations were found and offer two options: (1) remove the old installation, or (2) reorder PATH so the new install takes precedence. Ask which they prefer before proceeding |
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
| `aws --version` returns an older version than just installed | A previous AWS CLI installation exists in a different location (e.g., `C:\Program Files\Amazon\AWSCLIV2\`) and takes precedence on PATH | Run `Get-Command aws -All` to show all install locations. Inform the user which locations were found and offer two options: (1) uninstall the old version via Apps & Features, or (2) reorder PATH so the new install takes precedence. Ask which they prefer before proceeding |
| `LOCALAPPDATA is not set` | Rare environment issue | Set the variable or use `-System` for a Program Files install |

### **Step 3: Log in to AWS**

Check if the user's prompt includes their AWS Region (e.g., "Your AWS Region is: us-east-2").

- If not provided and the AWS experience parameter is our advanced AWS experience, ask the user: "What AWS Region do you want to use as your default Region?"
- If not provided and the AWS experience parameter is our new AWS experience, ask the user: "What AWS Region was your project created in?" They can find this value in the additional info tab of their project in AWS Settings.

Then configure it before logging in:

```bash
aws configure set region <region from prompt> --profile <profile_name>
```

Then sign in to the AWS CLI using the dedicated profile, passing the Region explicitly:

```bash
aws login --region <region from prompt> --profile <profile_name>
```

A browser window will open for authentication. The human user will authenticate. If the human user wants to cancel this command at any time, let them.

Wait for the command to exit before proceeding to Step 4.

**Success**: `aws login` exits with code 0.

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Region not provided in prompt | User pasted the prompt without region context | Ask the user the relevant follow up question depending on their AWS experience parameter. Then, set it with `aws configure set region <value> --profile <profile_name>` |
| command not found: `aws` | PATH not set correctly after install | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |
| `Profile '<profile_name>' is already configured with Access Key credentials` | User previously configured static access keys for this profile via `aws configure` | Offer the user two options: (1) Use a different profile name and re-run `aws login --profile <new_name>`, or (2) Remove the `aws_access_key_id` and `aws_secret_access_key` lines from `~/.aws/credentials` (under the `[<profile_name>]` section), then re-run `aws login --profile <profile_name>` |
| aws login exits with non-zero | User closed the browser without completing auth, or timed out | Re-run `aws login --profile <profile_name>` and instruct the user to complete authentication in the browser |
| Browser did not open | Headless environment or no default browser configured | Run `aws login --region <region from prompt> --profile <profile_name> --remote`. Then let the human user finish the process. |

### Step 4: Verify access

Verify AWS CLI access:

```bash
aws sts get-caller-identity --profile <profile_name>
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
aws configure agent-toolkit --yes --region us-east-1 --profile <profile_name>
```

**Note:** The Agent Toolkit service is currently only available in `us-east-1`, regardless of your Region. Use `us-east-1` here and in Step 6 — do not substitute the user's current Region.

**Success:** Command exits with code 0.

**Error handling**:

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `--yes` not recognized or `invalid choice` | CLI version doesn't support this flag yet | Remove the flag and retry: `aws configure agent-toolkit --region us-east-1 --profile <profile_name>` |
| Exit code 253 or "requires interactive terminal" | Agent's bash tool runs in a non-interactive subshell; wizard cannot prompt for input | Inform the user: "Almost done! Run this command in your terminal to finish setup: `aws configure agent-toolkit --region us-east-1 --profile <profile_name>`. It's a one-time interactive wizard (~30 seconds). Once complete, come back here and I'll verify everything is working." Then proceed to Step 6 only after the user confirms completion. |
| `Unable to locate credentials` or `ExpiredToken` | Session expired during setup | Re-run Step 3, then retry Step 5 |
| `command not found: aws` | PATH not set correctly | Re-run `export PATH="$HOME/.local/bin:$PATH"` and retry |

#### Point the AWS MCP Server at the user's profile

After the command completes, the Agent Toolkit writes an `aws-mcp` server entry into each detected AI tool's MCP configuration file. This entry does NOT reference the profile the user authenticated with in Step 3 — it falls back to the `default` profile. Because this set up file always authenticates under a named `<profile_name>`, you MUST propagate that profile into each generated `aws-mcp` entry, or the MCP server will fail to start with `JSON-RPC error: -32602: Invalid request parameters("")` (it cannot locate credentials under the `default` profile).

For each MCP configuration file the Agent Toolkit updated, open the file, locate the `aws-mcp` entry under `mcpServers`, and add an `env` block that sets `AWS_MCP_PROXY_PROFILES` to `<profile_name>`. You MUST NOT remove or modify any other server entries. Only the `env` block is added — leave `command`, `args`, `timeout`, and `transport` exactly as generated:

```json
"aws-mcp": {
  "command": "uvx",
  "args": ["mcp-proxy-for-aws@latest", "https://aws-mcp.us-east-1.api.aws/mcp", "--metadata", "INSTALL_SOURCE=aws-cli"],
  "env": {
    "AWS_MCP_PROXY_PROFILES": "<profile_name>"
  },
  "timeout": 100000,
  "transport": "stdio"
}
```

MCP configuration file locations by tool:

| Agent       | MCP configuration file    |
| ----------- | ------------------------- |
| Claude Code | ~/.claude.json            |
| Cline       | ~/.cline/mcp.json         |
| Cursor      | ~/.cursor/mcp.json        |
| Kiro        | ~/.kiro/settings/mcp.json |

Notes:

- Use `AWS_MCP_PROXY_PROFILES` (not `AWS_PROFILE`) because it also enables cross-account switching later.

After adding the `env` block, tell the user: "To use another AWS account later, run `aws login --profile <name>`, add that profile name to the space-separated `AWS_MCP_PROXY_PROFILES` list in each MCP configuration file above, and restart your AI tool."

### Step 6: Verify Agent Toolkit installation

Run the following command to list all available skills in the remote catalog.

```bash
aws agent-toolkit list-available-skills --region us-east-1 --profile <profile_name>
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

Then retrieve the AWS experience rules file based on their AWS experience parameter. Read its full contents, and
save them to that tool's rules file (creating the directory if needed):

If the AWS experience parameter is our new AWS experience, fetch the rule file. The rule file is located at:
https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-starter-rules.md

If the AWS experience parameter is our advanced AWS experience, the rule file is located at:
https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-agent-rules.md

**Success**: Rule file is saved to the correct location for each AI tool. End the set up by telling the user:

"Setup is complete! Close this session and start a new one. Your AI tool will automatically use the rules and skill files we just installed. Try this as your first prompt:

Please make a single page webapp game and deploy it to AWS.

If you’re looking to explore what you can do on AWS, that prompt will get you started with a fun project. You can replace the game request with anything you’d like to build"

**Error handling:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| HTTP 404 or download failure | URL changed or no internet connectivity | Verify network access; check if the URL is still valid at the GitHub repository |
| Permission denied when saving file | No write access to the target directory | Create the directory with mkdir -p or run with appropriate permissions |
| Cannot determine AI tool configuration directory | Unknown or unsupported AI coding tool | Ask the user which AI tool they are using and where its configuration directory is |
| File saved but tool doesn't recognize it | Incorrect file path or naming convention | Verify the path matches the tool's expected location per the Agent Toolkit documentation |
