# Agent Toolkit for AWS

A plugin marketplace hosting installable agent plugins for AWS. Ships with the `aws-core` plugin and supports Claude Code, Codex, and Kiro.

## Plugins

| Plugin | Description | Skills | MCP Servers |
|--------|-------------|--------|-------------|
| [aws-core](plugins/aws-core/) | AWS agent plugin with skills and MCP server connections | [find-aws-skills](skills/find-aws-skills/) | [aws-mcp](https://aws-mcp.us-east-1.api.aws/mcp) |

## Installation

### Claude Code

```bash
# Add the marketplace
/plugin marketplace add aws/agent-toolkit-for-aws

# Install a plugin
/plugin install aws-core@agent-toolkit-for-aws
```

### Codex

The Codex marketplace manifest is at `.agents/plugins/marketplace.json`. Codex discovers plugins from the repository automatically.

### Kiro

Kiro support is provided via the `@every-env/compound-plugin` converter, which reads the Claude Code plugin structure and generates `.kiro/` format externally.

## Skills

All skills live in the top-level [`skills/`](skills/) directory. This is the canonical source. The `aws-core` plugin bundles a default subset for out-of-the-box use.

| Skill | Description |
|-------|-------------|
| [find-aws-skills](skills/find-aws-skills/) | Discover and load AWS skills at runtime |

## Rules

Platform-agnostic agent configuration snippets are in [`rules/`](rules/). Copy the relevant sections into your `AGENTS.md`, `CLAUDE.md`, or `.kiro/steering/` files.

## Development

This project uses [Mise](https://mise.jdx.dev/) as a task runner.

```bash
# Run full build (lint + validate + security)
mise run build

# Run only validation
python3 tools/validate.py

# Validate a single plugin
python3 tools/validate.py --plugin aws-core
```

## Contributing

This project is not accepting external contributions at this time.

## Security

If you discover a potential security issue in this project, please notify AWS/Amazon Security via the [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

## License

This project is licensed under the Apache-2.0 License.
