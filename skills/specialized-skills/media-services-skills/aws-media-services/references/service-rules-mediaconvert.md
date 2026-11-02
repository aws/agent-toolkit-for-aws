# Service Rules: MediaConvert

Loaded conditionally when the task involves MediaConvert. The cross-service rules in `service-rules-core.md` are always loaded alongside this file.

---

## MediaConvert

### IAM

- Role MUST trust `mediaconvert.amazonaws.com`.
- Role MUST have `s3:GetObject` on source bucket and `s3:PutObject` on destination bucket.
- If using DRM/SPEKE, role MUST also have access to the key provider.

### Job configuration

- For ABR output, output group type MUST be one of: `HLS_GROUP_SETTINGS`, `DASH_ISO_GROUP_SETTINGS`, or `CMAF_GROUP_SETTINGS`.
- Accelerated transcoding (`AccelerationSettings.Mode: PREFERRED` or `ENABLED`) is only available for certain codecs and resolutions.
- `TimecodeConfig.Source` MUST be set at job level when using accelerated transcoding. The job-wide setting MUST NOT be `EMBEDDED` (use `SPECIFIEDSTART` or `ZEROBASED`). The per-input `TimecodeSource` MAY be set to `EMBEDDED`, but the job-level `TimecodeConfig.Source` MUST NOT.

### Output paths

- MediaConvert appends the output group name and name modifier to the destination path. Agents MUST NOT assume exact output file paths; they SHOULD check `OutputGroupDetails` in the job result.

### Job queue

- A default on-demand queue exists in every account (no setup REQUIRED).
- Reserved queues MAY be used for lower per-minute cost with upfront commitment.

---
