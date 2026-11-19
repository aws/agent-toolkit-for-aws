# Service Rules: Core (Cross-Service)

This file is ALWAYS loaded by the skill. It contains:

- Common agent mistakes that span multiple services
- Inter-service compatibility constraints (IAM, AZ alignment, codec/packaging compat, MediaLive→MediaPackage handoff, MediaTailor prerequisites, CloudFront origin compat)

Per-service rules live in companion files (`service-rules-mediaconnect.md`, `service-rules-medialive.md`, etc.) and are loaded conditionally based on the task.

---

## Common Agent Mistakes

Verified corrections for behaviors that AI agents frequently get wrong. When your
pre-training conflicts with these statements, trust this file.

- After presenting a plan, the agent MUST wait for explicit user approval before making any tool calls, API calls, or resource modifications. The agent MUST NOT interpret the act of presenting a plan as implicit authorization to execute it.
- **Destructive actions on live MediaPackage v2 endpoints:** Agents MUST NOT delete, replace, or recreate origin endpoints that may be serving active viewer sessions. Deleting an in-use endpoint immediately terminates ALL viewer streams using that endpoint's URL. When a configuration change is needed (e.g., changing segment format from TS to CMAF), agents MUST update the existing endpoint in-place or create a NEW endpoint alongside the existing one — NEVER delete-then-recreate. Before any delete operation on a MediaPackage v2 origin endpoint, agents MUST ask the user to confirm the endpoint is not serving production traffic.
- MediaConnect billing continues while flow is `ACTIVE`, even with zero outputs. Flows SHOULD be stopped when not in use.
- MediaConnect and MediaLive "input security groups" are NOT VPC security groups. They are service-specific CIDR allowlists. Agents MUST NOT conflate these with EC2/VPC security groups.
- VPC interface flows MUST have TWO subnets in different AZs, even for SINGLE_PIPELINE channels.
- A MediaConnect flow MUST NOT have more than 1 EFA interface. The second interface MUST be ENA type. EFA is REQUIRED for CDI and ST 2110 JPEG XS sources.
- MediaLive `STARTING` does not indicate a running state. Agents MUST poll `State` until `RUNNING` before proceeding. The same applies to `STOPPING`; agents MUST wait for `IDLE`.
- MediaLive supports H.264, H.265 (HEVC), and MPEG-2 as input video codecs across input types. RTMP push inputs are limited to H.264. HLS pull inputs accept H.264 and H.265 (HEVC). Verify the current MediaLive supported-input matrix when working with less common codec/container combinations.
- MediaConnect is codec-agnostic for transport stream flows. It transports whatever is in the container without decoding.
- Segment duration MUST be an integer multiple of GOP size. A 2-second GOP fits cleanly into 2/4/6/8-second segments. A 2-second GOP SHOULD be used unless the workflow has specific requirements for a different value. Segment duration conventions differ by output protocol: HLS endpoints SHOULD use 6-second segments (per Apple HLS Authoring Specification); DASH endpoints SHOULD use 2-second segments (industry convention for faster ABR adaptation). A 2-second GOP satisfies both (6s = 3×GOP, 2s = 1×GOP). GOP size MUST be identical across all ABR rungs. For Low-Latency HLS (LL-HLS), GOP size SHOULD be 1 second to match the shorter segment/part duration.
- MediaConvert direct regional endpoints (e.g., `https://mediaconvert.us-west-2.amazonaws.com`) are supported and SHOULD be used. Agents MUST NOT hardcode account-specific endpoint URLs, and SHOULD NOT call `describe-endpoints` to discover them.
- MediaPackage v2 origin endpoints have a 1000 RPS hard limit (verify current value from [Service Quotas](https://docs.aws.amazon.com/mediapackage/latest/userguide/quotas.html)) and do not auto-scale. Production deployments MUST front MediaPackage v2 with a CDN, and every CDN origin pulling from MediaPackage v2 MUST have Origin Shield enabled. Single-CDN deployments without Origin Shield can exhaust the origin capacity at well below 1000 RPS due to per-POP request fan-out.
- A MediaPackage v2 endpoint policy is REQUIRED for CloudFront access. Without it, CloudFront receives 403. This is a two-pass operation: the policy requires the CloudFront distribution ARN, which doesn't exist until the distribution is created. Create the endpoint first (Step 2), create the CloudFront distribution (Step 8), then update the endpoint policy with the distribution ARN.
- MediaPackage v2 MUST NOT be used for epoch locking. Epoch locking REQUIRES a passthrough origin.
- MediaPackage v2 supports both CMAF ingest (fMP4) and HLS ingest (TS). The MediaLive output group type MUST match the MediaPackage channel's `InputType`. `CmafIngestGroupSettings` is RECOMMENDED for new workflows. `HlsGroupSettings` with CDN setting `hls basic put` MAY be used when the channel InputType is HLS.
- MediaTailor MUST NOT be described as capable of injecting SCTE-35 markers. It only consumes markers from upstream (MediaLive).
- Ad avail mode MUST be configured in MediaLive. It MUST NOT be configured in MediaTailor.
- MediaTailor prefetch is NOT enabled by default. It MUST be explicitly configured when needed.
- CloudFront error caching TTL for live streaming SHOULD be set to a low value (around 1 second) for all error codes (403, 404, 500, 502, 503, 504). The default 5-minute TTL MUST NOT be used for live workflows — it causes player stalls and prevents fast recovery from transient origin errors.
- CloudFront Origin Shield is SEPARATE from regional edge cache. It MUST be explicitly enabled.
- Separate cache behaviors MUST be configured for manifests vs segments. A single cache behavior MUST NOT serve both.
- CDI REQUIRES same-AZ placement. Agents MUST use AZ IDs (`use1-az1`), NOT AZ names (`us-east-1a`), because names differ across accounts.
- IAM roles for MediaLive MUST include `sts:TagSession` permission. Without it, channel creation fails.
- Resource creation order: MediaPackage channel MUST exist before MediaLive channel. MediaLive input MUST exist before MediaConnect output.
- To pass SCTE-35 markers through a CMAF Ingest output group, `Scte35Type` in `CmafIngestGroupSettings` MUST be set to `SCTE_35_WITHOUT_SEGMENTATION`. The value `SCTE_35_ENHANCED` MUST NOT be used; it is not a valid enum value.
- Agents MUST ask the user for resource naming preferences before creating resources. If the user hasn't specified names, ask once (e.g., "What prefix or naming convention should I use for these resources?"). Agents MUST NOT invent resource names without user input.
- When any resource reference changes (new S3 bucket, different MediaPackage channel, switched account), agents MUST verify and update ALL IAM policies that reference the old resource. This includes MediaLive execution role S3 permissions, MediaConvert role bucket policies, and MediaPackage endpoint policies. Failure to update IAM after changing resource references is a common cause of silent failures that agents misdiagnose.
- When stating that a feature or configuration is incompatible with another, agents MUST always provide the recommended alternative or workaround in the same response — do not just state the incompatibility without giving the user a path forward.
- Agents MUST NOT use `Resource: "*"` or `Action: "*"` in IAM policies as a troubleshooting shortcut. Policies MUST be scoped to specific resource ARNs. If a permission error occurs, agents MUST identify the specific resource ARN that needs access and add only that permission — not broaden the policy to all resources.

---

## Inter-Service Compatibility Rules

### IAM trust policies

- A shared role MAY be used if the trust policy includes ALL services in use.
- Required service principals: include exactly the principals for services that actually use the role. For live, that means `medialive.amazonaws.com` always, plus `mediaconnect.amazonaws.com` only when MediaConnect is in the chain. For VOD: `mediaconvert.amazonaws.com`. Adding unused principals is harmless but creates configuration drift.
- `sts:TagSession` MUST be included in the Action array alongside `sts:AssumeRole`.
- The trust policy MUST be verified BEFORE creating resources.
- For MEDIACONNECT input types, the role needs `mediaconnect:ManagedDescribeFlow`, `ManagedAddOutput`, and `ManagedRemoveOutput`. These actions require Resource `arn:aws:mediaconnect:<region>:<account>:flow:*` AND `arn:aws:mediaconnect:<region>:<account>:output:*`. Specific flow ARNs do NOT work — MediaLive validates against the output resource type at input creation time.

### AZ alignment (critical for CDI)

- CDI: MediaConnect output and MediaLive input MUST be in the same AZ.
- ST 2110 JPEG XS: supports cross-AZ transfers (no AZ constraint).
- SRT/RTMP/RTP: no AZ constraint (uses IP networking).
- Subnet AZs MUST be confirmed to match before creating CDI resources.

### Security groups

- ST 2110: separate UDP ports per essence. ALL ports MUST be open (video, audio, ancillary).
- CDI between MediaConnect and MediaLive: a self-referencing security group rule is REQUIRED (same SG on both).
- Source ingest rules MUST be scoped to source CIDR. 0.0.0.0/0 MUST NOT be used.
- MediaLive outputs to MediaPackage: no SG rules are needed (uses HTTPS).

### Codec to packaging compatibility

- H.264 + HLS: universally compatible.
- H.265 + HLS: REQUIRES fMP4 segments (not MPEG-TS).
- CMAF: supports both H.264 and H.265 (always fMP4).

### MediaLive to MediaPackage ingest compatibility

- CMAF ingest (`CmafIngestGroupSettings`) is RECOMMENDED for MediaPackage v2. HLS ingest (`HlsGroupSettings` with `hls basic put`) is also supported when the channel InputType is HLS. Output group type MUST match the channel's InputType.
- MediaPackage segment duration MUST be an integer multiple of MediaLive GOP size (e.g., 2-second GOP with 6-second segments).
- All ABR rungs MUST use the same GOP size.

### MediaTailor prerequisites from upstream

- MediaLive MUST pass SCTE-35 markers (configure `Scte35Behavior` in M3u8Settings for HLS output groups, or `Scte35Type` in CmafIngestGroupSettings for CMAF ingest).
- MediaLive MUST include `EXT-X-PROGRAM-DATE-TIME` in HLS/CMAF output.
- MediaPackage MUST expose SCTE-35 in the manifest.
- MediaPackage endpoint policy MUST allow `mediatailor.amazonaws.com` with action `mediapackagev2:GetObject` when OAC restricts the endpoint to CloudFront-only. MediaTailor fetches the origin manifest directly from MediaPackage, not through CloudFront. Without this, MediaTailor returns 504 (gateway timeout) because it cannot read the upstream manifest.
- Without the first three prerequisites, MediaTailor ad insertion will not function. The fourth (endpoint policy for mediatailor.amazonaws.com) is additionally required when OAC restricts the endpoint.

### MediaConnect to MediaLive handoff

- For uncompressed UHD, CDI MUST be used. Same AZ is REQUIRED. EFA interface is REQUIRED on the MediaConnect flow.
- For compressed UHD (HEVC/H.264 at high bitrate), the native MEDIACONNECT input type with a Large or Extra Large flow MUST be used. CDI is NOT required and the same-AZ constraint does NOT apply.
- For everything else, the native MEDIACONNECT input type SHOULD be used. MediaLive auto-creates/removes the flow output. Agents MUST NOT call `add-flow-outputs` for this input type.

### MediaConnect Router ↔ MediaLive

- Router I/O and MediaLive pipeline MUST be in the same AZ and same region.
- MediaLive input type MUST be "MediaConnect router" when connecting to the Router. This is NOT the same as the MEDIACONNECT input type (which is for flows).
- Encryption scheme on the Router side MUST match the MediaLive side (automatic key or Secrets Manager).
- A MediaLive resource (input or channel output) can connect to only one router I/O at a time.
- Connected resources MUST be disconnected before deletion.
- IAM: MediaLive needs `MediaLiveAccessRole` or a custom role with permissions to interact with MediaConnect (`medialive:UpdateInput`, `medialive:UpdateChannel`).

### Router vs Flows (decision criteria)

- Router: dynamic any-to-any switching, master control, playout, ≤50 Mbps, cross-region with adaptive multipath.
- Flows: CDI/ST 2110/NDI/Zixi protocols, >50 Mbps, entitlements (cross-account sharing), static point-to-point contribution.
- If both dynamic switching AND high bitrate are needed: use Flows for transport, Router for downstream switching.

### CloudFront to origin compatibility

- MediaPackage v2 origin: HTTPS origin protocol MUST be used. All query strings MUST be forwarded.
- MediaTailor origin: the session initialization URL MUST be used as origin.
- S3 origin (VOD): OAC MUST be used. Bucket policy MUST be restricted to the CloudFront distribution.
- For MediaPackage v2 access control, CloudFront OAC with an endpoint policy SHOULD be the default. The CDN-authorization-header pattern (custom origin header `X-MediaPackageV2-CDNIdentifier` matched in the endpoint policy) MAY be used for multi-CDN deployments where OAC is not available on every CDN. Plain custom origin headers without a corresponding endpoint policy MUST NOT be relied on as access control — they are not authentication.
- Resource policies (endpoint policies, bucket policies) MUST include `aws:SourceArn` or `aws:SourceAccount` condition keys to prevent confused-deputy attacks, regardless of which access-control mechanism is used.

---

## Security Considerations

This section consolidates security requirements and risks specific to AWS media services workflows.

### Credentials and secrets

- SRT passphrases, DRM key provider credentials, and CDN authorization secrets MUST be stored in AWS Secrets Manager. Agents MUST NOT embed secrets inline in API calls or templates.
- IAM roles (ephemeral credentials) MUST be used. IAM users with static access keys MUST NOT be created for media service access.

### IAM and access control

- Roles MUST use least-privilege policies scoped to specific resources. `*FullAccess` managed policies (e.g., `AmazonMediaLiveFullAccess`) MUST NOT be attached to service roles.
- Trust policies MUST include only the required service principals and MUST include `sts:TagSession` alongside `sts:AssumeRole`.
- MediaPackage v2 endpoints deny all access by default. An endpoint policy MUST be attached before playback will function.
- Production endpoints MUST NOT retain `Principal: "*"`. Use OAC to restrict access to CloudFront only.

### Network security

- Source ingest security groups MUST be scoped to the source CIDR. `0.0.0.0/0` MUST NOT be used.
- SRT passphrase length MUST be ≥10 characters.
- ST 2110 UDP ports MUST be scoped to the source CIDR per the SDP.

### Origin protection

- CloudFront OAC MUST be configured for all production MediaPackage v2 and S3 origins. OAC uses SigV4 signing — no shared secrets, cannot be spoofed.
- Origin Shield MUST be enabled to protect against the 1000 RPS origin limit.
- WAF + Shield Advanced is RECOMMENDED for all production CloudFront distributions.

### Encryption

- DRM (SPEKE v2 with FairPlay/Widevine/PlayReady) SHOULD be used for premium content.
- AES-128 clear key MUST NOT be used with H.265/HEVC — it is only valid with H.264 in MPEG-TS.
- S3 buckets used for media SHOULD enable SSE-KMS or SSE-S3 encryption at rest.

### Auditing and logging

- A CloudTrail trail SHOULD be created for persistent logging of all AWS media services API calls to S3. CloudTrail is enabled by default but only retains 90 days in Event History without a trail.
- CloudFront standard logging (v2) SHOULD be enabled to S3 for cache-hit analysis, error debugging, and viewer analytics.
- For high-concurrency live events, CloudFront real-time logs SHOULD be enabled to Kinesis Data Streams for seconds-latency operational visibility.
- CloudTrail S3 destination MUST use SSE-KMS encryption. CloudWatch Log Groups used by media services SHOULD have KMS encryption enabled to protect operational metadata. S3 access-log buckets SHOULD enable SSE-S3 at minimum. Kinesis Data Streams used for real-time logs SHOULD enable server-side encryption (SSE) with a KMS key.

### Risks specific to media workflows

- **Direct origin access**: without OAC, anyone with the MediaPackage endpoint URL can pull content directly, bypassing CDN protections and potentially exhausting the 1000 RPS limit.
- **Stale endpoint policies**: deleting CloudFront and forgetting to update the endpoint policy leaves the origin open.
- **SRT without encryption**: SRT supports AES-128/256 passphrase encryption. Unencrypted SRT over the public internet exposes content to interception.
- **Over-permissioned roles**: a role trusted by `medialive.amazonaws.com` with broad S3 access can be used to exfiltrate data from any bucket it can reach.

For additional guidance, refer to the [AWS Well-Architected Framework — Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/) and the security chapters in individual AWS media services documentation.
