# Agent Plugin for AWS

AWS agent plugin with skills and MCP server connections.

## Skills

| Skill | Description |
|-------|-------------|
| [find-aws-skills](skills/find-aws-skills/) | Discover and load AWS skills at runtime |

## MCP Servers

| Server | Transport | Description |
|--------|-----------|-------------|
| aws-mcp | stdio | AWS MCP server via `mcp-proxy-for-aws` |

## Installation

### Claude Code

```bash
/plugin marketplace add aws/agent-toolkit-for-aws
/plugin install agent-plugin-for-aws@agent-toolkit-for-aws
```

### Codex

Discovered automatically from the marketplace manifest.

## License

Apache-2.0
