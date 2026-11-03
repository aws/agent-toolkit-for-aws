# Subtitles and Accessibility

Patterns for captioning, multi-language subtitles, and accessibility compliance.

---

## Caption Source Selection

```
IF captions embedded in source stream (CEA-608/708):
  → MediaLive extracts and passes through or converts
IF captions in sidecar file (SRT, VTT, TTML):
  → MediaConvert (VOD): attach as input sidecar
  → MediaLive (live): not supported as sidecar input
IF no captions exist and auto-captioning needed:
  → Amazon Transcribe (real-time for live, batch for VOD)
  → CONSTRAINT: adds 5-10s latency for live
IF burn-in (open captions) required:
  → MediaLive or MediaConvert burn-in output setting
  → CONSTRAINT: cannot be turned off by viewer
```

---

## Live Captioning

| | |
|---|---|
| **Preconditions** | MediaLive channel with caption-capable source or Transcribe integration |
| **Outputs** | Captions in manifest (WebVTT or embedded CEA-608/708) |

### Decision: Caption delivery method

```
IF source has embedded CEA-608/708:
  → Pass through in MediaLive (default behavior)
  → Convert to WebVTT sidecar in MediaPackage for HLS/DASH
IF using Amazon Transcribe for live auto-captioning:
  → Transcribe real-time streaming → MediaLive caption input
  → Adds 5-10s latency
IF burn-in required (regulatory, accessibility):
  → Enable burn-in in MediaLive output settings
  → Choose font, size, position, background
```

**Multi-language (live):**

- Each language requires a separate audio rendition + caption track
- Plan for encoding overhead with 10+ languages
- Use audio description tracks for visually impaired viewers

---

## VOD Captioning

| | |
|---|---|
| **Preconditions** | Source file + sidecar caption files (or embedded) |
| **Outputs** | Multi-language caption tracks in output manifest |

### Decision: Caption format for VOD

```
IF delivering HLS:
  → WebVTT sidecar (preferred) or embedded CEA-608
IF delivering DASH:
  → TTML or WebVTT sidecar
IF delivering CMAF:
  → WebVTT (works for both HLS and DASH manifests)
IF burn-in needed:
  → MediaConvert burn-in settings per output
```

**MediaConvert sidecar input:**

1. Add caption input selector referencing the sidecar file (SRT, VTT, TTML, SCC)
2. Map to output caption track with language code
3. Multiple sidecar files = multiple languages

---

## Accessibility Compliance

### Decision: Compliance requirements

```
IF FCC compliance (US broadcast):
  → CEA-608/708 passthrough required
  → Maintain caption timing accuracy
IF CVAA compliance (US internet video):
  → Closed captions must be available on all platforms
  → User must be able to customize appearance (font, size, color)
  → WebVTT with player-side rendering (not burn-in)
IF EU/EAA compliance:
  → Audio description track required
  → Multi-language subtitles
```

---

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Burn-in when closed captions needed | Viewers can't disable/customize | Use WebVTT sidecar instead |
| Missing caption track in ABR manifest | Some renditions have no captions | Configure captions on all output renditions |
| Wrong timecode base for sidecar files | Captions out of sync | Match sidecar timecode to video timecode |
| Auto-captioning without review | Errors in proper nouns, technical terms | Human review/correction for production |
| Single caption track for multi-language | Only one language available | Separate tracks per language |
