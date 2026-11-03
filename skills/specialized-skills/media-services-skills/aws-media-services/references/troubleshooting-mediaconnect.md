# Troubleshooting: MediaConnect

Per-service troubleshooting guidance for MediaConnect flow and Router issues.

---

## Symptom Router

```
IF flow won't start:
  → See "Flow Won't Start" below
IF source not receiving (flow ACTIVE but no content):
  → See "Source Not Receiving" below
IF output not delivering (source OK but destination not getting content):
  → See "Output Not Delivering" below
IF MediaConnect Router issues (paired resilient endpoints, downstream NDI converter):
  → See "MediaConnect Router Issues" below
  → LOAD references/workflow-contribution-distribution.md for router architecture patterns
```

---

## Flow Won't Start

| | |
|---|---|
| **Symptom** | Flow stuck in STANDBY or errors on start |
| **Check first** | VPC interfaces, AZ alignment, IAM role, flow size |

**Decision tree:**

```
IF error mentions VPC interface:
  → EFA required for CDI/ST2110 JPEG XS. Max 1 EFA per flow. Second must be ENA.
  → Subnet and SG MUST be in same AZ as flow.
  → Verify subnet has available IP addresses.
IF error mentions "Unable to assume role":
  → IAM trust policy MUST include mediaconnect.amazonaws.com
  → Action array MUST include sts:TagSession alongside sts:AssumeRole
IF CDI workflow:
  → Flow and MediaLive input MUST be in same AZ (use AZ IDs, not names)
IF source bitrate exceeds flow size:
  → Flow tiers set the max bitrate: Standard 80 Mbps, Large 150 Mbps, Extra Large 400 Mbps.
  → ST 2110/CDI REQUIRE Large or Extra Large.
```

---

## Source Not Receiving

| | |
|---|---|
| **Symptom** | Flow is ACTIVE, SourceBitRate = 0 |
| **Check first** | Security groups, CIDR allowlist, SRT config, DX bandwidth |

**Decision tree:**

```
IF protocol is ST 2110:
  → Verify ALL ports open (separate UDP per essence: video, audio, ancillary)
  → WhitelistCidr is INVALID at source level for ST 2110 JPEG XS
  → Define ports in MediaStreamSourceConfigurations[].InputConfigurations[]
IF protocol is CDI:
  → Self-referencing SG rules required (same SG on both MediaConnect and MediaLive)
IF protocol is SRT:
  → Verify caller/listener mode matches between source and MediaConnect
  → Latency SHOULD be approximately 4× measured RTT; insufficient latency causes packet loss
  → Passphrase must match (10-79 characters)
IF using Direct Connect:
  → Keep DX utilization well below the link's steady-state ceiling so SRT retransmission bursts do not cause loss (around 50% is a common operator target)
  → Monitor DX utilization, have backup path
```

**Validation:** CloudWatch `SourceBitRate` > 0 confirms source is flowing.

---

## Output Not Delivering

| | |
|---|---|
| **Symptom** | Source OK (SourceBitRate > 0) but destination not receiving |
| **Check first** | AZ alignment (CDI), destination existence, PTS errors |

**Decision tree:**

```
IF CDI output:
  → Output and destination MUST be in same AZ. Cross-AZ CDI is not supported.
  → Verify using AZ IDs (use1-az1), not AZ names.
IF targeting MediaLive input:
  → MediaLive input MUST exist before creating MediaConnect output
  → Verify endpoint IPs are correct (from describe-input)
IF SourcePTSError > 0:
  → PTS discontinuities in source. Check encoder stability.
  → Increase MaxSyncBuffer (valid: 0-250) for jittery sources.
IF entitlement (cross-account):
  → Verify entitlement is active and subscriber has accepted it.
```

---

## MediaConnect Router Issues

| | |
|---|---|
| **Symptom** | Availability concerns, downstream NDI converter problems |

**Redundancy decision:**

```
IF full AZ redundancy needed:
  → Dual-AZ input → Dual-AZ output (paired resilient endpoints)
IF dual-AZ input → single-AZ output:
  → WARNING: negates availability benefit
IF cross-account routing needed:
  → Use VPC peering or MediaConnect entitlements (not natively supported)
```

**SRT-to-NDI converter limitations (downstream of MediaConnect):**

When an external NDI converter is used downstream of a MediaConnect SRT
output, test the full chain before production. Converter-side issues observed
include:

- Intermittent audio stops on NDI output
- Repeated fields with interlaced content
- Timecode passthrough that requires specific converter firmware
- 10-bit content playback issues on some NDI receivers

These are limitations of the NDI converter, not MediaConnect.

---

## CloudWatch Metrics

| Metric | Expected | Alert if |
|--------|----------|----------|
| SourceBitRate | Non-zero, stable | = 0 for >5s (source lost) |
| OutputBitRate | Non-zero per output | = 0 (output disconnected) |
| SourcePTSError | 0 | > 0 (PTS discontinuity) |
| SourceDroppedPackets | 0 | Increasing (network congestion) |
| RoundTripTime (SRT) | Stable | Increasing (network degradation) |
| OverflowPackets | 0 | > 0 (buffer overflow) |
