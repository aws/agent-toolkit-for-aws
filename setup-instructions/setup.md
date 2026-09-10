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

Per-step error handling lives in [setup-troubleshooting.md](setup-troubleshooting.md). If a step fails, open the matching section there, apply the resolution, then resume at that step.

## Before you start

Gather the following inputs and confirm prerequisites **before** running any step. Ask for all required inputs in a single message, then proceed autonomously.

### Required inputs

- **profile_name** (required): The AWS CLI profile name to use for all commands. You MUST ask the user: "What profile name do you want to use for your AWS CLI credentials?"
- **AWS experience** (required): The user has access to either our new AWS experience or our advanced AWS experience. If not provided in the prompt, you MUST ask the user: "Did you sign up recently for AWS using a social provider like Google or GitHub, and did you create a project?" If they say yes, they are using our new AWS experience. If they say no, they are using our advanced AWS experience.
- **Region** (required): The default AWS Region for the user's account. If not provided in the prompt, you MUST ask for it before proceeding:
  - If the AWS experience parameter is our advanced AWS experience, ask: "What AWS Region do you want to use as your default Region?"
  - If the AWS experience parameter is our new AWS experience, ask: "What AWS Region was your project created in?" They can find this value in the additional info tab of their project in AWS Settings.
- **operating_system** (optional): macOS, Linux, or Windows. If not provided, Step 1 detects it automatically. You MUST detect the OS automatically before asking the user.

### Input constraints

- You MUST NOT ask the user for AWS credentials, access keys, or secret keys — authentication is handled entirely through the `aws login` browser flow.
- You MUST inform the user that credentials are valid for 12 hours and can be renewed for 90 days without re-authenticating in the browser.
- IF the AWS experience parameter is "our new AWS experience" THEN the user's account is part of a "project". Always use the term "project" when talking to the user.

### Prerequisites

- You MUST verify the following tools are available: curl (macOS/Linux) or PowerShell (Windows), and uv (all platforms).
- If uv is not installed, install it before proceeding:
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `irm https://astral.sh/uv/install.ps1 | iex`
- You MUST verify internet connectivity to `https://awscli.amazonaws.com`.
- You MUST inform the user about any missing tools with a clear message, ask if they want to proceed despite missing tools, and respect the customer's decision to abort at any point.
- You MUST NOT require node, python3, or any other runtime beyond the shell and uv — the installer handles all other dependencies.

## How to run this file

- After you gather the required inputs above, complete the steps yourself by running the commands directly. You MUST explain to the customer what step is being executed, why, and which tool is being called.
- Two steps require the human user to act; pause and let them complete these:
  - **Step 3 (`aws login`)** opens a browser for sign-in.
  - **Step 5 (`aws configure agent-toolkit`)** is an interactive wizard.
- If a step fails, consult [setup-troubleshooting.md](setup-troubleshooting.md) for that step, apply the resolution, and resume. For errors not covered there, report the full error output and do not proceed.

## Steps

### Step 1: Determine operating system

Determine the operating system. Check session context first; if it's not there, run a detection command:

- On Unix-like shell: `uname -s`
- On Powershell: `$env:OS`

**Success:** OS identified as macOS, Linux, or Windows. Then:

- **macOS or Linux** → Proceed to Step 2 (macOS/Linux)
- **Windows** → Proceed to Step 2 (Windows)

If this step fails, see [Troubleshooting: Step 1](setup-troubleshooting.md#step-1-determine-operating-system).

### Step 2 (if using macOS or Linux)

Determine if the user has the AWS CLI installed:

```bash
aws --version
```

If the AWS CLI is installed, this step is complete. If not, download and run the shell installer:

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

**Success:** Installer exits with code 0 and prints the installed version.

> **Note on the piped installer:** The command above runs AWS's official install script directly. Security-conscious users can instead download the script first, inspect it, and then run it, or follow the manual steps on the [official AWS CLI install page](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

If this step fails, see [Troubleshooting: Step 2 (macOS or Linux)](setup-troubleshooting.md#step-2-macos-or-linux-install-the-aws-cli).

### Step 2 (if using Windows)

Download and run the PowerShell installer:

```powershell
irm 'https://awscli.amazonaws.com/v2/install.ps1' | iex
```

**Success:** Installer exits successfully and prints the installed version.

> **Note on the piped installer:** The command above runs AWS's official install script directly. Security-conscious users can instead download the script first, inspect it, and then run it, or follow the manual steps on the [official AWS CLI install page](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

If this step fails, see [Troubleshooting: Step 2 (Windows)](setup-troubleshooting.md#step-2-windows-install-the-aws-cli).

### Step 3: Log in to AWS

Configure the Region (gathered in "Before you start"), then sign in:

```bash
aws configure set region <region from prompt> --profile <profile_name>
```

```bash
aws login --region <region from prompt> --profile <profile_name>
```

A browser window will open for authentication. The human user will authenticate. If the human user wants to cancel this command at any time, let them. Wait for the command to exit before proceeding to Step 4.

**Success:** `aws login` exits with code 0.

If this step fails, see [Troubleshooting: Step 3](setup-troubleshooting.md#step-3-log-in-to-aws).

### Step 4: Verify access

Verify AWS CLI access:

```bash
aws sts get-caller-identity --profile <profile_name>
```

**Success:** Returns AccountId, Arn, and UserId. Confirm to the user that credentials are working.

If this step fails, see [Troubleshooting: Step 4](setup-troubleshooting.md#step-4-verify-access).

### Step 5: Set up the Agent Toolkit

Run the following command to install AI coding agents, install default AWS skills, and configure the AWS MCP Server connection. This is an interactive wizard; let the human user complete any prompts.

```bash
aws configure agent-toolkit --yes --region us-east-1 --profile <profile_name>
```

**Note:** The Agent Toolkit service is currently only available in `us-east-1`, regardless of your Region. Use `us-east-1` here and in Step 6 — do not substitute the user's current Region.

**Success:** Command exits with code 0.

If this step fails, see [Troubleshooting: Step 5](setup-troubleshooting.md#step-5-set-up-the-agent-toolkit).

#### Point the AWS MCP Server at the user's profile

The command above writes an `aws-mcp` server entry into each detected AI tool's MCP configuration file. That generated entry falls back to the `default` profile. Because this set up file always authenticates under a named `<profile_name>`, you MUST add that profile to each generated `aws-mcp` entry, or the MCP server will fail to start with `JSON-RPC error: -32602: Invalid request parameters("")` (it cannot locate credentials under the `default` profile).

For each MCP configuration file the Agent Toolkit updated, open the file, locate the `aws-mcp` entry under `mcpServers`, and add (or merge in) an `env` block that sets `AWS_MCP_PROXY_PROFILES` to `<profile_name>`. You MUST NOT remove or modify any other server entries, and you MUST leave the generated `command`, `args`, `timeout`, and `transport` values exactly as written — only add the `env` block:

```json
"env": {
  "AWS_MCP_PROXY_PROFILES": "<profile_name>"
}
```

Notes:

- Use `AWS_MCP_PROXY_PROFILES` (not `AWS_PROFILE`) because it also enables cross-account switching later.
- If you find an existing `aws-mcp` entry, ask the user how they want to reconcile the new changes.
- If the MCP configuration file uses OpenCode, follow the OpenCode schema to modify the profile.
- The Agent Toolkit determines each tool's MCP configuration file location automatically. If you need to locate or confirm a file, see the [Agent Toolkit documentation](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/).

After adding the `env` block, tell the user: "To use another AWS account later, run `aws login --profile <name>`, add that profile name to the space-separated `AWS_MCP_PROXY_PROFILES` list in each MCP configuration file, and restart your AI tool."

### Step 6: Verify Agent Toolkit installation

Run the following command to list all available skills in the remote catalog:

```bash
aws agent-toolkit list-available-skills --region us-east-1 --profile <profile_name>
```

**Success:** Returns a JSON of skills with name, description, skillVersion, and categories values.

If this step fails, see [Troubleshooting: Step 6](setup-troubleshooting.md#step-6-verify-agent-toolkit-installation).

### Step 7: Get AWS experience rule

Identify which AI coding tool is in use and its rules file location (this is not an exhaustive list):

| Agent       | Project rules        | Location                  |
| ----------- | -------------------- | ------------------------- |
| Claude Code | CLAUDE.md            | Project root              |
| Codex       | AGENTS.md            | Project root              |
| Cursor      | .cursor/rules/\*.mdc | .cursor/rules/ directory  |
| Kiro        | .kiro/steering/\*.md | .kiro/steering/ directory |

Retrieve the AWS experience rules file based on the AWS experience parameter and read its full contents:

- New AWS experience: <https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-starter-rules.md>
- Advanced AWS experience: <https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/rules/aws-agent-rules.md>

Then add the rules to each detected tool's rules file **without destroying existing content**. `CLAUDE.md`, `AGENTS.md`, and files under `.cursor/rules/` or `.kiro/steering/` are the project's own agent instructions — often committed to version control and carrying accumulated project rules. You MUST NOT overwrite them.

- If the rules file does **not** exist, create it (creating the directory if needed) and write the retrieved rules.
- If the rules file **already exists**, append the retrieved rules under a clearly delimited heading rather than replacing the file. Use a stable marker so the operation is idempotent — for example, wrap the content between `<!-- BEGIN AWS Agent Toolkit rules -->` and `<!-- END AWS Agent Toolkit rules -->`. If that marked block is already present, replace only the content between the markers instead of appending a second copy.
- If you cannot determine whether appending is safe (for example, an unfamiliar rules format), ask the user how they want to proceed before writing.

Where a project's own instructions conflict with the AWS rules, the project's instructions take precedence.

**Success:** The AWS rules are present in the correct location for each AI tool, and any pre-existing project instructions are preserved. End the set up by telling the user:

> Setup is complete! Close this session and start a new one. Your AI tool will automatically use the rules and skill files we just installed. Try this as your first prompt:
>
> Please make a single page webapp game and deploy it to AWS.
>
> If you're looking to explore what you can do on AWS, that prompt will get you started with a fun project. You can replace the game request with anything you'd like to build.

If this step fails, see [Troubleshooting: Step 7](setup-troubleshooting.md#step-7-get-aws-experience-rule).
