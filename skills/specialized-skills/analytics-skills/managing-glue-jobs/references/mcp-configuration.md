# Spark Upgrade MCP Server Configuration

The assessment uses the SageMaker Unified Studio (SMUS) Spark Upgrade MCP server, reached through `mcp-proxy-for-aws` with SigV4 authentication.

## If the server is not connected

- Give the user the configuration below for their client.
- The client loads MCP servers only at session start. After saving the configuration, the user must restart the session (Claude Code: quit and start again, or `/mcp` to reconnect where supported; other clients: reload or restart), then ask again.
- Requirements: `uv` and AWS credentials (see Requirements below).
- Or continue without the assessment ([auto-version-setup.md](auto-version-setup.md) Phase 0, option 2).

## Configuration

### Claude Code / generic MCP clients (`.mcp.json`)

```json
{
  "mcpServers": {
    "spark-upgrade": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://sagemaker-unified-studio-mcp.<region>.api.aws/spark-upgrade/mcp",
        "--service",
        "sagemaker-unified-studio-mcp",
        "--region",
        "<region>",
        "--read-timeout",
        "180"
      ],
      "timeout": 180000,
      "description": "SageMaker Unified Studio MCP for Spark upgrade assessment and execution"
    }
  }
}
```

### Kiro (`.kiro/settings/mcp.json`)

```json
{
  "mcpServers": {
    "spark-upgrade": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://sagemaker-unified-studio-mcp.<region>.api.aws/spark-upgrade/mcp",
        "--service",
        "sagemaker-unified-studio-mcp",
        "--region",
        "<region>",
        "--read-timeout",
        "180"
      ],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

Replace `<region>` (in both the endpoint URL and `--region`) with the supported region closest to the jobs being assessed, for example `us-east-1`. Region availability changes over time — check the current list in the [SageMaker Unified Studio MCP documentation](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/) rather than assuming a region is supported.

## Verification Steps

1. Confirm the proxy is runnable: `uvx mcp-proxy-for-aws@latest --help`
2. Confirm AWS credentials resolve: `aws sts get-caller-identity` (add `--profile <name>` if using a named profile)
3. Start or restart the agent session and list MCP tools; confirm the `spark-upgrade` server is connected and `generate_assessment` is present
4. Tools can take a few seconds to appear on first launch — restart the chat session if they do not load

## Requirements

- The AWS credentials used by the proxy need IAM permissions for the SageMaker Unified Studio MCP service, plus read access to the Glue jobs and their S3 script locations
- `uv`/`uvx` installed locally
- Outbound HTTPS access to the regional `sagemaker-unified-studio-mcp` endpoint
