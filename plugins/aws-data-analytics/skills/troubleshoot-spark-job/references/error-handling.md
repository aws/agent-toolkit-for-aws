# Error Handling for Spark Troubleshooting

## MCP Server Failed to Load

- Verify MCP configurations are properly configured
- Validate JSON syntax: ensure no missing commas, quotes, or brackets
- Verify local AWS credentials for the MCP proxy
- Run `/mcp` (IDE chat slash-command) to verify MCP server availability

## Slow Tool Loading

- Tools may take a few seconds to load on first launch
- If tools don't appear, restart the chat
- Run `/tools` (IDE chat slash-command) to verify tool availability
- Run `/mcp` to confirm the server launched without error

## Documentation

For detailed setup, IAM permissions, and workflow guidance:

- [Overview](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshoot.html)
- [Features and Capabilities](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-features.html)
- [Setup](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-setup.html)
- [IAM Permissions](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-iam-setup.html)
- [Using the Agent](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-using-troubleshooting-agent.html)
- [Workflow Details](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-workflow.html)
- [Troubleshooting and Q&A](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-troubleshooting.html)
