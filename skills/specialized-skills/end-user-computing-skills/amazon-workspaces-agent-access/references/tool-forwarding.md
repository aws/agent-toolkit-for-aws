# MCP Tool Forwarding

Tool forwarding lets agents call MCP servers running **on the Windows desktop** — filesystem, fetch, or your own tools — alongside the desktop computer-use tools, through the same endpoint. Prefer forwarded tools over desktop automation for file and web tasks: reading a file with a forwarded tool is far more reliable than opening it in an app and reading pixels.

```
Agent → Agent Access MCP Server → DCV Server → your MCP server (stdio on the host)
```

## What has to be in place (both are required)

Tool forwarding needs **both** a service setting on the environment and an IAM grant for the agent — IAM access does not override the service setting.

1. **The environment:** `FORWARD_MCP_TOOLS` enabled in the stack's (or image builder's) `AgentAccessConfig`, and the MCP servers installed on the image and listed in its manifest, `C:/ProgramData/NICE/dcv/mcp_server_redirection_config.json`. Only stdio servers can be forwarded, not remote HTTP/SSE ones. Installing the servers and writing the manifest is the `setting-up-workspaces-applications` skill (image setup).
2. **IAM:** grant `agentaccess-mcp:CallForwardedTool` (plus `agentaccess-mcp:InvokeMcp` to establish the session, and any computer-use actions the agent also uses), scoped to the stack with the `agentaccess-mcp:StackArn` condition key (on an image builder, `agentaccess-mcp:ImageBuilderArn`; see image-builders.md). Prefer enumerated actions over `agentaccess-mcp:*`. `CallForwardedTool` allows every forwarded server on the image, so the manifest is the only per-tool control: list only the servers the agent may call.

   ```json
   {
     "Effect": "Allow",
     "Action": [
       "agentaccess-mcp:InvokeMcp",
       "agentaccess-mcp:CallForwardedTool"
     ],
     "Resource": "*",
     "Condition": {
       "ArnLike": { "agentaccess-mcp:StackArn": "arn:aws:appstream:<region>:<account>:stack/<stack>" }
     }
   }
   ```

If `tools/list` shows no `forwarded___` tools, one of these is missing: check `FORWARD_MCP_TOOLS` with `describe-stacks` or `describe-image-builders` (prerequisites.md), then the manifest on the image or builder.

## How forwarded tools appear

Forwarded tools are renamed to avoid collisions:

```
forwarded___<server-name>___<original-tool-name>
```

`<server-name>` is the server's key in the manifest. For example, a `get_forecast` tool on the `weather` server appears as `forwarded___weather___get_forecast`. Agent code matching on tool names must expect this prefix. (Bedrock Converse requires tool names to match `[a-zA-Z0-9_-]+`, so some clients turn dots into dashes. Match a forwarded tool by the exact name your client lists, never by its description, because any server on the image can describe its tools however it likes.)

## Calling them

- **5-second timeout.** Each forwarded tool call must complete within 5 seconds, or the server cancels it and returns an error. A tool that needs longer is a design problem on the server side, not something to retry.
- **Servers run as the session user**, with the session's environment, so their file access matches that user's.
- **Read the error string.** A failed forwarded call returns an error string; often it's a path outside the server's sandbox or the timeout (troubleshooting.md).
