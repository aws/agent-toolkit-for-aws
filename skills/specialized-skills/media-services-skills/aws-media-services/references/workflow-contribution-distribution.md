# Contribution and Distribution Transport

MediaConnect reliable transport patterns for getting content into and out of AWS.

---

## Protocol Selection

```
IF contribution over internet or Direct Connect:
  → SRT (encryption, retransmission, bandwidth estimation)
IF low-latency over managed network (no internet):
  → RTP+FEC (lowest latency, no retransmission)
IF simple cloud-native source:
  → RTMP (~10 Mbps max, legacy but universal)
IF uncompressed between AWS services (same AZ):
  → CDI (zero compression loss, requires EFA)
IF lightly compressed professional (cross-AZ OK):
  → ST 2110 JPEG XS (requires Large/XL flows)
```

**Default recommendation:** SRT for contribution over any network path.

---

## SRT Tuning

| | |
|---|---|
| **Preconditions** | Measured RTT between source and destination |
| **Key parameter** | Latency = 4× RTT |

### Decision: SRT latency

```
IF RTT is measured:
  → Set latency to ~4× RTT
IF RTT is unknown up front:
  → Start with a conservative value, then measure and adjust as soon as the path is live
IF path crosses internet with variable RTT:
  → Use ~4× worst-case RTT (not average)
```

**Thundering herd:** SRT bursts above steady-state during retransmissions. Keep Direct Connect utilization well below the link's steady-state ceiling (around 50% is a common operator target) so retransmission bursts do not cause loss.

**Caller/listener mode:**

- Listener (MediaConnect listens, source calls): simpler firewall rules
- Caller (MediaConnect calls source): use when source can't accept inbound

---

## SRT Encryption

| | |
|---|---|
| **Preconditions** | Source encoder supports SRT encryption (most do) |

### Decision: encrypt the SRT path?

```
IF the path crosses the public internet OR carries unreleased/sensitive content:
  → Enable SRT encryption (REQUIRED for production over public paths)
IF the path is fully on a private network (Direct Connect, customer VPN) AND
  → traffic is already protected at a lower layer:
  → Encryption is OPTIONAL but still RECOMMENDED for defense in depth
```

**Configuration:**

- Both source and MediaConnect MUST agree on the passphrase. Length: 10-79
  characters.
- Use AES-256 by default; AES-128 is acceptable when the source encoder
  does not support 256.
- Rotate passphrases periodically; use AWS Secrets Manager or your
  operator's secret store rather than embedding the passphrase in
  CloudFormation parameters or scripts.

**MediaConnect Source `Decryption` shape:**

```json
{
  "Algorithm": "aes256",
  "KeyType": "static-key",
  "RoleArn": "<role-arn>",
  "SecretArn": "<secrets-manager-arn>"
}
```

The Secrets Manager secret contains the passphrase as plaintext. The
referenced IAM role MUST allow `secretsmanager:GetSecretValue` on that
secret.

---

## Direct Connect Sizing

| | |
|---|---|
| **Preconditions** | Known source bitrate, number of feeds, redundancy requirements |

### Decision: Resilience level

```
IF production live event:
  → Multi-location + multi-connection per location (maximum redundancy)
  → LOAD references/workflow-resilience-patterns.md for DX failover patterns
IF non-critical workflow:
  → Multi-location + single-connection per location
IF dev/test only:
  → Single location + single connection
```

**Bandwidth planning:** Account for SRT retransmission bursts above steady-state when sizing the link. Always have a non-AWS backup path for critical signals.

| Source | Codec | Typical bitrate |
|--------|-------|----------------|
| 1080p contribution | H.264 | 30-40 Mbps |
| 4K contribution | H.265 | 70-95 Mbps |
| 720p contribution | H.264 | 7-32 Mbps |

---

## Fan-Out Patterns

**Single source to multiple destinations:**

```
Source → MediaConnect Flow
  → Output 1: MediaLive Channel A (primary encode)
  → Output 2: MediaLive Channel B (4K/HEVC)
  → Output 3: S3 recording
  → Output 4: Monitoring/multiviewer
```

**Multi-region distribution:**

```
Source → MediaConnect Flow (Region A)
  → Output 1: MediaLive (Region A)
  → Output 2: MediaConnect Flow (Region B, via SRT or entitlement)
    → MediaLive (Region B)
```

**Cross-account sharing:** Use MediaConnect entitlements (one-way, granting account controls access).

---

## MediaConnect Router Patterns

### Router use-case patterns

The Router provides dynamic, real-time routing of live video between sources and
destinations across AWS Regions. The following use cases are documented on the
[MediaConnect Router feature page](https://aws.amazon.com/mediaconnect/features/router/):

- **Cloud playout** — connect cloud services for playing videos, adding graphics, and switching live feeds.
- **Primary distribution** — deliver TV network channels to cable, satellite, and streaming services.
- **Central control** — dynamically route and manage live video streams between input and output resources across multiple AWS Regions from a single, unified management interface.
- **Live event production** — route live feeds to live production applications in the AWS Cloud.
- **FAST channel distribution** — manage and distribute multiple FAST channels.

Per the [Router documentation](https://docs.aws.amazon.com/mediaconnect/latest/ug/using-mediaconnect-router.html),
the Router can connect existing MediaConnect flows to router inputs and outputs,
use MediaLive inputs as destinations for router outputs, and use MediaLive channel
outputs as sources for router inputs. Each router I/O supports up to 50 Mbps;
content above that, or protocols other than SRT/RTP/RTP-FEC/RIST, requires Flows.

### Cloud playout architecture

```
Graphics/Slate source (SRT ≤50 Mbps)   → Router Standard Input "Slate"
Live feed A (SRT ≤50 Mbps)             → Router Standard Input "LiveA"
Live feed B (SRT ≤50 Mbps)             → Router Standard Input "LiveB"
Pre-recorded (from Flow)               → Router Flow Input "VOD-Feed"
                                          ↓
                                    Router Matrix (instant takes)
                                          ↓
Router MediaLive Output "Encode-Out"   → MediaLive (encode to ABR)
                                          → MediaPackage → CloudFront
```

**Key point:** The operator uses the Router control panel or matrix view to "take" different inputs to the output in real time. This replaces a traditional master control switcher.

### Primary distribution architecture

```
MediaLive Channel 1 → Router Input "Channel-ESPN"    (type: MediaLive channel)
MediaLive Channel 2 → Router Input "Channel-News"    (type: MediaLive channel)
MediaLive Channel 3 → Router Input "Channel-Sports"  (type: MediaLive channel)
                                          ↓
                                    Router Matrix
                                          ↓
Router Output "Affiliate-East" (SRT caller → affiliate encoder, us-east-1)
Router Output "Affiliate-West" (SRT caller → affiliate encoder, us-west-2)
Router Output "OTT-Encode"     (MediaLive output → OTT ABR encoding)
Router Output "Archive"        (Standard → recording endpoint)
```

**Key point:** One input can feed up to 10 outputs simultaneously. Route assignments change instantly — during breaking news, switch all affiliates from scheduled programming to the news feed with a single matrix operation.

### FAST channel distribution architecture

```
FAST Channel 1 (encoded ≤50 Mbps) → Router Input "FAST-Ch1"
FAST Channel 2 (encoded ≤50 Mbps) → Router Input "FAST-Ch2"
FAST Channel 3 (encoded ≤50 Mbps) → Router Input "FAST-Ch3"
...up to 20 inputs per region
                                          ↓
                                    Router Matrix
                                          ↓
Router Output → Platform A (Tubi ingest endpoint)
Router Output → Platform B (Pluto TV ingest endpoint)
Router Output → Platform C (Roku Channel endpoint)
Router Output → Cross-region (Router output in eu-west-1 for international)
```

**Key point:** Adding or removing a FAST platform is a route assignment change — no infrastructure reconfiguration needed. Cross-region routing is native.

### Hybrid pattern: high-bitrate contribution + Router switching

When source bitrate exceeds 50 Mbps, use Flows for ingest and the Router for switching downstream:

```
On-prem encoder (100 Mbps H.264 via SRT)
  → MediaConnect Flow (Extra Large, 400 Mbps capacity)
  → MediaLive (encode to mezzanine ≤50 Mbps)
  → Router Input (type: MediaLive channel)
  → Router Matrix (dynamic switching/distribution)
  → Router Outputs → multiple downstream destinations
```

This is REQUIRED when both dynamic switching AND high-bitrate contribution are needed. The Router CANNOT handle >50 Mbps directly.

### Decision: Router vs Flows

For the Router-vs-Flows decision tree (supported protocols, the 50 Mbps I/O
limit, and the documented Router use cases), see the **When to use Router vs
Flows** section in `references/service-rules-mediaconnect.md`. That file is the
single source of truth for the decision; this file covers how to set up and
integrate the Router once you have decided to use it.

### Router setup sequence

1. **Create network interfaces** — public (CIDR allowlist) or VPC (subnet + security groups).
2. **Create router I/Os** — specify type (standard, failover, merge, flow, MediaLive), protocol, network interface.
3. **Start I/Os** — async; poll until Active.
4. **Assign routes** — take input → output. Can be done regardless of I/O state.

### Router + MediaLive integration

**Router output → MediaLive (send routed content for encoding):**

1. MediaLive operator creates input with type "MediaConnect router", specifies AZ (and pipeline ID for standard channels).
2. In MediaConnect, create router output with type "MediaLive input", specify ML input ARN + pipeline ID.
3. Assign a route from a router input to this output.
4. Attach input to MediaLive channel and start channel.

**MediaLive → Router input (route encoded output for distribution):**

1. MediaLive operator configures channel with a "MediaConnect Router" output group, specifies AZ and output name.
2. In MediaConnect, create router input with type "MediaLive channel", specify ML channel ARN + pipeline ID + output name.
3. Start both the channel and the router input.
4. Assign routes from this input to downstream outputs.

**Constraint:** Router I/O and MediaLive pipeline MUST be in same AZ and region.

### Router redundancy patterns

```
IF production requiring full AZ redundancy:
  → Dual-AZ failover input (two source endpoints, automatic switching)
  → Supported failover protocols: RTP, RIST, SRT-listener, SRT-caller
IF content merge needed (e.g., primary + backup combined):
  → Merge input (two sources with configurable merge window)
  → Supported merge protocols: RTP, RIST only
IF single-AZ output used with dual-AZ input:
  → WARNING: negates availability benefit, SHOULD NOT be used for production
```

---

## SRT Egress (MediaLive → MediaConnect Flow)

Pattern for receiving encoded content back from MediaLive into a flow for redistribution.

### When to use

- MediaLive encodes, then content needs cross-region fan-out via MediaConnect.
- MediaLive output needs redistribution to multiple affiliates.

### Setup sequence

1. Agree on encryption passphrase with MediaLive operator; store in Secrets Manager.
2. Create MediaConnect flow with SRT listener source (port, latency, secret ARN).
3. Note flow's inbound IP address from Sources tab.
4. MediaLive operator creates SRT caller output group targeting flow's IP:port.
5. After channel creation, update flow's allowlist CIDR with MediaLive's source IP(s).
6. Start flow (wait for ACTIVE), then start MediaLive channel.

### Constraints

- Standard ML channel → two flow sources needed. Single-pipeline → one.
- Passphrase MUST be in Secrets Manager. MUST NOT be inline.
- VPC: ML channel subnet MUST have Secrets Manager VPC endpoint; same security group on both.

---

## Downstream NDI converter caveat

When an external NDI converter is placed after a MediaConnect SRT output, test
the full chain before production. Converter-side issues observed include
intermittent audio stops, repeated fields with interlaced content,
timecode-passthrough problems, and 10-bit playback issues on some receivers.
These are converter limitations, not MediaConnect limitations.

---

## On-Premises Encoder Integration

**Pre-event checklist:**

1. Pin encoder software versions (do not upgrade during event prep)
2. Reboot contribution encoders several days before event (clears timecode drift)
3. Set input loss behavior to Emit Output (not Pause) for live events
4. Set timecode source to system_clock for EXT-X-PROGRAM-DATE-TIME
5. Set encoder GOP size so segment duration is an integer multiple of it (typically 2-second GOP for 2/4/6-second segments)

**Validation:** Confirm content flowing via CloudWatch `SourceBitRate > 0` after encoder start.
