
Loaded conditionally when the task involves MediaTailor. The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

Rules here are derived from the public MediaTailor documentation and from behaviour measured against the live service. Where the two disagree, the measured behaviour is marked and wins.

## Table of Contents

- [Mutating a playback configuration](#mutating-a-playback-configuration)
- [Playback configuration fields](#playback-configuration-fields)
- [How a session starts, and why it sets the reporting mode](#how-a-session-starts-and-why-it-sets-the-reporting-mode)
- [Ad markers in the output manifest](#ad-markers-in-the-output-manifest)
- [CDN surfaces](#cdn-surfaces)
- [Creative conditioning](#creative-conditioning)
- [Prefetch](#prefetch)
- [SCTE-35 dependency](#scte-35-dependency)
- [Scaling for large events](#scaling-for-large-events)
- [Metrics that do not mean what they look like](#metrics-that-do-not-mean-what-they-look-like)
- [Quotas](#quotas)

---

## Mutating a playback configuration

This is the single most damaging MediaTailor mistake an agent can make, so it comes first.

`PutPlaybackConfiguration` is the only mutator. There is no Create, no Update, and no patch semantics. It replaces the whole object, so agents **MUST** assume that **any optional setting absent from the request reverts to its default**. Omission semantics are not documented field by field, and measurement shows they are not uniform, so the safe assumption is the only workable one.

- Agents **MUST** read the current configuration with `GetPlaybackConfiguration`, merge the change into the full response, strip the response-only fields, and write the whole object back.
- Agents **MUST NOT** send a partial `PutPlaybackConfiguration` request, even to change one field.
- Agents **MUST** capture the pre-change `GetPlaybackConfiguration` output before writing. There is no configuration version history and no rollback API, so that output is the only rollback artifact the customer controls. CloudTrail records the `requestParameters` of each call, which for a whole-object write is usually a complete configuration, but it captures what was sent rather than what was in effect, so agents **MUST NOT** treat it as a guaranteed rollback source.
- Agents **MUST** verify a configuration change with a brand-new session, never by reloading an existing player. Whether a change reaches sessions already in flight is not documented.

Measured: a request carrying only `Name`, `VideoContentSourceUrl` and `AdDecisionServerUrl` silently cleared `SlateAdUrl`, `PersonalizationThresholdSeconds`, `AvailSuppression`, `Bumper`, `CdnConfiguration`, `ConfigurationAliases`, `LivePreRollConfiguration`, `InsertionMode`, `AdConditioningConfiguration` and `DashConfiguration.MpdLocation`. `Tags` survived, and so did `ManifestProcessingRules.AdMarkerPassthrough.Enabled`, reproducibly. The reset set is not uniform, so agents **MUST NOT** reason about which fields persist.

Response-only fields that `Get` returns and the `Put` request does not accept, and which **MUST** be stripped before the write: `PlaybackConfigurationArn`, `PlaybackEndpointPrefix`, `SessionInitializationEndpointPrefix`, `DualStackPlaybackEndpointPrefix`, `DualStackSessionInitializationEndpointPrefix`, `HlsConfiguration`, `LogConfiguration`. `DashConfiguration` **MUST** be narrowed to `MpdLocation` and `OriginManifestType`, because the request type carries only those two, which also drops the response-only `DualStackManifestEndpointPrefix` nested inside it.

The two dual-stack prefixes are easy to miss because they appear only on dual-stack-enabled configurations. A strip list that omits them passes on one configuration and fails validation on the next.

```
IF changing any playback configuration field:
  → Get the current configuration in full
  → Merge the change into that object
  → Strip the response-only fields listed above
  → Put the whole object
  → Get again and diff against the pre-change output
  IF a field you did not touch changed:
    → CAUSE: a field was dropped from the request and reverted to its default
    → FIX: restore from the pre-change output, then re-apply the change as a merge
```

Agents **SHOULD** treat every `PutPlaybackConfiguration` call as a whole-object write in reviews and in
generated code, and **SHOULD** reject a proposed change that constructs the request from scratch.

## Playback configuration fields

A playback configuration needs two URLs to do anything: where the content comes from, and where the ads come from. Only `Name` is marked `Required: Yes` on the API. Both URLs are `Required: No`, which means the service accepts a configuration that can never serve an ad. Agents **MUST** treat both as functionally mandatory and **MUST NOT** rely on the API to reject a configuration missing either.

- `VideoContentSourceUrl` is the origin manifest URL prefix minus the asset id. Commonly a MediaPackage v2 origin endpoint, but any public HLS or DASH origin reachable on port 80 or 443 with a certificate from a well-known CA qualifies. Agents **MUST NOT** flag a non-MediaPackage origin as a misconfiguration.
- `AdDecisionServerUrl` is the ad decision server. Without it there is no ad decision and therefore no ad insertion, so it is the field to check first when a configuration produces no ads at all. It is a template: `[session.*]`, `[avail.*]`, `[scte.*]` and `[player_params.*]` macros are substituted per request. Square brackets only; `${session.id}` is **NOT** substituted. A static VAST URL is valid here for testing.
- The ADS response **MUST** be VAST through 4.3, VMAP 1.0, or VPAID 2.0. Some VAST 4.0-and-later features are not supported. `TrackingEvents` **MUST** use IAB-compliant standard event types: a non-standard tracking event makes MediaTailor reject the whole VAST response and fill no ad for that avail.
- Because `PutPlaybackConfiguration` replaces the whole object, a partial write can silently clear `AdDecisionServerUrl` and the API will not stop it. The configuration then serves unpersonalized content with no error, which is the worst failure mode in this service: the stream keeps playing and the revenue stops.
- `CdnConfiguration` (content and ad segment prefixes) is OPTIONAL. Without it MediaTailor emits origin-direct segment URLs, which works but bypasses CDN caching.
- `SlateAdUrl` is OPTIONAL for non-VPAID workflows and mandatory for VPAID. Slate is live and live-to-VOD only. Without a slate, MediaTailor falls back to the underlying content stream in every situation where it would have shown slate: unfilled break time, an empty VAST or VMAP response, an ADS timeout or 5xx, and a creative that has not finished conditioning.
- `PersonalizationThresholdSeconds` caps underfilled ad time. Past the cap, MediaTailor abandons personalization of the break and shows the underlying content, so it works with or without a slate. It applies to ad **replacement**, not ad insertion, because it relies on there being underlying content to fall back to.
- `InsertionMode` defaults to `STITCHED_ONLY`. `PLAYER_SELECT` only *permits* server-guided insertion; each session still has to ask for it, and a session that does not ask gets stitched output with no error.
- Agents **MUST NOT** read defaults from `aws mediatailor put-playback-configuration --generate-cli-skeleton`. The skeleton emits the first enum value, which for at least two fields is the opposite of the real default. Agents **SHOULD** use the skeleton only to check whether the installed CLI build carries a field at all, because the CLI ships its own API model and lags the service.

## How a session starts, and why it sets the reporting mode

Ad stitching happens only inside a MediaTailor session, and the player's first request creates one. There are three entry points:

| Entry point | Protocol | Session id |
|---|---|---|
| `GET /v1/master/<hash>/<config>/<asset>.m3u8` | HLS, implicit | none needed |
| `GET /v1/dash/<hash>/<config>/<asset>.mpd` | DASH, implicit | returned via redirect carrying `?aws.sessionId=` |
| `POST /v1/session/<hash>/<config>/<asset>` with a JSON body | either, explicit | returned in the response body |

- The implicit HLS path needs no session id and **DOES** stitch ads. MediaTailor returns a personalized multivariant playlist whose variant URIs point at a per-session media playlist under `/v1/manifest/<hash>/<config>/<sessionId>/<n>.m3u8`. Ad segments appear there, never in the multivariant playlist.
- `aws.sessionId` is the DASH session identifier and the resume form of an explicit init. It is **NOT** a precondition for HLS stitching. Agents **MUST NOT** tell a customer that `/v1/master` without `aws.sessionId` fails to stitch.
- `POST` returns `manifestUrl` and `trackingUrl` as **paths**, not absolute URLs. Agents **MUST** resolve them against the scheme and host of `PlaybackEndpointPrefix` before handing either to a player.
- **The entry point sets the default reporting mode.** Implicit `GET` defaults to server-side reporting; explicit `POST` defaults to client-side. Agents **MUST NOT** migrate a working player from implicit `GET` to `POST /v1/session` without also confirming who fires the beacons: on client-side, MediaTailor stops firing them, impressions fall to zero, and nothing errors.
- The manifest-parameter prefix differs by entry point: `manifest.<name>` on implicit init, `manifestParams` in the explicit POST body, `manifestParams.<name>` on explicit GET.

## Ad markers in the output manifest

- `ManifestProcessingRules.AdMarkerPassthrough.Enabled` is HLS only (`ManifestProcessingRules` has no DASH equivalent) and defaults to `false`.
- It gates `EXT-X-CUE-OUT`, `EXT-X-CUE-IN` and `EXT-X-SPLICEPOINT-SCTE35` only. `EXT-X-DATERANGE` is passed through regardless of the setting, and `EXT-X-DISCONTINUITY` is added at the break boundaries either way. `EXT-X-CUE-OUT-CONT` is never forwarded.
- MediaTailor applies no logic to the passed-through values. Measured: a 30 s break filled by one 15 s creative still emits `#EXT-X-CUE-OUT:30.000`. It is a break-boundary signal, so agents **MUST NOT** treat a passed-through duration as a fill-rate or impression source.
- SHOULD be enabled when downstream players or analytics need to see the original ad break boundaries.
- `[avail.source_content_time_epoch_ms]` derives from the `EXT-X-PROGRAM-DATE-TIME` of the origin segment that opened the avail, so the macro has no value on an HLS origin without PDT. The HLS specification separately requires a Media Playlist carrying `EXT-X-DATERANGE` to carry `EXT-X-PROGRAM-DATE-TIME`. On VOD, MediaTailor adds PDT itself and preserves origin PDT where present.

## CDN surfaces

Constructing the distribution belongs to `service-rules-cloudfront.md`. What matters here is that MediaTailor serves three different kinds of response and they need opposite cache treatment.

| Surface | Path | Cacheable | Forward |
|---|---|---|---|
| Personalized manifests, session init, tracking | `/v1/*` | **NO** | all viewer headers and query strings |
| Server-side reporting redirect | `/segment/*` | **NO** | all viewer headers and query strings |
| Ad segments | `/tm/*` | YES, 24h+ | **nothing** |
| Server-guided interstitial media | `/v1/i-media/*` | YES, **unless guided prefetch is in use** | nothing |

- Agents **MUST** set `TTL=0` on the manifest, session and `/segment/*` behaviours, and **MUST** forward all query strings and `User-Agent` there so targeting variables and device information reach the ad decision server. A shared cache entry on any of them leaks one viewer's session to another.
- `/segment/*` is the server-side reporting redirect, not an ad segment. It **MUST** reach MediaTailor on every view for the beacon to fire, so agents **MUST NOT** apply the ad segment caching rules to it.
- Agents **MUST NOT** forward query strings, headers or cookies on the `/tm/*` ad segment behaviour: ad segments are identical for every viewer, so forwarding gives each viewer a private cache entry and raises both CDN cost and ad delivery out with no change in behaviour.
- `/v1/i-media/*` **MUST NOT** be cached when guided prefetch is in use. The player's refresh of each interstitial media manifest is the prefetch heartbeat, so a cache hit means the request never reaches MediaTailor and no prefetch is enqueued. Nothing errors: prefetch just stops happening. Without guided prefetch the same path is shared and caches like a segment.
- Every MediaTailor behaviour **SHOULD** carry a CORS response headers policy. Missing CORS headers on the ad segment behaviour breaks playback in browser-based players.
- Compression **SHOULD** stay enabled on the manifest behaviours. Agents **MUST NOT** recommend disabling it as a general measure: manifests are the highest-request-rate text in the workflow, so compression there is a material delivery cost saving.
- Content segments never traverse MediaTailor, so caching them reduces origin and CDN cost, not MediaTailor cost.

## Creative conditioning

- The first sighting of a creative is skipped by design, while MediaTailor conditions it to the content's renditions. Agents **MUST NOT** report a first-sighting skip as a defect. Diagnosis is in `troubleshooting-mediatailor.md`.
- Creatives do **NOT** have to match the content's bitrate, frame rate or resolution. That is what conditioning does.
- MediaTailor conditions the **highest-bitrate** `MediaFile` only, with no fallback to a lower one, so that entry is the only one whose reachability and format matter.
- MediaTailor recognises a conditioned creative by three things together: the creative id, the AWS account id, and the **transcode variant set**, meaning the playback renditions of the underlying content. Change any of them and it is a new variant that must be conditioned again. So a creative warm on one playback configuration is warm on another only where the rendition ladder matches, and agents **MUST NOT** promise account-wide warmth across configurations with different ladders.
- A bitrate that fails to match after rounding to the nearest 8,000 bits counts as a different variant, which is why an encoder ladder change can produce a wave of first-sighting skips on creatives that were already warm.
- The index key is the `id` on `<Creative>`. Agents **MUST** advise a unique id per creative: MediaTailor serves stored content for a known id, so a reused id plays the older ad silently.

## Prefetch

- Prefetch is **NOT** enabled by default and **MUST** be configured explicitly.
- Two mechanisms exist and they share no configuration surface. Schedule-based prefetch (`CreatePrefetchSchedule`) serves stitched sessions. Guided prefetch (`aws.guidedPrefetchMode=MANIFEST` on the session) serves server-guided sessions.
- Agents **MUST NOT** create a prefetch schedule for a guided session. The API accepts it, it never fires, and no error or log event is raised.
- Retrieval is free; insertion bills on consumption; transcoding **is** charged for prefetched creatives.

## SCTE-35 dependency

MediaTailor consumes markers, it does not create them. Markers **MUST** flow through the whole chain: source encoder to MediaLive to MediaPackage to MediaTailor. See `service-rules-medialive.md` and `service-rules-mediapackage.md` for the upstream configuration, and `troubleshooting-mediatailor.md` for the diagnostic order.

On live, every `EXT-X-CUE-OUT` needs either a duration or a matching `EXT-X-CUE-IN`. A break that never closes has two possible layers: the packager never closed it (mismatched `segmentation_event_id`, an MediaPackage v2 concern), or MediaTailor could not time it.

## Scaling for large events

- SSAI manifests are personalized per session by design. There is no mode that coalesces viewers onto a shared manifest, so agents **MUST NOT** propose one. Scale the session count.
- Audience-specific *content* is a different feature: Channel Assembly Program Rules, where an audience cohort selects alternate media on a STANDARD tier LINEAR channel. Agents **MUST NOT** describe it as an SSAI scaling mode.
- Events above **500,000 concurrent viewers** require a Support engagement: contact AWS Support at least two weeks ahead so capacity is in place for ad personalization. Agents **MUST** raise this before any architectural suggestion, because no amount of CDN design substitutes for the capacity request. Request quota increases through the Service Quotas console in the same window.
- Origin manifest fetches do **NOT** scale one-to-one with player requests, because MediaTailor holds a fetched origin manifest and serves it to more than one session. `Origin.Age` and `GetManifest.MediaTailorAge` split the resulting staleness between origin-held and MediaTailor-held time. Agents **MUST NOT** compute a reuse ratio from `SampleCount` of `Origin.Age` against `Requests`: `Requests` is concurrent transactions per second across all request types, so the two are not comparable. Compare `Origin.Age` `SampleCount` against the content origin's own access logs instead.
- Anything that makes the origin URL unique per request (a per-session token, a rotating signature, CDN auth in the URL) defeats that reuse. Protecting a MediaPackage v2 origin with **SigV4** avoids the trade-off: grant `mediatailor.amazonaws.com` principal access plus `mediapackagev2:GetObject` on the endpoint policy, and authentication rides in the signature rather than the URL, so the origin stays protected and the URL stays stable. The `mediatailor.amazonaws.com` service-principal grant is a cross-service confused-deputy surface, so agents **MUST** scope it with `aws:SourceAccount` (your account id) and **SHOULD** further scope it with `aws:SourceArn` (the specific playback-configuration ARN) in the endpoint-policy condition block, so only your MediaTailor configurations can exercise the grant.
- No documented setting reduces origin fetches beyond that reuse. Agents **MUST NOT** invent one, and **MUST NOT** offer CDN Origin Shield as the remedy: Origin Shield on the MediaTailor origin reduces the requests reaching MediaTailor from CloudFront edges, which is the opposite direction. Where an origin RPS limit binds, the lever is a quota increase.
- Pipeline locking on MediaLive matches segment numbers across pipelines and SHOULD be enabled for failover-sensitive SSAI. It is not required for SSAI to function.

## Metrics that do not mean what they look like

Definitions for the documented metrics are in the [CloudWatch metrics reference](https://docs.aws.amazon.com/mediatailor/latest/ug/monitoring-cloudwatch-metrics.html). These are the ones that mislead:

| Metric | What it is not | What it is |
|---|---|---|
| `Avail.FillRate` | percent of breaks that got an ad | the **planned simple average of per-avail fill percentages**, unweighted by avail duration, and capped at 100%. A 30 s break with one 15 s ad contributes 50%. Two avails filled 50% and 75% report 62.5%, whatever their durations. For a duration-weighted rate use metric math `100*m1/m2` with `Avail.FilledDuration` Sum as `m1` and `Avail.Duration` Sum as `m2` |
| `Avail.Duration`, `Avail.FilledDuration` | delivered ad time | **planned** values. The measured equivalents are the `Avail.Observed*` family |
| `AdsBilled` | impressions | insertions. Use `Avail.Impression` for beacons, and `sum(Avail.Complete)/sum(Avail.Impression)` for completion rate |
| `Avail.Impression` | ads viewers saw | ads for which MediaTailor fired a beacon **during server-side reporting**. A client-side configuration reports zero here while delivering normally |
| `Origin.*` | origin health | emitted only when the response came from the origin itself. `Origin.Age` is **not** emitted when the response came from a CDN, so a CDN in front of the origin blinds this metric and `0` errors is not evidence of a healthy origin |
| `SkippedReason.PersonalizationThresholdExceeded` | a count | a **duration**. It never matches a log count of skipped ads; the other ten `SkippedReason.*` metrics are counts |

Agents **MUST NOT** alarm on a metric name absent from a reference table. `ResponseTime`, `AdDecisionServer.Ads.Skipped` and `Avail.SlateOnly` appear in User Guide prose, are defined in no metric table, and do not exist. Note that the metrics page is not the complete inventory: the six `AdDecisionServer.Overlay*` metrics are real and documented on the overlay ads page instead.

## Quotas

Agents **MUST** verify a current quota through the Service Quotas API before relying on a limit, rather than restating a number. Two worth knowing about because the failure is silent or confusing:

- The ad decision server request timeout is **configurable** (`AdsPersonalizationTimeouts.AdsRequestTimeoutMilliseconds`, default 3000). The quotas page still describes it as a fixed, non-adjustable 3 seconds; that is stale.
- `ListPrefetchSchedules` documents `MaxResults` as 1 to 100. Observed in `aws-cli/2.34.63`, a value of 51 was rejected by client-side validation. Agents **SHOULD** verify against the installed CLI version rather than treating either bound as fixed.
