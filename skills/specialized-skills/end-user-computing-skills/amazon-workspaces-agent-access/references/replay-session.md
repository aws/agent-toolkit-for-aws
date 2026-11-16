# Replay Session (recording agent sessions and retrieving the audit trail)

**Replay Session** records a reviewable audit trail of an agent's session on a WorkSpaces
Applications stack and delivers it to **your own S3 bucket**. Each session produces a
semantic transcript, a stitched screen recording, and a self-contained HTML report. There is
no console viewer for recordings: you retrieve them from the bucket.

Two halves, both covered here: an administrator **enables** it on the stack, and a reviewer
**retrieves** the artifacts afterwards.

## Enabling Replay Session on a stack

Replay Session is a field on the stack's `AgentAccessConfig` (the `setting-up-workspaces-applications`
skill covers that structure). Set `ReplaySessionEnabled: true` on `CreateStack` or `UpdateStack`. Two
fields matter:

| Field | Meaning |
|---|---|
| `ReplaySessionEnabled` | `true` records every session on the stack. Default `false`. |
| `KmsKeyArn` | Optional customer-managed KMS key for the captured frames. See Encryption below for exactly what it covers. |

**Prerequisites, all enforced at `CreateStack`/`UpdateStack`:**

- `COMPUTER_VISION` must be `ENABLED` — capture is screenshot-based.
- `S3BucketArn` must be set, and the bucket must exist and be owned by your account.
- `KmsKeyArn` requires `ReplaySessionEnabled: true`.
- `KmsKeyArn` must be a **key ARN** (`arn:aws:kms:<region>:<account>:key/<id>`). An alias ARN
  is rejected by the API contract; nothing resolves one for you.
- The key must resolve in the **stack's Region**, be enabled, and be a symmetric encryption
  key usable for encrypt and decrypt. The service validates it with `kms:DescribeKey` under
  your own credentials at configuration time, so you need that permission on the key.
- Not supported on **image builders** — only on stacks.

To turn Replay Session off or clear `KmsKeyArn` later: `UpdateStack` merges `AgentAccessConfig`,
so a field you leave out keeps its value. Send an explicit `"ReplaySessionEnabled": false`, and use
`--attributes-to-delete AGENT_ACCESS_CONFIG_KMS_KEY_ARN` to clear the key.

## Where the artifacts land

```text
s3://<your-bucket>/agentaccess/replay-session/year={YYYY}/month={MM}/day={DD}/{mcp-session-id}/
    ├── replay_session_transcript.json   # semantic transcript of the agent's actions
    ├── replay_session_video.mp4         # stitched screen recording
    └── replay_session_report.html       # self-contained reviewable report
```

- The date is the session's **start** time in **UTC**, not the delivery date or local time.
- The leaf is the **MCP session ID** (`get_session_info` → `mcpSessionId`), not the streaming
  session ID.

Delivery is performed as **your own IAM identity**: the one that signs the agent's MCP
requests. That identity needs `s3:PutObject` on
`arn:aws:s3:::your-bucket/agentaccess/replay-session/*`, with `"StringEquals": {"s3:ResourceAccount": "<account>"}` so a bucket of the same name in another account never receives recordings; without it, no recording arrives. The same permission lets the agent's identity overwrite a delivered transcript, report or video, so protect the prefix as below. If
the bucket's default encryption is SSE-KMS with your own key, it also needs
`kms:GenerateDataKey` and `kms:Decrypt` on that bucket key: the video is uploaded in parts,
which needs both, so without `kms:Decrypt` only the transcript and report arrive. Separately,
if the stack sets `KmsKeyArn`, the same identity needs the permissions in "Key policy for
`KmsKeyArn`" below.

### Protecting the delivered recordings

Turn on versioning and S3 Object Lock on the bucket, which keep every earlier copy of an
object that is overwritten. Then add a bucket policy statement that refuses a write to the
prefix unless it arrives through Agent Access:

```json
{
  "Sid": "DenyReplayWritesNotViaAgentAccess",
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:PutObject", "s3:DeleteObject"],
  "Resource": "arn:aws:s3:::EXAMPLE-BUCKET/agentaccess/replay-session/*",
  "Condition": {
    "StringNotEqualsIfExists": {
      "aws:CalledViaAWSMCP": "agentaccess-mcp.amazonaws.com"
    }
  }
}
```

Delivery is made with the credentials Agent Access forwards, so it carries that key and is
allowed, while the same identity calling S3 directly is denied. If the agent reaches several
AWS MCP servers and any of them may write here, condition on the boolean instead:

```json
{
  "Sid": "DenyReplayWritesNotViaAnMcpService",
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:PutObject", "s3:DeleteObject"],
  "Resource": "arn:aws:s3:::EXAMPLE-BUCKET/agentaccess/replay-session/*",
  "Condition": {
    "BoolIfExists": { "aws:ViaAWSMCPService": "false" }
  }
}
```

Either statement also denies a person or a tool writing to the prefix with their own
credentials, so keep anything that has to write there outside it. Reading is unaffected.
Check that a recording still arrives for the next session after you add the statement,
because a write the condition refuses is denied silently rather than reported to the agent.

### Retrieving them

```bash
# Every session recorded on a given day
aws s3 ls s3://your-bucket/agentaccess/replay-session/year=2026/month=03/day=14/

# One session's artifacts
aws s3 ls s3://your-bucket/agentaccess/replay-session/year=2026/month=03/day=14/<mcp-session-id>/

# Download all three
aws s3 cp s3://your-bucket/agentaccess/replay-session/year=2026/month=03/day=14/<mcp-session-id>/ \
    ./replay/ --recursive
```

Open `replay_session_report.html` in a browser to play the video alongside a searchable
transcript. Keep the three files in the same folder; the report links to the transcript next
to it.

**If you know the session ID but not its start date, search rather than guess the partition:**

```bash
aws s3api list-objects-v2 \
    --bucket your-bucket \
    --prefix agentaccess/replay-session/ \
    --query "Contents[?contains(Key, '<mcp-session-id>')].Key" \
    --output text
```

That scans every partition, so narrow `--prefix` to the year or month whenever you can
(`agentaccess/replay-session/year=2026/month=03/`).

### When they appear

**Nothing appears while the session is running.** The transcript, video, and report are
produced after the MCP session closes (the client's HTTP `DELETE`). A short session is
typically delivered about a minute after it closes; processing time grows with session
length. Poll the prefix rather than treating the first empty listing as failure.

## Fallback content (when processing fails)

A `replay_fallback_content/` directory in the session folder means processing failed. It holds
the raw capture: `frames/` (pre-action screenshots), `metadata/` (per-action JSON) and
`results/` (tool results). Together with whichever `replay_session_*` files completed, they
still show what the agent did, action by action. Fallback content is not encrypted with
`KmsKeyArn`; your bucket's default encryption applies, as for the other artifacts, and reading
it never needs `KmsKeyArn`.

## Monitoring

Each time a session's recording is processed, Replay Session publishes one of two CloudWatch
metrics to **your** AWS account, in the namespace `AWS/AgentAccessMCP`:

- `ReplaySessionSucceeded` — the transcript, video and report were delivered to your bucket.
- `ReplaySessionFailed` — processing or delivery failed. Whatever was produced (the raw
  capture in `replay_fallback_content/` plus any completed artifacts) is delivered where
  possible.

Alarm on `ReplaySessionFailed`, on `ReplaySessionSucceeded` going missing while agents run,
and on CloudTrail `DisableKey` and `PutKeyPolicy` events for the `KmsKeyArn` key, which
block every desktop action.

## Reading the transcript

`replay_session_transcript.json` records each action's exact tool call (`tool_name`,
`arguments`); treat that as the record of what happened. The per-frame `inferred` fields and
the `session_summary` are AI-generated interpretations.

## How capture behaves

- Each frame shows the screen **before** the action ran, so the last action's result has no
  frame.
- Only desktop actions are captured; `screenshot` and `get_session_info` calls produce no frame.
- An `execute_sequence` call gets one frame, taken before it runs. A window opened and closed
  inside a sequence shows only in the transcript, so read the transcript for sequences.
- Capture is **fail-closed**: if a frame cannot be captured or stored, the action is rejected
  and does not run. The tool returns an error such as `Replay Session enabled but action
  blocked due to internal service error.` When the customer-managed key is the cause, the
  message includes the KMS error code and operation, for example `The customer managed key
  call failed. KMS returned AccessDeniedException for GenerateDataKey: ...`. Fix the key
  rather than retrying the same call (see Encryption below and troubleshooting.md).

## Permissions to read the artifacts

On your own bucket, the reader needs:

- `s3:ListBucket`, scoped with an `s3:prefix` condition of `agentaccess/replay-session/*`
- `s3:GetObject` on `arn:aws:s3:::your-bucket/agentaccess/replay-session/*`
- `kms:Decrypt` **only if** you configured your bucket's default encryption as SSE-KMS with
  your own key — see below

## Encryption — what `KmsKeyArn` does and does not cover

- `KmsKeyArn` encrypts the **captured frames, their per-frame metadata, and the pipeline's
  intermediate artifact checkpoints while they are held in AWS-managed storage**,
  client-side with the AWS Encryption SDK. That temporary AWS-managed storage is its whole
  scope.
- **Objects delivered to your bucket carry no service-supplied encryption header.** Your
  bucket's **default encryption** therefore applies, exactly as it would for an object you
  wrote yourself; set it to SSE-KMS with your own key if you want a key to cover them.

### Key policy for `KmsKeyArn`

- The key is used with **your own credentials**, forwarded by Agent Access: the identity that
  creates or updates the stack, and the identity the agent signs its MCP requests with. It is
  not used by a service principal, so do not add one to the key policy.
- The key policy must let the agent's signing identity call `kms:GenerateDataKey`,
  `kms:Decrypt` and `kms:DescribeKey`, and the identity that creates or updates the stack call
  `kms:DescribeKey`, when the request comes through Agent Access. Condition the agent's
  statement on `kms:CallerAccount` (your account ID) and `kms:ViaService`
  (`agentaccess-mcp.<region>.amazonaws.com`) rather than a blanket allow. For the stack
  identity's `kms:DescribeKey`, use the `kms:ViaService` value in the current
  [Agent Access documentation](https://docs.aws.amazon.com/appstream2/latest/developerguide/agent-access-mcp-server.html).
- If the key later becomes unusable (policy changed, key disabled), every desktop action is
  blocked with a KMS error, and the raw frames can't be delivered as fallback content either.
  See "How capture behaves" above.
