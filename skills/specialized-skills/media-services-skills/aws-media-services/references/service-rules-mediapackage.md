# Service Rules: MediaPackage v2

Loaded conditionally when the task involves MediaPackage v2. The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

---

## MediaPackage v2

### Resource hierarchy

- Channel Group -> Channel -> Origin Endpoint(s).
- Channel Group: logical container; namespaces channels and provides a shared egress domain.
- Channel: receives ingest from MediaLive (or S3 for VOD). `InputType` (CMAF or HLS) is set on the Channel, not the Channel Group. When the user has not specified a container type preference, agents SHOULD state the assumption (CMAF preferred) and ask the user to confirm before proceeding.
- Origin Endpoint: serves manifests to viewers/CDN. Multiple endpoints per channel are OPTIONAL.

### Origin endpoint multi-format serving

- MediaPackage v2 has two orthogonal configuration axes: **manifest type** (HLS, DASH) and **segment container type** (CMAF/fMP4, TS). Agents MUST NOT conflate these — HLS and DASH are manifest formats; CMAF and TS are container/segment formats. A single endpoint can serve both HLS and DASH manifests from the same segments.
- A single MediaPackage v2 origin endpoint can serve BOTH HLS and DASH manifests simultaneously. Separate endpoints are NOT required for different manifest formats.
- Agents MUST NOT tell users that different manifest formats (HLS, DASH) require separate endpoints — this is incorrect.
- Each endpoint exposes both an HLS manifest URL and a DASH manifest URL by default (when both are configured on the endpoint).
- When a user requests adding a format (e.g., "add HLS" to an existing DASH endpoint), agents MUST check whether the existing endpoint already serves that format before creating a new endpoint.
- Agents MUST NOT create a separate endpoint solely to serve a different manifest format from the same content.
- HLS segment container type (TS vs CMAF/fMP4) is configured per-endpoint. CMAF/fMP4 SHOULD be preferred over TS for HLS — it provides smaller payload, allows segment reuse between HLS and DASH from the same endpoint, and is required for H.265/HEVC. To change segment format, update the existing endpoint configuration — do NOT delete and recreate.
- **LL-HLS does NOT require CMAF.** Low-Latency HLS (LL-HLS) is supported on MediaPackage v2 with both TS and CMAF/fMP4 segment containers. Users do not need to switch from TS to CMAF to enable LL-HLS.

### Scaling limit (CRITICAL)

- MediaPackage v2 has a 1000 manifest requests-per-second hard limit (verify current value from [Service Quotas](https://docs.aws.amazon.com/mediapackage/latest/userguide/quotas.html)). All CDNs pulling from MediaPackage v2 MUST have Origin Shield enabled.
- For major events that may exceed the default per-region limit, open a Service Quotas request or an AWS Support case in advance with expected peak concurrency, CDN count, and event window.

### Input types

- CMAF is RECOMMENDED for live ingest from MediaLive.
- HLS MAY be used as an alternative.
- MediaPackage v2 MAY egress HLS TS even when ingesting CMAF.
- Dual ingest endpoints are for pipeline redundancy, NOT multi-source aggregation. Multiple MediaLive channels contributing renditions to one manifest MUST target the same endpoint.
- For pipeline redundancy on a STANDARD-class MediaLive channel, the channel's `Destinations[].Settings` array MUST list BOTH endpoint URLs — `IngestEndpoints[0].Url` for pipeline 0 and `IngestEndpoints[1].Url` for pipeline 1. Reusing the same URL for both pipelines defeats redundancy.

### Access control

- Origin endpoints DENY all access by default. An endpoint policy MUST be added.
- Testing: Agents MUST NOT use `Principal: "*"` in endpoint policies, even for ad-hoc testing. Instead, use a scoped policy with `aws:SourceIp` condition restricting to the developer's IP range, or configure OAC from the start — it takes the same effort and avoids forgetting to lock down later.
- Production: OAC (Origin Access Control) MUST be used to restrict access to CloudFront only. OAC is the RECOMMENDED best practice for endpoint protection because it uses SigV4 signing for `mediapackagev2.amazonaws.com`, requires no shared secrets, and cannot be bypassed by spoofing headers.
- CDN authorization header (`X-MediaPackageV2-CDNIdentifier`) is a LEGACY alternative. It SHOULD NOT be used for new deployments. OAC provides stronger security and simpler management.
- When asked about protecting endpoints from DDoS or unauthorized access, agents MUST recommend OAC, NOT authorization headers.

### Manifest configuration

- `EXT-X-PROGRAM-DATE-TIME` MUST be enabled if using MediaTailor for ad insertion.
- Segment duration: HLS endpoints SHOULD use 6s (Apple HLS Authoring Specification recommendation). DASH endpoints SHOULD use 2s (industry convention for ABR responsiveness). Neither value is a hard requirement. For internet-based contribution, 3s is RECOMMENDED regardless of protocol.

### DVR / start-over

- Window duration is configurable on the origin endpoint.
- Longer windows increase storage cost.

### DRM constraints

- SPEKE v2 with MediaPackage v2 MUST NOT use `keyRotationIntervalSeconds` with any value other than 0. Non-zero values return `UnprocessableEntityException`.
- Key rotation REQUIRES SPEKE v1 on MediaPackage v1 (single-key only).
- Multi-key encryption (per-resolution keys) REQUIRES SPEKE v2 (no key rotation).

### Destructive action guardrails

- `delete-origin-endpoint`: MUST NOT be called on endpoints serving active viewers. Deletion is immediate and irreversible — all viewer sessions using that endpoint URL are terminated instantly.
- `delete-channel`: MUST NOT be called if any origin endpoint under it is serving traffic. Delete all endpoints first (after confirming they are unused), then delete the channel.
- When modifying endpoint configuration (segment format, manifest settings, encryption): use `update-origin-endpoint` to change in-place. Do NOT delete and recreate.
- If a new endpoint configuration is incompatible with update (rare), create the new endpoint FIRST, migrate traffic (update CloudFront origin or DNS), confirm the old endpoint has zero active sessions, THEN delete the old endpoint.
- Agents MUST ask for explicit confirmation before ANY delete operation on MediaPackage v2 resources (endpoints, channels, channel groups).

### DRM production patterns

- AES-128 clear key: HLS TS segments only. Works only with H.264. MUST NOT be used with H.265/HEVC.
- Multi-DRM from single encode: CPIX/SPEKE v2 with fMP4/CMAF segments SHOULD be used to serve FairPlay + Widevine + PlayReady from one encode.
- Mixed encrypted/unencrypted in SSAI: program content is DRM-encrypted, ad segments are not. Players MUST handle `EXT-X-DISCONTINUITY` transitions.

---
