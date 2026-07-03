# Networking

How traffic gets in and out of a MicroVM, what protocols are supported, and how the proxy header conventions work.

## Big picture

```
┌────────────┐  HTTPS / WSS    ┌─────────────────┐  TLS-PSK   ┌──────────────┐  TLS?  ┌─────────────────┐
│   Client   │ ── auth token ─▶│  Service proxy  │ ──────────▶│  MicroVM     │ ──────▶│  Application    │
│ (browser,  │                 │  (TLS terminate;│            │  Proxy Agent │        │  (any TCP-based │
│  curl,     │                 │   port routing) │            │              │        │   server: HTTP, │
│  app)      │                 │                 │            │              │        │   gRPC, WS)     │
└────────────┘                 └─────────────────┘            └──────────────┘        └─────────────────┘
```

> The proxy agent auto-detects whether the guest application speaks TLS.

Each MicroVM gets a **dedicated, service-managed HTTPS endpoint** (`https://<microvm-id>.lambda-microvm.<region>.on.aws`).

## Ingress (inbound)

### Default routing

By default, traffic on the proxy's external **port 443** is forwarded to **port 8080** inside the MicroVM.

### Choosing a different target port

Per-request: include `X-aws-proxy-port: <port>` (HTTP) or the WebSocket subprotocol `lambda-microvms.port.<port>`.

### Allowed ports inside the MicroVM

HTTP/HTTP2/gRPC/WebSocket on **any port**. Your application just needs to expose the port its hooks and server bind to.

### Ingress connector

For most workloads the default ingress is enough. Ports are configured per auth token via `--allowed-ports` on `create-microvm-auth-token`, not by ingress connectors.

### Per-token port restrictions

When generating an auth token, you can scope it to specific ports:

```bash
aws lambda-microvms create-microvm-auth-token \
  --microvm-identifier microvm-... \
  --expiration-in-minutes 30 \
  --allowed-ports '[{"port":8080},{"range":{"startPort":9000,"endPort":9001}}]'
```

The `allowedPorts` field is required. Each entry is one of: `{"port": N}` (single port), `{"range": {"startPort": N, "endPort": M}}` (range), or `{"allPorts": {}}` (unrestricted).

## Authenticating requests

The proxy expects a valid auth token in `X-aws-proxy-auth`. Tokens come from `CreateMicrovmAuthToken`. Max 60 min TTL.

### Two token APIs

| API | Purpose |
|---|---|
| `create-microvm-auth-token` | Application traffic. Requires `allowedPorts`. |
| `create-microvm-shell-auth-token` | Shell access (only when the `SHELL_INGRESS` network connector is attached). Works from the AWS console or a terminal WebSocket client. |

Both return a `TokenParts` map (multiple key/value entries) — typically you want the `X-aws-proxy-auth` value.

### curl

```bash
curl 'https://<microvm-endpoint>/' \
  -H "X-aws-proxy-auth: $TOKEN" \
  -H 'X-aws-proxy-port: 8080'
```

### Python

```python
import requests
r = requests.get(
    "https://<microvm-endpoint>/",
    headers={"X-aws-proxy-auth": TOKEN, "X-aws-proxy-port": "8080"},
)
```

### Browser / WebSocket

Browsers can't set arbitrary headers on WebSocket connections, so all proxy metadata travels via subprotocols:

```js
const protocols = [
  "lambda-microvms",                                   // required base
  `lambda-microvms.authentication.${authToken}`,        // auth
  "lambda-microvms.port.9000",                          // target port
];
const ws = new WebSocket("wss://<microvm-endpoint>/path", protocols);
```

The `lambda-microvms.*` subprotocols are **stripped before forwarding** to your application; your server should not see them on the upgrade request.

## Protocol support

| Protocol | Notes |
|---|---|
| HTTP/1.1 | Default. |
| HTTP/2 | Negotiated via ALPN on TLS (if supported), with HTTP/1.1 fallback. For plaintext connections, send `X-aws-proxy-force-h2: true` to force HTTP/2 over plaintext (H2C) to the upstream. |
| gRPC | Just HTTP/2 — works as soon as your server is on HTTP/2. |
| WebSockets | Standard upgrade flow. Use subprotocols for auth/port (above). |
| TLS to upstream | Optional. The proxy auto-detects whether your server speaks TLS and adjusts (re-encrypt for end-to-end TLS, or terminate at proxy). |

> Protocol negotiation in this table applies to proxy agent → guest application traffic inside the MicroVM. Client → proxy service traffic is always TLS-encrypted and negotiates HTTP/2 independently.

### Bandwidth ("proxy bandwidth capability")

Proxy throughput **scales with MicroVM size: ~1 MB/s per vCPU**. Exceeding the cap causes the in-guest proxy to apply backpressure (latency increases, no errors). Either reduce throughput or pick a larger MicroVM size.

## Egress (outbound)

### Public internet (default)

By default a MicroVM can reach any public address. No connector configuration required. Consider using VPC egress connectors to restrict outbound traffic to only required destinations for production workloads handling sensitive data.

### VPC egress (private resources)

Attach an **egress network connector** of type `VPC_EGRESS` to reach RDS / Aurora, ElastiCache, internal NLBs, on-prem via Direct Connect / VPN, S3 via VPC endpoints, etc.

Steps:

1. Build a `NetworkConnectorOperatorRole` (trust `lambda.amazonaws.com`; permissions to manage ENIs in your VPC):
   - `ec2:CreateNetworkInterface`, `ec2:CreateTags`.
2. Create the connector:

   ```bash
   aws lambda-core create-network-connector \
     --name my-vpc-egress \
     --configuration '{"VpcEgressConfiguration":{"SubnetIds":["subnet-..."],"SecurityGroupIds":["sg-..."],"NetworkProtocol":"IPv4","AssociatedComputeResourceTypes":["MicroVm"]}}' \
     --operator-role arn:aws:iam::<account>:role/NetworkConnectorOperatorRole
   ```

   States: `PENDING` (provisioning ENIs, up to ~10 min) → `ACTIVE` → `DELETING`. Failure → `FAILED` with `StateReason`.
3. Pass the connector ARN returned by `create-network-connector` at run time:

   ```bash
   aws lambda-microvms run-microvm \
     --image-identifier arn:aws:lambda:<region>:<account>:microvm-image:my-image \
     --egress-network-connectors '["arn:aws:lambda:<region>:<account>:network-connector:<connector-id>"]'
   ```

Constraints:

- All subnets in the connector must be in the same VPC.
- Security groups must be in that VPC.
- Connector must be in the same Region as the MicroVM image.
- `NetworkProtocol` supports both `IPv4` and `DualStack`.
- The connector is **bound at run time** — you can't swap connectors on suspend/resume.
- For internet *and* VPC access, configure a **NAT gateway** in your VPC.

## Reserved / stripped headers

The proxy reserves the `x-aws-proxy-*` namespace. Specifically:

- `X-aws-proxy-auth` — auth token (required).
- `X-aws-proxy-port` — target port (overrides default 8080).
- `X-aws-proxy-force-h2` — force HTTP/2 to upstream (`true`).

Unrecognized `x-aws-proxy-*` headers are stripped before forwarding. Don't use that namespace in your own application headers.

## Verifying connectivity

After run:

```bash
# Endpoint comes from RunMicrovm response or get-microvm
ENDPOINT=$(aws lambda-microvms get-microvm --microvm-identifier microvm-... --query 'endpoint' --output text)
TOKEN=$(aws lambda-microvms create-microvm-auth-token \
  --microvm-identifier microvm-... --expiration-in-minutes 5 \
  --allowed-ports '[{"port":8080}]' \
  --query 'authToken."X-aws-proxy-auth"' --output text)

curl -i "$ENDPOINT/" -H "X-aws-proxy-auth: $TOKEN"
```

A 502 from the proxy with the MicroVM in `RUNNING` state generally points at:

- App not listening on the target port (default 8080).
- TLS mismatch (proxy expects plaintext upstream, app speaks TLS without ALPN advertising HTTP/1.1).

See [`troubleshooting.md`](troubleshooting.md) for more.
