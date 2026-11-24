---
name: setup
description: Connect this agent to AWS Context
---

Read `${CLAUDE_PLUGIN_ROOT}/skills/aws-context/references/connecting.md` (the `connecting.md` reference of this plugin's aws-context skill)
to pick the mode with the user. Ask for their Region and graph ID. If they have no graph yet,
point them to the `setting-up-aws-context` skill in the AWS core plugin.

The plugin ships an OAuth connection for us-east-1. If that is the user's mode and Region, there is
nothing to write: follow the OAuth steps in `connecting.md`.

Otherwise add an `aws-context` server to the user's own MCP configuration, not to the plugin's
files, which a plugin update replaces. Use the user's Region in the endpoint
`https://context-mcp.<region>.api.aws/mcp`. The SigV4 rows run `mcp-proxy-for-aws-cli`, the
version-pinned command-line build of the open-source MCP Proxy for AWS:

| Client | OAuth | SigV4 (local signing proxy, signs with the user's AWS profile) |
|---|---|---|
| Claude Code | `claude mcp add --scope user --transport http aws-context <endpoint>` | `claude mcp add --scope user aws-context -- uvx mcp-proxy-for-aws-cli@1.8.0 <endpoint> --service context-mcp --region <region> --profile <profile>` |
| Codex (`~/.codex/config.toml`) | `[mcp_servers.aws-context]` with `url = "<endpoint>"` | `[mcp_servers.aws-context]` with `command = "uvx"` and `args = ["mcp-proxy-for-aws-cli@1.8.0", "<endpoint>", "--service", "context-mcp", "--region", "<region>", "--profile", "<profile>"]` |
| Other JSON clients | `{"type": "http", "url": "<endpoint>"}` under `mcpServers.aws-context` | `{"command": "uvx", "args": [same as Codex]}` under `mcpServers.aws-context` |

Then ask the user to turn off the plugin's own AWS Context server in their client's MCP panel
(in Claude Code, `/mcp`), so the agent does not keep using the us-east-1 OAuth connection, and to
reload MCP servers. When the connection works, run one test search and show the user the result.
