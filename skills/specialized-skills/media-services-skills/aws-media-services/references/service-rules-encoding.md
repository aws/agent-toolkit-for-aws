# Service Rules: Encoding (Distribution & Contribution)

Loaded conditionally when the task involves encoding (MediaLive live encoding OR MediaConvert VOD transcoding). The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

Settings below apply to both MediaLive and MediaConvert except where marked
**[MediaLive only]** or **[MediaConvert only]**. API field names are given
in parentheses.

---

## Distribution Encoding

**Rate control:**

- QVBR (Quality-Defined Variable Bitrate) with Quality Level Auto SHOULD be used for all distribution encoding.
  - MediaLive H.264: `H264Settings.RateControlMode: QVBR`, `H264Settings.QvbrQualityLevel` (omit or set to default for Auto)
  - MediaConvert H.264: `H264Settings.RateControlMode: QVBR`, `H264Settings.QvbrSettings.QvbrQualityLevel`
- QVBR uses `MaxBitrate` (not `Bitrate`) to set the bitrate ceiling. `Bitrate` MUST NOT be used with QVBR; it causes a validation error.
- CBR SHOULD be used only for contribution feeds.

**Bandwidth Reduction Filter [MediaLive only]:**

- (`H264Settings.FilterSettings.BandwidthReductionFilter`)
- Strength SHOULD be set to Auto for most content.
- For graphics/screen capture content: MUST be set to Off (sharp edges need preservation).
- For UGC at low resolution/bitrate: High is RECOMMENDED.
- The Bandwidth Reduction Filter and Temporal Noise Reducer MUST NOT be used simultaneously. They conflict.
- MediaConvert exposes a different filter set (e.g., `NoiseReducer`); see the Noise Reducer note below.

**Lookahead:**

- MediaLive: `H264Settings.LookAheadRateControl` SHOULD be `HIGH` for standard distribution; MUST be `LOW` for low-latency (LL-HLS, contribution).
- MediaConvert exposes equivalent behavior through its quality-tuning level (see "Quality tuning" below); there is no direct LookAheadRateControl field.

**GOP configuration:**

- GOP size SHOULD be 2 seconds for distribution. Segment/fragment duration MUST be an integer multiple of GOP size.
- GOP size MUST be identical across all ABR rungs — varying GOP per rung breaks segment alignment.
- For Low-Latency HLS (LL-HLS), GOP size SHOULD be 1 second to match the shorter segment/part duration.
  - MediaLive: `H264Settings.GopSize: 2`, `H264Settings.GopSizeUnits: SECONDS`
  - MediaConvert: `H264Settings.GopSize: 2`, `H264Settings.GopSizeUnits: SECONDS`
- B-Frames: 3 is RECOMMENDED for general content. For low-bitrate moderate-motion UGC, 5 MAY be used.
  - MediaLive: `H264Settings.GopNumBFrames: 3` and `H264Settings.GopBReference: ENABLED`
  - MediaConvert: `H264Settings.NumberBFramesBetweenReferenceFrames: 3` and `H264Settings.GopBReference: ENABLED`
- Reference Frames: 3 is RECOMMENDED (`H264Settings.NumRefFrames: 3` on both services).
- Dynamic Sub-GOP **[MediaConvert only]**: `H264Settings.DynamicSubGop: ADAPTIVE` SHOULD be enabled.

**Profiles:**

- H.264: High profile with CABAC entropy MUST be used for ALL ABR rungs. Baseline or Main profiles MUST NOT be used on lower rungs.
  - MediaLive: `H264Settings.Profile: HIGH`, `H264Settings.EntropyEncoding: CABAC`
  - MediaConvert: `H264Settings.CodecProfile: HIGH`, `H264Settings.EntropyEncoding: CABAC`
- HEVC: Main profile (or Main 10-bit for HDR/10-bit sources) SHOULD be used.
  - MediaLive: `H265Settings.Profile: MAIN` or `MAIN_10BIT`
  - MediaConvert: `H265Settings.CodecProfile: MAIN_MAIN` or `MAIN10_MAIN`

**Adaptive Quantization:**

- SHOULD be set to Auto.
  - MediaLive: `H264Settings.AdaptiveQuantization: AUTO`; FlickerAQ via `H264Settings.FlickerAq: ENABLED`
  - MediaConvert: `H264Settings.AdaptiveQuantization: AUTO`; flicker control via `H264Settings.FlickerAdaptiveQuantization`
- Flicker AQ SHOULD be enabled only for pulsing artifacts on grass/textures (sports) or dark/night content.

**Input video filters (content-dependent):**

- Sports: No filter SHOULD be used (preserve motion detail).
- Filter strength: 3-4 is RECOMMENDED for low-bitrate content (below 4 Mbps at 1080p, 2 Mbps at 720p, 1 Mbps at SD).

**Noise Reducer:**

- MediaConvert (`NoiseReducer.Filter` on the input): for old film content, `CONSERVE` mode SHOULD be used. For clean sources, the noise reducer SHOULD NOT be applied.
- MediaLive uses the Bandwidth Reduction Filter (above) for similar purposes.

**Quality/density trade-off [MediaLive only]:**

- MediaLive sets quality vs. throughput indirectly via `LookAheadRateControl` and the channel class; there is no numeric "speed" parameter.

**Quality tuning [MediaConvert only]:**

- `H264Settings.QualityTuningLevel: SINGLE_PASS_HQ` SHOULD be used for live VOD encoding when wall-clock matters.
- `H264Settings.QualityTuningLevel: MULTI_PASS_HQ` MAY be used for non-time-sensitive VOD (slower, higher quality).
- HEVC: `H265Settings.QualityTuningLevel: SINGLE_PASS_HQ` for sub-4K, `SINGLE_PASS` for 4K when real-time performance matters.

**Scaling:**

- Scaling Sharpness when downscaling SHOULD be 100 (preserve contour detail).
- Scaling Sharpness when upscaling SHOULD be 50 or 25 (avoid aliasing artifacts).

**Deinterlacing (interlaced sources):**

- For sports with interlaced source (e.g., 1080i): frame rate SHOULD be doubled to progressive (29.97i to 59.94p or 25i to 50p) using the Interpolation deinterlace algorithm.
- If source is interlaced and output is set to progressive WITHOUT enabling the deinterlacer, the output will have combing artifacts. The deinterlacer MUST be enabled.

**H.264 Level by resolution (typical, both services):**

- 1080p60: `H264_LEVEL_4_2`
- 1080p30: `H264_LEVEL_4_1`
- 720p60: `H264_LEVEL_4_0`
- 720p30: `H264_LEVEL_3_1`
- 480p30: `H264_LEVEL_3_1`
- When in doubt, set Level to AUTO and let the encoder pick.

---

## Contribution Encoding

Contribution feeds prioritize low latency and high bitrate over encoding efficiency.

**Key differences from distribution:**

- Rate control: CBR MUST be used.
- Lookahead: MUST be Low.
- B-Frames: MUST be 0.
- Dynamic Sub-GOP [MediaConvert only]: MUST be Disabled.
- Bandwidth Reduction Filter [MediaLive only]: MUST be Disabled.
- Input video filters: MUST be Disabled.
- Adaptive Quantization: SHOULD be Low (spatial only, no temporal).
- GOP size: SHOULD be 1 second.

**H.264 vs HEVC for contribution:**

- At high bitrates (>50 Mbps for 1080p, >80 Mbps for 4K), H.264 and HEVC perform similarly.
- H.264 is RECOMMENDED for contribution due to lower latency and better real-time performance.
- HEVC contribution at 4K 50/60p and 80+ Mbps MAY NOT maintain real-time on all encoder hardware.
