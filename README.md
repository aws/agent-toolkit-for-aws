# Agent Toolkit for AWS

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Build](https://github.com/aws/agent-toolkit-for-aws/actions/workflows/build.yml/badge.svg)](https://github.com/aws/agent-toolkit-for-aws/actions/workflows/build.yml)
[![Status](https://img.shields.io/badge/status-GA-green.svg)](https://github.com/aws/agent-toolkit-for-aws)

Help AI coding agents build, deploy, and manage applications on AWS.

The Agent Toolkit for AWS gives AI coding agents the tools, knowledge, and guardrails they need to work with AWS services. It works with the coding agents developers already use — including Claude Code, Codex, and Kiro.

## Quick start

### Claude Code

The plugins are available on the official Anthropic marketplace (`claude-plugins-official`) which is added to your Claude Code installation by default.
Use the following commands to install supported plugins from the toolkit:

For `aws-core` that covers service selection, CDK/CloudFormation, serverless, containers, storage, observability, billing, SDK usage, and deployment:

```
/plugin install aws-core@claude-plugins-official
```

> **Tip:** If you get `Plugin not found`, update your local marketplace index first:
>
> ```
> /plugin marketplace update claude-plugins-official
> ```

For `aws-agents` that covers building AI agents on AWS with Amazon Bedrock and AgentCore:

```
/plugin install aws-agents@claude-plugins-official
```

For `aws-data-analytics` that covers data lake, analytics, and ETL workflows with S3 Tables, AWS Glue, and Athena:

```
/plugin install aws-data-analytics@claude-plugins-official
```

### Codex

In your terminal:

```
codex plugin marketplace add aws/agent-toolkit-for-aws
```

Then launch Codex and run `/plugins` to browse and install the **aws-core** plugin.

### Kiro

Add the AWS MCP Server to your Kiro MCP configuration (`.kiro/settings/mcp.json`):

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

Then install skills from this repository:

```
npx skills add aws/agent-toolkit-for-aws/skills
```

> **Prerequisites:** You need [uv](https://docs.astral.sh/uv/) installed. An AWS account with credentials configured locally is required for API calls and script execution, but not for documentation search or skill discovery. See the [user guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/) for detailed setup instructions.

### Other agents

See the [AWS MCP Server getting started guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/getting-started-aws-mcp-server.html) for instructions on configuring the AWS MCP Server with your agent.

Then install skills from this repository:

```
npx skills add aws/agent-toolkit-for-aws/skills
```

> **Prerequisites:** You need [uv](https://docs.astral.sh/uv/) installed. An AWS account with credentials configured locally is required for API calls and script execution, but not for documentation search or skill discovery. See the [user guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/) for detailed setup instructions.

## What's included

### Plugins

Plugins bundle the AWS MCP Server configuration and agent skills into a single install for your coding agent.

| Plugin | Description |
|--------|-------------|
| [aws-core](plugins/aws-core/) | Core AWS skills and MCP Server configuration. Covers service selection, CDK/CloudFormation, serverless, containers, storage, observability, billing, SDK usage, and deployment. **Start here.** |
| [aws-agents](plugins/aws-agents/) | Skills for building AI agents on AWS with Amazon Bedrock and AgentCore. |
| [aws-data-analytics](plugins/aws-data-analytics/) | Skills for data lake, analytics, and ETL workflows with S3 Tables, AWS Glue, and Athena. |

Plugins are currently available for Claude Code and Codex. For other agents, configure the AWS MCP Server directly and install skills from this repository.

### Skills

Agent skills are curated packages of instructions and reference materials that help agents complete specific AWS tasks. Skills are loaded on demand — agents discover and retrieve only what's relevant to the current task.

```
npx skills add aws/agent-toolkit-for-aws/skills
```

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

For details on operation, available tools, authentication, and supported Regions, see the [AWS MCP Server documentation](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html).

## Documentation

- [User guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/) — Setup, configuration, and reference documentation.
- [AWS MCP Server tools](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html) — Reference for all available MCP tools.

## How the Agent Toolkit relates to the MCP servers, skills, and plugins in AWS Labs
In 2025, AWS began releasing MCP servers, skills, and plugins as part of [AWS Labs](https://github.com/awslabs). The Agent Toolkit for AWS is the successor to those tools. We recommend using the Agent Toolkit for AWS, because it offers key features including:

- IAM condition keys that distinguish between agent actions and human actions, so you can write policies that apply only to agents. For example, you can write policies that only allow read-only actions through the MCP server, even if the user’s underlying IAM role can take write actions).
- CloudWatch metrics and CloudTrail audit logging for every request, so you can monitor and audit coding agent activity.
- Agent skills that have undergone thorough end-to-end evaluations, so you can be confident that workflows will complete successfully.

[AWS Labs](https://github.com/awslabs) MCP servers, skills, and plugins will continue to work and accept contributions, and over time the best of AWS Labs will be transitioned to the Agent Toolkit for AWS to ensure that customers can access the broadest array of tooling and guidance for their agents.

## License

This project is licensed under the Apache-2.0 License. See [LICENSE](LICENSE) for details.
