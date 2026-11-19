# Ad Insertion Workflow

## Architecture Selection

```
IF standard live event with personalized ads (<500K concurrent):
  → Standard SSAI (1:1 personalized sessions)
IF >500K concurrent:
  → Standard SSAI, PLUS contact AWS Support at least 2 weeks ahead for capacity
  → See "Scaling for Large Events" below before proposing any architecture change
IF extreme scale:
  → Multi-region MediaTailor + CDN mid-tier caching
  → LOAD references/workflow-resilience-patterns.md for multi-region scaling
IF schedule-driven VOD channel with ad breaks:
  → Channel Assembly with SSAI

```

```
Source → MediaLive (SCTE-35 passthrough) → MediaPackage v2
  → MediaTailor (fetches the origin manifest, personalizes per session)
    → CloudFront: /v1/master, /v1/manifest, /v1/dash, /v1/session, /v1/tracking, /segment
  → CloudFront: /out/v1/* content segments direct from MediaPackage, bypassing MediaTailor
```

AWS does **NOT** recommend positioning a CDN between a content origin and MediaTailor. MediaTailor
already holds a fetched origin manifest and serves it to more than one session, so origin fetches sit
well below player requests. The exception is a channel assembly content source, where AWS recommends
a CDN in between. See `service-rules-cloudfront.md`.

**Actions:**

1. Create the MediaTailor playback configuration (content source URL + ADS URL). Any public HLS or
   DASH origin qualifies, not only MediaPackage
2. Configure `CdnConfiguration` prefixes (content and ad segment) so segment URLs route through
   CloudFront
3. Configure `SlateAdUrl` if the break should show slate rather than the underlying content. Slate
   is live and live-to-VOD only, optional for non-VPAID and mandatory for VPAID
4. Set `AdMarkerPassthrough` only if downstream players or analytics need the original break
   boundaries. It is HLS only, defaults to `false`, and gates `EXT-X-CUE-OUT`, `EXT-X-CUE-IN` and
   `EXT-X-SPLICEPOINT-SCTE35`. `EXT-X-DATERANGE` passes through regardless

**SCTE-35 chain validation (all MUST be true):**

- MediaLive: `Scte35Type: SCTE_35_WITHOUT_SEGMENTATION` in CmafIngestGroupSettings
- MediaLive: `EXT-X-PROGRAM-DATE-TIME` included in HLS/CMAF output
- MediaPackage v2: exposes SCTE-35 in the manifest
- MediaTailor: receives markers in manifest

**CDN cache rules:**

- Manifest, session and tracking behaviours: TTL=0, forward all query strings and `User-Agent`
- Ad segment behaviour: cache hard, and forward **nothing**. Ad segments are identical for every
  viewer, so forwarding query strings or headers gives each viewer a private cache entry
- Content segments: TTL=24h+, served from MediaPackage, never through MediaTailor

**Validation:** a `GET` of the playback URL returns a personalized multivariant playlist. The ad
segments are in the per-session media playlist under `/v1/manifest/...`, not in the multivariant
playlist, so agents **MUST** follow a variant URI to confirm stitching.

---

## Extreme Scale

| | |
|---|---|
| **Preconditions** | Standard SSAI working; CDN mid-tier cache configured; AWS Support engaged |
| **Use when** | Concurrency far above the 500K Support-engagement threshold |

SSAI manifests are personalized per session by design, so there is no mode that coalesces viewers
onto a shared manifest. Scale the session count, do not try to reduce it.

```
IF viewership is at extreme scale:
  → Confirm AWS Support has capacity in place for the event before anything else
  → Deploy CDN mid-tier caching between viewers and MediaTailor
  → Enable CloudFront Origin Shield on the MediaTailor origin to cut requests reaching MediaTailor
  → Deploy MediaTailor in multiple regions and route session init to the nearest
IF audience-specific content (not ad personalization) is the requirement:
  → That is Channel Assembly Program Rules, not an SSAI scaling mode. Audience cohorts there select
    alternate media on a STANDARD tier LINEAR channel
  → LOAD references/workflow-linear-channel.md
```

---

## Scaling for Large Events

| | |
|---|---|
| **Preconditions** | Standard SSAI deployed and tested |
| **Decision triggers** | Expected concurrency >500K, multi-region requirement, ADS latency concerns |

### Decision: Scaling pattern

```
IF expected concurrency >500K:
  → Contact AWS Support at least 2 WEEKS before the event so capacity is in place for ad
    personalization. This is the documented first step and no CDN design substitutes for it
  → Request quota increases through the Service Quotas console in the same window
  → Enable CloudFront Origin Shield on the MediaTailor origin. It reduces the requests reaching
    MediaTailor, NOT MediaTailor's own fetches from the content origin
  → Enable prefetch for mid-roll ad breaks, and price it first: every prefetched creative
    MediaTailor transcodes is billed at the standard transcoding rate whether or not it is consumed
IF a multi-region deployment is required:
  → Deploy MediaTailor in multiple regions, with a playback configuration per region
  → Route session init to the nearest region
  → For CloudFront media quality aware routing, an origin group with the media quality score
    option and a matching MediaTailor configuration in each region are both required
  → LOAD references/workflow-resilience-patterns.md for multi-region patterns
IF ADS latency >1500ms P90:
  → Tune AdsRequestTimeoutMilliseconds, and use prefetch to take the ADS call off the manifest path
  → TPS-based traffic shaping is a PREFETCH schedule feature, not a general ADS latency control
IF VAST beacons point to non-functional endpoints:
  → Fix the beacon endpoints. ?aws.reportingMode=CLIENT stops MediaTailor firing them, which
    moves ALL beaconing to the player: an unmodified player then reports nothing and impressions
    go to zero. Agents MUST confirm the player fires beacons from the tracking endpoint first
```

**Pipeline locking (recommended for failover-sensitive workflows):** Pipeline locking on MediaLive matches segment numbers across both pipelines so a pipeline failover does not break in-flight MediaTailor sessions. It is RECOMMENDED for large-scale or failover-sensitive SSAI deployments. Without it, SSAI still works under steady-state but a pipeline failover may cause player session reinitialization or brief glitches.

## Monitoring Thresholds

| Metric | Typical target | If exceeded |
|--------|----------------|-------------|
| `AdDecisionServer.Errors` | <1% | Investigate ADS health |
| `AdDecisionServer.Timeouts` | <1% | Check ADS latency, increase timeout |
| `Avail.FillRate` | operator target only | Planned simple average of per-avail fill percentages, not percent of breaks filled. Use metric math on `Avail.FilledDuration` / `Avail.Duration` for a duration-weighted rate |
| `GetManifest.Errors` | <1% | Check origin health |
| `GetManifest.Latency` P90 | <1500ms | Investigate origin health, or CloudFront Origin Shield on the MediaTailor origin |

---

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Caching personalized manifests | All viewers see same ads | TTL=0 on every MediaTailor manifest and session behaviour |
| Forwarding query strings on the ad segment behaviour | Per-viewer ad segment cache entries; CDN and MediaTailor ad delivery out both rise | Forward nothing on `/tm/*`. Keep full forwarding on `/segment/*`, which is the beacon redirect |
| Reusing a `<Creative id>` | The older stored ad plays, with no error, no skip reason and no metric | A unique id per creative |
| Migrating from implicit `GET` to `POST /v1/session` | Reporting mode flips to client-side, MediaTailor stops firing beacons, impressions go to zero silently | Confirm who fires beacons before changing the entry point |
| Not forwarding User-Agent | ADS receives CDN user agent | Forward User-Agent header through CDN |
| Not forwarding query strings | Ad targeting variables lost | Forward all query strings |
| Missing SCTE-35 at any chain point | No ad breaks detected | Verify at each service (see rules file) |
