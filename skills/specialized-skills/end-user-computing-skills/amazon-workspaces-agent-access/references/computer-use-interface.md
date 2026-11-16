# Computer Use Interface

A computer use interface makes the Agent Access MCP server publish desktop tools in the format a computer-use model was trained on. The agent passes the model's computer-use calls to the MCP server without translating them in its own loop.

The customer selects the interface with this HTTP header:

```text
x-amzn-agentaccess-computer-use-interface-id: ANTHROPIC_COMPUTER_20250124
```

The header name is case-insensitive. Its value is case-sensitive. Send it on `tools/list` and every related `tools/call`. A missing or empty header keeps the standard tools from tools-reference.md.

Send the value only as the HTTP header. It is not a tool argument or stack setting.

## Supported interface

| Customer header value | What `tools/list` returns in place of the standard desktop tools |
|---|---|
| `ANTHROPIC_COMPUTER_20250124` | One `computer` tool that takes an `action`, as Claude's `computer_20250124` tool does |

Another header value is rejected with JSON-RPC `-32602`. Confirm current availability in the [Agent Access documentation](https://docs.aws.amazon.com/appstream2/latest/developerguide/agent-access-mcp-server.html) when precision matters.

Use this interface only with a model that produces Claude `computer_20250124` calls. A model using another computer-use tool version needs translation in the agent until Agent Access accepts a matching header value.

## Configure the MCP client

Configure the client to send the header on every request. With `mcp-proxy-for-aws`, add this argument to the configuration in connection-setup.md, under "From a coding agent's MCP config":

```json
"--header", "x-amzn-agentaccess-computer-use-interface-id=ANTHROPIC_COMPUTER_20250124"
```

A programmatic client adds the same value to the `headers` dictionary that names the stack, user, streaming URL, or image builder:

```python
headers={
    "x-amzn-agentaccess-computer-use-interface-id": "ANTHROPIC_COMPUTER_20250124",
    # Add the headers that identify the desktop session here.
}
```

The interface is selected per request. It is not stored on the stack or MCP session. Changing the header affects the next `tools/list` or `tools/call` request.

## Permissions

Interface calls use the `agentaccess-mcp` actions they perform. A `computer` call with `action: "left_click"` needs `LeftClick`, and one with `action: "screenshot"` needs `GetScreenshot`. The interface adds no IAM actions, so keep the stack-scoped or image-builder-scoped policy in connection-setup.md.

The signing principal does not need `appstream:DescribeStacks` for interface selection. Agent Access does not read `AgentAccessConfig.ComputerUseInterfaceId` from the stack.

## How the agent uses it

- Read the tool list from `tools/list` and give it to the model. Pass each computer-use call to the MCP tool with the same name and unchanged arguments.
- Only the standard desktop tools are replaced. Session tools such as `connection_status`, forwarded tools (`forwarded___<server>___<tool>`) and application catalog tools stay as they are.
- Actions the desktop cannot perform are absent from the interface schema and return JSON-RPC `-32602`. Claude `computer_20250124` actions such as `cursor_position` and `wait` are not accepted. Pause in the agent's own loop instead of calling `wait`.
- Claude actions that omit `coordinate`, such as `left_mouse_down` or a click at the current cursor, use the last pointer position the server saw. Before the first pointer action in a session there is no saved position, so provide a coordinate.

## When the standard tools appear instead

Check these items:

1. Confirm the client sends `x-amzn-agentaccess-computer-use-interface-id` on `tools/list` and each related `tools/call`.
2. Confirm the interface is enabled for the caller in the current Agent Access documentation. During rollout, a caller not enabled for interface selection receives the standard tools without an error.

If a related `tools/call` omits the header, Agent Access treats that request as using the standard interface, so the `computer` tool returns `Unknown tool`.

If the value is invalid, Agent Access returns JSON-RPC `-32602` instead of silently serving standard tools.
