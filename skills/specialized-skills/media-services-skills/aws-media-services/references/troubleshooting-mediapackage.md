# Troubleshooting: MediaPackage v2

Per-service troubleshooting guidance for MediaPackage v2 issues.

---

## Symptom Router

```
IF no ingest (IngressBytes = 0):
  → See "Ingest Failures" below
IF 403 on playback URL:
  → See "Endpoint Access Denied" below (most common issue)
IF manifest issues (404, empty, wrong variants):
  → See "Manifest Issues" below
IF 429/503 under load:
  → See "1000 RPS Limit" below (CRITICAL for production)
IF migrating from v1 to v2:
  → See "Migration Issues" below
```

---

## Ingest Failures

| | |
|---|---|
| **Symptom** | IngressBytes = 0, MediaLive is RUNNING |
| **Check first** | Ingest URL, channel policy, output group type |

**Decision tree:**

```
IF MediaPackage channel was recreated:
  → Ingest URL changed. Update MediaLive output group destination.
IF channel policy missing:
  → Add policy allowing MediaLive role to perform mediapackagev2:PutObject
IF MediaLive uses CmafIngestGroupSettings but channel expects HLS (or vice versa):
  → Match ingest format. Preferred: CMAF for MediaPackage v2.
IF MediaLive ActiveOutputs < expected:
  → Output group may have failed to start. Check MediaLive alerts.
```

**Validation:** CloudWatch `IngressBytes` > 0 confirms ingest flowing.

---

## Endpoint Access Denied (403)

| | |
|---|---|
| **Symptom** | Playback URL returns 403 Forbidden |
| **Root cause** | Origin endpoints DENY all access by default |

**Decision tree:**

```
IF no endpoint policy exists:
  → Add one. Even for testing, do NOT use `Principal: "*"`. Use a scoped
    policy for `mediapackagev2:GetObject` with an `aws:SourceIp` condition
    (developer IP/CIDR), or configure OAC from the start.
  → Production: use CloudFront OAC (recommended). The CDN authorization
    header (`X-MediaPackageV2-CDNIdentifier`) is a legacy fallback — use
    only when OAC is unavailable (e.g., a non-CloudFront CDN).
IF using X-MediaPackageV2-CDNIdentifier header:
  → Verify header value matches between CDN config and endpoint policy
  → ALL CDNs must send this header
IF using CloudFront OAC:
  → Verify distribution ID is allowed in endpoint policy
  → Verify CloudFront is signing requests with SigV4
```

---

## 1000 RPS Limit (CRITICAL)

| | |
|---|---|
| **Symptom** | 429 or 503 errors under load, viewer playback failures |
| **Root cause** | MediaPackage v2 hard limit: 1000 manifest RPS from ALL CDNs combined |

**Decision tree:**

```
IF any CDN lacks Origin Shield:
  → Add Origin Shield immediately. Single CDN without it can overwhelm origin.
IF MediaTailor requests counting against limit:
  → Measure the reuse ratio first: compare AWS/MediaTailor Origin.Age SampleCount against the
    content origin's own access logs (NOT the Requests metric, which is not comparable).
    MediaTailor reuses origin manifests, so fetches sit far below player requests
  → Check nothing makes the origin URL unique per request; that defeats reuse
  → No documented setting reduces those fetches further. If the limit binds, request a quota increase
  → Origin Shield on the MediaTailor origin does NOT help here. It reduces requests reaching
    MediaTailor, not MediaTailor's fetches from the origin
  → AWS does not recommend a CDN between a content origin and MediaTailor, so do not add one to
    buy origin headroom. The exception is a channel assembly source, where AWS recommends it
  → Above 500,000 concurrent viewers, contact AWS Support at least 2 weeks before the event
IF a CDN already sits between the content origin and MediaTailor AND manifests fail to parse:
  → CAUSE: some CDNs deliver corrupt gzip payloads on that leg
  → FIX: disable compression on that leg ONLY. Keep compression everywhere else, including the
    viewer-facing manifest behaviours, where it is a material delivery cost saving. A blanket
    compression disable multiplies manifest egress for no benefit
IF approaching limit (EgressRequestCount > 800):
  → Open a Service Quotas request or AWS Support case for a limit increase. Include peak concurrency, CDN count, and event window.
```

**Prevention:** Always enable Origin Shield on EVERY CDN before production.

---

## Manifest Issues

| | |
|---|---|
| **Symptom** | 404 on manifest, empty manifest, wrong variant count |

**Decision tree:**

```
IF 404:
  → Verify URL path components match resource names (case-sensitive)
  → MediaLive may not have run long enough to fill manifest window
IF empty manifest:
  → Wait for at least one full manifest window duration after MediaLive starts
IF wrong variant count:
  → Check MediaLive ActiveOutputs (some renditions may have failed)
```

---

## Migration Issues (v1 → v2)

| | |
|---|---|
| **Symptom** | Issues after migrating from MediaPackage v1 to MediaPackage v2 |

**Decision tree:**

```
IF stuck avails (CUE-OUT never closes):
  → MediaPackage v2 uses SCTE35_ENHANCED (tracks by segmentation_event_id)
  → CUE-IN event ID MUST match CUE-OUT event ID
  → Fix upstream signaling
IF 429/503 (didn't have this on v1):
  → MediaPackage v2 has stricter 1000 RPS limit. Add Origin Shield to ALL CDNs.
IF ingest errors:
  → Update MediaLive from HlsGroupSettings to CmafIngestGroupSettings
  → MediaPackage v2 can still egress HLS TS (no player changes needed)
IF epoch locking broken:
  → MediaPackage v2 JIT packaging is incompatible with epoch locking
  → Use passthrough origin for epoch-locked segments
```

---

## CloudWatch Metrics

| Metric | Expected | Alert if |
|--------|----------|----------|
| IngressBytes | Non-zero, stable | = 0 for >10s |
| EgressRequestCount | < 1000 RPS | > 800 (approaching limit) |
| Egress4xxErrors | 0 | Spike (check endpoint policy) |
| Egress5xxErrors | 0 | > 0 (service issue) |
| IngressResponseTime | < 100ms | > 500ms (ingest bottleneck) |
