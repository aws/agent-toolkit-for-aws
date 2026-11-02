# Live Event Workflow

Cross-service pattern guidance for live event workflows.

Signal chain: Source → MediaConnect → MediaLive → MediaPackage v2 → (MediaTailor) → CloudFront → Viewers

---

## Architecture Selection

```
IF source is on-premises or remote (ST 2110, CDI, SRT):
  → Full chain: Source → MediaConnect → MediaLive → MediaPackage v2 → CloudFront
  → LOAD references/workflow-contribution-distribution.md for transport protocol details
IF source is cloud-native or direct push (RTMP, HLS pull):
  → Direct ingest: Source → MediaLive → MediaPackage v2 → CloudFront
IF delivering both H.264 and HEVC:
  → Dual channel: Source → MediaConnect → [ML Channel A (H.264) + ML Channel B (HEVC)] → MediaPackage v2 → CloudFront
IF user mentions redundancy, failover, multi-region, or epoch locking:
  → LOAD references/workflow-resilience-patterns.md
```

---

## Resource Creation Sequence

```
DEPENDENCY GRAPH:
  Step 1 [VPC, IAM]
    ↓
  Step 2 [MediaPackage v2] ──────────────────────────┐
    ↓                                                 │
  Step 3 [MediaConnect Flow] (if contribution)        │
    ↓                                                 │
  Step 4 [MediaLive Input]                            │
    ↓                                                 │
  Step 5 [MediaConnect Output] (CDI only)             │
    ↓                                                 │
  Step 6 [MediaLive Channel] ←── needs ingest URL ───┘
    ↓
  Step 7 [MediaTailor] (optional)
    ↓
  Step 8 [CloudFront]
```

---

### Step 1: Foundation (VPC, IAM)

| | |
|---|---|
| **Preconditions** | None (first step) |
| **Outputs** | `vpc_id`, `subnet_ids[]` (≥2 AZs), `security_group_id`, `iam_role_arn` |
| **Needed by** | Steps 2-6 |

**Actions:**

1. Create or identify VPC with subnets in ≥2 Availability Zones
2. Create security groups with rules for ingest traffic (scope to source CIDR)
3. Create IAM role with trust policy for the services actually used in the chain

The trust policy below is for the common case where MediaConnect feeds
MediaLive. If MediaConnect is NOT in the chain (e.g., RTMP_PUSH, SRT, or
HLS-pull direct to MediaLive), drop `mediaconnect.amazonaws.com` from the
Service array.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": ["medialive.amazonaws.com", "mediaconnect.amazonaws.com"]
    },
    "Action": ["sts:AssumeRole", "sts:TagSession"]
  }]
}
```

The role also needs permission policies sufficient for what each service
does — at minimum: `mediapackagev2:PutObject` on the target channel for
MediaLive→MediaPackage v2 ingest, plus any S3, SSM, secrets, or KMS
permissions the channel touches. Do NOT attach `AmazonMediaLiveFullAccess`
to a service role — that policy grants `medialive:*` and is intended for
human operators, not for the role MediaLive assumes.

**MediaConnect input type:** The role MUST include `mediaconnect:ManagedDescribeFlow`, `ManagedAddOutput`, and `ManagedRemoveOutput` with Resource `flow:*` + `output:*` (account/region scoped). Specific flow ARNs do not work.

**Validation:** Call `iam:GetRole` and confirm the principals match the
services in your chain. MediaConnect returns "Unable to assume role" if its
principal is missing when it is needed.

---

### Step 2: MediaPackage v2

| | |
|---|---|
| **Preconditions** | IAM role exists (Step 1) |
| **Outputs** | `channel_ingest_url`, `origin_endpoint_url` |
| **Needed by** | Step 6 (ingest URL), Step 7/8 (origin endpoint URL) |

**Actions:**

1. Create Channel Group (no `InputType` field — it is namespacing only)
2. Create Channel under the channel group with `InputType: CMAF` (or `HLS`)
3. Create Origin Endpoint (under the channel) with the desired manifest types
4. Endpoint policy — see decision below

#### Decision: Access control

```
IF building the full chain with CloudFront (Step 8):
  → Do NOT add a policy here. Leave the endpoint in default-deny.
    The OAC-scoped policy will be applied in Step 8 after the distribution
    ID is known. An open (`Principal: "*"`) policy MUST NOT be used, even
    temporarily.
IF dev/test only (no CDN, need immediate playback validation):
  → Add a scoped endpoint policy for `mediapackagev2:GetObject` with an
    `aws:SourceIp` condition restricting to the developer's IP/CIDR, or
    configure OAC from the start. Do NOT use `Principal: "*"`, even for
    testing — an open policy is easily copied to production and left in place.
```

**Validation:** `GET {origin_endpoint_url}` returns 200 (when authorized) or 403 (default-deny). If 403 from production traffic, the endpoint policy is missing or doesn't match the CDN's identity.

---

### Step 3: MediaConnect Flow

| | |
|---|---|
| **Preconditions** | VPC, subnets, security groups (Step 1) |
| **Outputs** | `flow_arn`, `flow_source_ingest_ip` |
| **Needed by** | Step 4 (MEDIACONNECT input type) or Step 5 (CDI output) |
| **Skip if** | Direct ingest (no contribution transport) |

#### Decision: Flow size

```
IF source is ST 2110 JPEG XS or CDI:
  → Large (150 Mbps) or Extra Large (400 Mbps)
  → EFA interface REQUIRED
IF source is SRT/RTP ≤80 Mbps:
  → Standard (80 Mbps)
IF source is SRT/RTP >80 Mbps:
  → Large (150 Mbps)
```

**Actions:**

1. Create flow with source configuration matching ingest protocol
2. Add VPC interfaces (EFA for CDI/ST2110, ENA otherwise)
3. Do NOT create outputs yet (need MediaLive input endpoint IPs first)

**Source-side ingest details (operationally required):**

After the flow becomes ACTIVE, read the source-side ingest details from
the flow description and hand them to the team operating the source
encoder. For SRT listener and RTP/UDP sources, the relevant fields are
`Flow.Source.IngestIp` and `Flow.Source.IngestPort` — the encoder must
connect to that IP/port pair.

The source encoder is started later in the Startup Sequence (see below);
without an active source feed, the channel will start but not produce
output.

**Validation:** `describe-flow` shows `Status: STANDBY` and source configuration is correct. Once started, `Status: ACTIVE` and CloudWatch `SourceBitRate > 0` confirms the encoder is actually delivering content.

---

### Step 4: MediaLive Input

| | |
|---|---|
| **Preconditions** | VPC, subnets (Step 1); MediaConnect flow (Step 3, if applicable) |
| **Outputs** | `input_id`, `input_endpoint_ips[]` |
| **Needed by** | Step 5 (CDI output destination), Step 6 (channel input attachment) |

#### Decision: Input type

```
IF MediaConnect is in chain AND source is NOT UHD:
  → MEDIACONNECT input type (references flow ARN directly)
  → This SKIPS Step 5 entirely (auto-wires output)
IF MediaConnect is in chain AND source IS UHD/uncompressed:
  → CDI input type
  → Step 5 is REQUIRED (manual output, same-AZ constraint)
IF no MediaConnect:
  → SRT, RTMP_PUSH, or RTP input type (direct from source encoder)
```

**Actions:**

1. Create input with selected type, VPC config, and security group
2. Capture input endpoint IPs/URLs from the response

**Pipeline redundancy (CRITICAL for STANDARD class):**

A `STANDARD`-class MediaLive channel runs two pipelines and needs two
sources of content. The shape of the input depends on input type:

- **MEDIACONNECT input type, STANDARD channel:** the input MUST reference
  TWO MediaConnect flow ARNs (one per pipeline). A single-flow input forces
  the channel into single-pipeline operation regardless of class. The two
  flows MUST be in different AZs for full AZ redundancy.
- **MEDIACONNECT input type, SINGLE_PIPELINE channel:** one flow ARN.
- **CDI input type, any class:** both subnets are provided at input
  creation. STANDARD uses both; SINGLE_PIPELINE uses one.
- **SRT, RTMP_PUSH, RTP (push-based):** STANDARD class provisions two
  ingest endpoints from a single input definition. The source encoder
  MUST push to both endpoints.
- **HLS pull, MP4 file (pull-based):** the input definition is a single
  object containing the source URL(s); both pipelines pull from it
  independently. No encoder push configuration is required.

**Validation:** `describe-input` shows `State: ATTACHED` or `DETACHED` (not `CREATING` or `DELETED`). For MEDIACONNECT inputs on STANDARD channels, confirm `MediaConnectFlows` has two entries.

---

### Step 5: MediaConnect Output (CDI only)

| | |
|---|---|
| **Preconditions** | Flow exists (Step 3), MediaLive input exists (Step 4) |
| **Outputs** | Output attached to flow |
| **Needed by** | Step 6 (content flows from source through to MediaLive) |
| **Skip if** | Using MEDIACONNECT input type (auto-wired) or no MediaConnect |

**Constraint:** MediaConnect output and MediaLive CDI input MUST be in the same AZ. Verify using AZ IDs (e.g., `use1-az1`), not AZ names.

**Actions:**

1. Create output on the MediaConnect flow targeting MediaLive input endpoint IPs
2. Set encoding names: `raw` (video), `pcm` (audio), `smpte291` (ancillary)

**Validation:** `describe-flow` shows output with `Status: ACTIVE` after flow is started.

---

### Step 6: MediaLive Channel

| | |
|---|---|
| **Preconditions** | Input (Step 4), MediaPackage ingest URL (Step 2), IAM role (Step 1) |
| **Outputs** | `channel_id` |
| **Needed by** | Startup sequence |

#### Decision: Channel class

```
IF production live event:
  → STANDARD (dual-pipeline, automatic failover)
  → LOAD references/workflow-resilience-patterns.md for pipeline redundancy, input failover, and dual-AZ patterns
IF dev/test or cost-sensitive non-critical:
  → SINGLE_PIPELINE
```

#### Decision: Output group type

```
IF destination is MediaPackage v2:
  → CmafIngestGroupSettings (NOT HlsGroupSettings)
IF destination is S3 archive:
  → ArchiveGroupSettings
IF destination is non-MediaPackage HLS:
  → HlsGroupSettings
```

**Actions:**

1. Create channel with input attachment, encoder settings, output group
2. Set output destination to the MediaPackage v2 ingest URLs from Step 2 (see Destination wiring below)
3. Configure GOP size = 2 seconds across all ABR rungs (segment duration must be an integer multiple of GOP size — e.g., 2s GOP with 6s segments)

**Destination wiring (CRITICAL for STANDARD class):**

A MediaPackage v2 channel returns two ingest endpoints (`IngestEndpoints[0]`
and `IngestEndpoints[1]`) for pipeline redundancy. A STANDARD-class
MediaLive channel's `Destinations[].Settings` array MUST contain BOTH
endpoint URLs — `[0]` for pipeline 0 and `[1]` for pipeline 1. Pumping
both pipelines into the same endpoint defeats the redundancy that STANDARD
class provides.

```
Destinations:
  - Id: emp-dest
    Settings:
      - Url: <IngestEndpoints[0].Url>   # pipeline 0
      - Url: <IngestEndpoints[1].Url>   # pipeline 1
```

For SINGLE_PIPELINE channels, use one Settings entry with `IngestEndpoints[0].Url`.

**IF using MediaTailor (ad insertion):**

- LOAD `references/workflow-ad-insertion.md` for SSAI scaling patterns and ADS configuration
- Set `Scte35Type: SCTE_35_WITHOUT_SEGMENTATION` in `CmafIngestGroupSettings`
- Enable `EXT-X-PROGRAM-DATE-TIME` in output settings
- Without both, MediaTailor will have no ad break signals

**Canonical CMAF Ingest output-group shape:**

For MediaPackage v2, the typical pattern is one shared audio output plus
one video-only output per ABR rung. This keeps a single audio rendition
across all video qualities (no audio bitrate change on ABR switches) and
matches what most production deployments do.

```yaml
OutputGroups:
  - Name: cmaf
    OutputGroupSettings:
      CmafIngestGroupSettings:
        Destination: { DestinationRefId: emp-dest }
        Scte35Type: SCTE_35_WITHOUT_SEGMENTATION   # only when SCTE-35 is in use
    Outputs:
      # Shared audio output — referenced by all video rungs via the manifest
      - OutputName: audio_aac
        AudioDescriptionNames: [audio_shared]
        OutputSettings:
          CmafIngestOutputSettings: { NameModifier: _audio }
      # Video-only outputs per rung
      - OutputName: video_1080p
        VideoDescriptionName: video_1080p
        OutputSettings:
          CmafIngestOutputSettings: { NameModifier: _1080p }
      - OutputName: video_720p
        VideoDescriptionName: video_720p
        OutputSettings:
          CmafIngestOutputSettings: { NameModifier: _720p }
      - OutputName: video_480p
        VideoDescriptionName: video_480p
        OutputSettings:
          CmafIngestOutputSettings: { NameModifier: _480p }
```

`AudioDescriptions[]` defines `audio_shared` once. `VideoDescriptions[]`
defines `video_1080p` / `video_720p` / `video_480p`. Multiple language
tracks are added by defining additional AudioDescriptions and additional
audio-only Outputs (one per language).

**Validation:** `describe-channel` shows `State: IDLE`. Channel is ready to start.

---

### Step 7: MediaTailor (optional)

| | |
|---|---|
| **Preconditions** | MediaPackage origin endpoint URL (Step 2), ADS URL from customer |
| **Outputs** | `mediatailor_playback_url` |
| **Needed by** | Step 8 (CloudFront origin) |
| **Skip if** | No ad insertion needed |

**Actions:**

1. Create playback configuration with video content source and ADS URL
2. Configure CDN prefixes (content and ad segment)
3. Configure slate URL (shown when no ad fills the break)

**Validation:** `GET {mediatailor_playback_url}` returns a rewritten manifest with MediaTailor session tokens.

---

### Step 8: CloudFront Distribution (REQUIRED for production)

| | |
|---|---|
| **Preconditions** | MediaTailor URL (Step 7) or MediaPackage endpoint URL (Step 2) |
| **Outputs** | `distribution_domain_name` (viewer-facing URL) |
| **Needed by** | Viewers |

A CDN is REQUIRED for any production live workflow. MediaPackage v2 has a
1000 RPS hard limit and will not scale to viewer traffic without a CDN
fronting it. Every CDN that pulls from MediaPackage v2 MUST have Origin
Shield enabled.

Skip this step ONLY for dev/test workflows where viewer count is bounded
and origin RPS is well below the limit.

#### Decision: Origin

```
IF using MediaTailor:
  → Origin = MediaTailor playback URL
  → MediaTailor session init (POST) requires AllowedMethods to include POST
IF no MediaTailor:
  → Origin = MediaPackage v2 origin endpoint URL
  → Configure OAC (Origin Access Control), and set the MediaPackage v2
    endpoint policy to allow only this distribution
```

**Actions:**

1. Create custom cache policies (MUST be created before the distribution):
   - Manifest cache policy: DefaultTTL = half the segment duration configured on MediaPackage (e.g., 3s for 6s segments). If using MediaTailor personalized manifests, TTL MUST be 0 (unique per viewer, MUST NOT be cached).
   - Segment cache policy: MinTTL=86400, DefaultTTL=86400, MaxTTL=86400 (segments are immutable).
   - Managed `CachingOptimized` MUST NOT be used for manifest behaviors. It sets a 24-hour default TTL that causes stale manifests.
2. Set `ViewerProtocolPolicy: redirect-to-https` on all cache behaviors to enforce encryption in transit. If using a custom domain (CNAME), attach an ACM certificate provisioned in us-east-1 and set minimum protocol version to `TLSv1.2_2021`.
3. Create OAC (Origin Access Control):
   - Origin type: `mediapackagev2`
   - Signing protocol: SigV4
   - Signing behavior: Always
4. Create the CloudFront distribution with MediaPackage v2 origin, attach the OAC from step 3. Capture the **distribution ID** from the response.
5. MUST update the MediaPackage v2 endpoint policy to allow ONLY this distribution. This step is REQUIRED — without it, CloudFront receives 403 from the endpoint. The policy requires the distribution ARN from step 4:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "AllowCloudFrontOAC",
       "Effect": "Allow",
       "Principal": {"Service": "cloudfront.amazonaws.com"},
       "Action": "mediapackagev2:GetObject",
       "Resource": "<origin-endpoint-ARN>",
       "Condition": {
         "StringEquals": {
           "AWS:SourceArn": "arn:aws:cloudfront::<account>:distribution/<distribution-ID>",
           "aws:SourceAccount": "<account>"
         }
       }
     }]
   }
   ```

   This replaces any prior testing policy (e.g., an `aws:SourceIp`-scoped dev policy). If the endpoint had no policy before this step, CloudFront will return 403 until this policy is applied — that is expected and correct. Do NOT fall back to a permissive policy to avoid the transient 403.
   If MediaTailor SSAI is used (Step 7), additionally allow `mediatailor.amazonaws.com` with action `mediapackagev2:GetObject` in the same endpoint policy. MediaTailor fetches origin manifests directly from MediaPackage, not through CloudFront. Scope this service-principal grant against cross-service confused-deputy abuse: agents **MUST** add an `aws:SourceAccount` (your account id) condition and **SHOULD** add `aws:SourceArn` (the playback-configuration ARN), so only your own MediaTailor configurations can exercise it.
6. Configure cache behaviors using the cache policy IDs from step 1:
   - Default behavior (manifests .m3u8, .mpd): manifest cache policy. Compress=true.
   - Segment behaviors (.m4s, .cmfv, .cmfa, .ts): segment cache policy. Compress=false.
7. Set error caching TTL = 1 second for all error codes (403, 404, 500, 502, 503, 504)
8. Enable Origin Shield (region closest to origin)
9. Forward all query strings and `User-Agent` header (required for MediaTailor ADS targeting)

**Constraint:** OAC MUST be configured when CloudFront fronts MediaPackage v2. Without it, the origin endpoint remains publicly accessible, exposing it to DDoS and bypassing the CDN's 1000 RPS protection. Agents MUST NOT leave endpoints with `Principal: "*"` after adding CloudFront.

**Constraint:** Cache policies are a prerequisite dependency. The `create-cache-policy` calls MUST complete and return policy IDs BEFORE calling `create-distribution`. Do NOT substitute managed policies to avoid this step.

**Validation:** `GET https://{distribution_domain_name}/{manifest_path}` returns `#EXTM3U` with expected variant streams.

**Logging:** Enable CloudFront standard logging (v2) to S3 for operational visibility. For high-concurrency live events, enable real-time logs to Kinesis Data Streams for seconds-latency debugging of cache behavior and viewer errors.

---

## Startup Sequence

Start upstream first. Poll each resource to its running state before proceeding.

| Order | Action | Poll | Ready state | Notes |
|-------|--------|------|-------------|-------|
| 1 | `start-flow` (MediaConnect) | `Flow.Status` | `ACTIVE` | Billing starts here |
| 1b | (Router input only) Confirm router I/Os are Active and a route is assigned to the MediaLive-facing output | I/O state / route | Active + route assigned | Content flows only once a route is "taken" to the output |
| 2 | Start source encoder | CloudWatch `SourceBitRate > 0` | — | Confirm content flowing |
| 3 | `start-channel` (MediaLive) | `State` | `RUNNING` | Async — poll until RUNNING; large channels take longer |
| 4 | Verify end-to-end | GET manifest URL | `#EXTM3U` with variants | Check `IngressBytes > 0` |

**MediaConnect Router startup:** When using a MediaConnect Router (MediaConnect router input type), start the router I/Os (Standby→Active) and the MediaLive channel. Content reaches the MediaLive input only once the router I/Os are Active AND a route has been assigned ("taken") to the output feeding that input — there is no separate "enable output" API. Per the AWS setup order, routes may be assigned before or after starting the I/Os.

## Shutdown Sequence

Reverse of startup. Poll each resource to its stopped state before proceeding.

| Order | Action | Poll | Stopped state | Notes |
|-------|--------|------|---------------|-------|
| 1 | `stop-channel` (MediaLive) | `State` | `IDLE` | — |
| 2 | Stop source encoder | — | — | — |
| 3 | `stop-flow` (MediaConnect) | `Flow.Status` | `STANDBY` | Billing stops here |

**Lifecycle reminder:** A flow left in `ACTIVE` and a channel left in
`RUNNING` continue to bill until explicitly stopped. After any non-permanent
event (test runs, recurring linear windows that have a defined off-period,
post-event teardown), confirm both resources are in their stopped state.
For long-lived 24/7 channels, this guidance applies only to the test/staging
copies — production-linear channels are expected to stay running.
