# Service Rules: MediaConnect

Loaded conditionally when the task involves MediaConnect. The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

---

## MediaConnect

### Flow sizing

- Flow size determines max bitrate: Standard (80 Mbps), Large (150 Mbps), Extra Large (400 Mbps). These tiers are a stable, core part of the service and drive flow-sizing decisions; see the [MediaConnect Service Quotas documentation](https://docs.aws.amazon.com/mediaconnect/latest/ug/quotas.html) for the full specification.
- ST 2110 JPEG XS and CDI REQUIRE Large or Extra Large flows.

### VPC interfaces

- A flow MUST NOT have more than 1 EFA interface. The second interface MUST be ENA type.
- EFA is REQUIRED for CDI and ST 2110 JPEG XS sources.
- Subnet and security groups MUST be in the same AZ as the flow.

### ST 2110 JPEG XS sources

- `WhitelistCidr` and `IngestPort` MUST NOT be specified at the source level. Ports MUST be defined in `MediaStreamSourceConfigurations[].InputConfigurations[]`.
- Exactly TWO `InputConfigurations` are REQUIRED per media stream (for redundancy).
- Both MUST use DISTINCT interface names but the SAME port.
- `MaxSyncBuffer` valid range: 0-250.
- Each essence MUST have its own port: video (e.g., 5000), audio (e.g., 5001), ancillary (e.g., 5002).

### CDI outputs

- Encoding names MUST be: `raw` (video), `pcm` (audio), `smpte291` (ancillary). The value `cdi` MUST NOT be used.
- `destinationConfigurations` MUST NOT be included for CDI outputs (ST 2110 outputs only).
- `CidrAllowList` MUST NOT be included for CDI protocol.
- CDI outputs MUST NOT be configured for cross-AZ transfers.
- When a user proposes cross-AZ CDI, agents MUST flag the AZ constraint and MUST suggest ST 2110 JPEG XS as the cross-AZ alternative for high-quality transport.

### SRT

- MediaConnect MAY act as either caller or listener.
- Passphrase length MUST be 10-79 characters if encryption is enabled.
- SRT latency SHOULD be configured to approximately 4× the measured round-trip time. If RTT cannot be measured up front, configure a conservative initial value, then measure and adjust. Worst-case path RTT (not average) SHOULD be used for variable internet paths.
- Direct Connect utilization SHOULD be kept well below the link's steady-state ceiling (around 50% is a common operator target) so SRT retransmission bursts do not cause packet loss.

### MediaConnect Router

- Resilient endpoints are paired zonal endpoints. For full AZ redundancy, a dual-AZ input MUST be paired with a dual-AZ output.
- Dual-AZ input with single-AZ output negates the availability benefit and SHOULD NOT be used for production.
- Cross-account routing is not natively supported. VPC peering or MediaConnect entitlements SHOULD be used to share content across accounts.
- When an external NDI converter is used downstream of an SRT output, validate behavior end-to-end before production: NDI converters can exhibit intermittent audio stops, repeated fields with interlaced content, timecode-passthrough issues, and 10-bit playback issues on some receivers. These are converter-side limitations, not MediaConnect limitations.

### General

- A flow MUST be in STANDBY to modify its configuration (add/remove outputs, change source).
- Billing starts when flow status is ACTIVE, regardless of whether outputs are consuming.
- `start-flow` / `stop-flow` are async. Agents MUST poll `Flow.Status` until ACTIVE or STANDBY.

---

## MediaConnect Router

The Router is a separate capability from Flows — a software-defined routing matrix for dynamic live switching. When a query involves dynamic any-to-any switching, central control across regions, or cloud playout, the Router is the primary recommendation.

### When to use Router vs Flows

Use the Router when the workflow needs **dynamic, real-time switching** between sources and destinations. Use Flows for protocols or bitrates the Router does not support.

```
IF protocol is CDI, ST 2110 JPEG XS, NDI, or Zixi:
  → Flows (Router supports only SRT, RTP, RTP-FEC, RIST)
IF bitrate > 50 Mbps per stream:
  → Flows (Router I/O is capped at 50 Mbps)
IF dynamic any-to-any switching across many sources and destinations:
  → Router
IF cloud playout (switching live feeds, adding graphics via cloud services):
  → Router
IF primary distribution (TV network channels to cable, satellite, streaming):
  → Router
IF FAST channel distribution (manage and distribute multiple FAST channels):
  → Router
IF live event production (routing live feeds to production applications):
  → Router
IF central control across multiple regions from one interface:
  → Router
```

The supported use cases above are from the [MediaConnect Router feature page](https://aws.amazon.com/mediaconnect/features/router/). Protocol and bitrate limits are from the [Router considerations and limitations](https://docs.aws.amazon.com/mediaconnect/latest/ug/using-mediaconnect-router.html) documentation.

**Key differentiator:** the Router provides unified, cross-region management — create and manage router I/Os across multiple AWS Regions from a single console, view all active routes at once, and make bulk route changes. Flows are individual point-to-point transport pipes.

### Common hybrid pattern (Flows + Router together)

When content arrives at high bitrate (>50 Mbps) or uses protocols the Router doesn't support, use Flows for ingest and the Router for downstream switching:

```
Source (100 Mbps H.264 via SRT)
  → MediaConnect Flow (transport into AWS, supports up to 400 Mbps)
  → MediaLive (encode to ≤50 Mbps ABR or mezzanine)
  → MediaConnect Router input (type: MediaLive channel)
  → Router matrix (dynamic switching/distribution)
  → Router outputs → downstream destinations (affiliates, CDNs, other regions)
```

This is the recommended architecture when BOTH dynamic switching AND high-bitrate contribution are required. Agents MUST NOT recommend the Router alone for >50 Mbps content.

### Correct Router setup sequence

Agents MUST follow this order when setting up a Router workflow:

1. **Create network interfaces** — public (with CIDR allowlist) or VPC (with subnet + security groups). These define how Router I/Os connect to the network.
2. **Create router inputs** — specify type (standard, failover, merge, flow, MediaLive channel), protocol, and network interface.
3. **Create router outputs** — specify type (standard, flow, MediaLive), protocol, and network interface.
4. **Start I/Os** — async operation; MUST poll until Active before content can flow.
5. **Assign routes** — "take" an input to each output. Routes CAN be assigned regardless of I/O state (before or after starting), but an output with no assigned input carries no content.

**Critical pitfall for Router-to-MediaLive:** content reaches a MediaLive input only once (a) the router I/Os are Active AND (b) a route has been assigned to the output feeding MediaLive. There is NO separate "enable output" action — assigning the route (the "take") is what connects a source to the output. An output left with no input assigned is the most common reason MediaLive receives nothing.

### Supported protocols

- SRT, RTP, RTP-FEC, RIST only.
- CDI, ST 2110 JPEG XS, Zixi, and NDI MUST NOT be used with the Router. These require Flows.

### Capacity limits

- **Router I/O size:** each router I/O supports up to 50 Mbps. This per-I/O ceiling is a stable, core service characteristic and a primary decision driver — content above 50 Mbps per stream MUST use Flows instead of the Router.
- Each router output connects to only one input at a time; one input can feed multiple outputs.
- Region-level counts (router inputs/outputs per Region) and network-interface limits (interfaces per Region, CIDR ranges per public interface, security groups per VPC interface) are adjustable account quotas — look up current values in [MediaConnect Service Quotas](https://docs.aws.amazon.com/mediaconnect/latest/ug/quotas.html) and [Router considerations and limitations](https://docs.aws.amazon.com/mediaconnect/latest/ug/using-mediaconnect-router.html).

### I/O types

- **Standard input**: single source endpoint.
- **Failover input**: two source endpoints, manual or automatic switching. Supported protocols: RTP, RIST, SRT-listener, SRT-caller.
- **Merge input**: combines two source endpoints with configurable merge window. Supported protocols: RTP, RIST only.
- **Flow input**: receives content from a MediaConnect flow.
- **MediaLive channel input**: receives content from a MediaLive channel output.
- **Standard output**: sends to a downstream destination.
- **Flow output**: sends content to a MediaConnect flow.
- **MediaLive output**: sends content to a MediaLive input.
- Converting between failover and merge input types REQUIRES recreating the input.

### Cross-region routing

- The Router supports native cross-region routing with adaptive multipath delivery. No entitlements are needed (entitlements are a Flow concept).
- ARQ latency on inputs is configured for source-to-input distance only; the Router manages inter-region transport internally.
- ARQ latency on outputs is configured for output-to-destination distance only.

### State management

- I/Os have states: Standby → Active. `start` / `stop` operations are async; agents MUST poll until the expected state is reached.
- I/Os MUST be in standby to change maintenance schedule.
- Maintenance restarts occur automatically every 60-66 days from I/O start. Preferred day/hour can be set at creation or while in standby.
- Route assignments (takes) can be made regardless of I/O state.

### Fault tolerance

- The Router provides automatic fault tolerance at EC2, AZ, and regional levels by migrating and restoring I/O state.

### API operations
Key Router API operations:
`CreateRouterInput`, `CreateRouterOutput`, `UpdateRouterInput`, `UpdateRouterOutput`,
`DeleteRouterInput`, `DeleteRouterOutput`, `AssignRoute`, `StartRouterIo`,
`StopRouterIo`, `CreateRouterNetworkInterface`, `DeleteRouterNetworkInterface`.

API reference: https://docs.aws.amazon.com/mediaconnect/latest/api/

When working with the Router, agents SHOULD read the API reference to discover
required parameters rather than guessing. Agents MUST NOT substitute Flow API
operations (create-flow, add-flow-outputs) when the user requests Router functionality.

---

## SRT Egress (MediaLive → MediaConnect)

Pattern for receiving encoded SRT output from MediaLive into a flow for redistribution.

### Setup sequence

1. Store agreed SRT encryption passphrase in Secrets Manager (AES-128, AES-192, or AES-256).
2. Create MediaConnect flow with SRT listener source (specify port, latency, encryption secret ARN).
3. Note the flow's inbound IP address from the Sources tab.
4. MediaLive operator creates SRT caller output group pointing to the flow's IP:port.
5. After MediaLive channel is created, update flow's allowlist CIDR with MediaLive channel's source IP(s).
6. Start flow first (wait for ACTIVE), then start MediaLive channel.

### Constraints

- Standard MediaLive channel → two flow sources (one per pipeline). Single-pipeline → one source.
- Encryption passphrase MUST be stored in Secrets Manager. Agents MUST NOT embed passphrases inline.
- For VPC delivery: subnet for MediaLive's channel output MUST have a Secrets Manager VPC endpoint. The subnet and endpoint MUST share the same security group.
- Same-account services MAY share one Secrets Manager secret. Cross-account requires separate secrets with identical passphrases.

---
