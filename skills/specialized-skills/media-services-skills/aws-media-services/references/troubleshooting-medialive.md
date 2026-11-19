# Troubleshooting: MediaLive

Per-service troubleshooting guidance for MediaLive channel issues.

---

## Symptom Router

```
IF channel won't start (stuck CREATING or fails to reach RUNNING):
  → See "Channel Won't Start" below
IF channel RUNNING but output is black/missing:
  → See "Black Frames / No Video" below
IF audio issues (sync drift, missing, wrong track):
  → See "Audio Issues" below
IF SCTE-35 not passing through:
  → See "SCTE-35 Not Passing" below
  → LOAD references/workflow-ad-insertion.md for full SSAI chain
IF pipeline failover causing glitches:
  → See "Pipeline Failover Issues" below
  → LOAD references/workflow-resilience-patterns.md for epoch locking
IF latency too high:
  → See "High Latency" below
```

---

## Channel Won't Start

| | |
|---|---|
| **Symptom** | Channel stuck in CREATING or fails to reach RUNNING |
| **Check first** | Input existence, IAM role, output destination, resource limits |

**Decision tree:**

```
IF "Unable to assume role" or "Access denied":
  → Trust policy MUST include medialive.amazonaws.com
  → Action MUST include sts:AssumeRole AND sts:TagSession
IF input not found:
  → Input may have been deleted/recreated (new ID). Update channel config.
  → CDI inputs: both subnets MUST be provided even for SINGLE_PIPELINE
IF output destination unreachable:
  → Verify MediaPackage channel exists and ingest URL is current
  → If MediaPackage was recreated, ingest URL changed
IF resource limits:
  → Check Service Quotas for MediaLive in the region
IF 4K HEVC or other large-profile channel:
  → Provisioning takes longer than smaller channels. Start well in advance of any time-sensitive event and verify the channel reaches RUNNING before the event begins.
```

**Validation:** `describe-channel` shows `State: RUNNING` (not STARTING).

---

## Black Frames / No Video

| | |
|---|---|
| **Symptom** | Channel RUNNING, no alerts, but output is black or missing |
| **Check first** | InputVideoFrameRate, input loss behavior, encoder overload, HDR slate |

**Decision tree:**

```
IF InputVideoFrameRate = 0:
  → Problem is upstream (source encoder, MediaConnect, network)
  → LOAD references/troubleshooting-mediaconnect.md
IF InputVideoFrameRate > 0 but OutputVideoFrameRate = 0:
  → Encoder overload. Check DroppedFrames metric.
  → Reduce ABR rungs, use shared encode outputs, lower complexity.
IF input loss behavior = EMIT_OUTPUT:
  → Channel outputs black on input loss BY DESIGN (keeps players alive)
  → This is correct for production. Check upstream for actual input loss.
IF HDR channel with SDR slate:
  → Slate MUST match channel colorspace/transfer function
  → SDR slates on HDR channels cause encoder errors
```

---

## Audio Issues

| | |
|---|---|
| **Symptom** | Audio sync drift, missing audio, wrong track |

**Decision tree:**

```
IF audio sync drift:
  → Check MediaConnect SourcePTSError (PTS discontinuities)
  → Verify SRT latency ≥4× RTT
  → For 8+ hour events: reboot encoders before (timecode drift accumulates)
IF missing audio:
  → Verify audio PID mapping in input settings matches source
  → Each language track needs separate audio selector
  → Check source codec is supported (PCM, AAC, AC3, EAC3, MPEG Audio)
IF inconsistent levels (program vs ads):
  → Enable ITU-R BS.1770 loudness normalization (BS.1770-4)
  → Target: -16 LKFS (streaming) or -24 LKFS (broadcast, ATSC A/85)
```

---

## SCTE-35 Not Passing

| | |
|---|---|
| **Symptom** | MediaTailor not detecting ad breaks, SCTE-35 missing from manifest |
| **Check** | Each link in the chain independently |

**Diagnostic chain (check each step):**

```
1. Source encoder: SCTE-35/SCTE-104 being inserted?
2. MediaConnect: passthrough (no config needed)
3. MediaLive (HLS): Scte35Behavior in M3u8Settings PER OUTPUT (NOT HlsGroupSettings level)
4. MediaLive (CMAF): Scte35Type = SCTE_35_WITHOUT_SEGMENTATION in CmafIngestGroupSettings
   → SCTE_35_ENHANCED MUST NOT be used (invalid enum)
5. MediaPackage: SCTE-35 in manifest (default if present in ingest)
   → MediaPackage v2 SCTE35_ENHANCED: CUE-IN event ID MUST match CUE-OUT event ID
```

**IF epoch locking enabled:**

- SCTE-35 cannot create segment boundaries
- Use ID3 metadata via schedule actions for ad signaling instead

---

## Pipeline Failover Issues

| | |
|---|---|
| **Symptom** | Failover causes glitches, time jumps, player errors |

**Decision tree:**

```
IF pipeline locking not enabled:
  → Pipelines produce different sequence numbers → failover causes time jump
  → Enable pipeline locking (requires same source content on both pipelines)
IF file inputs (S3 MP4/TS):
  → No live timecode → standard pipeline locking won't work
  → Use InputClipSettings with zero-based approach
IF primary/secondary from different encode paths:
  → Pipeline locking not possible
  → Manual failover with session reinitialization required
  → MediaTailor SSAI also affected (sequence number mismatch)
```

---

## High Latency

| Setting | Latency impact | Low-latency setting |
|---------|---------------|---------------------|
| Lookahead: High | +500ms | Low |
| B-Frames: 3 | +100ms | 0 (contribution only) |
| GOP size: 2s | Segment boundary | Reduce (match segment duration) |
| Segment duration: 6s | Player buffers ≥1 segment | 2-4s |
| BRF | Minimal | Keep enabled |

**Quick wins:** Reduce segment duration (2-4s), reduce lookahead (Low), reduce B-frames (0 for contribution).

---

## CloudWatch Metrics

| Metric | Expected | Alert if |
|--------|----------|----------|
| InputVideoFrameRate | Matches source FPS | = 0 for >5s |
| DroppedFrames | 0 | > 0 (encoder overload) |
| InputLossSeconds | 0 | > 0 (source interruption) |
| ActiveOutputs | Matches ABR rung count | < expected |
| OutputVideoFrameRate | Non-zero | = 0 (output failure) |
