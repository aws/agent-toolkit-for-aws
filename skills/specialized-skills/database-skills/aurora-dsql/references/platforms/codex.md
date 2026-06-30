# MCP Setup: Codex

Part of [MCP Server Setup](../mcp-setup.md). The skill PREFERS direct `psql` for ad-hoc DSQL
queries (via [`scripts/psql-connect.sh`](../../scripts/psql-connect.sh)) and the
[AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html) for AWS
knowledge and AWS API access.

---

## AWS MCP Server (recommended)

Follow the official setup guide at
[Setting up the AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/getting-started-aws-mcp-server.html)
for the Codex-specific install command and `~/.codex/config.toml` entry.

### Verification

```bash
codex mcp
```

You should see the AWS MCP Server listed and connected.
