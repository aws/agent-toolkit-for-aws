# Service Rules: MediaLive

Loaded conditionally when the task involves MediaLive. The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

---

## MediaLive

### Input creation

- CDI inputs MUST be created as STANDARD class (two subnets REQUIRED).
- The `--input-class` CLI parameter does not exist. Agents MUST NOT attempt to use it.
- The channel class (`SINGLE_PIPELINE` or `STANDARD`) determines which pipeline endpoint is used, not the input class.
- For single-pipeline channels using CDI, both subnets MUST be provided at input creation; the channel uses only one.
- RTMP push inputs: MediaLive provides the ingest URL. Agents MUST NOT specify a source address.
- SRT inputs: caller or listener mode and port MUST be specified.

### Channel class

- `STANDARD`: dual-pipeline, automatic failover. REQUIRES inputs that provide two sources of content (see below).
- `SINGLE_PIPELINE`: single pipeline, lower cost. Uses only one endpoint/flow.
- Channel class MUST NOT be changed after creation. The channel MUST be deleted and recreated.

### STANDARD-class input requirements (per input type)

- **MEDIACONNECT input type:** the input MUST reference TWO MediaConnect flow ARNs (one per pipeline). A single-flow MEDIACONNECT input on a STANDARD channel forces single-pipeline operation. The two flows SHOULD be in different AZs.
- **CDI input type:** both subnets are provided at input creation; both MUST be in different AZs.
- **SRT, RTMP_PUSH, RTP (push-based):** the input definition is a single object; MediaLive provisions two ingest endpoints automatically from it. The source encoder MUST push to both endpoints.
- **HLS pull, MP4 file (pull-based):** the input definition is a single object containing the source URL(s). Both pipelines independently pull from the same source; no encoder push configuration is required.

### Epoch locking

- Epoch locking REQUIRES source timecode. Without it, epoch locking cannot synchronize segments. When the source's timecode capability is uncertain (e.g., RTMP from OBS, consumer encoders), agents MUST ask the user to confirm whether their source embeds UTC timecode before ruling epoch locking in or out.
- Epoch locking is incompatible with SCTE-35 segmentation. ID3 metadata via MediaLive schedule actions MUST be used for ad break signaling instead — ID3 carries the cue payload without requiring a segment break, so it coexists with epoch locking.
- Epoch locking MUST NOT be used with MediaPackage JIT packaging. Passthrough origins are REQUIRED.

### Pipeline locking with file inputs

- File inputs (S3 MP4/TS) do not contain live timecode. Standard pipeline locking based on timecode will not work.
- `InputClipSettings` with a zero-based approach SHOULD be used to synchronize pipelines when using file inputs.

### Input loss behavior

- `EMIT_OUTPUT`: On input loss, the channel continues outputting black frames / silence. RECOMMENDED for production live events (prevents player buffering and stalls).
- `PAUSE`: On input loss, the channel stops outputting. SHOULD be used only for cross-region epoch-locked workflows where a 4xx triggers region switch.

### Encoder settings

- SCTE-35 passthrough for HLS: `Scte35Behavior: PASSTHROUGH` MUST be set in `M3u8Settings` on each individual output. `M3u8Settings` is the ONLY correct location. It MUST NOT be placed at `HlsGroupSettings` level (that field does not exist there).

**SCTE-35 setting disambiguation (agents frequently confuse these):**

- **HLS output groups**: `Scte35Behavior: PASSTHROUGH` in `M3u8Settings`, per-output (NOT at `HlsGroupSettings` level).
- **CMAF Ingest output groups**: `Scte35Type: SCTE_35_WITHOUT_SEGMENTATION` in `CmafIngestGroupSettings`, group-level.
- These are different settings for different output group types. They are NOT interchangeable.
- GOP size MUST be identical across all ABR rungs for proper segment alignment.
- GOP size SHOULD be 2 seconds (aligns with both HLS 6-second segments and DASH 2-second segments as an integer divisor). For Low-Latency HLS (LL-HLS), GOP size SHOULD be 1 second to match the shorter segment/part duration.
- MediaPackage v2 supports two ingest types: CMAF (fMP4) and HLS (TS). The MediaLive output group MUST match the MediaPackage channel's `InputType`: CMAF InputType → `CmafIngestGroupSettings`; HLS InputType → `HlsGroupSettings` with CDN settings `hls basic put`. `CmafIngestGroupSettings` is RECOMMENDED for new workflows (fMP4, lower latency, segment reuse).
- When duplicating a MediaLive channel for locking, redundancy, or cross-region failover, the duplicate MUST be an identical clone of the original except for: channel name, input attachment IDs, and channel class (a STANDARD primary with a SINGLE_PIPELINE backup in another region is allowed for cost optimization). All encoder settings, output group settings, output names/modifiers, GOP size, frame rate, segment duration, and SCTE-35 configuration MUST be identical.
- Frame rate configuration differs by codec:
  - **H.264**: `H264Settings.FramerateControl: INITIALIZE_FROM_SOURCE` to match source frame rate automatically.
  - **H.265**: No `FramerateControl` field exists. Frame rate MUST be set explicitly via `H265Settings.FramerateNumerator` and `H265Settings.FramerateDenominator` (e.g., 60/1 for 60fps, 30/1 for 30fps, 30000/1001 for 29.97fps).

### Codec constraints

- H.264 (AVC): max practical resolution for live is 1080p. 4K AVC SHOULD NOT be used (requires 30+ Mbps, HEVC is RECOMMENDED instead).
- H.265 (HEVC): supports up to 2160p (4K UHD). MAIN or MAIN_10BIT profile SHOULD be used. Industry-typical target for 4K HEVC live distribution: 10-20 Mbps with QVBR (sports/high-motion at the high end, low-motion at the low end).
- A single channel MUST NOT output both H.264 and H.265 simultaneously. Separate channels are REQUIRED for multi-codec delivery. Both channels MUST target the same MediaPackage v2 channel via CMAF ingest so MediaPackage produces a unified multi-codec manifest. Routing to separate MediaPackage channels produces separate manifests and defeats the purpose of multi-codec ABR. GOP size, frame rate, segment duration, and output names MUST be identical across the codec channels so MediaPackage can align them into a coherent manifest.
- AES-128 encryption MUST NOT be used with H.265/HEVC. AES-128 works only with H.264 in MPEG-TS segments. For encrypted HEVC delivery, CPIX/SPEKE with fMP4 segments MUST be used.
- Heavy ABR stacks (many renditions at varying frame rates and codecs) MAY overwhelm the encoder. Shared encode outputs SHOULD be used where possible.

### Audio configuration

- Audio normalization SHOULD use ITU-R BS.1770 loudness normalization (current revision: BS.1770-4). Target: -16 LKFS (streaming) or -24 LKFS (broadcast alignment, e.g., ATSC A/85).
- Surround audio SHOULD use EAC3 (Dolby Digital Plus, formal name "E-AC-3") at 192-384 Kbps as a separate rendition alongside stereo AAC.
- Stereo audio SHOULD use AAC-LC at 64-128 Kbps. HE-AAC v1 at 32 Kbps MAY be used for lowest-bitrate mobile renditions.
- Each language track REQUIRES a separate audio rendition.

### HDR configuration

- HDR10 MUST use HEVC MAIN_10BIT profile with BT.2020 colorspace and PQ (ST 2084) transfer function. fMP4 segments are REQUIRED (not MPEG-TS).
- HLG MUST use HEVC MAIN_10BIT profile with BT.2020 colorspace and HLG transfer function.
- DolbyVision REQUIRES external conversion. MediaLive does not natively generate DolbyVision metadata.
- Loss-of-signal slates for HDR channels MUST be encoded with matching HDR metadata (colorspace, transfer function). SDR slates MUST NOT be used on HDR channels.

### Output groups

- `CmafIngestGroupSettings`: MUST be used for MediaPackage v2 CMAF ingest.
- `HlsGroupSettings`: for HLS output to S3 or non-MediaPackage destinations.
- `ArchiveGroupSettings`: for recording to S3 (MPEG-TS container).
- `MediaPackageGroupSettings`: targets MediaPackage v1, which remains supported but is being superseded by MediaPackage v2. New workflows SHOULD target MediaPackage v2 via `CmafIngestGroupSettings`. Continue to use v1 only when an existing v1-dependent workflow does not justify migration cost.
- A channel MAY have multiple output groups simultaneously.
- CMAF Ingest outputs MUST contain only ONE track: either a video description, one audio description, or one caption description. Multiple tracks per output MUST NOT be used. Video, audio, and caption tracks MUST be separate outputs within the output group.

### SCTE-35 in CMAF Ingest output groups

- To pass SCTE-35 markers, `Scte35Type` in `CmafIngestGroupSettings` MUST be set to `SCTE_35_WITHOUT_SEGMENTATION`.
- `SCTE_35_ENHANCED` and `SCTE35_ENHANCED` MUST NOT be used; they are not valid enum values.
- Without setting `Scte35Type`, SCTE-35 markers from schedule actions will NOT appear in the CMAF ingest stream.
- This is separate from `Scte35Behavior` in `M3u8Settings` (which applies to HLS output groups only).

### State machine

- Channel states: `CREATING` -> `IDLE` -> `STARTING` -> `RUNNING` -> `STOPPING` -> `IDLE`.
- `start-channel` / `stop-channel` are async. Agents MUST poll `State`.
- Channel MUST be IDLE to modify encoder settings or output groups.
- `start-channel` returns immediately; channel state transitions through `STARTING` to `RUNNING` asynchronously. Provisioning time varies with channel class, codec, and resolution. Agents MUST poll until `RUNNING` rather than assume any specific duration. For time-sensitive events, start channels well in advance and verify they reach `RUNNING` before the event begins.

---
