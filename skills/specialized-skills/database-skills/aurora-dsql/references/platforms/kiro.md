# MCP Setup: Kiro

Part of [MCP Server Setup](../mcp-setup.md). The skill PREFERS direct `psql` for ad-hoc DSQL
queries (via [`scripts/psql-connect.sh`](../../scripts/psql-connect.sh)) and the
[AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html) for AWS
knowledge and AWS API access.

---

## AWS MCP Server (recommended)

Follow the official setup guide at
[Setting up the AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/getting-started-aws-mcp-server.html)
for the Kiro-specific install instructions.

### Choosing the Right Scope

Kiro offers 2 scopes: workspace (default) and user.

1. **Workspace-Scoped** servers live at `.kiro/settings/mcp.json` in the project root and are
   only accessible from the current workspace. Useful for project-specific tools that should
   stay within the codebase and can be checked into version control.
2. **User-Scoped** servers live at `~/.kiro/settings/mcp.json` and are accessible across all
   workspaces the user opens in Kiro.

When both files define the same server name, **workspace settings take precedence**.

### Kiro-Specific Fields

- `disabled` (bool) — set `true` to suspend a server without deleting its entry
- `autoApprove` (string array) — tool names that skip the per-call approval prompt.
  Leave empty to require approval for every call. For tools that can mutate state
  (cluster lifecycle APIs, write SQL paths), keep this empty so the user approves each call.
- `disabledTools` (string array) — hide specific tools from this server
- `env` supports `${VAR}` expansion from the shell environment,
  e.g. `"AWS_PROFILE": "${DSQL_PROFILE}"`

### Verification

Open the command palette (`Cmd/Ctrl+Shift+P`) → search `MCP` → open the MCP view in the Kiro
panel. The AWS MCP Server should appear in the server list with an active status.
