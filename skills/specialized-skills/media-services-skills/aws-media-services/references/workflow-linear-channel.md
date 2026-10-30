# Linear Channel Workflow

24/7 linear channels with schedule-driven content switching, file-to-live playout, and ad insertion.

---

## Architecture Selection

```
IF live sources mixed with file-based content, or need custom ABR:
  → MediaLive-based linear channel (real encoding, input switching)
IF all content is pre-transcoded VOD and goal is schedule-driven monetization:
  → MediaTailor Channel Assembly (no encoding, manifest stitching)
  → Lower cost, near-zero latency
```

| Dimension | MediaLive linear | Channel Assembly |
|-----------|-----------------|-----------------|
| Encoding | Real-time | None (pre-transcoded) |
| Live sources | Yes | Yes (live source refs) |
| Cost model | Per-hour channel | Per-output-hour (lower) |
| Latency | 10-30s (encoding) | Near-zero (stitching) |
| Ad insertion | SCTE-35 → MediaTailor | Built-in ad breaks |

---

## Approach 1: MediaLive Input Switching

| | |
|---|---|
| **Preconditions** | MediaLive channel running, file inputs in S3, IAM role with s3:GetObject |
| **Outputs** | Continuous live stream with scheduled content transitions |

### File Input Configuration

#### Decision: Source End Behavior

```
IF file should repeat until manually switched away (slates, holding patterns):
  → LOOP
IF file should play once then advance to next action (countdown, credits):
  → CONTINUE
```

Supported containers: MP4 (H.264/H.265, AAC) and Transport Stream (H.264/H.265/MPEG-2, various audio).

### Schedule Action Timing

```
IF pre-planned event with known start time:
  → Fixed timing (specific UTC time)
IF manual/ad-hoc switching during live operation:
  → Immediate timing
IF chaining file inputs (countdown → live → credits):
  → Follow timing (executes when referenced action's input finishes)
  → CONSTRAINT: Follow can only reference CONTINUE inputs (not live, not LOOP)
```

### Typical Program Structure

```
1. "intro" (LOOP) — holds until event ready
2. Schedule: Immediate → "countdown" (CONTINUE)
3. Schedule: Follow countdown → "live" input
4. Schedule: Immediate → "credits" (CONTINUE)
5. Schedule: Follow credits → "outro" (LOOP) — holds until channel stops
```

### SCTE-35 with Input Switching

```
IF ad insertion needed at transition points:
  → Configure Scte35InputSettings in InputSwitchScheduleActionSettings
  → LOAD references/workflow-ad-insertion.md for full SSAI chain
```

---

## Approach 2: MediaTailor Channel Assembly

| | |
|---|---|
| **Preconditions** | Pre-transcoded VOD assets in S3, served via CloudFront |
| **Outputs** | HLS/DASH manifest URL from MediaTailor channel |

### Setup Sequence

1. Create Source Location (base URL = CloudFront distribution domain)
2. Create VOD Sources (relative paths to HLS/DASH manifests)
3. Create Channel (LOOP or LINEAR mode)
4. Create Programs with schedule and ad breaks
5. Start channel via `StartChannel` API

#### Decision: Channel mode

```
IF continuous playout (programs repeat when schedule ends):
  → LOOP mode
IF programs play once, then filler/slate when empty:
  → LINEAR mode
```

### Content Preparation

All VOD content MUST be pre-transcoded with identical settings:

- Same codec, resolution ladder, and segment duration across all sources
- Store in S3, serve via CloudFront for segment delivery
- Use MediaConvert to produce HLS/DASH output (CMAF/fMP4 segments)

### Ad Insertion

```
IF monetizing with dynamic ads:
  → Add AdBreak configuration in program definitions
  → Channel Assembly emits SCTE-35 markers (EXT-X-DATERANGE/EXT-X-CUE-OUT for HLS, EventStream for DASH) into the output manifest based on the ad breaks defined in the program schedule
  → Layer MediaTailor playback configuration on top of channel — MediaTailor consumes these markers to trigger ad decisioning
  → The SCTE-35 chain for Channel Assembly is: program schedule ad breaks → Channel Assembly manifest (markers emitted) → MediaTailor (markers consumed, ads stitched)
  → Ad content MUST match channel encoding settings
  → LOAD references/workflow-ad-insertion.md for scaling patterns
```

---

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Follow action referencing live input | Never triggers (live never ends) | Follow only with CONTINUE file inputs |
| Mismatched encoding across Channel Assembly sources | Playback glitches at transitions | Identical encoding settings on all sources |
| Missing S3 permissions for file inputs | Input switch fails | s3:GetObject on source bucket |
| LOOP on file that should play once | Content repeats | Set to CONTINUE |
| Channel Assembly without CloudFront | S3 throttling | Always front with CloudFront |
| Ad content doesn't match channel encoding | Black frames during ads | Pre-transcode ads with same settings |
