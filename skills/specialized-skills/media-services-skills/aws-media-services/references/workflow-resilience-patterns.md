# Resilience Patterns

Cross-service resilience and redundancy patterns for live streaming workflows.

---

## Pattern Selection

```
IF single-region production event:
  → Dual-pipeline (STANDARD channel class) + Origin Shield
IF cross-region seamless failover required:
  → Epoch locking + multi-region encode (supported on MediaPackage v2 via epoch-locked CMAF ingest; see the MediaPackage v2 User Guide, "Working with cross-Region failover", for current requirements)
  → REQUIRES: reliable source timecode on the contribution feed
  → CONSTRAINT: incompatible with SCTE-35 segmentation
IF multi-CDN architecture:
  → Origin Shield on EVERY CDN (MediaPackage v2 per-endpoint egress limits)
  → LOAD references/workflow-contribution-distribution.md for DX redundancy
IF migrating from MediaPackage v1 to v2:
  → LOAD references/workflow-mediapackage-migration.md (full discover → plan → execute workflow)
  → See Migration section below for the cutover readiness risks
```

---

## Epoch Locking

| | |
|---|---|
| **Preconditions** | Source timecode embedded in contribution feed |
| **Outputs** | Identical segments across all regions/channels |
| **Incompatible with** | SCTE-35 splice_insert segmentation |

**How it works:**

- MediaLive uses source timecode to align segment boundaries across all pipelines/regions
- All channels produce segments with identical names, timestamps, boundaries
- MediaPackage v2 returns errors on stale or incomplete manifests at the primary endpoint (endpoint error configuration), so the CDN fails over to the alternate region

**Decision: Use epoch locking?**

```
IF cross-region per-segment failover needed AND source has timecode:
  → Yes, use epoch locking
  → Use ID3 metadata (not SCTE-35) for ad signaling
  → MediaPackage v2 supports this via epoch-locked CMAF ingest (see the MediaPackage v2 User Guide, "Working with cross-Region failover", for current requirements)
IF single-region OR no source timecode OR need SCTE-35 segmentation:
  → No, use standard dual-pipeline redundancy instead
```

**Pre-event:** Reboot contribution encoders several days before (clears timecode drift).

---

## Multi-CDN Architecture

| | |
|---|---|
| **Preconditions** | Multiple CDNs configured, traffic steering service |
| **Key constraint** | Every CDN MUST have Origin Shield enabled (MediaPackage v2 per-endpoint egress limits) |

**Origin shield layering:**

- Third-party origin shield as primary, CloudFront Origin Shield as backup
- Failover between origin shields is typically manual (DNS change)
- A single CDN without origin shield can overwhelm the origin

**Traffic distribution:**

- Static (fixed percentages) or dynamic (based on real-time CDN performance)
- Manual CDN switching propagation: 30 seconds to 5+ minutes (depends on DNS TTL)

**Example CDN-health steering thresholds (tune to your workload):**

- VPF above your investigation target → steer traffic away
- Rebuffering above your investigation target → steer traffic away
- Response latency consistently elevated vs baseline → steer traffic away

---

## CloudFront Advanced Patterns

### Decision: Large event preparation

```
IF expected peak >1 Tbps:
  → Open an AWS Support case to request capacity reservations (per-region, per-POP) ahead of the event
  → Set Price Class: ALL
  → Enable segment sharding (multiple cache behaviors by path pattern)
IF using Embedded POPs (ePOP):
  → Onboarding has lead time; start well before the event
  → Monitor embedded-POP appliance utilization (CF Functions can 503 under high CPU / I/O wait)
IF token validation at edge:
  → CF Functions + KVS for HMAC-SHA256 validation
  → Separate CF Function associations per cache behavior (independent scaling)
  → Remove auth tokens before forwarding to origin (prevents cache key pollution)
```

**Real-time logging:** Use 40-50% sampling for large events (100% can exceed Kinesis limits).

**WAF:** Consider disabling on segment paths (high RPS); keep on manifest/API paths only.

---

## MediaPackage v1 → v2 Migration

| | |
|---|---|
| **Key risks** | SCTE-35 mode change, per-endpoint egress limits, ingest format change |

This section covers **cutover readiness** only. For the migration itself —
inventorying v1, planning channel groups, translating endpoint configs,
generating and executing the plan — LOAD `references/workflow-mediapackage-migration.md`.

### Decision: Migration readiness

```
IF SCTE-35 event IDs match between CUE-OUT and CUE-IN:
  → Safe to migrate (SCTE35_ENHANCED mode will work)
IF event IDs don't match:
  → Fix upstream signaling first (stuck avails will occur)
IF all CDNs have Origin Shield enabled:
  → Safe from RPS perspective
IF any CDN lacks Origin Shield:
  → Add Origin Shield before migrating (per-endpoint egress limits: about 500 segment / 10,000 manifest RPS; check current values in Service Quotas)
```

**Ingest format:** Only if the v2 channel uses `CMAF` input. A v2 channel accepts HLS ingest too, so a like-for-like migration keeps `HlsGroupSettings` and changes nothing on the encoder — see the channel input type step in `references/mediapackage-migration-channel-groups.md`. Switch MediaLive to `CmafIngestGroupSettings` when the channel was deliberately created with `CMAF` input (required for epoch locking). Either way MediaPackage v2 can still egress HLS TS, so no player changes are needed.

---

## Operational Readiness (Live Events)

**Pre-event checklist:**

1. Pre-create all resources well before event (no just-in-time creation)
2. Start channels well before the event and verify each reaches `RUNNING` before content needs to flow (large channels — 4K HEVC, complex ABR stacks — take longer to provision than small ones)
3. Request capacity increases where the quota is adjustable: MediaLive channel limits, CloudFront Tbps, DynamoDB (MediaTailor), Lambda concurrency. MediaPackage v2's per-endpoint egress rates are **hard** quotas (confirm with the `Adjustable` field from `aws service-quotas list-service-quotas --service-code mediapackagev2`) — design within them (Origin Shield on every CDN, cache-hit ratio) rather than asking for an increase
4. Pin encoder software versions, code freeze 2-4 weeks before
5. End-to-end load test at expected peak concurrency
6. CDN failover test, SSAI load test with full DVR window

**KPI targets (industry-typical baselines, not AWS commitments):**

These ranges are operator-side targets used by many video platforms; tune
them to your own workload, content type, and audience. They are not service
SLAs.

| Metric | Target | Investigate | Likely incident |
|--------|--------|-------------|-----------------|
| VPF (video playback failures) | <0.5% | 0.5-2% | >2% |
| Rebuffering (CIRR) | <0.1% | 0.1-0.8% | >0.8% |
| Video Start Time | <4s | 4-8s | >8s |
| CDN Cache Hit Ratio | >99% | 95-99% | <95% |
| 4xx Error Rate | <0.1% | 0.1-1% | >1% |
| 5xx Error Rate | <0.01% | 0.01-0.4% | >0.4% |
