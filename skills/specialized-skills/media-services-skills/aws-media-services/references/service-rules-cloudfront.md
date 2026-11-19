# Service Rules: CloudFront (media delivery)

Loaded conditionally when the task involves CloudFront (media delivery). The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

---

## CloudFront (media delivery)

### Origin configuration

- For MediaPackage v2: the origin endpoint URL MUST be used as the origin domain.
- For MediaTailor: the MediaTailor playback URL MUST be used as the origin. MediaTailor returns child manifest URLs as relative paths with directory traversal (`../../../`); the CloudFront origin path depth MUST match what MediaTailor expects so relative URL resolution in the player still lands on the right cache behaviors. Leaving OriginPath empty is the simplest configuration that works in most cases. If a non-empty OriginPath is used, the cache behavior path patterns MUST be aligned to compensate.
- MediaTailor session initialization (/v1/session/) supports both POST (JSON body) and GET (query parameters prefixed with `ads.` and `manifestParams.`). If using GET-based session init, no additional CloudFront method configuration is needed. If using POST-based session init, AllowedMethods MUST include POST.
- For S3 VOD: OAC MUST be used.

### Origin Shield (CRITICAL for live)

- Origin Shield MUST be enabled on EVERY CDN pulling from MediaPackage v2.
- MediaTailor's origin manifest fetches DO count against the MediaPackage v2 1000 manifest-RPS limit, but MediaTailor reuses a fetched origin manifest across player requests, so fetch volume sits well below player volume. Measure it by comparing `Origin.Age` `SampleCount` against the content origin's own access logs, not against `Requests` (which counts all request types and is not comparable). No documented setting reduces those fetches further, so where the limit binds the lever is a quota increase.
- Origin Shield on the MediaTailor origin reduces the requests reaching MediaTailor from CloudFront edges. It does NOT reduce MediaTailor's own fetches from the content origin, so it MUST NOT be offered as a remedy for an origin RPS limit.
- AWS does not recommend positioning a CDN between a **content origin** and MediaTailor: it introduces cache-key collisions, stale manifests, and corrupt gzip payloads that break manifest parsing, and it suppresses `Origin.Age` because that metric is emitted only when the response came from the origin. Diagnosis and the narrow gzip remedy are in `troubleshooting-mediapackage.md`.
- The exception is **channel assembly**: where the content source is a channel assembly channel, AWS recommends a CDN in between as a best practice, because ad insertion can generate additional origin requests. Proxy the channel assembly manifests through the CDN and set the CDN-prefixed URL as the content source. Agents **MUST NOT** apply the general warning to a channel assembly source.
- Removing a CDN from that leg can break manifest fetches with 403s if the origin policy names only the CDN. On MediaPackage v2 with SigV4, grant `mediatailor.amazonaws.com` principal access and `mediapackagev2:GetObject` first. Scope that service-principal grant against cross-service confused-deputy abuse: agents **MUST** add an `aws:SourceAccount` (your account id) condition and **SHOULD** add `aws:SourceArn` (the playback-configuration ARN) to the endpoint policy, so only your own MediaTailor configurations can assume the grant.
- Target cache hit ratio: 90-100%.

### Origin timeouts

- Origin connection timeout SHOULD be lowered well below the segment duration so a slow origin doesn't tie up viewer-facing requests (a value around half the segment length is a common starting point). Default timeouts of 10s/30s MUST NOT be used for live streaming.

### Error caching

- Error response TTL SHOULD be set to a low value (around 1 second) for all live-streaming error codes (403, 404, 500, 502, 503, 504). The default 5-minute TTL MUST NOT be used for live.

### Cache behavior for live

- Separate cache behaviors for manifests vs segments are REQUIRED.
- Manifest files (.m3u8, .mpd): TTL SHOULD be half segment duration (2-4 seconds for 6s segments).
- Segment files (.ts, .m4s, .cmfv, .cmfa): TTL SHOULD be 24+ hours (segments are immutable).
- Query string forwarding: all query strings MUST be forwarded.
- Compression SHOULD be enabled on manifests.

### CloudFront with MediaTailor — split-origin routing (RECOMMENDED)
When CloudFront fronts MediaTailor, the AWS-recommended pattern uses multiple origins with path-based routing for optimal caching and performance:

- **MediaTailor manifests origin** — `manifests.mediatailor.<region>.amazonaws.com`. Serves personalized manifests, per-session media playlists, server-side beacon redirects and server-guided interstitial media. Paths: `/v1/*` (which covers `/v1/master/*`, `/v1/manifest/*`, `/v1/dash/*`, `/v1/session/*`, `/v1/tracking/*` and, at higher precedence, `/v1/i-media/*`) plus `/segment/*`. Omitting `/v1/manifest/*` breaks HLS playback because the per-session media playlist lives there, and omitting `/segment/*` breaks server-side beaconing.
- **MediaTailor ad segments origin** — `segments.mediatailor.<region>.amazonaws.com`. Serves transcoded ad segments on `/tm/*`.
- **MediaPackage v2 origin** — serves content segments (shared, cacheable). Paths: `/out/v1/*` (or whatever the MediaPackage endpoint path prefix is).
Every MediaTailor behavior SHOULD carry a CORS response headers policy. Missing CORS headers on the ad segment behavior breaks playback in browser-based players.

MediaTailor rewrites manifests with segment URLs pointing back to CloudFront. If content segments route to MediaTailor instead of MediaPackage, players receive errors because MediaTailor does not serve content segments.

Cache behaviors, in precedence order:

- `/tm/*` → ad segments origin, caching optimized, TTL 24h+, forward **nothing** (no headers, cookies or query strings in the cache key or origin request), CORS response headers
- `/v1/i-media/*` → manifests origin, forward nothing, CORS response headers. Caching optimized **only when guided prefetch is not in use**. With guided prefetch, caching MUST be disabled on this path: the player's manifest refresh is the prefetch heartbeat, and a cache hit stops it reaching MediaTailor, which silently disables prefetching
- `/v1/*` → manifests origin, caching **disabled**, forward all viewer headers and query strings, CORS response headers
- `/segment/*` → manifests origin, caching **disabled**, forward all viewer headers and query strings, CORS response headers. This is the server-side reporting redirect, not an ad segment: it MUST reach MediaTailor on every view for the beacon to fire
- `/out/v1/*` → MediaPackage v2 origin, TTL=24h+ (segments are immutable), Origin Shield enabled

Compression SHOULD stay enabled on the manifest behaviors. Manifests are the highest-request-rate text in the workflow, so compression there is a material delivery cost saving.

MediaTailor `CdnConfiguration.ContentSegmentUrlPrefix` MUST be set to the CloudFront distribution domain with the full MediaPackage path prefix (e.g., `https://<cf-domain>/out/v1/<channel-group>/<channel>/<endpoint>`) so that segment URLs in the rewritten manifest route through the correct CloudFront cache behavior to MediaPackage.

Without `CdnConfiguration` prefixes, MediaTailor emits origin-direct segment URLs, bypassing CloudFront caching. This works but loses CDN caching benefits for segments.

### Cache behavior for VOD

- Manifests MAY be cached longer (minutes to hours) since content does not change.
- Segments SHOULD be cached indefinitely (immutable).

### CORS for browser-based players

- Browser-based players (hls.js, dash.js, Shaka) require CORS headers when the player application is served from a different origin than the media content. Without CORS, browser playback fails silently or with a network error.
- CORS SHOULD be configured via a CloudFront Response Headers Policy (not S3 bucket CORS). Set `Access-Control-Allow-Origin` to the allowed application origins (or `*` for unrestricted), `Access-Control-Allow-Methods` to `GET, HEAD, OPTIONS`, and enable "Override origin" to ensure consistent headers regardless of origin behavior.
- When building a VOD or live workflow intended for browser playback, agents SHOULD proactively include a CORS-configured Response Headers Policy on the CloudFront distribution.

### Security response headers

- CloudFront Response Headers Policies SHOULD include security headers for browser-delivered content: `Strict-Transport-Security: max-age=31536000` (HSTS, 1 year), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (or SAMEORIGIN if the player must be embedded), and `Referrer-Policy: strict-origin-when-cross-origin`. AWS provides a managed `SecurityHeadersPolicy` that includes these.
- These headers apply to manifest paths and any HTML/player pages served through the distribution.

### OAC (Origin Access Control)

- REQUIRED when restricting MediaPackage or S3 origin to CloudFront-only access.
- OAC is the RECOMMENDED method for all production MediaPackage v2 deployments. It MUST be preferred over CDN authorization headers (`X-MediaPackageV2-CDNIdentifier`).
- OAC uses SigV4 request signing — no shared secrets to rotate, cannot be spoofed.
- When creating OAC for MediaPackage v2: signing protocol = SigV4, signing behavior = Always, origin service = `mediapackagev2.amazonaws.com`.
- MediaPackage endpoint policy MUST allow the CloudFront distribution and MUST NOT retain `Principal: "*"` after OAC is configured.

### Security

- Signed URLs or signed cookies SHOULD be used for content access control.
- Geo-restriction SHOULD be enabled (allowlist licensed territories only).
- WAF + Shield Advanced is RECOMMENDED for all production distributions.

---
