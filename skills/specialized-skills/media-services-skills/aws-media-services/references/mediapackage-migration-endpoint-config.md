# Endpoint Configuration Planning

Plan how each v1 origin endpoint's configuration will translate to v2. Identify opportunities to merge endpoints, and present all suggestions to the user for approval before proceeding.

> **V1 SAFETY:** Only read commands are permitted for v1 resources. Use `describe-origin-endpoint` to get full configs — never modify v1 resources.
>
> **SUGGEST ONLY:** Do NOT write any files or execute any create/update commands during this phase. Present all suggestions and wait for explicit user confirmation before saving anything.
>
> **NO PROBE RESOURCES:** Do not create a v2 resource to check whether a value or a
> CLI flag is accepted. Use `aws mediapackagev2 create-origin-endpoint --generate-cli-skeleton`
> and `aws mediapackagev2 create-origin-endpoint help` to read the real field names,
> enum values, and numeric ranges from the installed API model.

---

## Contents

- [Step 1: Begin](#step-1-begin)
- [Step 2: Load Data](#step-2-load-data)
- [Step 3: Map Each Endpoint](#step-3-map-each-endpoint)
- [Container Type Mapping](#container-type-mapping)
- [Manifest names — stricter than v1, and unique per endpoint](#manifest-names--stricter-than-v1-and-unique-per-endpoint)
- [V2 value constraints](#v2-value-constraints)
- [Zero-handling — three fields, three different rules](#zero-handling--three-fields-three-different-rules)
- [HLS Endpoint Mapping (v1 `hlsPackage` → v2 `TS` container + HLS manifest)](#hls-endpoint-mapping-v1-hlspackage--v2-ts-container--hls-manifest)
- [DASH Endpoint Mapping (v1 `dashPackage` → v2 `CMAF` container + DASH manifest)](#dash-endpoint-mapping-v1-dashpackage--v2-cmaf-container--dash-manifest)
- [CMAF Endpoint Mapping (v1 `cmafPackage` → v2 `CMAF` container + HLS manifest)](#cmaf-endpoint-mapping-v1-cmafpackage--v2-cmaf-container--hls-manifest)
- [MSS Endpoint Mapping (v1 `mssPackage` → v2 `ISM` container + MSS manifest)](#mss-endpoint-mapping-v1-msspackage--v2-ism-container--mss-manifest)
- [DASH SCTE Configuration](#dash-scte-configuration)
- [Segment-Level SCTE Configuration](#segment-level-scte-configuration)
- [Encryption Mapping (SPEKE v1 → SPEKE v2)](#encryption-mapping-speke-v1--speke-v2)
- [Access control — v1's three fields become v2 policies](#access-control--v1s-three-fields-become-v2-policies)
- [CDN authorization (v1 `authorization` → v2 CDN auth)](#cdn-authorization-v1-authorization--v2-cdn-auth)
- [Origin Endpoint Policies](#origin-endpoint-policies)
- [Known Incompatibilities](#known-incompatibilities)
- [Step 4: Present Mapping Results](#step-4-present-mapping-results)
- [Step 5: Identify Endpoint Merge Opportunities](#step-5-identify-endpoint-merge-opportunities)
- [Step 6: Compile Incompatibility Summary](#step-6-compile-incompatibility-summary)
- [Step 6.5: Pre-flight Validation (run this before saving the plan)](#step-65-pre-flight-validation-run-this-before-saving-the-plan)
- [Step 7: Save Plan](#step-7-save-plan)
- [Step 8: Hand Off](#step-8-hand-off)

---

## Step 1: Begin

Work from the inventory and the confirmed channel-group plan. Treat all mappings and merges as suggestions until the user confirms (see SUGGEST ONLY above).

---

## Step 2: Load Data

Use (read from `.mediapackage-migration/` if written, otherwise from context):

- the discovery inventory (`v1-resource-inventory.json`) — full endpoint configs
- the channel-group plan (`migration-plan.json`) — channel group assignments from the previous stage

---

## Step 3: Map Each Endpoint

For each origin endpoint in the inventory, apply the mapping rules below based on its type. If the `fullConfig` in the inventory doesn't have enough detail, fetch it:

```
aws mediapackage describe-origin-endpoint --id <endpoint-id> --region <region>
```

---

## Container Type Mapping

This is the fundamental mapping — each v1 endpoint type maps to a specific v2 container type and manifest type:

| V1 Endpoint Type | V2 Container Type | V2 Manifest Type | Notes |
|---|---|---|---|
| HLS (`hlsPackage`) | `TS` | HLS manifest | TS segments, HLS playlist |
| DASH (`dashPackage`) | `CMAF` | DASH manifest | CMAF segments, DASH MPD |
| CMAF (`cmafPackage`) | `CMAF` | HLS manifest | CMAF segments, HLS playlist (v1 CMAF only produced HLS) |
| MSS (`mssPackage`) | `ISM` | MSS manifest | ISM segments, Smooth Streaming manifest |

---

## Manifest names — stricter than v1, and unique per endpoint

Every v2 manifest carries a `manifestName` that becomes a path segment in the
playback URL. The rules are tighter than v1's:

- **Allowed characters on create: `A-Z`, `a-z`, `0-9`, and `-` (hyphen) only**,
  1–256 characters. **No underscores. No dots.** v1 permitted both, so v1 names
  like `manifest_name` or `index.2` are **not portable** and must be rewritten
  (e.g. `manifest-name`, `index-2`).
- **Names must be unique within the origin endpoint.** v2 explicitly forbids
  reusing a name between an HLS and a low-latency HLS manifest, and requires MSS
  manifest names to be unique within the endpoint. Generate distinct names across
  every manifest on an endpoint regardless of type — it is always safe and avoids
  relying on how cross-type collisions happen to be enforced.
- **Always emit a value.** `manifestName` is required on every v2 create shape.
  Don't rely on the documented `index` default.

> ⚠️ **Merges almost always require a rename.** v1's endpoint-level
> `manifestName` defaulted to `index` in practice, so two v1 endpoints being merged
> commonly arrive with the *same* manifest name. Since v2 requires them to be
> unique within the merged endpoint, at least one must be renamed. Never emit two
> manifests named `index` on one endpoint. Propose names that describe what each
> manifest is (e.g. `index` + `index-dvrwin`, or `main` + `twin`) and get the
> user to approve them — these names are in the playback URL.

Note that the URI *separator* is a different setting: `uriSeparator` defaults to
`UNDERSCORE`, so underscores still appear in generated child-manifest and segment
URIs even though they are illegal in the manifest name itself.

---

## V2 value constraints

v1 published almost no numeric bounds; v2 publishes several. A perfectly legal v1
value can be **rejected** by v2, or worse, silently replaced by a v2 default. Check
each planned value against this table, and surface every clamp to the user as a
behavior change rather than fixing it quietly.

| V2 field | Valid range | What to do when the v1 value is outside it |
|---|---|---|
| `segment.segmentDurationSeconds` | 1–30 | Out of range is a blocker — ask the user |
| `*Manifests[].manifestWindowSeconds` | min 30; max is the account's applied live manifest length quota (`L-B20140A1`, default 900 = 15 min, adjustable) | v1 had no published minimum. Clamp a sub-30 value up to 30 and warn that the live manifest window changed. Above the applied maximum is a blocker: ask whether to request a quota increase before cutover or shorten the window — this is the sliding window of segments in the manifest, not DVR depth, which is `startoverWindowSeconds` |
| `startoverWindowSeconds` | 0–1209600 | See zero-handling below |
| `*Manifests[].programDateTimeIntervalSeconds` | 1–1209600 | See zero-handling below |
| `*Manifests[].filterConfiguration.timeDelaySeconds` | 0–1209600, **and smaller than the endpoint's `startoverWindowSeconds`** | See zero-handling below |
| `dashManifests[].minUpdatePeriodSeconds` | 1–3600 | Clamp and warn |
| `dashManifests[].minBufferTimeSeconds` | 0–3600 | Clamp and warn |
| `dashManifests[].suggestedPresentationDelaySeconds` | 0–3600 | Clamp and warn |
| `encryption.keyRotationIntervalSeconds` | 300–31536000 | See the encryption section |
| `encryption.constantInitializationVector` | exactly 32 hex chars | Reject anything else |
| Manifests per endpoint | 1–25 | A merge that would exceed 25 must be split |

Verify these against the installed API model rather than trusting this table alone:
`aws mediapackagev2 create-origin-endpoint help`.

---

## Zero-handling — three fields, three different rules

`0` means something different in each of these, and conflating them silently
changes playback behavior. Handle each explicitly.

### `startoverWindowSeconds` — `0` is valid, map it through

`startoverWindowSeconds` is an **endpoint-level** field. Map the v1 value
**directly** to v2, including the value `0`.

> **Validation rule:** `0` is a VALID value (`0` = no start-over / DVR window).
> Map `0` → `0`. Do NOT omit or set the field to null when the v1 value is `0` —
> omitting it makes MediaPackage v2 apply its **default of 900 seconds**, silently
> giving the endpoint a 15-minute DVR window that v1 did not have. Only omit
> `startoverWindowSeconds` when the v1 endpoint genuinely did not set it at all.
>
> ⚠️ **CLI landmine:** older AWS CLI versions reject
> `--startover-window-seconds 0` in *client-side* validation (their model still
> carries an old minimum of 60), even though the service accepts `0`. A local
> `ParamValidation` error on `--startover-window-seconds 0` means the user's CLI is
> one of them. Do NOT drop the flag to make the command run — that
> produces exactly the 900-second silent change described above. Upgrade the CLI,
> or generate SDK/CloudFormation output instead, and tell the user why.

### `programDateTimeIntervalSeconds` — `0` is invalid, omit it

v2's minimum is `1`, and v1 used `0` to mean "no PDT tags". Omitting the field in
v2 also means "no PDT tags", so **omit it entirely** when the v1 value is `0`.
Include it only when the value is ≥ 1.

> **`DATERANGE` ad markers:** v2 requires `programDateTimeIntervalSeconds` ≥ 1
> whenever `scteHls.adMarkerHls` is `DATERANGE` (EXT-X-DATERANGE tags are anchored
> to EXT-X-PROGRAM-DATE-TIME). v1 enforces the same constraint — it rejects
> `adMarkers: DATERANGE` with a PDT of `0` on both create and update — so a
> discovered `DATERANGE` endpoint always carries a PDT ≥ 1. Carry it through
> unchanged; the pre-flight check below exists only to catch a plan that dropped it.

### `timeDelaySeconds` — `0` means "unset", omit it

v1's `describe-origin-endpoint` returns `TimeDelaySeconds: 0` on endpoints that
never configured a time delay, rather than omitting the field. v2 accepts `0`, so
this will not error — but writing `TimeDelaySeconds: 0` into every manifest's
`filterConfiguration` adds meaningless configuration to every endpoint. **Treat a
v1 value of `0` as unset and omit it.** Map only positive values through.

Note this is the opposite of the `startoverWindowSeconds` rule. The difference is
that v2 has no default for `timeDelaySeconds` to fall back to, so omitting it
changes nothing — whereas omitting `startoverWindowSeconds` triggers a 900s default.

> **Time delay must be smaller than the start-over window.** v1 accepts a time
> delay with any start-over window — including `timeDelaySeconds: 30` with
> `startoverWindowSeconds: 0`. v2 rejects that: *"Filter's time delay seconds must be
> smaller than endpoint start over window"* (verified against both services). So a
> v1 endpoint with a time delay and a start-over window of `0` (or one shorter than
> the delay) cannot be copied as-is. Flag it and ask the user which to change:
> raise `startoverWindowSeconds` above the delay (this turns on a DVR window v1 did
> not have), or drop the time delay. Do not pick for them.
---

## HLS Endpoint Mapping (v1 `hlsPackage` → v2 `TS` container + HLS manifest)

| V1 Field | V2 Field | Mapping |
|---|---|---|
| `hlsPackage.segmentDurationSeconds` | `segment.segmentDurationSeconds` | Direct |
| `hlsPackage.playlistWindowSeconds` | `hlsManifests[].manifestWindowSeconds` | Clamp to ≥ 30, flag above the applied maximum — see "V2 value constraints" above |
| `hlsPackage.playlistType` | — | `EVENT`/`VOD` — note for user, v2 handles differently |
| `hlsPackage.adMarkers` | `hlsManifests[].scteHls.adMarkerHls` | See ad marker mapping below |
| `hlsPackage.includeIframeOnlyStream` | `segment.includeIframeOnlyStreams` | Direct (boolean) |
| `hlsPackage.useAudioRenditionGroup` | `segment.tsUseAudioRenditionGroup` | Direct (boolean) |
| `hlsPackage.programDateTimeIntervalSeconds` | `hlsManifests[].programDateTimeIntervalSeconds` | Omit when the v1 value is `0` (v2 minimum is 1) — see zero-handling above |
| `hlsPackage.encryption` | `segment.encryption` | See encryption mapping below |
| `hlsPackage.streamSelection.minVideoBitsPerSecond` | `hlsManifests[].filterConfiguration.manifestFilter` | Convert to manifest filter string |
| `hlsPackage.streamSelection.maxVideoBitsPerSecond` | `hlsManifests[].filterConfiguration.manifestFilter` | Convert to manifest filter string |
| `hlsPackage.streamSelection.streamOrder` | — | **No v2 equivalent.** Flag as an incompatibility — see below |
| `hlsPackage.includeDvbSubtitles` | `segment.tsIncludeDvbSubtitles` | Direct (boolean) |
| `hlsPackage.encryption.repeatExtXKey` | — | **No v2 equivalent.** Flag if `true` |
| `startoverWindowSeconds` | `startoverWindowSeconds` | Endpoint level — see zero-handling above |
| `timeDelaySeconds` | `hlsManifests[].filterConfiguration.timeDelaySeconds` | Manifest level in v2 — omit when v1 value is `0` |
| `manifestName` (endpoint level) | `hlsManifests[].manifestName` | Sanitize to `[a-zA-Z0-9-]+` — see "Manifest names" above |
| `authorization` | `CdnAuthConfiguration` + OriginEndpointPolicy | v2 CDN authorization. **Not a field copy** — see "CDN authorization" below for the four prerequisites |
| `Whitelist` | OriginEndpointPolicy with an `aws:SourceIp` condition | v2 has no endpoint-level IP allow-list field. Flag it, don't drop it — see "Access control" below |
| `Origination` | — | **No v2 equivalent.** `DENY` has no translation — see "Access control" below |

### Ad Marker Mapping

| V1 `adMarkers` | V2 `scteHls.adMarkerHls` |
|---|---|
| `NONE` | omit `scteHls` |
| `PASSTHROUGH` | `SCTE35_ENHANCED` — **not guaranteed 1:1**, see below |
| `SCTE35_ENHANCED` | `SCTE35_ENHANCED` |
| `DATERANGE` | `DATERANGE` — requires `programDateTimeIntervalSeconds` ≥ 1 on the same manifest; see zero-handling |

`PASSTHROUGH` → `SCTE35_ENHANCED` is the closest available value, but it is **not a
guaranteed 1:1 output match** — list it for the user to verify. In v1,
`PASSTHROUGH` copies the encoder's own ad-marker tags through as-is; `SCTE35_ENHANCED`
has MediaPackage generate its own (`EXT-X-CUE-OUT`, `EXT-X-CUE-OUT-CONT`,
`EXT-X-CUE-IN`, `EXT-OATCLS-SCTE35`, `EXT-X-ASSET`). Whether the manifest actually
changes depends on what the encoder emits today, so the user should check the
result against their player and any SSAI vendor before cutover.

### Stream Selection → Manifest Filter Mapping

V1 uses `streamSelection.minVideoBitsPerSecond` and `maxVideoBitsPerSecond` to filter renditions. In v2, this is done via the `manifestFilter` string on the manifest's `filterConfiguration`.

The v2 filter syntax uses a **colon** between key and value:

| Element | Syntax |
|---|---|
| Key → value separator | `:` (colon) |
| Range | `min-max` (both bounds mandatory, both inclusive) |
| Multiple filters | `;` (semicolon) — logical AND |
| Multiple values for one key | `,` (comma) — logical OR |

> ⚠️ **`video_bitrate=<min>-<max>` is wrong and will fail.** An `=` separator is
> rejected with `ValidationException` / `INVALID_MANIFEST_FILTER` at
> `request.<type>Manifests.N.member.filterConfiguration.manifestFilter`. The
> separator is a colon. This defect broke a real migration run — get it right.

**Example conversion:**

- V1: `streamSelection: { minVideoBitsPerSecond: 500000, maxVideoBitsPerSecond: 2000000 }`
- V2: `filterConfiguration.manifestFilter: "video_bitrate:500000-2000000"`

Both bounds are mandatory in a range, so when v1 sets only one side, supply the
other from the supported limits (`0` – `2147483647` for `video_bitrate`):

- Only `min` set: `"video_bitrate:500000-2147483647"`
- Only `max` set: `"video_bitrate:0-2000000"`

If neither is set, omit `manifestFilter`. Treat `0` the same as absent/unset for both
`minVideoBitsPerSecond` and `maxVideoBitsPerSecond`. Only build a filter when there is
at least one **positive integer** bound.

Do **not** URL-encode the value written into the API field. Percent-encoding
(`%3A`, `%3B`, `%2C`) is required only in a playback query string
(`?aws.manifestfilter=...`), not in `FilterConfiguration.ManifestFilter`.

Other supported filter keys, should the user want more than a bitrate ceiling:
`audio_bitrate`, `audio_channels`, `audio_codec` (`AACL`/`AACH`/`AC-3`/`EC-3`),
`audio_language`, `audio_sample_rate`, `subtitle_language`, `trickplay_height`,
`trickplay_type`, `video_bitrate`, `video_codec` (`H264`/`H265`/`AV1`),
`video_dynamic_range` (`dv`/`hdr10`/`hlg`/`sdr`), `video_framerate`, `video_height`.
Supported keys and values can grow, so before emitting a key or value outside the bitrate
case, confirm it in the current MediaPackage v2 manifest-filtering documentation.

### `streamSelection.streamOrder` has no v2 equivalent

V1's `streamSelection.streamOrder` (`ORIGINAL`, `VIDEO_BITRATE_ASCENDING`,
`VIDEO_BITRATE_DESCENDING`) controlled the order renditions appear in the manifest.
**v2 has no equivalent** — `filterConfiguration` selects which renditions appear, not
their order.

Treat a v1 `streamOrder` of `VIDEO_BITRATE_ASCENDING` or `VIDEO_BITRATE_DESCENDING`
as a **listed incompatibility**, not a field to drop silently. Flag it, explain that
rendition order in v2 manifests is not configurable, and ask the user whether any
player in their fleet depends on the ordering. `ORIGINAL` needs no action.

---

## DASH Endpoint Mapping (v1 `dashPackage` → v2 `CMAF` container + DASH manifest)

| V1 Field | V2 Field | Mapping |
|---|---|---|
| `dashPackage.segmentDurationSeconds` | `segment.segmentDurationSeconds` | Direct |
| `dashPackage.manifestWindowSeconds` | `dashManifests[].manifestWindowSeconds` | Clamp to ≥ 30, flag above the applied maximum — see "V2 value constraints" above |
| `dashPackage.minBufferTimeSeconds` | `dashManifests[].minBufferTimeSeconds` | Clamp to 0–3600 — see "V2 value constraints" above |
| `dashPackage.minUpdatePeriodSeconds` | `dashManifests[].minUpdatePeriodSeconds` | Clamp to 1–3600 — see "V2 value constraints" above |
| `dashPackage.profile` | `dashManifests[].profiles` | See DASH Profile Mapping below (HBBTV_1_5 and HYBRIDCAST have no v2 equivalent) |
| `dashPackage.periodTriggers` | `dashManifests[].periodTriggers` | **NOT a direct copy** — `ADS` → `AVAILS`; absent → `["NONE"]` (never omit). See below |
| `dashPackage.segmentTemplateFormat` | `dashManifests[].segmentTemplateFormat` | v2 supports **only** `NUMBER_WITH_TIMELINE`. See below |
| `dashPackage.manifestLayout` | `dashManifests[].compactness` | `FULL` → `NONE`, `COMPACT` → `STANDARD`. See below |
| `dashPackage.utcTiming` + `utcTimingUri` | `dashManifests[].utcTiming.timingMode` + `.timingSource` | Hyphens become underscores. See below |
| `dashPackage.suggestedPresentationDelaySeconds` | `dashManifests[].suggestedPresentationDelaySeconds` | Clamp to 0–3600 — see "V2 value constraints" above |
| `dashPackage.encryption` | `segment.encryption` | See encryption mapping; use `cmafEncryptionMethod` |
| `dashPackage.streamSelection` | `dashManifests[].filterConfiguration.manifestFilter` | Convert to manifest filter |
| `dashPackage.adsOnDeliveryRestrictions` | — | **No v2 equivalent.** See Known Incompatibilities |
| `startoverWindowSeconds` | `startoverWindowSeconds` | Endpoint level — see zero-handling above |
| `timeDelaySeconds` | `dashManifests[].filterConfiguration.timeDelaySeconds` | Manifest level in v2 — omit when v1 value is `0` |

### DASH Period Triggers Mapping

v1's `periodTriggers` accepted exactly one value, `ADS`. **`ADS` is not a valid v2
value** — passing it through fails validation.

| V1 `periodTriggers` | V2 `dashManifests[].periodTriggers` |
|---|---|
| `["ADS"]` | `["AVAILS"]` |
| absent / `[]` (single-period MPD) | **`["NONE"]` — do NOT omit** |

> ⚠️ **Omitting `periodTriggers` does not give you a single-period manifest.** When the
> field is omitted *or* sent as an empty list, the service applies a default of
> `["AVAILS","DRM_KEY_ROTATION","SOURCE_CHANGES","SOURCE_DISRUPTIONS"]` — verified
> against a live endpoint. A v1 DASH endpoint with no period triggers was emitting a
> single-period MPD; migrated with the field omitted, it silently becomes multi-period
> on every ad avail and source change, which some players (HbbTV-class especially) do
> not tolerate. Always send `["NONE"]` explicitly to preserve single-period behavior.

The full v2 enum is `AVAILS`, `DRM_KEY_ROTATION`, `SOURCE_CHANGES`,
`SOURCE_DISRUPTIONS`, `NONE` — all except `AVAILS` and `NONE` are v2-only
capabilities with no v1 counterpart. Do not add them unless the user asks.

### DASH Segment Template Format — a real capability gap

| V1 `segmentTemplateFormat` | V2 | Action |
|---|---|---|
| `NUMBER_WITH_TIMELINE` | `NUMBER_WITH_TIMELINE` | Direct |
| `NUMBER_WITH_DURATION` | — | **Not supported in v2.** Flag as an incompatibility |
| `TIME_WITH_TIMELINE` | — | **Not supported in v2.** Flag as an incompatibility |

`NUMBER_WITH_TIMELINE` is the only value v2 accepts. This is a **significant gap**
and must be made explicit to the user, not quietly normalized:

- Migrating from **`TIME_WITH_TIMELINE`** changes the segment URL structure — the
  `media` template variable changes from `$Time$` (a timestamp) to `$Number$` (a
  sequence number). Anything that pattern-matches segment URLs must be
  re-validated: CDN cache-key and path rules, tokenization or WAF rules keyed on
  the timestamp, log analysis, and any client that constructs URLs itself. CDN
  caches start cold.
- Migrating from **`NUMBER_WITH_DURATION`** keeps the URL shape but changes the
  manifest: v2 emits a full `SegmentTimeline` per `SegmentTemplate` and drops the
  `duration` attribute. Manifests get larger, and players that only implement
  duration-based arithmetic must now parse `SegmentTimeline`.

### DASH Manifest Layout → Compactness

| V1 `manifestLayout` | V2 `compactness` | Notes |
|---|---|---|
| `FULL` | `NONE` | Both put `SegmentTemplate` in every `Representation` |
| `COMPACT` | `STANDARD` | Both hoist duplicate elements to `AdaptationSet` level |
| `DRM_TOP_LEVEL_COMPACT` | — | **No v2 equivalent.** Flag for user review |

> ⚠️ **The default flipped between versions.** v1 defaulted to a full manifest; v2
> defaults to `STANDARD` (compacted). A v1 DASH endpoint that never set
> `manifestLayout` was emitting full manifests, and will emit *compacted* manifests
> in v2 unless you say otherwise. **Set `compactness` explicitly on every DASH
> manifest** rather than relying on the default — the MPD structure is
> playback-visible.

### DASH UTC Timing Mapping

| V1 `utcTiming` | V2 `utcTiming.timingMode` |
|---|---|
| `HTTP-HEAD` | `HTTP_HEAD` |
| `HTTP-ISO` | `HTTP_ISO` |
| `HTTP-XSDATE` | `HTTP_XSDATE` |
| `NONE` | omit the `utcTiming` object |
| — | `UTC_DIRECT` (v2-only, no v1 counterpart) |

v1 `utcTimingUri` → v2 `utcTiming.timingSource`. Supply `timingSource` for the three
`HTTP_*` modes; do not supply it with `UTC_DIRECT`.

Two things to know: v2 has no `NONE` value, so a v1 `NONE` becomes "omit the object"
— reasonable, but not a documented equivalence, so mention it. And **`UTC_DIRECT` is
incompatible with DVB-DASH**: an endpoint using `profiles: ["DVB_DASH"]` must use one
of the `HTTP_*` modes.

### DASH Profile Mapping

| V1 `profile` | V2 `dashManifests[].profiles` | Notes |
|---|---|---|
| `NONE` | omit | No profile needed |
| `DVB_DASH_2014` | `["DVB_DASH"]` | Only on a CMAF-input channel. On an HLS-input channel, omit the profile or hold the endpoint back |
| `HBBTV_1_5` | — | No v2 equivalent. Flag to user as incompatible. |
| `HYBRIDCAST` | — | No v2 equivalent. Flag to user as incompatible. |

**`drmSignaling`** (v2 only, no v1 equivalent): valid values are `INDIVIDUAL` and
`REFERENCED`. The service enforces two rules:

- Set it on every DASH manifest of an **encrypted** endpoint, and omit it on an
  **unencrypted** one. Either mismatch is rejected with
  `DRM_SIGNALING_MISMATCH_SEGMENT_ENCRYPTION_STATUS`.
- `REFERENCED` requires `compactness: STANDARD`. With `compactness: NONE` (the mapping for
  v1 `manifestLayout: FULL`) it is rejected with
  `INCOMPATIBLE_DASH_COMPACTNESS_CONFIGURATION`, so offer only `INDIVIDUAL` there, or flag
  the conflict if the user wants `REFERENCED`.

AWS does not document what `INDIVIDUAL` and `REFERENCED` actually do, so present them
as a choice for the user to make against their player fleet rather than recommending
one.

**`dvbSettings`** (v2 only): If the user enables the `DVB_DASH` profile, ask if they want to configure DVB-specific settings (`dvbSettings`), which include font download configuration and error metrics reporting. These have no v1 equivalent. Two DVB-DASH requirements to carry over: the manifest must not use `UTC_DIRECT` for UTC timing, and **`DVB_DASH` is only available on CMAF-input channels**. On an HLS-input channel the service rejects the profile with `INCOMPATIBLE_DASH_PROFILE_DVB_DASH_CONFIGURATION`. The input type is decided, and fixed, at the channel step (see "Confirm the Channel Input Type" in the channel-group stage), so a `DVB_DASH_2014` endpoint on an HLS-input channel must either drop the profile (as with `HBBTV_1_5`) or be held back.

---

## CMAF Endpoint Mapping (v1 `cmafPackage` → v2 `CMAF` container + HLS manifest)

V1 CMAF endpoints produce HLS manifests with fMP4 (CMAF) segments.

| V1 Field | V2 Field | Mapping |
|---|---|---|
| `cmafPackage.segmentDurationSeconds` | `segment.segmentDurationSeconds` | Direct |
| `cmafPackage.segmentPrefix` | `segment.segmentName` | Direct. Note v1 auto-defaults this to the channel ID when unset, so it is almost never empty. Sanitize to `[a-zA-Z0-9_-]+` |
| `cmafPackage.hlsManifests[]` | `hlsManifests[]` | One v2 HLS manifest per v1 HLS manifest entry |
| `cmafPackage.hlsManifests[].playlistWindowSeconds` | `hlsManifests[].manifestWindowSeconds` | Clamp to ≥ 30, flag above the applied maximum — see "V2 value constraints" above |
| `cmafPackage.hlsManifests[].adMarkers` | `hlsManifests[].scteHls.adMarkerHls` | Same ad marker mapping as HLS |
| `cmafPackage.hlsManifests[].includeIframeOnlyStream` | `segment.includeIframeOnlyStreams` | Per-manifest in v1, endpoint-level in v2. Direct when every v1 HLS manifest on the endpoint has the same value. If they differ, one v2 endpoint cannot reproduce it: flag it and ask whether to enable I-frame streams for all manifests, disable them for all, or split the manifests across separate v2 endpoints |
| `cmafPackage.hlsManifests[].programDateTimeIntervalSeconds` | `hlsManifests[].programDateTimeIntervalSeconds` | Omit when the v1 value is `0` (v2 minimum is 1) — see zero-handling above |
| `cmafPackage.encryption` | `segment.encryption` | See encryption mapping; use `cmafEncryptionMethod` |
| `cmafPackage.streamSelection` | `hlsManifests[].filterConfiguration.manifestFilter` | Convert to manifest filter |
| `startoverWindowSeconds` | `startoverWindowSeconds` | Endpoint level — see zero-handling above |
| `timeDelaySeconds` | `hlsManifests[].filterConfiguration.timeDelaySeconds` | Manifest level in v2 — omit when v1 value is `0` |

---

## MSS Endpoint Mapping (v1 `mssPackage` → v2 `ISM` container + MSS manifest)

| V1 Field | V2 Field | Mapping |
|---|---|---|
| `mssPackage.segmentDurationSeconds` | `segment.segmentDurationSeconds` | Direct |
| `mssPackage.manifestWindowSeconds` | `mssManifests[].manifestWindowSeconds` | Clamp to ≥ 30, flag above the applied maximum — see "V2 value constraints" above |
| `mssPackage.encryption` | `segment.encryption` | See encryption mapping; use `ismEncryptionMethod` |
| `mssPackage.streamSelection` | `mssManifests[].filterConfiguration.manifestFilter` | Convert to manifest filter |
| `startoverWindowSeconds` | `startoverWindowSeconds` | Endpoint level — see zero-handling above |
| `timeDelaySeconds` | `mssManifests[].filterConfiguration.timeDelaySeconds` | Manifest level in v2 — omit when v1 value is `0` |

---

## DASH SCTE Configuration

These apply to any endpoint that produces a DASH manifest:

| V1 DASH Field | V2 Field | Notes |
|---|---|---|
| `dashPackage.periodTriggers` | `dashManifests[].periodTriggers` | `ADS` → `AVAILS`; none → `["NONE"]` (see DASH Period Triggers Mapping above) |
| *(no v1 equivalent)* | `dashManifests[].scteDash.adMarkerDash` | `BINARY` or `XML` — omit unless user specifies |

---

## Segment-Level SCTE Configuration

These apply at the segment level and are shared across all manifests on the endpoint, regardless of endpoint type (HLS, DASH, CMAF, or MSS):

| V1 Field | V2 Field | Notes |
|---|---|---|
| `adTriggers` (on any v1 endpoint) | `segment.scte.scteFilter` | Map SCTE-35 message types directly |
| v1 `PASSTHROUGH` ad marker mode | `segment.scte.scteInSegments: "ALL"` | Preserves binary SCTE-35 data in segments |
| v1 `SCTE35_ENHANCED` ad marker mode | `segment.scte.scteInSegments: "NONE"` | Enhanced markers are manifest-level only (verify against v2 API docs) |
| v1 `NONE` or `DATERANGE` ad marker mode | `segment.scte.scteInSegments: "NONE"` | No binary SCTE-35 in segments |

Note: MSS manifests have no SCTE manifest-level configuration in v2.

---

## Encryption Mapping (SPEKE v1 → SPEKE v2)

| V1 Field | V2 Field | Notes |
|---|---|---|
| `spekeKeyProvider.url` | `encryption.spekeKeyProvider.url` | Direct |
| `spekeKeyProvider.roleArn` | `encryption.spekeKeyProvider.roleArn` | Direct |
| `spekeKeyProvider.resourceId` | `encryption.spekeKeyProvider.resourceId` | Direct |
| `spekeKeyProvider.systemIds` | `encryption.spekeKeyProvider.drmSystems` | UUID → enum, then validate against the compatibility matrix below |
| `spekeKeyProvider.certificateArn` | `encryption.spekeKeyProvider.certificateArn` | Direct |
| `encryptionMethod` | `encryption.encryptionMethod.tsEncryptionMethod` / `cmafEncryptionMethod` / `ismEncryptionMethod` | **Do not copy verbatim** — see below |
| `constantInitializationVector` | `encryption.constantInitializationVector` | Direct (exactly 32 hex chars). Not supported on ISM |
| `keyRotationIntervalSeconds` | `encryption.keyRotationIntervalSeconds` | **Do not copy verbatim** — see key rotation below |

In v2, `encryption` requires **both** `encryptionMethod` and `spekeKeyProvider`, and
`spekeKeyProvider` requires all of `encryptionContractConfiguration`, `resourceId`,
`drmSystems`, `roleArn`, and `url`. There are no optional halves.

### DRM System ID Mapping

| SPEKE System ID | V2 `drmSystems` Value |
|---|---|
| `edef8ba9-79d6-4ace-a3c8-27dcd51d21ed` | `WIDEVINE` |
| `9a04f079-9840-4286-ab92-e65be0885f95` | `PLAYREADY` |
| `94ce86fb-07ff-4f43-adb8-93d2fa968ca2` | `FAIRPLAY` |
| `80a6be7e-1448-4c37-9e70-d5aebe04c8d2` | `IRDETO` |
| `3ea8778f-7742-4bf9-b18b-e834b2acbd47` | `CLEAR_KEY_AES_128` |

`drmSystems` accepts 1–4 values. A UUID that isn't in this table has no v2 mapping —
flag it rather than guessing.

### Encryption method must be derived from the DRM system, not copied

> ⚠️ **This is a real migration defect, not a theoretical one.** A v1 HLS endpoint
> with a FairPlay system ID and v1's default `encryptionMethod: AES_128` is an
> **unsupported v2 configuration**. FairPlay on a TS container requires
> `SAMPLE_AES`; `AES_128` is valid only with Clear Key AES-128. Copying the v1 value
> through produces either a create-time failure or unplayable DRM output. The same
> class of problem exists on every container type, so always cross-check the pair.

**Valid combinations per container type:**

| V2 Container | Encryption method | Compatible `drmSystems` |
|---|---|---|
| `TS` | `SAMPLE_AES` | `FAIRPLAY` only |
| `TS` | `AES_128` | `CLEAR_KEY_AES_128` only |
| `CMAF` | `CENC` | `WIDEVINE`, `PLAYREADY`, `IRDETO` |
| `CMAF` | `CBCS` | `WIDEVINE`, `PLAYREADY`, `FAIRPLAY` |
| `ISM` | `CENC` | `PLAYREADY` only |

Read the other direction when a v1 endpoint has several system IDs — the whole set
must fit one method. Widevine + FairPlay on CMAF forces `CBCS`; adding Irdeto to that
set has no valid v2 configuration and is a blocker to raise with the user.

DRM support can change as the service adds systems. Before treating a combination as a
blocker, confirm it against the current API model (`aws mediapackagev2 create-origin-endpoint help`,
under `EncryptionMethod` and `DrmSystems`) or the MediaPackage v2 DRM documentation.

**Mapping the v1 method value:**

| V1 container | V1 `encryptionMethod` | Proposed v2 value |
|---|---|---|
| HLS (→ TS) | `AES_128` | `AES_128` — **only if** the DRM system is Clear Key AES-128; if FairPlay, this must become `SAMPLE_AES` |
| HLS (→ TS) | `SAMPLE_AES` | `SAMPLE_AES` |
| CMAF (→ CMAF) | `AES_CTR` | `CENC` |
| CMAF (→ CMAF) | `SAMPLE_AES` | `CBCS` |
| DASH (→ CMAF) | *(none — v1 DASH had no method field and used common encryption)* | `CENC` |
| MSS (→ ISM) | *(none — v1 MSS had no method field)* | `CENC` |

AWS does not publish a v1→v2 mapping for the CMAF values, so the `AES_CTR` → `CENC`
and `SAMPLE_AES` → `CBCS` rows are this workflow's proposal, not documented guidance.
Because the choice decides which DRM systems remain legal, **present it to the
user for confirmation instead of applying it silently.**

### Key rotation

v2's range is **300–31536000**. v1's default was **60** and it accepted `0` to mean
"disabled", so most v1 endpoints need a decision here:

| V1 `keyRotationIntervalSeconds` | V2 | Tell the user |
|---|---|---|
| `0` | omit the field | v1 used `0` to disable rotation; `0` is out of range in v2, and omitting means no rotation |
| `1`–`299` (including the implicit v1 default of 60) | `300` | Rotation gets **slower**. This is a behavior change — get it acknowledged, don't just clamp |
| `≥ 300` | same value | Direct |
| any value, ISM container | omit the field | MSS/ISM does not support key rotation at all |

One nuance worth raising: v1 required `keyRotationIntervalSeconds: 0` on endpoints
using SPEKE v2 presets. v2 has no such restriction, so a v1 SPEKE-v2 endpoint pinned
at `0` was not necessarily *choosing* no rotation — ask whether they want rotation
enabled now that it is allowed.

### SPEKE v2 Requirement

MediaPackage v2 supports only SPEKE v2. If a v1 endpoint uses SPEKE v1 encryption, flag this to the user:

> Your v1 endpoint uses SPEKE v1 encryption. MediaPackage v2 requires SPEKE v2. You will need to ensure your SPEKE key provider server is SPEKE v2 compliant before migrating encryption.
>
> Additionally, v2 requires an `EncryptionContractConfiguration` with `presetSpeke20Audio` and `presetSpeke20Video` values. These define how content keys are distributed across audio and video tracks.

`EncryptionContractConfiguration` is required on **every** encrypted v2 endpoint, not
only on ones migrating from SPEKE v1. A v1 endpoint that already used SPEKE v2 has one
to carry over — but note the values are spelled differently:

> ⚠️ **v1 used hyphens, v2 uses underscores.** v1: `PRESET-AUDIO-1`, `PRESET-VIDEO-1`.
> v2: `PRESET_AUDIO_1`, `PRESET_VIDEO_1`. Rewrite the separators when carrying a
> contract across. (AWS's own v2 docs still write the presets with hyphens in prose
> while the valid-values list uses underscores — the underscore form is the wire
> contract.)

For an endpoint migrating **from SPEKE v1**, there is no contract to copy. SPEKE v1
used a single key for all tracks, and `SHARED` + `SHARED` reproduces that behavior —
suggest it as the faithful translation, and offer per-track-type keys as an upgrade.

Ask the user to provide:

- **presetSpeke20Audio**: `PRESET_AUDIO_1` (one key for all audio — most common), `PRESET_AUDIO_2`, `PRESET_AUDIO_3`, `SHARED`, or `UNENCRYPTED`
- **presetSpeke20Video**: `PRESET_VIDEO_1` (one key for all video — most common), `PRESET_VIDEO_2` through `PRESET_VIDEO_8`, `SHARED`, or `UNENCRYPTED`

Preset values can be added over time. Confirm the current list in `aws mediapackagev2
create-origin-endpoint help`, under `EncryptionContractConfiguration`.

**Constraints:**

- If either preset is `SHARED`, both must be `SHARED`
- Both cannot be `UNENCRYPTED`; `UNENCRYPTED` may pair only with a numbered preset on
  the other axis, never with `SHARED`
- If the container type is `ISM`, both presets MUST be `SHARED` (MSS uses the same DRM
  information across video, audio and subtitle segments)

- On an encrypted `TS` container with `tsUseAudioRenditionGroup: false`, both presets
  MUST be `SHARED` (audio is muxed into the video segments). The service rejects any
  other preset with `ENCRYPTION_CONTRACT_WITHOUT_AUDIO_RENDITION_INCOMPATIBLE`. v1
  `useAudioRenditionGroup` defaults to `false`, so most encrypted v1 HLS endpoints land
  here: propose `SHARED` + `SHARED` for them, not `PRESET_AUDIO_1` / `PRESET_VIDEO_1`.

### MSS / ISM encryption limits

MSS content supports **PlayReady only**, with `ismEncryptionMethod: CENC`, both presets
`SHARED`, and **no key rotation and no constant IV**. Do not emit
`keyRotationIntervalSeconds` or `constantInitializationVector` on an ISM endpoint.

---

## Access control — v1's three fields become v2 policies

v1 controlled endpoint access with three endpoint fields: `Whitelist` (IP allow-list),
`Authorization` (CDN auth), and `Origination` (ALLOW/DENY). v2 has none of them. Access
is controlled by an **origin endpoint policy**, attached with
`put-origin-endpoint-policy` after the endpoint exists.

> ⚠️ **The default is not "public".** An endpoint with no policy is reachable only by
> callers presenting this account's credentials — there is no anonymous playback. A v1
> endpoint that served the open internet will **stop working for its viewers** in v2
> until an explicit policy is attached. Never let this be discovered at playback time,
> and never make an endpoint public unless the user asks for it.

Ask what access model each endpoint needs:

1. **Public** — attach a public policy allowing `mediapackagev2:GetObject` to `"*"`.
   This is the only option that reproduces a v1 endpoint with no access controls.
2. **CloudFront origin access control (OAC)** — a policy granting
   `cloudfront.amazonaws.com` the `mediapackagev2:GetObject` and
   `mediapackagev2:GetHeadObject` actions, conditioned on `AWS:SourceArn` matching the
   distribution ARN. Use when the user wants the endpoint reachable only through
   their CloudFront distribution.
3. **IP range restriction** — a policy with an `aws:SourceIp` condition. This is where
   a v1 `Whitelist` goes; there is no endpoint-level IP allow-list field in v2, so
   translate it into policy conditions rather than dropping it.
4. **CDN authorization** — the direct equivalent of v1 `Authorization`. See below.
5. **IAM/SigV4** — leave the endpoint with no policy; only account credentials work.

`v1 Origination: DENY` has **no v2 equivalent** — there is no origination toggle.
Flag it and ask what the endpoint was for: if it existed only to harvest live-to-VOD
content (the usual reason for `DENY`), v2 has first-class harvest jobs and the endpoint
may not need to exist at all. `ForceEndpointErrorConfiguration` is *not* a substitute —
it is for CDN-driven failover, not for switching an endpoint off.

---

## CDN authorization (v1 `authorization` → v2 CDN auth)

This is the migration path most likely to fail at execution time, because v2 changes
**four** things and none of them are field copies. Identify all four during
**planning**, not during execution.

v1 stored `authorization: { cdnIdentifierSecret, secretsRoleArn }` on the endpoint. In
v2, CDN auth is two coupled things sent in a single `put-origin-endpoint-policy` call:
a `CdnAuthConfiguration` (`cdnIdentifierSecretArns` — a list, minimum 1 —
plus `secretsRoleArn`) **and** an endpoint policy whose `Bool` condition on
`mediapackagev2:RequestHasMatchingCdnAuthHeader` is what actually enforces it. Setting
the configuration without the matching policy condition enforces nothing.

**The four prerequisites — all must be resolved before execution:**

1. **The secret key name changed.** v2 requires the Secrets Manager secret to hold a
   key named exactly **`MediaPackageV2CDNIdentifier`**. v1 secrets are keyed
   `MediaPackageCDNIdentifier`. **An existing v1 secret cannot be reused as-is** — it
   needs the v2 key added, or a new secret. The secret must be in the **same account
   and Region** as the endpoint (no cross-account or cross-Region sharing), and the
   value must be 8–256 characters (UUIDv4 recommended).
2. **The IAM role trust policy changed.** v2 assumes the role as
   **`mediapackagev2.amazonaws.com`**; a v1 role trusts `mediapackage.amazonaws.com`.
   Reusing the v1 role **requires editing its trust policy** — otherwise v2 cannot
   fetch the secret and playback fails. In an opt-in Region, the Region-qualified
   principal (e.g. `mediapackagev2.ap-southeast-4.amazonaws.com`) must be listed too.
3. **The role's permissions changed.** v2 needs
   `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` scoped to the
   secret ARN, **plus `secretsmanager:BatchGetSecretValue` on `"Resource": "*"`** —
   that action does not accept a resource scope, so it belongs in its own statement.
   Customer-managed KMS keys also need `kms:Decrypt` and `kms:DescribeKey`. A v1
   policy carried over is both over-permissioned (v1 used `ListSecrets` /
   `ListSecretVersionIds` and `iam:GetRole`/`PassRole`) and missing
   `BatchGetSecretValue`, so it will not work.
4. **The CDN header name changed.** v1 used `X-MediaPackage-CDNIdentifier`; v2 uses
   **`X-MediaPackageV2-CDNIdentifier`**. The user must update the custom origin
   header in their CDN distribution. This is outside MediaPackage, so it will not
   appear in any generated script — call it out as a user action.

Also note: `--cdn-auth-configuration` needs a recent AWS CLI; confirm with
`aws mediapackagev2 put-origin-endpoint-policy help` (the flag is listed only if
supported). And
`put-origin-endpoint-policy` is a *replace*, not a merge — always send the policy and
the CDN auth configuration together, or a later policy update will drop the auth
configuration.

For rotation, the documented order is: update the secret first, wait 5 minutes for
MediaPackage's cache to pick it up (both old and new values are accepted during the
overlap), then update the CDN header value.

---

## Origin Endpoint Policies

Attach policies with `put-origin-endpoint-policy` **after** the endpoint exists. For
CDN-auth endpoints, send `--cdn-auth-configuration` in the same call.

A CDN-auth policy looks like this — note that the principal is `"*"` and the
*condition* is what restricts access, so do not "harden" it by narrowing the
principal:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowGetObjectAccessForAuthorizedRequest",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "mediapackagev2:GetObject",
      "Resource": "arn:aws:mediapackagev2:<region>:<account>:channelGroup/<cg>/channel/<ch>/originEndpoint/<oe>",
      "Condition": {
        "Bool": {
          "mediapackagev2:RequestHasMatchingCdnAuthHeader": "true"
        }
      }
    }
  ]
}
```

The condition value is the **string** `"true"`, not a JSON boolean.

### Channel policies

v2 also has channel policies (`put-channel-policy`), which govern **ingest** rather
than playback. v1 had no equivalent. A channel policy is not required when the
encoder is in the same account (e.g. MediaLive in-account) — the channel is active and
ingesting as soon as it is created. Ask whether content is pushed from another
account; if so, a channel policy granting `mediapackagev2:PutObject` is needed.
Scope that grant tightly: name the specific IAM role the encoder in the other
account uses as the `Principal` (not that account's root, and never `"*"`), and set
`Resource` to the one channel's ARN. If the grant is to a service principal rather
than an IAM role, add `aws:SourceAccount` (the encoder's account) and, where the
caller's ARN is known, `aws:SourceArn` conditions so no other account can use it.

Don't skip this question just because v1 had nothing to migrate here.

---

## Known Incompatibilities

When you encounter these, explain the incompatibility to the user and ask how to proceed. **Never drop one silently** — a dropped setting is a behavior change the user finds out about in production.

| V1 Feature | V2 Status | Recommended Action |
|---|---|---|
| DASH `profile: HBBTV_1_5` | Not supported (v2 `profiles` accepts only `DVB_DASH`) | Ask: omit the profile, use `DVB_DASH`, or hold the endpoint back |
| DASH `profile: HYBRIDCAST` | Not supported (same reason) | Same as above |
| DASH `segmentTemplateFormat: NUMBER_WITH_DURATION` | Not supported (v2 is `NUMBER_WITH_TIMELINE` only) | Explain the manifest-structure change and get it acknowledged |
| DASH `segmentTemplateFormat: TIME_WITH_TIMELINE` | Not supported (same reason) | Explain the **segment URL structure change** (`$Time$` → `$Number$`) and the CDN/tokenization re-validation it forces |
| DASH `manifestLayout: DRM_TOP_LEVEL_COMPACT` | No v2 equivalent (v2 `compactness` is `STANDARD`/`NONE`) | Flag for review; validate DRM signaling in the migrated manifest against the player fleet |
| DASH `utcTiming: NONE` | No v2 `NONE` value | Omit the `utcTiming` object; mention that this is an inferred equivalence |
| `streamSelection.streamOrder` (ascending/descending) | No v2 equivalent | Flag it. Rendition order is not configurable in v2 |
| `adsOnDeliveryRestrictions` | Not supported in v2 | Note as a limitation; v2's `segment.scte.scteFilter` is the nearest control. See the note below |
| `adTriggers` (specific SCTE-35 triggers) | Simplified in v2 | Map to v2 `segment.scte.scteFilter` — format differs from v1 |
| `Origination: DENY` | No v2 equivalent | Ask what the endpoint is for; v2 harvest jobs may remove the need for it |
| `Whitelist` (IP allow-list) | No endpoint field; policy-only | Translate to an endpoint policy with an `aws:SourceIp` condition |
| `authorization` (CDN auth) | Supported, but with four changed prerequisites | See "CDN authorization" above — secret key name, role trust, role permissions, CDN header name |
| SPEKE v1 | Not supported (v2 is SPEKE v2 only) | Key provider must be SPEKE v2 compliant; synthesize an `encryptionContractConfiguration` |
| `keyRotationIntervalSeconds` < 300 | Below v2 minimum | Raise to 300 (a behavior change) or omit to disable rotation |
| `encryptionMethod: AES_128` with a FairPlay system ID | Unsupported combination | Change the method to `SAMPLE_AES`; do not carry `AES_128` over |
| `playlistType: EVENT` / `VOD` | No v2 equivalent | Note for the user; v2 handles playlist type differently |
| `repeatExtXKey` | No v2 equivalent | Flag if `true` |
| manifest names containing `_` or `.` | Illegal in v2 manifest names | Rename — see "Manifest names" above |

A note on `adsOnDeliveryRestrictions`: v1 populates it (commonly `RESTRICTED`) by
default on most endpoints, so it will show up on nearly everything and can look like
noise. Report it as faithful discovery — it is genuinely set on the v1 endpoint — but
say plainly that it is a v1 default rather than an intentional configuration, so the
user isn't alarmed by a long list.

For each incompatibility, ask the user:

1. **Skip** — omit this setting from the v2 config
2. **Alternative** — use the recommended alternative
3. **Pause** — stop migration for this endpoint and come back to it later

---

## Step 4: Present Mapping Results

For each channel, show:

1. The v1 endpoint and its type
2. The proposed v2 configuration (container type, manifest type, key settings)
3. Any non-trivial mapping decisions with explanations
4. Any incompatibilities found

Example:
> **Channel: example-sports-football**
>
> | V1 Endpoint | Type | V2 Container | V2 Manifest | Notes |
> |---|---|---|---|---|
> | football-hls | HLS | TS | HLS | Direct mapping, 6s segments |
> | football-dash | DASH | CMAF | DASH | Direct mapping, 6s segments |
>
> ⚠️ `football-hls` has `timeDelaySeconds: 30` — mapped to `filterConfiguration.timeDelaySeconds: 30` on the HLS manifest.
>
> ⚠️ `football-hls` has CDN authorization configured. v2 supports this, but it needs four prerequisites first: a Secrets Manager secret keyed `MediaPackageV2CDNIdentifier` (your v1 secret uses the old key name), the IAM role's trust policy extended to `mediapackagev2.amazonaws.com`, `secretsmanager:BatchGetSecretValue` added to that role, and your CDN's custom origin header renamed to `X-MediaPackageV2-CDNIdentifier`. **Migrate to v2 CDN auth, switch to CloudFront OAC, or hold this endpoint back?**

**Wait for the user to review and confirm each channel's endpoint plan before proceeding.**

---

## Step 5: Identify Endpoint Merge Opportunities

After mapping all endpoints, look for opportunities to merge multiple v1 endpoints into a single v2 origin endpoint with multiple manifests. This is possible because v2 endpoints support multiple manifest types on the same endpoint.

### Merge Rules

Two or more v1 endpoints on the **same channel** can be merged into a single v2 origin endpoint if and only if:

1. **They map to the same v2 container type.** For example:
   - DASH (`CMAF`) + CMAF (`CMAF`) → can merge (both are CMAF container)
   - HLS (`TS`) + HLS (`TS`) → can merge (both are TS container)
   - HLS (`TS`) + DASH (`CMAF`) → **cannot merge** (different container types)
   - MSS (`ISM`) + anything else → **cannot merge** (ISM only pairs with ISM)

2. **The endpoint-level and segment-level settings that cannot vary per manifest must
   match exactly:**
   - `segmentDurationSeconds` must be identical
   - `startoverWindowSeconds` must be identical (endpoint-level in v2, cannot differ per manifest)
   - Encryption settings must be identical (same SPEKE URL, role ARN, resource ID, DRM systems, encryption method, contract presets) — or both must have no encryption
   - SCTE/ad marker **segment-level** settings must match (`segment.scte`)
   - `includeIframeOnlyStreams` must match
   - `tsUseAudioRenditionGroup` must match (for TS containers)
   - `tsIncludeDvbSubtitles` must match (for TS containers)

3. **They are on the same v1 channel** (and therefore the same v2 channel).

4. **They need the same access control.** Endpoint policies are per *endpoint* in v2,
   not per manifest, so a merged endpoint has exactly one access model. Two v1
   endpoints where one is public and the other has a `Whitelist` (IP allow-list) or `Authorization`
   cannot be merged without forcing one model onto both. Treat differing access
   control as a merge blocker, and tell the user they can merge anyway if they
   accept a single policy for both.

Settings that live **per manifest** in v2 may differ freely and are not merge
blockers — `manifestWindowSeconds`, `programDateTimeIntervalSeconds`, per-manifest
SCTE (`scteHls`/`scteDash`), and `filterConfiguration` (`manifestFilter`,
`timeDelaySeconds`). Two HLS endpoints differing only in playlist window are a clean
merge into one endpoint with two manifests.

#### `segmentName` is chosen, not matched

`segment.segmentName` (v2) is a single endpoint-level value, so a merged endpoint has
exactly one. Do **not** treat it as a field that must already match — that would make
the DASH + CMAF merge impossible, because v1 `CmafPackage.SegmentPrefix` defaults to
the channel ID while v1 DASH has no equivalent field at all, so the two can never be
equal.

Instead, **pick one value and confirm it with the user**: carry the v1 CMAF
`segmentPrefix` over when exactly one source endpoint has one, and otherwise propose a
name. Note that `segmentName` appears in segment URLs, so changing it invalidates CDN
cache entries for that endpoint.

#### Manifest names must be made unique

Merged endpoints almost always arrive with **colliding manifest names**, because v1's
endpoint-level `manifestName` was commonly left at `index` on every endpoint. v2
requires manifest names to be unique within the endpoint, so at least one side must be
renamed as part of the merge.

Propose names that say what each manifest is, and include them in the merge suggestion
so the user approves them explicitly — they end up in the playback URL. Also check
the merged endpoint stays within **25 manifests**.

### What Gets Merged

When endpoints merge, the **segment configuration is shared** (since it's identical), and each v1 endpoint contributes its **manifest configuration** to the merged v2 endpoint:

- DASH v1 endpoint → contributes a `dashManifests[]` entry
- CMAF v1 endpoint → contributes an `hlsManifests[]` entry
- HLS v1 endpoint → contributes an `hlsManifests[]` entry
- MSS v1 endpoint → contributes an `mssManifests[]` entry

### How to Present Merge Suggestions

For each channel, after showing the individual endpoint mappings, check for merge opportunities and suggest them:

> **Merge opportunity on channel example-sports-football:**
>
> I noticed `football-dash` (DASH → CMAF) and `football-cmaf` (CMAF → CMAF) both map to the CMAF container type and have identical segment configs (6s segments, no encryption, same SCTE settings).
>
> These can be merged into a **single v2 origin endpoint** with 2 manifests:
>
> - Endpoint name: `football-cmaf-combined` (or suggest a name)
> - Container: `CMAF`
> - Manifests: 1 DASH manifest + 1 HLS manifest
> - Shared segment config: 6s duration, no encryption
> - ⚠️ Both v1 endpoints use the manifest name `index`, which v2 won't allow on one
>   endpoint. I'd name them `index` (DASH) and `index-hls` (HLS) — these appear in the
>   playback URL, so tell me if you'd prefer different names.
> - ⚠️ `segment.segmentName` is one value per endpoint. I'd carry over
>   `football-cmaf`'s v1 segment prefix. Note this changes segment URLs for the DASH
>   side, so CDN caches for it start cold.
>
> This reduces your endpoint count from 2 to 1 for this channel.
>
> **Would you like to merge these, or keep them as separate endpoints?**

If no merge opportunities exist for a channel, say so:
> No merge opportunities for this channel — all endpoints have different container types or different segment configs.

**Always wait for explicit user confirmation before applying any merge.**

---

## Step 6: Compile Incompatibility Summary

Before proceeding, present a summary of all incompatibilities and their resolutions:

> **Incompatibility Summary:**
>
> - 2 endpoints with CDN authorization → migrating to v2 CDN auth
> - 1 endpoint with an IP allowlist → mapped to an endpoint policy with an `aws:SourceIp` condition
> - 1 DASH endpoint with `HBBTV_1_5` → profile omitted (your decision)
> - 3 endpoints with key rotation below 300s → raised to 300s (rotation will be slower)
>
> **Prerequisites you'll need to complete before execution:**
>
> - Create a Secrets Manager secret keyed `MediaPackageV2CDNIdentifier` in us-west-2
> - Add `mediapackagev2.amazonaws.com` to the trust policy on `arn:aws:iam::...:role/cdn-auth-role`
> - Add `secretsmanager:BatchGetSecretValue` to that role
> - Rename the custom origin header in your CloudFront distribution to `X-MediaPackageV2-CDNIdentifier`
>
> All incompatibilities resolved. Ready to save the endpoint configuration plan?

**Wait for user confirmation before saving.**

---

## Step 6.5: Pre-flight Validation (run this before saving the plan)

Every item below has caused a real create-time failure. Walk the whole list against
each planned endpoint **now** — a validation error found here costs a sentence; the
same error found during execution leaves a half-migrated account.

**Names**

- [ ] Channel group / channel / endpoint names match `[a-zA-Z0-9_-]+`
- [ ] Manifest names match `[a-zA-Z0-9-]+` — no `_`, no `.`
- [ ] Manifest names are unique within each endpoint
- [ ] Every manifest has an explicit name

**Numeric ranges** (see "V2 value constraints" above)

- [ ] `segmentDurationSeconds` 1–30
- [ ] no v1 CMAF endpoint has HLS manifests with differing `includeIframeOnlyStream` values left unresolved (v2 sets it once per endpoint)
- [ ] every `manifestWindowSeconds` ≥ 30 and ≤ the account's applied live manifest length quota (`L-B20140A1`, default 15 minutes)
- [ ] `startoverWindowSeconds` 0–1209600, and `0` is preserved as `0`
- [ ] `programDateTimeIntervalSeconds` omitted when the v1 value was `0`, else ≥ 1
- [ ] `timeDelaySeconds` omitted when the v1 value was `0`, and otherwise smaller than the
      endpoint's `startoverWindowSeconds`
- [ ] `minUpdatePeriodSeconds` 1–3600, `minBufferTimeSeconds` and
      `suggestedPresentationDelaySeconds` 0–3600
- [ ] `keyRotationIntervalSeconds` ≥ 300, or omitted

**Enum values**

- [ ] `periodTriggers` is set explicitly on every DASH manifest: `["AVAILS"]` where v1 had
      `ADS`, `["NONE"]` where v1 had none — never omitted, never `ADS`
- [ ] `profiles` contains only `DVB_DASH`, or is omitted
- [ ] `profiles: ["DVB_DASH"]` appears only on endpoints whose channel has CMAF input
- [ ] `segmentTemplateFormat` is `NUMBER_WITH_TIMELINE` or omitted
- [ ] `utcTiming.timingMode` uses underscores, not hyphens
- [ ] SPEKE presets use underscores (`PRESET_AUDIO_1`), not hyphens
- [ ] `manifestFilter` uses `:`, not `=`, and is not URL-encoded
- [ ] `adMarkerHls` is `DATERANGE` or `SCTE35_ENHANCED`
- [ ] Every manifest with `adMarkerHls: DATERANGE` also sets `programDateTimeIntervalSeconds` ≥ 1

**Encryption**

- [ ] `drmSystems` values came from the UUID table, and every one is compatible with
      the container type *and* the chosen encryption method
- [ ] no `AES_128` paired with FairPlay
- [ ] `encryptionContractConfiguration` present on every encrypted endpoint
- [ ] preset pairing is legal (`SHARED` with `SHARED`; `UNENCRYPTED` only with a
      numbered preset)
- [ ] ISM endpoints: PlayReady only, `CENC`, both presets `SHARED`, no key rotation,
      no constant IV
- [ ] encrypted DASH manifests set `drmSignaling`, and unencrypted ones omit it
- [ ] no DASH manifest pairs `drmSignaling: REFERENCED` with `compactness: NONE`
- [ ] encrypted `TS` endpoints with `tsUseAudioRenditionGroup: false` use `SHARED` for
      both presets

**Structure**

- [ ] manifest types match the container (`TS` → HLS/LL-HLS; `CMAF` → HLS/LL-HLS/DASH;
      `ISM` → MSS only)
- [ ] ≤ 25 manifests per endpoint, ≤ 10 endpoints per channel, ≤ 10 channels per
      channel group, and the channel-group count fits the account quota
- [ ] `compactness` set explicitly on every DASH manifest

**Prerequisites outside MediaPackage**

- [ ] CDN-auth secret exists with the v2 key name, in the right account and Region
- [ ] CDN-auth role trust policy and permissions updated
- [ ] SPEKE key provider is SPEKE v2 compliant
- [ ] AWS CLI version supports every flag the plan needs
- [ ] quota increases requested where needed

Report the results as part of the plan, including the checks that *passed* on
non-obvious items — the user should be able to see that `startoverWindowSeconds: 0`
survived, rather than take it on trust.

---

## Step 7: Save Plan

Only after the user has confirmed all endpoint configurations and merge decisions, save to `.mediapackage-migration/migration-plan.json`.
Carry forward the fields channel-group planning already saved — `channelGroupAssignments` and `channelInputType` — rather than overwriting the file with endpoint data alone; execution reads `channelInputType` when creating channels, and it cannot be changed afterwards.

```json
{
  "channelGroupAssignments": [...],
  "channelInputType": "HLS",
  "endpointMappings": [
    {
      "targetOriginEndpointName": "football-hls",
      "targetChannelGroupName": "example-sports",
      "targetChannelName": "example-sports-football",
      "v2ContainerType": "TS",
      "v1Sources": [
        { "v1EndpointId": "football-hls", "v1Type": "HLS", "contributesManifest": "HLS" }
      ],
      "v2Config": { ... },
      "incompatibilities": [...]
    },
    {
      "targetOriginEndpointName": "football-cmaf-combined",
      "targetChannelGroupName": "example-sports",
      "targetChannelName": "example-sports-football",
      "v2ContainerType": "CMAF",
      "merged": true,
      "v1Sources": [
        { "v1EndpointId": "football-dash", "v1Type": "DASH", "contributesManifest": "DASH" },
        { "v1EndpointId": "football-cmaf", "v1Type": "CMAF", "contributesManifest": "HLS" }
      ],
      "v2Config": { ... },
      "incompatibilities": []
    }
  ]
}
```

---

## Step 8: Hand Off

Tell the user: "Endpoint configuration planning is complete. Ready to generate the migration plan? You can say 'generate plan' to continue."

<!-- markdownlint-disable-file MD036 -->
