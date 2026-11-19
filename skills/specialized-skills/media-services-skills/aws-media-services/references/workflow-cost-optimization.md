# Cost Optimization

Model cost implications for both existing and proposed resources. Present each
decision as a spectrum — not a binary choice.

## Existing State — Query First

| Service | Query | Flag |
|---------|-------|------|
| MediaConnect | `list-flows` → ACTIVE with 0 outputs | Idle billing |
| MediaLive | `list-channels` → STANDARD in non-prod | Over-provisioned |
| MediaLive | Channel RUNNING but no viewers downstream | Idle encoding cost |
| MediaConvert | Recent job volume vs queue type | Reserved queue candidate |
| MediaPackage v2 | Origin endpoints with no egress (EgressBytes = 0) | Unused packaging |
| MediaPackage v2 | Long startover/DVR windows on low-viewership channels | Excess origin storage |
| MediaTailor | Playback configs with zero active sessions | Unused SSAI capacity |
| CloudFront | Cache hit ratio < 80% on segment behaviors | Excess origin pulls (cost + RPS risk) |
| CloudFront | Origin Shield disabled with multiple edge locations | Redundant origin requests |
| S3 | Archive output groups writing but never accessed | Unused recordings — lifecycle policy needed |

## Proposed State — Decision Spectrums

For each decision, present: the variable, how cost scales, what drives the right
answer, and a concrete recommendation for the user's context.

### Encoding and source transport

| Decision | Cost driver | Scaling | Right-size by asking |
|----------|------------|---------|---------------------|
| ABR renditions | Each rung = encode + packaging + storage + CDN egress per viewer on that rung | Multiplied across entire chain | What devices/bandwidths does the audience use? Remove rungs with <5% viewership. Sports needs more rungs than talking-head. |
| Bitrate targets | Higher bitrate = more storage + CDN egress (largest cost at scale) | Linear | Use QVBR — target quality level, not fixed bitrate. |
| Channel uptime | Billed per-second while RUNNING/ACTIVE | Linear with time | 24/7 linear or event-based? Event = stop between uses. |
| Idle channel cost | MediaLive charges for attached inputs even when channel is IDLE | Continuous while input attached | Detach or delete inputs on channels that won't run for days+. |
| Redundancy | STANDARD = 2x SINGLE_PIPELINE | Step (1x or 2x) | Cost of 30s downtime during failover? Acceptable → single. |
| MediaLive reserved pricing | Input + output reservations (12-month commit; check current reserved-vs-on-demand savings on the MediaLive pricing page) | Threshold: channel runs >16 hrs/day | Is this channel 24/7 or near-24/7? → Reserved. Event-only? → On-demand. |
| MediaLive add-on features | Advanced Audio adds per-channel surcharge | Per-channel flat fee | Do you actually need Advanced Audio (Dolby, audio normalization)? If not, disable. |
| MediaConvert tier | Professional tier costs more than Basic per normalized minute (confirm the current multiplier on the MediaConvert pricing page) | Step (Basic vs Professional) | Do you need broadcast features (HEVC, HDR, Dolby)? If just H.264 web delivery → Basic tier. |
| MediaConvert accelerated transcoding | 2-4x cost per job vs standard | Multiplier on job cost | Is turnaround time critical? Long-form content benefits. Short clips don't need it. |
| MediaConvert volume discounts | Tiered pricing — more normalized minutes/month = lower per-minute rate | Staircase down with volume | Consolidate jobs in one account/region to hit higher tiers. Use Organizations for aggregated billing. |
| MediaConvert reserved slots | Fixed monthly rate per RTS (check current reserved-vs-on-demand savings on the MediaConvert pricing page) | Threshold: steady daily volume | Consistent daily volume? → Reserved. Bursty/unpredictable? → On-demand with tiered discounts. |
| HEVC vs H.264 | HEVC: higher encode cost, materially lower storage+CDN (more bitrate-efficient than H.264 — quantify against current pricing) | Trade-off crosses based on egress volume | % audience supporting HEVC? Monthly egress? |
| Bandwidth Reduction Filter | Reduces output bitrate 10-20% | Multiplicative savings on storage+CDN | Enable unless contribution feed where every bit matters. |
| MediaConnect flow size | Standard (80 Mbps) vs Large (150) vs XL (400) | Step pricing per tier | What's the actual source bitrate? Don't over-provision. |
| MediaConnect Router vs TS flow | Router charges per-input-hour + per-output-hour by bitrate tier. TS flow charges per-flow-hour + per-GB transfer. | Different models | Few outputs, high bitrate → Router may cost more. Many outputs, low bitrate → Router may be cheaper. Compare. |
| MediaConnect reserved outbound | Commit to monthly outbound bandwidth for discount | Threshold: sustained egress | Steady outbound to internet/other regions? → Reserve. Bursty? → On-demand. |
| MediaConnect output count | Each output on a flow adds cost | Linear per output | Can destinations share a single output (multicast/entitlement)? Minimize outputs where possible. |
| LookAheadRateControl: HIGH | Better quality at same bitrate → can target lower MaxBitrate | Indirect — reduces downstream egress | Enable HIGH for distribution. Allows lowering bitrate ceiling without visible quality loss. |
| Input switching (channel reuse) | One channel with schedule actions vs multiple channels | Eliminates N-1 channel costs | Multi-segment events (pre-show/main/post)? → Use input switching, not separate channels. |
| Shared encode outputs | Same rendition reused across multiple output groups | Avoids duplicate encoding | Same ABR rung going to both archive and packaging? → Share the encode. |

### Packaging and origin (MediaPackage v2)

| Decision | Cost driver | Scaling | Right-size by asking |
|----------|------------|---------|---------------------|
| Segment duration | Shorter = more manifest requests (origin + CDN) but lower latency | Inverse with segment length | Latency requirement? 6s default, 2s for low-latency, 1s only for LL-HLS. |
| DVR/startover window | Longer window = more origin storage and manifest size | Linear with window duration | How far back do viewers actually rewind? Match to actual usage, not "just in case." |
| Number of origin endpoints | Each endpoint = separate packaging pass and egress metering | Linear per endpoint | One endpoint serves both HLS and DASH — don't create duplicates. |
| Ingest redundancy | Dual-ingest (STANDARD channel) doubles ingest volume | 2x ingest cost | Production = dual. Dev/test = single pipeline saves ingest cost. |
| Egress via CDN vs direct | Content served from CDN cache does NOT incur MediaPackage egress charge | Eliminates origin egress at high cache hit | Always use CloudFront (or equivalent) — direct viewer access costs origin egress per-GB on every request. |
| Volume commitment | Discounted pricing at 10+ TB/month annual commitment | Step discount | Sustained high-viewership channels? → Commit for discount. |

### Ad insertion (MediaTailor)

| Decision | Cost driver | Scaling | Right-size by asking |
|----------|------------|---------|---------------------|
| SSAI vs CSAI | SSAI: per-ad-impression cost. CSAI: zero MediaTailor cost but client complexity | Per impression | Ad volume? If <1000 impressions/day, SSAI cost is negligible. At millions/day, it's material. |
| Ad transcoding overflow | First 10 transcodes per 1,000 insertions are free. Beyond that, billed at MediaConvert rates. | Step — free tier then per-transcode | How many unique ad creatives? High creative diversity = more transcodes. Pre-condition creatives to avoid. |
| Ad delivery (segment egress) | Delivering ad segments and manifests over internet/CDN is billed per-GB | Linear with ad volume × bitrate | Use CDN caching for ad segments — popular ads served from cache avoid repeated delivery charges. |
| Session duration | Longer sessions = more manifest manipulation requests | Linear with session count × duration | Average view time? Short-form = many sessions. Long-form = fewer but longer. |
| Prefetch | Reduces ad latency but increases ADS calls | More ADS requests (may increase ADS cost) | Is ad fill rate critical? Prefetch helps fill rate but costs more ADS calls. |
| Channel Assembly tier | Basic (VOD-only) vs Standard (VOD+live, higher rate) — check current Channel Assembly pricing | Per-hour per-channel | Do you need live source stitching? If VOD-only schedule → Basic saves. |
| Channel Assembly vs live encode | Channel Assembly avoids encoding cost for schedule-based linear | Eliminates MediaLive cost entirely | Is source already encoded VOD assets? → Channel Assembly. Live source? → MediaLive required. |

### CDN delivery (CloudFront)

| Decision | Cost driver | Scaling | Right-size by asking |
|----------|------------|---------|---------------------|
| Origin Shield | Per-request cost at shield tier, but reduces origin load dramatically | Net savings when >5 edge locations hit origin | How many edge locations serve viewers? >5 → likely saves money AND protects origin. |
| Cache TTLs | Shorter manifest TTL = more origin requests | Inverse | Don't go below half-segment-duration. Longer = cheaper but staler. |
| Price class | All edge locations vs subset (100/200) | Step — fewer locations = lower per-GB in some regions | Where are viewers? If 95% in NA/EU, PriceClass_100 saves on AP/SA egress pricing. |
| Regional pricing variation | AP, SA, Middle East, Africa regions cost 2-3x NA/EU per-GB | Geographic | Geo-restrict to licensed territories — saves money AND enforces rights. |
| Per-request charges | Billed per 10K HTTP/S requests, separate from data transfer | Linear with request count | Short segments (2s) = 3x the requests of 6s segments. Factor request cost, not just transfer. |
| Compression on manifests | Reduces transfer size 60-80% | Multiplicative on manifest egress | Always enable on manifests. Never on segments (already compressed). |
| Reserved capacity | CloudFront committed pricing at volume (check current CloudFront pricing for savings) | Savings scale with sustained egress | Monthly egress >10 TB sustained? → Reserved pricing. |
| Origin-to-CloudFront transfer | Data from AWS origins (S3, MediaPackage) to CloudFront is free | Zero cost | This is why CDN-fronting MediaPackage saves money — origin egress is free to CloudFront. |

### Storage (S3)

| Decision | Cost driver | Scaling | Right-size by asking |
|----------|------------|---------|---------------------|
| Archive retention | Every hour of live archive = bitrate × duration in storage | Linear, accumulates indefinitely | How long must recordings be kept? Set lifecycle policies. 30 days? 90? |
| Storage class | Standard vs IA vs Glacier | Step savings (50-90%) for infrequent access | Are archives accessed after 24h? → IA. After 90d? → Glacier. |
| VOD output duplication | Multiple output formats = multiplied storage | Linear per format | Do you need MP4 + HLS + DASH separately, or can MediaPackage v2 JIT-package from one? |
| Request costs (PUT/GET) | High segment counts = high request volume (each segment = 1 PUT on archive, 1 GET on playback) | Linear with segment count | At 2s segments, a 1-hour recording = 1,800 PUTs. At 6s = 600. Request costs can exceed storage for short-lived content. |
| Lifecycle transitions | Moving to IA/Glacier incurs per-object transition fee | Per-object one-time | Many small segments = high transition cost. Consider fewer, larger archive chunks if lifecycle is planned. |

## Cost Amplifiers — Upstream Decisions That Cascade

These decisions multiply cost across multiple downstream services simultaneously.
Flag them early because they have outsized impact.

| Upstream decision | Services amplified | Example |
|-------------------|-------------------|---------|
| Adding an ABR rung | MediaLive encode + MediaPackage ingest + MediaPackage egress + CloudFront egress + S3 archive | 1 extra rung at 3 Mbps with 10K viewers = (encoding hrs × rate) + (egress GB × per-GB price × viewer count) across the chain, not just encoding |
| Increasing bitrate | MediaPackage egress + CloudFront egress + S3 storage | Doubling bitrate roughly doubles egress cost (the dominant cost at scale) |
| Shortening segment duration | MediaPackage request count + CloudFront request count + Origin Shield requests | 2s segments = 3x the requests of 6s segments |
| Extending DVR window | MediaPackage origin storage + manifest size + CloudFront manifest transfer | 4-hour DVR vs 15-min = 16x origin storage for that channel |
| STANDARD vs SINGLE_PIPELINE | MediaLive (2x) + MediaConnect (2x outputs) + MediaPackage (2x ingest) | Full chain doubles, not just encoding |

When presenting cost optimization, always trace the decision through the full
chain to show total impact, not just the single-service cost.

## Procedure

1. Gather context: environment (prod/dev), audience profile, SLA, content type, expected viewership.
2. Query existing resources for baseline costs and utilization.
3. For each applicable decision, state where on the spectrum you recommend and why.
4. Find current per-unit pricing for the relevant services. If the AWS MCP server's `search_documentation` tool is available, use it; otherwise consult the public AWS pricing pages for each service.
5. **Compute costs deterministically, not in your head** — do NOT perform mental math or approximate in prose. If a Python runtime is available (the AWS MCP server's `run_script` tool, or a local interpreter), write and run a script that:
   - Accepts the pricing units from step 4 and the user's parameters (hours, bitrate, viewer count, segment duration, etc.)
   - Calculates monthly cost per service and total
   - Computes all variants in one script when comparing scenarios, returning a comparison table
   If no runtime is available, lay out the arithmetic explicitly (per-unit price × quantity for each line item) and sum it step by step so the calculation is auditable.
6. Present results as a table with per-service breakdown. If multiple scenarios, show side-by-side.
7. Wait for user approval before creating resources.
