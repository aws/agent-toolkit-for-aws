# Workflow Discovery Checklist

Before creating ANY resources for a new workflow, gather the following from the
user. Do not proceed until all required items are answered. Ask in this order —
later questions depend on earlier answers.

## 1. Workflow mode (ask first)

- Are we working in **prod** or **dev/test**?
- Are we **modifying an existing workflow** or **building a new one**?
  - If modifying: identify existing resources (flow ARNs, channel IDs, endpoint
    names) before making changes. Use describe/list API calls to understand
    current state.
  - If new: proceed through the full checklist below.
- What kind of workflow is this? (reference the workflow types from the routing table in SKILL.md).

## 2. Cost and scale constraints (ask second)

- Is there a **monthly budget target** or cost ceiling?
- Expected **concurrent viewership** (drives CDN egress — the dominant cost at scale)?
- Is this **always-on** (24/7 linear) or **event-based** (start/stop)?
  - Always-on → flag reserved pricing opportunities (MediaLive, MediaConnect, CloudFront).
  - Event-based → on-demand pricing, but remind to stop resources between events.
- Any existing **reserved capacity** or commitments (MediaLive reservations, CloudFront committed pricing, MediaConvert reserved slots)?

Use answers here to shape downstream decisions: channel class, ABR rung count,
segment duration, DVR window, and CDN price class. Load
`references/workflow-cost-optimization.md` if the user has explicit cost constraints
or asks for a cost comparison between options.

## 3. Implementation approach (ask third)

- AWS CDK or direct API/CLI calls?
- Note: MediaConnect and MediaLive have limited L2 CDK constructs. You may need
  L1 `CfnResource` for some resources.

## 4. Source information (required)

- Source protocol: ST 2110 JPEG XS, CDI, RTP, SRT, RTMP, or other?
- Video format: resolution, frame rate, scan mode (progressive/interlace)
- Video codec at source: uncompressed, JPEG XS, H.264, H.265/HEVC?
- Audio format: PCM, AAC, Dolby (AC3/EAC3)?
- Number of audio tracks/channels
- Ancillary data: captions, timecode, SCTE-35 markers, AFD?
- Source location: on-premises (via Direct Connect), same VPC, cross-region, public internet?
- Source IP range/CIDR for security group rules
- Redundancy: single source or dual-source failover?
- Dynamic source switching needed? (multiple sources that swap in/out → Router)
  - How many simultaneous sources × destinations? (many-to-many → Router)
  - Bitrate per source? (>50 Mbps → Flows required; Router limited to 50 Mbps per I/O)
  - If CDI/ST 2110/NDI/Zixi → Flows required (Router supports SRT, RTP, RTP-FEC, RIST only)

## 5. Network and VPC (required for live)

- Existing VPC or create new?
- Subnet IDs and their Availability Zones (need at least 2 in different AZs)
- Existing security groups or create new?
- Are all ingest ports accounted for? (ST 2110 needs separate ports per essence)

## 6. Encoding requirements (required)

- ABR ladder: how many rungs? (suggest based on source resolution if user unsure)
- Target codecs: H.264, H.265, or both?
- Frame rate handling: maintain source frame rate on all rungs, or drop on lower?
- GOP size preference (default: 2 seconds for HLS/DASH compatibility)

## 7. Ad insertion (optional)

- SCTE-35 ad signaling needed? splice_insert or time_signal mode?
- SCTE-35 source: embedded in stream, or injected via MediaLive schedule API?
- Server-side ad insertion (MediaTailor) needed?
- Ad decision server URL (VAST/VMAP endpoint)?

## 8. Packaging and distribution (required)

- Output formats: HLS, DASH, CMAF, MSS?
- Low-latency HLS needed?
- DVR/start-over window duration?
- CDN: CloudFront, third-party, or direct from MediaPackage?
- Access control: public, CloudFront-only, IP-restricted, or authenticated?

## 9. IAM (required)

- Existing IAM role? If yes, confirm it trusts the service principals for all
  services in the workflow.
- If no existing role: confirm permission to create one.

## 10. VOD-specific (if VOD or live-to-VOD)

- Source file location: S3 bucket and path/prefix
- Source format: container (MP4, MXF, MOV, TS) and codec
- Output formats: HLS, DASH, CMAF, MP4, MXF?
- Output ABR ladder or single rendition?
- DRM/encryption: none, AES-128, CPIX (Widevine/FairPlay/PlayReady)?
- Thumbnail/frame capture needed?
- Caption handling: embedded, sidecar (SRT, VTT, TTML), burn-in?
- Output destination: S3, MediaPackage v2 VOD, or both?
- Job queue: on-demand or reserved pricing?
- Accelerated transcoding needed?
