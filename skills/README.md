# Agent Skills for AWS

This directory contains agent skills — curated packages of instructions and reference materials that help AI coding agents complete AWS tasks effectively. We plan to release new and updated skills on a regular cadence.

## Using skills

There are three ways to get skills:

- **Install a plugin** — If you installed a plugin (aws-core, aws-agents, or aws-data-analytics), the skills bundled with that plugin are already available to your agent.

- **Install locally** — Copy skill directories from this repository to your agent's skills location, or use `npx skills add aws/agent-toolkit-for-aws/skills`.

- **Discover at runtime** — Agents can search for and load skills on demand through the AWS MCP Server, without any local installation. Ask your agent: "Search for AWS skills related to databases."

To install skills locally, copy the skill directory to your agent's skills location:

| Agent | Global skills path | Project skills path |
|-------|-------------------|-------------------|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.codex/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `.cursor/skills/` |
| Kiro | `~/.kiro/skills/` | `.kiro/skills/` |

## Skill categories

Skills are organized into two categories: **core** and **specialized**.

### Core skills

Core skills are bundled with the [aws-core plugin](../plugins/aws-core/) and provide
broad guidance across the most commonly used AWS services and development patterns.
We recommend installing the aws-core plugin as your starting point if you're building
and operating applications on AWS. It gives your agent foundational knowledge about
service selection, architecture decisions, SDK usage, infrastructure-as-code, security,
observability, and cost management.

Core skills cover:

- AWS SDK usage patterns (Python, JavaScript, Swift)
- Infrastructure as code (CDK, CloudFormation)
- Compute (serverless, containers)
- Security and identity (IAM)
- Observability (CloudWatch, X-Ray, CloudTrail)
- Application integration (messaging, streaming)
- Cost management (Billing and Cost Management)
- Full-stack applictaion development (AWS Blocks)
- Generative AI (Bedrock)

### Specialized skills

Specialized skills offer service-specific guidance and detailed workflows for common
tasks that agents struggle with. These go deeper than core skills — providing
step-by-step procedures for specific operations like creating a data lake table,
launching an EC2 instance with best practices, or troubleshooting EFS connectivity.

Install specialized skills when you're working in a specific domain and want your
agent to follow AWS-recommended procedures rather than improvising from general
knowledge.

Specialized skills are organized by AWS service category:

- **[Analytics](specialized-skills/analytics-skills/)**
- **[Database](specialized-skills/database-skills/)**
- **[EC2](specialized-skills/ec2-skills/)**
- **[Migration & Modernization](specialized-skills/migration-and-modernization-skills/)**
- **[Networking & Content Delivery](specialized-skills/networking-and-content-delivery-skills/)**
- **[Operations](specialized-skills/operations-skills/)**
- **[Security & Identity](specialized-skills/security-and-identity-skills/)**
- **[Serverless](specialized-skills/serverless-skills/)**
- **[Storage](specialized-skills/storage-skills/)**
- **[Web & Mobile development](specialized-skills/aws-amplify/)**
