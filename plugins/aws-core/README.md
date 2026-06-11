# aws-core

The primary plugin for the Agent Toolkit for AWS. This plugin gives your AI coding agent the AWS MCP Server configuration and a curated set of agent skills — everything it needs to build, deploy, and manage applications on AWS.

## Install

### Claude Code

```
/plugin install aws-core@claude-plugins-official
/reload-plugins
```

### Codex

In your terminal:

```
codex plugin marketplace add aws/agent-toolkit-for-aws
```

Then launch Codex and run `/plugins` to browse and install the **aws-core** plugin.

## What's included

### AWS MCP Server

This plugin configures the [AWS MCP Server](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html), a managed server that gives your agent:

- Real-time AWS documentation search through `search_documentation` (no authentication required)
- On-demand skill discovery and retrieval through `retrieve_skill` (no authentication required)
- Authenticated access to any of the 300+ AWS services through `call_aws`
- Sandboxed Python script execution through `run_script`

### Skills

This plugin includes the following default skills:

| Skill | Description |
|-------|-------------|
| billing-and-cost-management | Analyze, monitor, and optimize AWS costs |
| aws-sdk-js-v3-usage | Best practices for the AWS SDK for JavaScript v3 |
| aws-sdk-python-usage | Best practices for the AWS SDK for Python (boto3) |
| aws-sdk-swift-usage | Best practices for the AWS SDK for Swift |
| aws-serverless | Build serverless applications on AWS |
| bedrock | Build with Amazon Bedrock foundation models |
| cdk | Define and manage AWS infrastructure with CDK and CloudFormation |
| cloudformation | CloudFormation deployment, validation, and troubleshooting |
| observability | Monitor applications with CloudWatch |
| containers | Run containerized workloads on AWS |
| storage | Store and manage data with AWS storage services |
| amplify-gen2 | Build full-stack web and mobile applications with AWS Amplify Gen2 |

<!-- [TODO] Confirm final skill list matches what ships in the plugin. deploy-to-aws status is RED in tracker. -->

### Rules files

Recommended AWS rules files are available separately in the [`rules/`](../../rules/) directory of this repository.

## Documentation

- [User guide](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/)
- [AWS MCP Server tools reference](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/understanding-mcp-server-tools.html)
