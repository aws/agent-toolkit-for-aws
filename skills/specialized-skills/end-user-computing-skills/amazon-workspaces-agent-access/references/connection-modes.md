# Connection Modes: BLOCKING vs POLLING

> **Connect mode is an HTTP header, not a tool parameter.** There is no `connect_to_desktop` tool and no `connection_mode` argument. You select the mode with the `X-Amzn-AgentAccess-Connect-Mode` request header (`BLOCKING` or `POLLING`), sent alongside whatever names the session (stack and user ID, streaming URL, a domain-joined stack ARN or SAML assertion, or image builder name).

Control how the agent waits for the desktop session with the `X-Amzn-AgentAccess-Connect-Mode` header. Applies to fleets, domain-joined or not, and to image builders — set it alongside whichever way the session is named.

| Mode | Behavior | When to use |
|---|---|---|
| `BLOCKING` (default) | Server waits until the desktop connection is fully established before responding. When `tools/list` returns, all desktop tools are immediately available. | Simple agents that can afford to wait on connect. |
| `POLLING` | Server responds immediately. `tools/list` initially returns only the `connection_status` tool. The agent polls it until the desktop is ready, then the full tool set appears. | The agent wants to do other work while the desktop starts, or you want explicit control over connection-timeout behavior. |

## POLLING flow

```python
import asyncio, json

headers = {
    "X-Amzn-AgentAccess-Streaming-Session-Url": streaming_url,  # non-domain-joined
    "X-Amzn-AgentAccess-Connect-Mode": "POLLING",
}

# After initialize, tools/list returns immediately with only agentaccess___connection_status:
tools = await session.list_tools()          # -> [agentaccess___connection_status]

# Poll until CONNECTED, and give up after 10 minutes:
deadline = asyncio.get_running_loop().time() + 600
while True:
    result = await session.call_tool("agentaccess___connection_status", {})
    status = json.loads(result.content[0].text)
    if status["state"] == "CONNECTED":
        break
    if asyncio.get_running_loop().time() > deadline:
        raise TimeoutError("the desktop did not connect within 10 minutes")
    await asyncio.sleep(2)

# Now the full desktop tool set is available:
tools = await session.list_tools()          # -> agentaccess___screenshot, agentaccess___left_click, ...
```

Key points:

- In POLLING mode, calling a desktop tool before `connection_status` reports `CONNECTED` will not work — only `connection_status` is exposed until the desktop connects.
- Re-list tools after `CONNECTED` to pick up the full set.
- The desktop typically connects in 5–30s (longer on cold starts).
