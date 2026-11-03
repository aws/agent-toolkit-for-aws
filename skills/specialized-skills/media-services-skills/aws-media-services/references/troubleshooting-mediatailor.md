# Troubleshooting: MediaTailor

Per-service troubleshooting for MediaTailor server-side ad insertion. Load `service-rules-mediatailor.md` alongside this file.

## Table of Contents

- [The five stages](#the-five-stages)
- [Symptom Router](#symptom-router)
- [No ads at all](#no-ads-at-all)
- [Ads appear only from the second play](#ads-appear-only-from-the-second-play)
- [Some breaks fill, others do not](#some-breaks-fill-others-do-not)
- [Skip reasons, and which ones are normal](#skip-reasons-and-which-ones-are-normal)
- [Wrong ad, or the same ad everywhere](#wrong-ad-or-the-same-ad-everywhere)
- [Beacons and impression counts](#beacons-and-impression-counts)
- [Latency and stale manifests](#latency-and-stale-manifests)
- [Targeting parameters not reaching the ad server](#targeting-parameters-not-reaching-the-ad-server)
- [Log groups and how to join them](#log-groups-and-how-to-join-them)
- [Before opening a support case](#before-opening-a-support-case)

---

## The five stages

Ad delivery is a pipeline, and every stage fails independently. Agents **MUST** work it top down and **MUST** stop at the first stage that fails, because the log proving one stage says nothing about the next.

| # | Stage | Proof it passed | Where |
|---|---|---|---|
| 1 | Break detection | `AD_MARKER_FOUND` | ADS interaction log |
| 2 | Ad decision | `MAKING_ADS_REQUEST` then `VAST_RESPONSE` then `FILLED_AVAIL` | ADS interaction log |
| 3 | Creative conditioning | `TRANSCODE_COMPLETED` for the `creativeUniqueId` | transcode log |
| 4 | Manifest assembly | `EXT-X-DISCONTINUITY` plus ad segment URIs in the personalized media playlist | fetch the manifest |
| 5 | Delivery and reporting | `Avail.Impression`, `BEACON_FIRED` | metrics, ADS log |

**The most common misdiagnosis in SSAI:** `FILLED_AVAIL` records the ad *decision*, two stages before delivery. Agents **MUST NOT** conclude ads are playing from `FILLED_AVAIL` alone. If the creative was still conditioning, the avail renders empty and `AdNotReady` plus `SkippedReason.NewCreative` fire instead.

## Symptom Router

```
IF no ads in any break, ever:
  → See "No ads at all"
IF ads absent on first play, present on replay:
  → See "Ads appear only from the second play" (this is usually correct behaviour)
IF some breaks fill and others do not:
  → See "Some breaks fill, others do not"
IF ads play but the wrong ad, or every viewer sees the same ad:
  → See "Wrong ad, or the same ad everywhere"
IF ads play but impressions are missing or doubled:
  → See "Beacons and impression counts"
IF playback starts slowly, or manifests go stale:
  → See "Latency and stale manifests"
IF ad targeting is wrong or the ad server sees no parameters:
  → See "Targeting parameters not reaching the ad server"
IF the break never closes (CUE-OUT with no CUE-IN):
  → LOAD references/troubleshooting-mediapackage.md — MediaPackage v2 tracks avails by
    segmentation_event_id and a mismatched CUE-IN leaves the avail open
IF SCTE-35 never reaches MediaTailor:
  → LOAD references/troubleshooting-medialive.md for the upstream chain
```

## No ads at all

```
IF no ads in the personalized manifest:
  → Check: can you reproduce the session yourself?
  IF yes:
    → FIX: use per-session debug logging, NOT sampling. Append ?aws.logMode=DEBUG to the
      playback request for server-side reporting, or send "logMode": "DEBUG" in the session
      initialization body for client-side. That logs the one session you care about
    → Agents SHOULD prefer this over raising PercentEnabled: sampling picks sessions at
      random, so it may never capture the session under investigation, and it multiplies
      billed log volume across every session on the configuration
  IF no, and LogConfiguration.PercentEnabled is 0:
    → CAUSE: no per-session detail is being recorded, so nothing can be traced after the fact
    → FIX: raise it to a sampling percentage to catch an intermittent fault, then lower it
      again. CloudWatch metrics still publish by default, so fill rate, skip reasons and ADS
      errors remain visible in aggregate meanwhile
  → Check: does the ADS interaction log show AD_MARKER_FOUND for the session?
  IF no AD_MARKER_FOUND:
    → CAUSE: MediaTailor saw no break. The markers are missing or unparseable upstream
    → FIX: fetch the ORIGIN manifest directly and look for EXT-X-CUE-OUT / EXT-X-DATERANGE
      (HLS) or an EventStream (DASH). If absent, the fault is upstream: check MediaLive
      SCTE-35 passthrough and that MediaPackage exposes markers
    → NOTE: on VOD, #EXT-X-CUE-OUT:0 is the insertion marker and is a real break. Agents
      MUST NOT treat a zero duration as "no break declared"
  IF AD_MARKER_FOUND present:
    → Check: MAKING_ADS_REQUEST present?
    IF no MAKING_ADS_REQUEST:
      → CAUSE: the break was seen but no ad request was made
      → FIX: check AdDecisionServerUrl is set on the configuration FIRST. The API accepts a
        playback configuration with no ADS URL, so a partial PutPlaybackConfiguration can
        clear it and the stream keeps serving unpersonalized content with no error
      → Then check AvailSuppression mode and PersonalizationThresholdSeconds, which also
        suppress the request: avail suppression by position, the threshold by break duration
    IF MAKING_ADS_REQUEST present:
      → Check: what followed it?
      IF ERROR_ADS_TIMEOUT:
        → CAUSE: the ad server did not answer in time. Every timeout is an unfilled break
        → FIX: the timeout is configurable (AdsPersonalizationTimeouts, default 3000 ms,
          range 250 to 6000). Fix the ad server first; raising the timeout moves the latency
          into the manifest request path
      IF ERROR_ADS_INVALID_RESPONSE:
        → CAUSE: the ad server returned a non-200
        → FIX: ad server side. Note a 204 is an error here, not a no-fill signal: to signal
          no fill, return 200 with a VAST document containing zero <Ad> elements
      IF EMPTY_VAST_RESPONSE:
        → CAUSE: the ad server chose not to fill. This is an ad server decision, NOT a
          MediaTailor fault
        → FIX: escalate to ad ops with the adsRequestUrl from the log
      IF ERROR_ADS_RESPONSE_PARSE:
        → CAUSE: MediaTailor could not use the VAST. See "Some breaks fill, others do not"
      IF FILLED_AVAIL:
        → The decision succeeded. Go to stage 3 and check conditioning
```

## Ads appear only from the second play

This is the designed cost of conditioning and is usually **not** a fault.

```
IF the first play shows no ad but a later play does:
  → Check: SkippedReason.NewCreative and AdNotReady in metrics
  IF both non-zero and falling:
    → CAUSE: first sighting. MediaTailor is conditioning the creative to the content ladder
    → FIX: none required. Confirm the same creativeUniqueId fills on a later request. To keep
      it off the viewer's path use prefetch, preconditioned ads, or a warm creative pool
  IF SkippedReason.NewCreative is high and NOT falling:
    → CAUSE: creatives are rotating faster than they can be conditioned, or the creative id
      changes every response
    → FIX: check that <Creative id> is stable. With no id, MediaTailor indexes by media file
      URL, so a cache-busting query string makes every request a brand-new creative and
      guarantees a permanent skip floor
```

A skip is per session, not per creative. Every session building a manifest for that break during the conditioning window skips independently, so at high concurrency a healthy service produces a large `SkippedReason.NewCreative` value. The count tracks concurrency, not health.

## Some breaks fill, others do not

```
IF fill is partial:
  → Check: avail.skippedAds[].skippedReason inside FILLED_AVAIL records
  IF TRANSCODE_ERROR:
    → CAUSE: conditioning failed on the selected creative
    → FIX: MediaTailor conditions the HIGHEST-BITRATE MediaFile only, with no fallback.
      Confirm that file is a reachable, high-quality MP4. No ProRes, no odd resolutions
      such as 855x481
  IF NO_VARIANT_MATCH:
    → CAUSE: the creative could not be matched to a content rendition
    → FIX: align the creative ladder to the content ladder, or author a transcode profile
      covering every current variant. Creatives do NOT need to match content encoding;
      this is a matching failure, not a quality mismatch
  IF AVAIL_DURATION_EXCEEDED:
    → CAUSE: the ad server returned more ad time than the break holds. MediaTailor never
      clips an ad, so creatives that do not fit are dropped whole
    → FIX: size the pod with [session.avail_duration_secs] in the ADS URL
  IF LEFTOVER_AVAIL_EXCEEDED_THRESHOLD:
    → CAUSE: unfilled time exceeded PersonalizationThresholdSeconds, so the break was
      abandoned rather than partially filled
    → FIX: this is the setting doing its job. Raise the threshold or improve fill
  IF EARLY_CUE_IN:
    → CAUSE: the live signal closed the break early. Expected on live
  IF the response was rejected (ERROR_ADS_RESPONSE_PARSE):
    → CAUSE: the VAST breaks one of MediaTailor's structural rules
    → Check first for a granular event on the same session. The ADS interaction log defines
      ERROR_VAST_MISSING_CREATIVES, ERROR_VAST_MISSING_IMPRESSION, ERROR_VAST_MISSING_MEDIAFILES,
      ERROR_VAST_MISSING_OVERLAYS, ERROR_VAST_MULTIPLE_LINEAR, ERROR_VAST_MULTIPLE_TRACKING_EVENTS,
      ERROR_VAST_INVALID_MEDIA_FILE, ERROR_VAST_INVALID_VAST_AD_TAG_URI and three
      ERROR_VAST_REDIRECT_* events. One of those names the failing rule directly
    → NOTE: a crafted-fixture run did not surface any granular event, only
      ERROR_ADS_RESPONSE_PARSE. So agents MUST NOT conclude from its absence that the response
      is structurally fine, and SHOULD re-run with ?aws.logMode=DEBUG before deciding the log
      cannot say which rule failed
    → FIX: capture RAW_ADS_RESPONSE and inspect the document. Counting is per owning parent,
      not per <Ad>: at most one <Linear> per <Creative>, one <Duration> and one <MediaFiles>
      per <Linear> in use, at most one <TrackingEvents> per owner, at least one <Impression>
      per <InLine>
```

## Skip reasons, and which ones are normal

The class column below is analytic, derived from each reason's mechanics. AWS classifies none of them, so agents **MUST NOT** attribute the classification to AWS.

| Class | Reasons | Action |
|---|---|---|
| Expected, self-resolving | `NEW_CREATIVE`, `TRANSCODE_IN_PROGRESS`, `IMPORT_IN_PROGRESS` | none, if the same creative fills later |
| Expected on live | `EARLY_CUE_IN`, `AVAIL_DURATION_EXCEEDED`, `LEFTOVER_AVAIL_EXCEEDED_THRESHOLD` | tune pod sizing or thresholds, not a defect |
| Transient, fault when sustained | `NO_VARIANT_MATCH` | align ladders after an encoder or ladder change |
| Fault | `TRANSCODE_ERROR`, `IMPORT_ERROR`, `PROFILE_NOT_FOUND`, `INTERNAL_ERROR` | investigate |

Agents **SHOULD** lead with what is normal before treating a skip as a defect, and **SHOULD** check whether the rate is steady rather than rising.

Corroborating a log count against a metric is sound, with one exception: `SkippedReason.PersonalizationThresholdExceeded` reports a **duration**, not a count, so it never matches a log count of skipped ads.

## Wrong ad, or the same ad everywhere

```
IF every viewer sees the same ad:
  → CAUSE: a personalized manifest is being cached and shared
  → FIX: TTL=0 on every MediaTailor manifest and session behaviour. Ad segments are the
    opposite and SHOULD be cached hard
IF the wrong ad plays, with no error and no skip reason:
  → CAUSE: a reused <Creative id>. MediaTailor stores conditioned creatives by that id and
    serves the stored asset for a known id
  → FIX: a fresh unique id per creative. There is no documented way to purge a mis-indexed
    creative
IF ads play in the wrong order in a pod:
  → CAUSE: pod order comes from the ADS response, not from MediaTailor. The sequence
    attribute appears on both <Ad> and <Creative> in VAST
  → FIX: read the ordering out of RAW_ADS_RESPONSE first and confirm the ADS sent the
    order the customer expected. Agents MUST NOT attribute pod order to a MediaTailor
    setting: no documented playback configuration field controls it
```

## Beacons and impression counts

```
IF ads deliver but Avail.Impression is zero:
  → Check: how does the session start?
  IF explicit POST /v1/session:
    → CAUSE: explicit init defaults to CLIENT-side reporting. MediaTailor fires nothing and
      CloudWatch sees no beacons. This is expected, not a fault
    → FIX: either the player fires beacons from the tracking endpoint, or move to implicit
      GET for server-side reporting
  IF implicit GET:
    → Check: did the player actually fetch the ad segments? Beacons fire only on real
      requests to the /segment/ URLs, never during manifest parsing
    IF the ad segments were never requested:
      → CAUSE: the ad played in no player. A manifest containing ads proves the decision,
        not the delivery
      → FIX: see the last Insights query below, which lists sessions that filled an avail
        and fired no beacon
    IF the segments were fetched and impressions are still zero:
      → CAUSE: the creatives carry no <Impression> URI. A VAST Ad with zero <Impression> is
        rejected outright, so check for ERROR_ADS_RESPONSE_PARSE and
        ERROR_VAST_MISSING_IMPRESSION too
IF impressions fire but no completes:
  → CAUSE: the creatives carry no complete tracking URI, or no ad played to the end
  → FIX: check the VAST for a complete event before assuming an audience problem.
    Completion rate is sum(Avail.Complete) / sum(Avail.Impression)
IF counts do not reconcile with the ad server:
  → Compare Avail.Impression against the ad server, NOT AdsBilled. AdsBilled counts
    insertions, so it answers a billing question rather than a measurement one
```

Agents **MUST NOT** fetch a tracking beacon URL while diagnosing. Reading the URL is safe; requesting it corrupts the customer's own impression counts.

## Latency and stale manifests

```
IF start-up is slow:
  → Check: AdDecisionServer.Latency
  IF above ~1000 ms average:
    → CAUSE: the ad server sits inside the manifest request path, so its latency is viewer
      start-up delay on the first break. Wrapper chains are the usual cause (MediaTailor
      follows up to 7 VAST wrapper levels)
    → FIX: reduce wrapper depth, or use prefetch to take the ADS call off the manifest path.
      TPS-based traffic shaping is a PREFETCH schedule feature, not a general latency control
IF manifests are stale:
  → Split the age: Origin.Age (time the origin held it) against
    GetManifest.MediaTailorAge (time MediaTailor held it). They sum to GetManifest.Age
  → Neither is a latency. Personalization latency is GetManifest.Latency
  → NOTE: GetManifest.MediaTailorAge rises with manifest reuse, which is normal and not a
    performance problem
IF origin request volume looks too high:
  → Compare Origin.Age SampleCount against the content origin's own access logs. Do NOT use
    the Requests metric as the denominator: it is concurrent transactions per second across
    all request types, so the ratio is meaningless
  → NOTE: Origin.Age is not emitted at all when the response came from a CDN, so a CDN in
    front of the origin removes the only MediaTailor-side view of this
  IF every player request produces an origin fetch:
    → CAUSE: something makes the origin URL unique per request, so no fetch is ever reused
    → FIX: make the origin URL stable across requests. Agents MUST NOT advise removing origin
      authentication to win cache reuse. On a MediaPackage v2 origin, protect it with SigV4 and
      grant mediatailor.amazonaws.com principal access plus mediapackagev2:GetObject, which
      keeps the URL stable and the origin protected
  → Otherwise see "Scaling for large events" in service-rules-mediatailor.md
IF manifest fetches fail with 403 after removing a CDN from the origin leg:
  → CAUSE: the origin policy still allows only the CDN principal
  → FIX: grant mediatailor.amazonaws.com access to the endpoint before cutting the CDN over
    (scope the grant with aws:SourceAccount/aws:SourceArn per the confused-deputy rule in
    service-rules-cloudfront.md)
```

## Targeting parameters not reaching the ad server

```
IF the ad server receives no parameters, or the wrong ones:
  → Check: adsRequestUrl on MAKING_ADS_REQUEST. Every [...] macro should be substituted
  IF a macro is still literal, or a parameter is empty:
    → CAUSE: unresolved macros become empty strings silently. No error, no skip reason, and
      the request is still sent
    → FIX: look for WARNING_URL_VARIABLE_SUBSTITUTION_FAILED, which carries adsRequestUrl.
      Confirm the syntax is square brackets: ${session.id} is NOT substituted
  IF the parameters are absent from the incoming request:
    → CAUSE: the CDN is not forwarding query strings, or the prefix is wrong for the entry
      point (manifest. on implicit init, manifestParams on explicit POST,
      manifestParams. on explicit GET)
    → FIX: forward all query strings on the manifest and session behaviours
  IF the ad server sees the CDN's user agent instead of the device:
    → FIX: forward User-Agent. MediaTailor proxies the player's user-agent and
      x-forwarded-for, but only if the CDN passes them through
```

## Log groups and how to join them

| Log group | Carries |
|---|---|
| `MediaTailor/AdDecisionServerInteractions` | break detection, ADS request and response, fill, skip reasons, beacons |
| `MediaTailor/TranscodeService` | creative conditioning lifecycle |
| `MediaTailor/ManifestService` | manifest generation and origin interaction |

- `sessionId` is the only precise join key across all three. `originId` is the playback configuration name and scopes a query to one configuration.
- Agents **MUST** scope every Insights query with `filter originId = '<config>'`; an unscoped query returns other configurations' records because the legacy log groups are account-wide.
- Vended logs SHOULD be preferred over legacy `LEGACY_CLOUDWATCH` delivery, which writes to those shared account-wide groups. `configure-logs-for-playback-configuration --percent-enabled` selects the legacy strategy.
- 100% session logging is a diagnostic setting, not a steady state. Log delivery is billed per GB and `RAW_ADS_RESPONSE` multiplies volume, so agents **SHOULD** turn it up to investigate and back down afterwards. For a reproducible fault, `?aws.logMode=DEBUG` on a single session is both cheaper and more certain than sampling.
- Event types can be excluded per request with `aws.adsInteractionLogExcludeEventTypes` and `aws.manifestServiceLogExcludeEventTypes`, which agents **SHOULD** use to keep a high-percentage investigation affordable.
- Agents **MUST NOT** reproduce the published Insights example queries. They filter on fields absent from the log schema (`skipReason`, `creativeId`, `adBreakIndex` do not exist; the field is `avail.skippedAds[].skippedReason`) and return zero rows.

### Queries that do return rows

Run these against `MediaTailor/AdDecisionServerInteractions`. Replace `<config>` with the playback
configuration name. Every one of them has been run against live records.

Where the funnel stops, for one configuration:

```
fields eventType
| filter originId = "<config>"
| filter eventType in ["AD_MARKER_FOUND","MAKING_ADS_REQUEST","VAST_RESPONSE",
    "EMPTY_VAST_RESPONSE","FILLED_AVAIL","BEACON_FIRED"]
| stats count() as events by eventType
| sort events desc
```

An empty ad response emits both `EMPTY_VAST_RESPONSE` and `VAST_RESPONSE`, so subtract the former from
the latter before reading the fill step.

Which skip reasons dominate:

```
fields avail.skippedAds.0.skippedReason, avail.skippedAds.0.creativeUniqueId
| filter originId = "<config>" and eventType = "FILLED_AVAIL"
| filter ispresent(avail.skippedAds.0.skippedReason)
| stats count() as skips by avail.skippedAds.0.skippedReason
| sort skips desc
```

Logs Insights indexes array members positionally, so this reads only the first skipped ad per event.
That is enough to rank causes, not to count them exactly.

One session end to end, in order, which is the query to run before escalating:

```
fields @timestamp, eventType, requestId, eventDescription
| filter sessionId = "<sessionId>"
| sort @timestamp asc
| limit 200
```

Sessions that planned an ad and fired no beacon:

```
fields sessionId
| filter originId = "<config>"
| filter eventType in ["FILLED_AVAIL","BEACON_FIRED"]
| fields (eventType = "FILLED_AVAIL") as isFill, (eventType = "BEACON_FIRED") as isBeacon
| stats sum(isFill) as fills, sum(isBeacon) as beacons by sessionId
| filter fills > 0 and beacons = 0
| sort fills desc
| limit 50
```

On server-side reporting that result is the population whose players never fetched the ad segments. A
`filter` after `stats` can reference the aggregate aliases, which is what makes the last lines work. If
`sum()` over a projected comparison returns empty, substitute `strcontains(eventType, "FILLED_AVAIL")`,
which is documented to return 1 or 0.

## Before opening a support case

Agents **SHOULD** gather all of the following, because a case without them will be sent back:

- the playback configuration name and Region
- the `sessionId` of a failing session, and the wall-clock time
- the full `GetPlaybackConfiguration` output
- the origin manifest fetched directly, and the personalized manifest for the same asset
- the ADS interaction log records for that session, and the transcode log records for the `creativeUniqueId`
- `RAW_ADS_RESPONSE` for the failing avail, if the fault is in the VAST

Before attaching any of the above to a support case or sharing it with ad ops, agents **MUST**
redact credentials and tokens from `AdDecisionServerUrl` and `adsRequestUrl` (ADS API keys and
auth tokens commonly ride in the query string), and **MUST** redact or truncate viewer identifiers
— IP addresses (`x-forwarded-for`), device/advertising IDs, and session-level targeting values —
from the ADS interaction log records and from `RAW_ADS_RESPONSE` (a third-party payload that can
embed tracking URLs with viewer identifiers). Agents **SHOULD** share the `sessionId` and timestamp
and let Support pull the raw records themselves rather than attaching them, where that is an option.

Escalate rather than guessing when the evidence points at `INTERNAL_ERROR`, `NO_MODEL_CREATIVE_MATCH`, or a manifest MediaTailor rejects with a 502 that a player can parse.
