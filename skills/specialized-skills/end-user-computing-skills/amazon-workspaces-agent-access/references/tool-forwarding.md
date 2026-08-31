# MCP Tool Forwarding

Tool forwarding lets agents call MCP servers running **on the Windows fleet host** — filesystem, fetch, or your own tools — alongside the desktop computer-use tools, through the same endpoint. Prefer forwarded tools over desktop automation for file and web tasks: reading a file with a forwarded tool is far more reliable than opening it in an app and reading pixels.

```
Agent → Agent Access MCP Server → DCV Server → your MCP server (stdio on the host)
```

## Setup (both are required)

Tool forwarding needs **both** an IAM grant and a service setting — IAM access does not override the service setting.

1. **Enable the service action:** turn on `FORWARD_MCP_TOOLS` in the stack's agent action configuration (API or console).
2. **IAM:** grant `agentaccess-mcp:CallForwardedTool` (plus `agentaccess-mcp:InvokeMcp` to establish the session, and any computer-use actions the agent also uses), scoped to the stack with the `agentaccess-mcp:StackArn` condition key. Prefer enumerated actions over `agentaccess-mcp:*`:
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
3. **Manifest on the fleet image** at `C:/ProgramData/NICE/dcv/mcp_server_redirection_config.json`:
   ```json
   {
     "mcpServers": {
       "filesystem": {
         "command": "C:/path/to/python.exe",
         "args": ["C:/mcpServerPath/filesystem.py", "C:/Users/Public/Documents"]
       },
       "weather": {
         "command": "C:/Program Files/my-mcp/weather.exe"
       }
     }
   }
   ```
   Only `command` (required, absolute path) and `args` (optional) are supported — no env vars or working directory. Servers inherit the session environment and run as the session user. The manifest must be saved as UTF-8 **without a BOM** — the service rejects a manifest that has one (Windows PowerShell 5.1's `Out-File -Encoding utf8` writes a BOM; ensure your editor/tool saves plain UTF-8).

## Constraints

- **stdio transport only.** Each entry launches a process that speaks MCP over stdin/stdout. Remote HTTP/SSE endpoints are not supported — wrap a remote endpoint in a local stdio server if needed.
- **Use forward slashes** in paths (JSON treats `\` as an escape). Windows accepts `/` in absolute paths.
- **5-second tool-call timeout.** Each forwarded tool call must complete within 5s or the server cancels it and returns an error. Design forwarded tools to return quickly.

## How forwarded tools appear

Forwarded tools are renamed to avoid collisions:
```
forwarded___<server-name>___<original-tool-name>
```
e.g. a `get_forecast` tool on the `weather` server appears as `forwarded___weather___get_forecast`. Agent code matching on tool names must expect this prefix. (Note: Bedrock Converse requires tool names match `[a-zA-Z0-9_-]+`, so some clients normalize dots to dashes — match forwarded tools by description, not exact spelling.)

## Requirements

Fleet image with a DCV Server build that supports MCP forwarding (check the current [Agent Access documentation](https://docs.aws.amazon.com/appstream2/latest/developerguide/agent-access-mcp-server.html) for the minimum version), Desktop stream view, `FORWARD_MCP_TOOLS` enabled on the stack, and MCP server binaries installed system-wide on the image.
