# Troubleshooting: Cross-Service Pipeline

Issues spanning multiple services in the signal chain.

---

## Symptom Router

```
IF no video at playback (end-to-end failure):
  → See "No Video at Playback" below (systematic trace)
IF high end-to-end latency:
  → See "High Latency" below
IF audio/video sync drift:
  → See "A/V Sync Drift" below
IF AZ alignment failures:
  → See "AZ Alignment" below
IF IAM trust policy issues:
  → See "IAM Issues" below
IF cross-region failover not working:
  → See "Cross-Region Failover" below
  → LOAD references/workflow-resilience-patterns.md for epoch locking patterns
```

---

## No Video at Playback

| | |
|---|---|
| **Symptom** | Playback fails, no video reaching viewers |
| **Approach** | Trace from viewer backward; first failing step identifies the problem |

**Systematic trace:**

| Step | Check | Tool | If failing, load |
|------|-------|------|-----------------|
| 1 | Source encoder running? | Encoder dashboard | — |
| 2 | Signal reaching AWS? | DX metrics, SRT status | troubleshooting-mediaconnect.md |
| 3 | MediaConnect ACTIVE, SourceBitRate > 0? | describe-flow, CW | troubleshooting-mediaconnect.md |
| 4 | MediaLive RUNNING, InputVideoFrameRate > 0? | describe-channel, CW | troubleshooting-medialive.md |
| 5 | MediaLive OutputVideoFrameRate > 0? | CW | troubleshooting-medialive.md |
| 6 | MediaPackage IngressBytes > 0? | CW | troubleshooting-mediapackage.md |
| 7 | Manifest URL returns #EXTM3U? | curl | troubleshooting-mediapackage.md |
| 8 | CDN serving? | CDN dashboard | troubleshooting-cloudfront.md |
| 9 | MediaTailor GetManifest 200? | CW, curl | troubleshooting-mediatailor.md |
| 10 | Player rendering? | Player logs, QoE tool | — |

---

## High Latency

| Component | Typical latency |
|-----------|----------------|
| Source capture + encoding | 1-3s |
| Contribution transport (SRT) | 0.5-2s |
| MediaConnect | <100ms |
| MediaLive encoding | 2-8s |
| MediaPackage packaging | <1s |
| CDN propagation | 1-3s |
| Player buffering | 3-12s |
| **Total (standard HLS)** | **8-30s** |

**Address largest contributors first:**

1. Player buffer → reduce segment duration (6s → 2-4s)
2. MediaLive encoding → reduce lookahead, B-frames, GOP
3. Contribution → optimize SRT latency (4× RTT)
4. CDN → reduce manifest TTL, enable Origin Shield

---

## A/V Sync Drift

**Decision tree:**

```
IF SourcePTSError > 0 (MediaConnect):
  → PTS discontinuities in source. Fix encoder or increase SRT latency.
IF timecode drift between encoders:
  → Use common timecode reference (GPS, NTP). Reboot encoders before events.
IF frame rate mismatch (59.94 vs 60):
  → Use INITIALIZE_FROM_SOURCE for frame rate
IF caption sync issues:
  → Prefer embedded captions (CEA-608/708) for guaranteed sync
  → Separate caption processing introduces drift risk
```

---

## AZ Alignment

**Decision tree:**

```
IF CDI between MediaConnect and MediaLive:
  → MUST be same AZ. Cross-AZ CDI fails silently.
  → Use AZ IDs (use1-az1), NOT AZ names (differ per account)
IF cross-account AZ alignment:
  → AZ names map differently per account
  → MUST use AZ IDs for cross-account alignment
IF MediaConnect resilient endpoints to MediaLive mismatch:
  → Map each MediaConnect zonal endpoint and each MediaLive pipeline to the same AZ
  → Mismatch negates redundancy during AZ failure
```

---

## IAM Issues

**Decision tree:**

```
IF "Unable to assume role":
  → Missing service principal in trust policy
  → Live: medialive.amazonaws.com + mediaconnect.amazonaws.com
  → VOD: mediaconvert.amazonaws.com
IF intermittent auth failures:
  → Missing sts:TagSession in Action array
  → MUST include alongside sts:AssumeRole
IF cross-account:
  → Trust policy must explicitly allow other account's principal (full ARN)
```

---

## Cross-Region Failover

**Decision tree:**

```
IF epoch-locked segments diverging between regions:
  → Source timecode drifting. Reboot encoders before events.
  → Verify segment names match across regions before event.
IF using MediaPackage as origin for epoch locking:
  → Incompatible. MediaPackage JIT generates its own segment names.
  → MUST use passthrough origin (S3, MediaStore) for epoch-locked segments.
IF origin group failover not triggering:
  → Primary returning 200 with stale content instead of error
  → Passthrough origins with lifecycle policies delete stale manifests (404 triggers failover)
IF DNS-based failover too slow:
  → Lower DNS TTL = faster failover but more queries
  → Typical: 30s to 5min depending on TTL and client DNS caching
```

---

## Security Group Issues

**Decision tree:**

```
IF ST 2110 partial signal (video but no audio):
  → Separate UDP ports per essence. ALL ports MUST be open.
  → Video (5000), audio (5001), ancillary (5002)
IF CDI not connecting:
  → Self-referencing SG required (same SG on both resources)
IF security concern with 0.0.0.0/0:
  → Scope to source encoder CIDR range
  → For VPC inputs: allow from VPC CIDR or specific subnets
```

---

## MediaLive Running but No Content at MediaPackage

Systematic checklist — check in this order:

```
1. IAM role: MediaLive execution role MUST have mediapackagev2:PutObject
   on the target channel. This is the most common cause of silent ingest
   failure. Verify the role's policy covers the specific channel ARN.

2. Channel state: Confirm State: RUNNING (not STARTING). Poll until confirmed.

3. Input receiving content: CloudWatch InputVideoFrameRate > 0.
   If zero → problem is upstream (source not sending), not ingest.

4. Output group type MUST match MediaPackage channel InputType:
   - CMAF InputType → CmafIngestGroupSettings
   - HLS InputType → HlsGroupSettings with CDN setting: hls basic put
   Mismatched types silently fail.

5. Destination URL: Must exactly match IngestEndpoints[].Url from
   MediaPackage channel describe. No trailing slash modifications,
   no path alterations.

6. Endpoint policy does NOT affect ingest. Endpoint policies control
   viewer/CDN egress access only. Do NOT modify endpoint policies
   to troubleshoot ingest issues — it is a red herring.

7. Check CloudWatch Output4xxErrors and Output5xxErrors on the
   MediaLive channel for HTTP error codes from MediaPackage.
```
