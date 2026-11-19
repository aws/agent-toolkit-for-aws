# Troubleshooting: CloudFront (Media Delivery)

Per-service troubleshooting guidance for CloudFront issues in video streaming workflows.

---

## Symptom Router

```
IF origin errors (403, 404, 502, 503, 504):
  → See "Origin Errors" below
  → IF 403 from MediaPackage: LOAD references/troubleshooting-mediapackage.md
IF stale content or low cache hit ratio:
  → See "Cache Issues" below
IF multi-CDN origin overwhelmed:
  → See "Multi-CDN Issues" below
  → LOAD references/workflow-resilience-patterns.md for Origin Shield patterns
IF Embedded POP (ePOP) issues:
  → See "ePOP Issues" below
IF CF Functions/Lambda@Edge errors:
  → See "Function Issues" below
```

---

## Origin Errors

| | |
|---|---|
| **Symptom** | 403, 404, 502, 503, or 504 from origin |

**Decision tree:**

```
IF 403 from MediaPackage:
  → Missing endpoint policy (endpoints DENY all by default)
  → If using CDN auth header: verify value matches in CDN config and policy
  → If using OAC: verify distribution ID in endpoint policy
IF 403 from S3:
  → OAC not configured, or bucket policy missing distribution ARN
  → If KMS-encrypted: OAC needs kms:Decrypt
IF 404:
  → Content not yet available (MediaLive not started, manifest window not filled)
  → For epoch-locked: stale manifest deleted by lifecycle (expected, triggers failover)
IF 502/503/504:
  → Origin overloaded. Check origin health directly (curl, bypass CF).
  → Origin connection timeout SHOULD be well below segment duration (around half is a common starting point); the 10s/30s defaults MUST NOT be used for live
```

---

## Cache Issues

| | |
|---|---|
| **Symptom** | Cache hit ratio < 90%, stale manifests, excessive origin requests |

**Decision tree:**

```
IF same TTL for manifests and segments:
  → MUST use separate cache behaviors
  → Manifests: 1-3s TTL. Segments: 24h+ TTL.
IF error caching TTL = default (5 min):
  → Lower it to a small value (around 1 second) for ALL live error codes (403, 404, 500-504). The 5-minute default MUST NOT be used for live.
  → This is one of the most impactful settings for live-streaming resilience.
IF compression on segment behaviors:
  → Disable. Wastes CPU, creates duplicate cache entries.
  → Enable compression only on manifest behaviors.
IF query strings not forwarded:
  → Forward ALL for MediaPackage (token auth, manifest filtering)
  → Forward ALL for MediaTailor (ad targeting variables)
IF Origin Shield not enabled:
  → Each POP makes independent origin requests without it
  → Enable in region closest to origin. Target: >90% hit ratio.
```

---

## Multi-CDN Issues

| | |
|---|---|
| **Symptom** | Origin overwhelmed, failover not working |

**Decision tree:**

```
IF any CDN lacks Origin Shield:
  → Add immediately. Single CDN without it can overwhelm MediaPackage v2 (1000 RPS limit).
IF origin shield failover needed:
  → Typically manual (DNS change). Pre-configure backup, test before event.
  → Failover time: 30s to 5min depending on DNS TTL.
IF CloudFront used as both origin shield AND viewer CDN:
  → MUST NOT chain in same distribution. Use separate distributions.
IF origin returns 200 with stale content instead of error:
  → Failover won't trigger (needs 4xx/5xx). Check lifecycle policies.
```

---

## Embedded POP (ePOP) Issues

| | |
|---|---|
| **Symptom** | 503 from embedded POPs, ePOP not serving traffic |

**Decision tree:**

```
IF CF Functions 503 on ePOPs:
  → High CPU / I/O wait on the embedded appliance
  → Create SEPARATE CF Function associations per cache behavior (independent scaling)
IF eDNS routing not working:
  → Verify distribution is enabled for eDNS routing
  → Some ISP DNS resolvers may not steer correctly to embedded POPs
IF not ready in time:
  → Onboarding has lead time. Plan early and keep a non-ePOP fallback.
```

---

## Function Issues

| | |
|---|---|
| **Symptom** | CF Function/Lambda@Edge errors, throttling |

**Decision tree:**

```
IF CF Function scaling bottleneck:
  → Single ARN shared across behaviors is the problem
  → Create separate function associations per cache behavior
  → Shard segment traffic across multiple behaviors by path pattern
IF KVS token validation issues:
  → Support secret rotation: store comma-separated secrets (old+new)
  → Remove auth tokens before forwarding to origin (cache key pollution)
IF Lambda@Edge cold starts:
  → Pre-warm with synthetic traffic before event
  → Raise L@E limits in all expected regions
IF WAF blocking legitimate requests:
  → Disable WAF on segment paths (high RPS)
  → Keep WAF only on manifest/API paths
```

---

## CloudWatch Metrics

| Metric | Alert threshold | Action |
|--------|----------------|--------|
| CacheHitRate | < 90% | Check Origin Shield, cache policy |
| 4xxErrorRate | > 1% | Check endpoint policy, token validation |
| 5xxErrorRate | > 0.4% | Check origin health, timeouts |
| OriginLatency P90 | > 2s | Origin overloaded |
| Requests | Approaching capacity | Engage capacity team |
