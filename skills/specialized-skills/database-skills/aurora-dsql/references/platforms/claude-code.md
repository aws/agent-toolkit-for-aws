# MCP Setup: Claude Code

Part of [MCP Server Setup](../mcp-setup.md). The skill PREFERS direct `psql` for ad-hoc DSQL
queries (via [`scripts/psql-connect.sh`](../../scripts/psql-connect.sh)) and the
[AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html) for AWS
knowledge and AWS API access.

---

## AWS MCP Server (recommended)

Follow the official setup guide at
[Setting up the AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/getting-started-aws-mcp-server.html).
The AWS docs page tracks the canonical install command, scopes (`local`, `project`, `user`), and
auth configuration for Claude Code — defer to it rather than caching the invocation here.

### Choosing the Right Scope

Claude Code offers 3 different scopes: local (default), project, and user.

1. **Local-scoped** servers represent the default configuration level and are stored in
   `~/.claude.json` under your project's path. They're **both** private to you and only accessible
   within the current project directory. This is the default `scope` when creating MCP servers.
2. **Project-scoped** servers **enable team collaboration** while still only being accessible in a
   project directory. Project-scoped servers add a `.mcp.json` file at your project's root directory.
   This file is designed to be checked into version control, ensuring all team members have access
   to the same MCP tools and services.
3. **User-scoped** servers are stored in `~/.claude.json` and are available across all projects on
   your machine while remaining **private to your user account.**

### Verification

After setup:

```bash
claude mcp list
```

You should see the AWS MCP Server listed and connected.
