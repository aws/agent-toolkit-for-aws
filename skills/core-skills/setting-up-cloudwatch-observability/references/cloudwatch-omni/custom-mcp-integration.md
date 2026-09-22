# Connecting a custom MCP server to CloudWatch Omni

This reference covers **first-time setup**: registering your own Model Context
Protocol (MCP) tool server with a CloudWatch Omni Space so the assistant can call
its tools, and choosing the authentication the server requires. Invoking the tools
once they are connected happens through the Omni assistant in the CloudWatch
console; these skills do not drive it.

CloudWatch Omni can call tools served by an MCP server, so you can extend the
assistant with your own capabilities.

## Who sets this up

Registering a custom MCP server is a self-serve action in the CloudWatch Omni web
app, under **Settings → Integrations**. It requires the CloudWatch integration
permissions.

## Registering a custom MCP server

A server you register uses one of **two transports**:

1. **HTTP** — point CloudWatch Omni at an HTTP endpoint that speaks MCP. Supply the
   URL and the authentication the endpoint requires (see below).
2. **stdio** — CloudWatch Omni launches the server as a local command over standard
   input/output. The command is restricted to **`uvx`** (for Python-packaged
   servers) or **`npx`** (for Node-packaged servers); you supply the arguments and
   any environment variables.

Authentication types apply to **HTTP** servers. A stdio server is launched rather
than called over the network, so it is configured with its command, arguments and
environment instead.

### stdio servers and credentials

For a stdio server that needs to call AWS, you can have CloudWatch Omni **inject
the Space's AWS credentials** into the launched process, so the server acts with
the access you have granted rather than carrying its own secrets. A stdio server
may also read named keys from an **AWS Secrets Manager** secret you point it at,
for credentials that are not AWS ones.

## Authentication for HTTP servers

When you register an HTTP MCP server, choose one of five authentication types. Each
is shown here with the identifier CloudWatch Omni uses for it:

- **None** (`NONE`) — the endpoint needs no credentials.
- **API Key** (`API_KEY`) — CloudWatch Omni sends an API key you provide on each
  request.
- **Bearer Token** (`BEARER_TOKEN`) — CloudWatch Omni sends a bearer token you
  provide.
- **OAuth2 Client Credentials** (`OAUTH2_CLIENT_CREDENTIALS`) — a
  machine-to-machine grant using a client ID and secret; CloudWatch Omni fetches
  the token directly, with no user prompt.
- **OAuth2 Authorization Code** (`OAUTH2_AUTHORIZATION_CODE`) — a user-consent
  grant. You additionally supply an **Authorization URL**, and CloudWatch Omni
  runs a two-step consent flow: you are redirected to the provider to approve
  access, then a callback completes the exchange and CloudWatch Omni stores the
  resulting token.

Credentials are held securely and are **never stored in the integration record**
itself; the record references them rather than embedding them.

### Which one for an OAuth-protected server

If your server is protected by OAuth, choose one of the two OAuth2 types — not
`API_KEY` or `BEARER_TOKEN`. Decide between them by **who consents**:

- Choose **OAuth2 Client Credentials** (`OAUTH2_CLIENT_CREDENTIALS`) when the
  server authenticates machine-to-machine — CloudWatch Omni holds a **client ID
  and secret** and fetches the token itself, with **no human in the loop**. This
  is the common choice for a service-to-service MCP endpoint.
- Choose **OAuth2 Authorization Code** (`OAUTH2_AUTHORIZATION_CODE`) when a
  **user must approve access** in the provider's consent screen. This type also
  requires an **Authorization URL**, and the setup runs the redirect-and-callback
  consent flow described above.

## Discovering and managing tools

- After you register a server, CloudWatch Omni **probes** it to discover the tools
  it exposes and reports the server's health, so you can confirm it connected
  before relying on it.
- You can **enable or disable individual tools** from a server, exposing only the
  ones you want the agent to use.
- An account can hold roughly **ten** active integrations at a time. Disable or
  remove servers you no longer need to stay within the limit.

## Next: using the connection

Once a custom MCP server is registered and healthy, the assistant can call its
enabled tools during a session. That invocation happens through the Omni assistant
in the CloudWatch console; these skills do not drive it.
