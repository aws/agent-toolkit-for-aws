# Agent Toolkit for AWS

Help AI coding agents build, deploy, and manage applications on AWS.

The Agent Toolkit for AWS gives AI coding agents the tools, knowledge, and guardrails they need to work with AWS services. It works with the coding agents developers already use — including Claude Code and Codex.

## Quick start

### Claude Code

```
/plugin marketplace add aws/agent-toolkit-for-aws
/plugin install aws-core@agent-toolkit-for-aws
/reload-plugins
```

### Codex

In your terminal:

```
codex plugin marketplace add aws/agent-toolkit-for-aws
```

Then launch Codex and run `/plugins` to browse and install the **aws-core** plugin.

### Agents that do not support plugins

Add the AWS MCP Server to your agent's MCP configuration:

```json
{
  "mcpServers": {
    "aws": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://aws-mcp.us-east-1.api.aws/mcp",
        "--metadata", "AWS_REGION=us-west-2"
      ]
    }
  }
}
```

Then copy skills from this repository to your agent's skills directory.

> **Prerequisites:** You need [uv](https://docs.astral.sh/uv/) installed. An AWS account with credentials configured locally is required for API calls and script execution, but not for documentation search or skill discovery. See the [user guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/) for detailed setup instructions.

## What's included

### Plugins

Plugins bundle the AWS MCP Server configuration and agent skills into a single install for your coding agent.

| Plugin | Description |
|--------|-------------|
| [aws-core](plugins/aws-core/) | Core AWS skills and MCP Server configuration. Covers service selection, CDK/CloudFormation, serverless, containers, storage, observability, billing, SDK usage, and deployment. **Start here.** |
| [aws-agent-building](plugins/aws-agent-building/) | Skills for building AI agents on AWS with Amazon Bedrock and AgentCore. |
| [aws-data-analytics](plugins/aws-data-analytics/) | Skills for data lake, analytics, and ETL workflows with S3 Tables, Glue, and Athena. |

Plugins are currently available for Claude Code and Codex. For other agents, configure the AWS MCP Server directly and install skills from this repository.

### Skills

Agent skills are curated packages of instructions and reference materials that help agents complete specific AWS tasks. Skills are loaded on demand — agents discover and retrieve only what's relevant to the current task.

Browse the [`skills/`](skills/) directory to see all available skills.

### Rules files

Recommended project-level configuration files that tell agents how to use AWS most effectively — for example, by using the AWS MCP Server, discovering available skills, or searching documentation before acting.

See [`rules/`](rules/) for details.

### AWS MCP Server

The [AWS MCP Server](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html) is a managed server that gives agents access to AWS through the Model Context Protocol. It provides:

- **Full AWS API coverage** — Interact with any of the 300+ AWS services through a single authenticated endpoint.
- **Sandboxed script execution** — Agents can run Python scripts in an isolated environment for complex multi-step operations.
- **Real-time documentation access** — Search and retrieve current AWS documentation, API references, and service capabilities without authentication.
- **Enterprise controls** — Amazon CloudWatch metrics, IAM context keys for agent-specific policies, and AWS CloudTrail audit logging.

## Documentation

- [User guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/) — Setup, configuration, and reference documentation.
- [AWS MCP Server tools](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html) — Reference for all available MCP tools.

## License

This project is licensed under the Apache-2.0 License. See [LICENSE](LICENSE) for details.
