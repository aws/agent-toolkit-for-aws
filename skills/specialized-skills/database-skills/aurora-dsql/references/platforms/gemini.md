# MCP Setup: Gemini

Part of [MCP Server Setup](../mcp-setup.md). The skill PREFERS direct `psql` for ad-hoc DSQL
queries (via [`scripts/psql-connect.sh`](../../scripts/psql-connect.sh)) and the
[AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html) for AWS
knowledge and AWS API access.

---

## AWS MCP Server (recommended)

Follow the official setup guide at
[Setting up the AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/getting-started-aws-mcp-server.html)
for the Gemini-specific install command and config-file paths.

### Choosing the Right Scope

Gemini offers 2 scopes: project (default) and user.

1. **Project-Scoped** servers are only accessible from the project's root directory and added to
   the project configuration: `.gemini/settings.json`. Useful for project-specific tools that
   should stay within the codebase.
2. **User-Scoped** servers are accessible from all projects you work on with the Gemini CLI and
   added to global configuration: `~/.gemini/settings.json`.

### Verification

```bash
gemini mcp list
```

You should see the AWS MCP Server listed and connected.
