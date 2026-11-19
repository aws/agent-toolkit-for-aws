# Migration Execution

This reference covers three stages: **Plan Generation**, **Execution**, and **Validation**. Proceed through whichever stage the conversation has reached.

> **V1 SAFETY:** NEVER modify or delete v1 resources. Only v2 create/list/describe commands are permitted during execution.

---

## Contents

- **Phase 5: Plan Generation**
  - [Step 1: Begin](#step-1-begin)
  - [Step 1.5: Confirm CLI capability before choosing a format](#step-15-confirm-cli-capability-before-choosing-a-format)
  - [Step 2: Ask Output Format](#step-2-ask-output-format)
  - [Step 3: Load Migration Plan](#step-3-load-migration-plan)
  - [Step 4: Generate Plan](#step-4-generate-plan)
  - [Step 5: Present Plan Summary](#step-5-present-plan-summary)
  - [Step 6: Save Plan](#step-6-save-plan)
  - [Step 7: Hand Off](#step-7-hand-off)
- **Phase 6: Execution**
  - [Step 1: Begin](#step-1-begin)
  - [Step 2: Idempotency Check](#step-2-idempotency-check)
  - [Step 3: Create Resources (in order)](#step-3-create-resources-in-order)
  - [Step 4: Error Handling](#step-4-error-handling)
  - [Step 5: Execution Summary](#step-5-execution-summary)
  - [Step 5.5: Persist Execution Results](#step-55-persist-execution-results)
  - [Step 6: Hand Off](#step-6-hand-off)
- **Phase 7: Validation**
  - [Step 1: Begin](#step-1-begin)
  - [Step 2: Enumerate Created Resources](#step-2-enumerate-created-resources)
  - [Step 3: Compare Against Plan](#step-3-compare-against-plan)
  - [Step 4: Validation Summary](#step-4-validation-summary)
  - [Step 5: Final Summary](#step-5-final-summary)

---

# Phase 5: Plan Generation

## Step 1: Begin

Work from the confirmed channel-group + endpoint plan.

> **Do not start here.** Generating artifacts requires an approved plan. If the
> user jumped straight to "generate the script", confirm the inventory, the
> channel-group plan, the endpoint mappings, and the pre-flight validation
> (`references/mediapackage-migration-endpoint-config.md`, Step 6.5) all exist and were approved.
> If they don't, go back and do those stages first — say so plainly rather than
> generating something from assumptions.

## Step 1.5: Confirm CLI capability before choosing a format

If the user wants CLI output, confirm the installed CLI can express the plan:

| Plan contains | Check |
|---|---|
| an MSS/ISM endpoint | `aws mediapackagev2 create-origin-endpoint help` lists `--mss-manifests` |
| CDN authorization | `aws mediapackagev2 put-origin-endpoint-policy help` lists `--cdn-auth-configuration` |
| `startoverWindowSeconds: 0` | `--startover-window-seconds 0` does not fail with a local `ParamValidation` error |

Tell the user that the migration relies on a current AWS CLI: if theirs is not the
latest version, the accuracy of the migration may be affected, because an older CLI
can reject valid v2 values or lack flags the plan needs. Recommend `aws update`.

If the installed CLI is older, **say so and ask** how to proceed — upgrade
(`aws update`), or generate CloudFormation/SDK output instead. Do not generate a script
that will fail, and do not silently drop the affected flags or switch to an SDK on your
own initiative. An older CLI rejecting `--startover-window-seconds 0` is *client-side*
validation, not the service: dropping the flag would silently give the endpoint v2's
900-second default.

## Step 2: Ask Output Format

Ask the user which output format they prefer:

> How would you like the migration plan generated?
>
> 1. **CLI** — Bash shell script with `aws mediapackagev2` commands
> 2. **CloudFormation** — YAML template with `AWS::MediaPackageV2::*` resources
> 3. **SDK code** — Code in your preferred language (Python, Java, Go, TypeScript, etc.)

Note the chosen format (and SDK language, if applicable).

## Step 3: Load Migration Plan

Read `.mediapackage-migration/migration-plan.json` for channel group assignments and endpoint mappings.

If `channelInputType` is absent from the plan (an earlier stage overwrote it), stop and
ask the user to confirm the channel input type before creating channels — do not
fall back to the default, because the input type cannot be changed after creation.

## Step 4: Generate Plan

> **Names in the examples below are placeholders.** `example-sports`, `example-sports-football`, `football-hls` and `index` illustrate the shape of each
> artifact. Every real channel group, channel, origin endpoint and manifest name — and
> every ARN built from them — comes from the approved plan in
> `.mediapackage-migration/migration-plan.json`. Never emit an example name into a
> user's artifact.

> **The examples show the public-endpoint case** (`Principal: "*"`), which is only
> allowed when discovery found the v1 endpoint publicly playable and the user chose to
> keep it public. When you generate it, tell the user that a public origin endpoint can
> be reached directly, bypassing any CDN. Recommend, as a follow-up after cutover,
> putting CloudFront in front with origin access control (OAC) scoped by `AWS:SourceArn`
> and `aws:SourceAccount`, serving viewers over HTTPS only (an ACM certificate on the
> distribution and a `redirect-to-https` or `https-only` viewer protocol policy), adding
> AWS WAF and a response headers policy (HSTS, X-Content-Type-Options, X-Frame-Options
> and, where it fits the player, a Content-Security-Policy) to the distribution, and then
> replacing the `Principal: "*"` policy with one that allows only that distribution.

Generate the migration artifacts in the chosen format. **Resource creation order must be:**

1. **Channel Groups** first
2. **Channels** second (reference their channel group)
3. **Channel policies** (only where content is ingested from another account) via `put-channel-policy`
4. **Origin Endpoints** (reference their channel and channel group)
5. **Origin endpoint policies** via `put-origin-endpoint-policy` — including
   `--cdn-auth-configuration` in the same call for CDN-auth endpoints

Every endpoint needs a policy decision. An endpoint left without one is reachable only
with this account's credentials, so a formerly-public v1 endpoint goes dark. If the plan
says an endpoint should be public, the script must attach the public policy — don't
leave it as a manual afterthought.

> **JSON parameter casing:** AWS CLI JSON arguments use the API's own member names,
> which are **PascalCase** — `{"SegmentDurationSeconds":6}`, not
> `{"segmentDurationSeconds":6}`. The mapping tables in
> `references/mediapackage-migration-endpoint-config.md` are written in camelCase to match the API
> documentation's prose style; translate to PascalCase when emitting CLI JSON,
> CloudFormation, or boto3. If unsure of a member's exact spelling, read it from
> `aws mediapackagev2 create-origin-endpoint --generate-cli-skeleton`.

> **API rate limit:** MediaPackage v2's REST API allows **20 requests/second steady, 50
> burst**, and this quota is **not adjustable** (confirm the current values with
> `aws service-quotas list-service-quotas --service-code mediapackagev2`). A script creating dozens of resources
> will hit it. Pace the calls (a short sleep between creates) and treat
> `ThrottlingException` / "Too many requests" as retryable with backoff — distinct from
> a validation failure, which is not.

### CLI Format

Generate a bash script. Example structure:

> **Shell safety:** When interpolating v1-sourced values (names, descriptions) into the bash script, always wrap them in single quotes. Replace any literal `'` in the value with `'\''` before embedding. Only script-owned variables like `$REGION` and `$FAILURES` should use double quotes.

> **JSON safety:** When embedding v1-sourced string values inside JSON arguments (e.g., `--segment`, `--hls-manifests`), apply JSON escaping first (escape `\`, `"`, and control characters such as newlines/tabs) before wrapping the outer JSON in single quotes for the shell.

```bash
#!/bin/bash
# MediaPackage v1 to v2 Migration Script
# Generated: <timestamp>
# Region: <region>
set -uo pipefail  # intentionally no -e: continue on individual failures
REGION="<region>"
EXPECTED_ACCOUNT="<account-id>"
# Per-category counters. Phase 6 Step 5 reconciles resources and policies
# SEPARATELY (a policy can fail while its endpoint succeeded), and Step 5.5
# persists each count, so policy outcomes never share a counter with resources.
CREATED=0
SKIPPED=0
FAILURES=0
POLICIES_ATTACHED=0
POLICIES_SKIPPED=0  # endpoints that pre-existed, so their live policy was left alone
POLICIES_FAILED=0

# Guard: refuse to run against the wrong account. This script creates real
# resources with permanent names — verify before the first create.
ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
if [ "$ACTUAL_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  echo "ERROR: expected account $EXPECTED_ACCOUNT but credentials are for $ACTUAL_ACCOUNT"
  exit 1
fi

# MediaPackage v2's REST API allows 20 req/sec steady (not adjustable), so pace EVERY
# create/put call — channel groups and channels included, not just endpoints.
throttle() { sleep 0.3; }

# A throttle is transient, so retry it with backoff. Everything else is a real
# failure and is NOT retried. Usage: run_with_retry <label> <command...>
is_throttle() { echo "$1" | grep -qE 'ThrottlingException|TooManyRequests|Too many requests|Rate exceeded'; }
run_with_retry() {
  local label="$1"; shift
  local delay=1 attempt=1 out
  while :; do
    out=$("$@" 2>&1) && { RETRY_OUT="$out"; return 0; }
    if is_throttle "$out" && [ "$attempt" -lt 5 ]; then
      echo "Throttled on $label, retrying in ${delay}s (attempt $attempt)"
      sleep "$delay"; delay=$(( delay * 2 )); attempt=$(( attempt + 1 )); continue
    fi
    RETRY_OUT="$out"; return 1
  done
}

echo "=== Creating Channel Groups ==="

# Every create/put below goes through run_with_retry so a throttle is retried
# rather than recorded as a failure.
run_with_retry 'create channel group example-sports' aws mediapackagev2 create-channel-group \
  --channel-group-name 'example-sports' \
  --description 'Example sports channels' \
  --region "$REGION" && { echo "Created channel group: example-sports"; CREATED=$((CREATED + 1)); } || {
  if echo "$RETRY_OUT" | grep -q 'ConflictException'; then
    echo "Skipped (already exists): example-sports"; SKIPPED=$((SKIPPED + 1))
  else
    echo "ERROR: Failed to create channel group: example-sports"
    echo "$RETRY_OUT"
    FAILURES=$((FAILURES + 1))
  fi
}
throttle

echo "=== Creating Channels ==="

run_with_retry 'create channel example-sports-football' aws mediapackagev2 create-channel \
  --channel-group-name 'example-sports' \
  --channel-name 'example-sports-football' \
  --description 'Football live channel' \
  --input-type HLS \
  --region "$REGION" && { echo "Created channel: example-sports-football"; CREATED=$((CREATED + 1)); } || {
  if echo "$RETRY_OUT" | grep -q 'ConflictException'; then
    echo "Skipped (already exists): example-sports-football"; SKIPPED=$((SKIPPED + 1))
  else
    echo "ERROR: Failed to create channel: example-sports-football"
    echo "$RETRY_OUT"
    FAILURES=$((FAILURES + 1))
  fi
}
throttle

echo "=== Creating Origin Endpoints ==="

run_with_retry 'create origin endpoint football-hls' aws mediapackagev2 create-origin-endpoint \
  --channel-group-name 'example-sports' \
  --channel-name 'example-sports-football' \
  --origin-endpoint-name 'football-hls' \
  --container-type TS \
  --segment '{"SegmentDurationSeconds":6}' \
  --hls-manifests '[{"ManifestName":"index","ManifestWindowSeconds":60}]' \
  --startover-window-seconds 300 \
  --region "$REGION" && { echo "Created origin endpoint: football-hls"; EP_football_hls=created; CREATED=$((CREATED + 1)); } || {
  if echo "$RETRY_OUT" | grep -q 'ConflictException'; then
    echo "Skipped (already exists): football-hls"; EP_football_hls=skipped; SKIPPED=$((SKIPPED + 1))
  else
    echo "ERROR: Failed to create origin endpoint: football-hls"
    echo "$RETRY_OUT"
    EP_football_hls=failed; FAILURES=$((FAILURES + 1))
  fi
}
throttle

echo "=== Attaching Origin Endpoint Policies ==="

# Per the plan's access decision (here: public playback, as v1 was). Attach ONLY
# to endpoints THIS run created. put-origin-endpoint-policy REPLACES, and an
# endpoint we skipped is not ours to change: "no policy" is itself a valid access
# model (v2 endpoints with no policy are reachable only with the account's own
# credentials, i.e. IAM/SigV4), so attaching the planned policy to a pre-existing
# endpoint can make a deliberately private endpoint public — or hit an unrelated
# endpoint that happens to share this name in a reused channel group.
#
# Deliberately NOT probed with get-origin-endpoint-policy: any error from that call
# (throttling, AccessDenied) is indistinguishable from "no policy exists" without
# inspecting the error code, and guessing wrong overwrites a live policy. Report
# pre-existing endpoints instead and let the user decide.
#
# Embed each policy document in the script. Do NOT emit `--policy file://...`
# pointing at a file the script does not create: the script must run on its own.
needs_policy_football_hls() {
  case "${EP_football_hls:-failed}" in
    created) return 0 ;;
    skipped)
      echo "SKIPPED policy: football-hls already existed (not created by this run) — its"
      echo "  current access configuration was left untouched. Review it yourself if the"
      echo "  plan expected a different access model."
      POLICIES_SKIPPED=$((POLICIES_SKIPPED + 1))
      ;;
    *)
      # The endpoint itself failed to create, so there is nothing to attach a policy
      # to. Counted as a policy failure, not a skip: the planned policy did not land,
      # and calling it "skipped" would report a broken endpoint as healthy.
      echo "NO POLICY: football-hls was not created (see the error above) — the planned"
      echo "  policy was not attached."
      POLICIES_FAILED=$((POLICIES_FAILED + 1))
      ;;
  esac
  return 1
}
if needs_policy_football_hls; then
  read -r -d '' POLICY_football_hls <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowPublicGetObject",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "mediapackagev2:GetObject",
    "Resource": "arn:aws:mediapackagev2:<region>:<account>:channelGroup/example-sports/channel/example-sports-football/originEndpoint/football-hls"
  }]
}
POLICY
  run_with_retry 'attach policy football-hls' aws mediapackagev2 put-origin-endpoint-policy \
    --channel-group-name 'example-sports' \
    --channel-name 'example-sports-football' \
    --origin-endpoint-name 'football-hls' \
    --policy "$POLICY_football_hls" \
    --region "$REGION" && { echo "Attached policy: football-hls"; POLICIES_ATTACHED=$((POLICIES_ATTACHED + 1)); } || {
    echo "ERROR: Failed to attach policy: football-hls"
    echo "$RETRY_OUT"
    POLICIES_FAILED=$((POLICIES_FAILED + 1))
  }
  throttle
fi

# Both counts are reported: Step 5 reconciles resources and policies separately.
echo "=== Migration Complete ==="
echo "Resources: created=$CREATED skipped=$SKIPPED failed=$FAILURES"
echo "Policies:  attached=$POLICIES_ATTACHED skipped=$POLICIES_SKIPPED failed=$POLICIES_FAILED"
echo "NOTE: this script never deletes or updates anything. If a resource failed,"
echo "      inspect it and clean it up yourself — re-running is safe (ConflictException"
echo "      is treated as 'already exists')."
exit $(( FAILURES + POLICIES_FAILED > 0 ? 1 : 0 ))
```

### CloudFormation Format

Generate a YAML CloudFormation template. Example structure:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: MediaPackage v1 to v2 Migration - Generated <timestamp>

Resources:
  ExampleSportsChannelGroup:
    Type: AWS::MediaPackageV2::ChannelGroup
    Properties:
      ChannelGroupName: example-sports
      Description: Example sports channels

  ExampleSportsFootballChannel:
    Type: AWS::MediaPackageV2::Channel
    DependsOn: ExampleSportsChannelGroup
    Properties:
      ChannelGroupName: example-sports
      ChannelName: example-sports-football
      Description: Football live channel
      InputType: HLS

  FootballHlsEndpoint:
    Type: AWS::MediaPackageV2::OriginEndpoint
    DependsOn: ExampleSportsFootballChannel
    Properties:
      ChannelGroupName: example-sports
      ChannelName: example-sports-football
      OriginEndpointName: football-hls
      ContainerType: TS
      Segment:
        SegmentDurationSeconds: 6
      HlsManifests:
        - ManifestName: index
          ManifestWindowSeconds: 60
      StartoverWindowSeconds: 300

  # Every endpoint needs its access decision in the template too, or the stack
  # creates endpoints that no viewer can reach. This example is the public case.
  # For a CDN-auth endpoint, see the variant after this template: the
  # CdnAuthConfiguration alone enforces nothing without the policy condition.
  FootballHlsEndpointPolicy:
    Type: AWS::MediaPackageV2::OriginEndpointPolicy
    DependsOn: FootballHlsEndpoint
    Properties:
      ChannelGroupName: example-sports
      ChannelName: example-sports-football
      OriginEndpointName: football-hls
      Policy:
        Version: "2012-10-17"
        Statement:
          - Sid: AllowPublicGetObject
            Effect: Allow
            Principal: "*"
            Action: mediapackagev2:GetObject
            Resource: !Sub "arn:aws:mediapackagev2:${AWS::Region}:${AWS::AccountId}:channelGroup/example-sports/channel/example-sports-football/originEndpoint/football-hls"
```

For an endpoint that used CDN authorization in v1, the policy resource carries both
parts. The `CdnAuthConfiguration` names the secret, and the policy `Condition` is what
actually enforces the header check. Emitting one without the other leaves the endpoint
either open or unreachable. Prerequisites (secret, `SecretsRoleArn` trust and
`BatchGetSecretValue`) are in `references/mediapackage-migration-endpoint-config.md`
under "CDN authorization".

```yaml
  FootballHlsEndpointPolicy:
    Type: AWS::MediaPackageV2::OriginEndpointPolicy
    DependsOn: FootballHlsEndpoint
    Properties:
      ChannelGroupName: example-sports
      ChannelName: example-sports-football
      OriginEndpointName: football-hls
      CdnAuthConfiguration:
        CdnIdentifierSecretArns:
          - arn:aws:secretsmanager:<region>:<account>:secret:<cdn-identifier-secret>
        SecretsRoleArn: arn:aws:iam::<account>:role/<role-mediapackage-can-assume>
      Policy:
        Version: "2012-10-17"
        Statement:
          - Sid: AllowGetObjectAccessForAuthorizedRequest
            Effect: Allow
            Principal: "*"
            Action: mediapackagev2:GetObject
            Resource: !Sub "arn:aws:mediapackagev2:${AWS::Region}:${AWS::AccountId}:channelGroup/example-sports/channel/example-sports-football/originEndpoint/football-hls"
            Condition:
              Bool:
                "mediapackagev2:RequestHasMatchingCdnAuthHeader": "true"
```

### SDK Code Format

Generate idiomatic code in the user's preferred language. Example for Python (boto3):

```python
"""MediaPackage v1 to v2 Migration Script - Generated <timestamp>"""
import json
import sys
import time
import boto3
from botocore.exceptions import BotoCoreError, ClientError

client = boto3.client('mediapackagev2', region_name='<region>')
# Per-category counters. Phase 6 Step 5 reconciles resources and policies
# SEPARATELY (a policy can fail while its endpoint succeeded), and Step 5.5
# persists each count, so policy outcomes never share a counter with resources.
created = 0
skipped = 0
failures = 0
policies_attached = 0
policies_failed = 0
skipped_policies = []  # endpoints that pre-existed, so their live policy was left alone

# Guard: refuse to run against the wrong account. This script creates real
# resources with permanent names — verify before the first create.
EXPECTED_ACCOUNT = '<account-id>'
actual_account = boto3.client('sts', region_name='<region>').get_caller_identity()['Account']
if actual_account != EXPECTED_ACCOUNT:
    sys.exit(f"ERROR: expected account {EXPECTED_ACCOUNT} but credentials are for {actual_account}")

# 20 req/sec steady (not adjustable): pace EVERY create/put call.
def throttle():
    time.sleep(0.3)


THROTTLE_CODES = {'ThrottlingException', 'TooManyRequestsException', 'RequestLimitExceeded'}


def call_with_retry(fn, **kwargs):
    """Retry throttles and transient connectivity errors with backoff.

    Any other ClientError is a real failure and is raised for the caller to count.
    A connectivity error (BotoCoreError: endpoint unreachable, timeouts) that
    persists after the retries is counted as that resource's failure and the run
    continues; re-running it is safe because an existing resource is reported as skipped.
    """
    delay = 1
    for attempt in range(5):
        try:
            return fn(**kwargs)
        except ClientError as e:
            if e.response['Error']['Code'] in THROTTLE_CODES and attempt < 4:
                print(f"Throttled, retrying in {delay}s")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except BotoCoreError as e:
            if attempt < 4:
                print(f"Connection problem ({e}), retrying in {delay}s")
                time.sleep(delay)
                delay *= 2
                continue
            # Re-raise as ClientError so each resource's handler counts it as a
            # failure and the run continues to the summary, as the bash script does.
            raise ClientError({'Error': {'Code': 'ConnectionError', 'Message': str(e)}},
                              getattr(fn, '__name__', 'call')) from e

# === Channel Groups ===
try:
    print("Creating channel group: example-sports")
    # Every create/put below goes through call_with_retry.
    call_with_retry(
        client.create_channel_group,
        ChannelGroupName='example-sports',
        Description='Example sports channels',
    )
    created += 1
except ClientError as e:
    if e.response['Error']['Code'] == 'ConflictException':
        print("Skipped (already exists): example-sports")
        skipped += 1
    else:
        print(f"ERROR: Failed to create channel group example-sports: {e}")
        failures += 1
throttle()

# === Channels ===
try:
    print("Creating channel: example-sports-football")
    call_with_retry(
        client.create_channel,
        ChannelGroupName='example-sports',
        ChannelName='example-sports-football',
        Description='Football live channel',
        InputType='HLS',
    )
    created += 1
except ClientError as e:
    if e.response['Error']['Code'] == 'ConflictException':
        print("Skipped (already exists): example-sports-football")
        skipped += 1
    else:
        print(f"ERROR: Failed to create channel example-sports-football: {e}")
        failures += 1
throttle()

# === Origin Endpoints ===
# Tri-state, not a boolean: the policy phase must tell "pre-existing, leave its policy
# alone" apart from "creation failed, there is nothing to attach to".
ep_football_hls = 'failed'
try:
    print("Creating origin endpoint: football-hls")
    call_with_retry(
        client.create_origin_endpoint,
        ChannelGroupName='example-sports',
        ChannelName='example-sports-football',
        OriginEndpointName='football-hls',
        ContainerType='TS',
        Segment={'SegmentDurationSeconds': 6},
        HlsManifests=[{'ManifestName': 'index', 'ManifestWindowSeconds': 60}],
        StartoverWindowSeconds=300,
    )
    ep_football_hls = 'created'
    created += 1
except ClientError as e:
    if e.response['Error']['Code'] == 'ConflictException':
        print("Skipped (already exists): football-hls")
        ep_football_hls = 'skipped'
        skipped += 1
    else:
        print(f"ERROR: Failed to create origin endpoint football-hls: {e}")
        failures += 1
throttle()

# === Origin Endpoint Policies ===
# Per the plan's access decision. ONLY for endpoints THIS run created:
# put_origin_endpoint_policy REPLACES, and an endpoint we skipped is not ours to
# change. "No policy" is itself a valid access model (reachable only with the
# account's own credentials via IAM/SigV4), so attaching the planned policy to a
# pre-existing endpoint can make a deliberately private endpoint public, or hit an
# unrelated endpoint sharing this name in a reused channel group.
def needs_policy(oe, outcome):
    """Attach only if THIS run created the endpoint.

    outcome is 'created' | 'skipped' | 'failed'. A failed create is NOT a skipped
    policy: there is no endpoint to attach to, and reporting it as pre-existing
    would describe a broken endpoint as healthy.
    """
    global policies_failed
    if outcome == 'created':
        return True
    if outcome == 'skipped':
        print(f"SKIPPED policy: {oe} already existed (not created by this run) — its current "
              f"access configuration was left untouched. Review it yourself if the plan "
              f"expected a different access model.")
        skipped_policies.append(oe)
    else:
        print(f"NO POLICY: {oe} was not created (see the error above) — the planned policy "
              f"was not attached.")
        policies_failed += 1
    return False


if needs_policy('football-hls', ep_football_hls):
    try:
        # Embed the policy document; do not read a file the script never writes.
        policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "AllowPublicGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "mediapackagev2:GetObject",
                "Resource": "arn:aws:mediapackagev2:<region>:<account>:channelGroup/"
                            "example-sports/channel/example-sports-football/originEndpoint/football-hls",
            }],
        })
        call_with_retry(
            client.put_origin_endpoint_policy,
            ChannelGroupName='example-sports',
            ChannelName='example-sports-football',
            OriginEndpointName='football-hls',
            Policy=policy,
        )
        print("Attached policy: football-hls")
        policies_attached += 1
    except ClientError as e:
        print(f"ERROR: Failed to attach policy football-hls: {e}")
        policies_failed += 1
    throttle()

# Both counts are reported: Step 5 reconciles resources and policies separately.
print("Migration complete")
print(f"Resources: created={created} skipped={skipped} failed={failures}")
print(f"Policies:  attached={policies_attached} skipped={len(skipped_policies)} "
      f"failed={policies_failed}")
sys.exit(1 if failures + policies_failed > 0 else 0)
```

For other languages (Java, Go, TypeScript), follow the same pattern using the appropriate AWS SDK.

## Step 5: Present Plan Summary

Show the user:

1. **Resource counts**: X channel groups, Y channels, Z origin endpoints
2. **Any skipped configs** (from incompatibility resolutions)
3. **Output format** and where the file will be saved
4. The generated plan content (or a summary if very large)

Ask for explicit confirmation:

> **Migration Plan Summary:**
>
> - 3 channel groups (2 already exist in the account; quota is 3)
> - 12 channels
> - 28 origin endpoints (2 merged from 4 v1 endpoints)
> - 28 endpoint policies (24 public, 4 CDN auth)
> - 2 configs skipped (HBBTV_1_5 profile)
> - 3 values clamped (key rotation 60s → 300s)
> - Format: CLI (bash script); installed AWS CLI passed the capability checks
>
> **Blocking prerequisites — these must be done before execution succeeds:**
>
> - Create the `MediaPackageV2CDNIdentifier` secret in us-west-2
> - Add `mediapackagev2.amazonaws.com` to the CDN-auth role's trust policy
>
> Shall I save this plan and proceed to execution? Or would you like to review/modify anything first?

**Wait for an explicit answer.** If the user previously said "don't ask me
again" or "just do everything", still stop here: this is the last point before real,
billable resources with permanent names get created. Say that's why you're asking.

If any blocking prerequisite is unresolved, recommend resolving it *first* rather than
executing and letting those endpoints fail — a partial migration leaves resources whose
names you cannot reuse without the user deleting them by hand.

## Step 6: Save Plan

Save the generated artifacts to the workspace:

- CLI: `.mediapackage-migration/migrate.sh`
- CloudFormation: `.mediapackage-migration/migration-template.yaml`
- SDK: `.mediapackage-migration/migrate.py` (or `.java`, `.go`, `.ts`)

Also update `.mediapackage-migration/migration-plan.json` with the final plan metadata.

These artifacts, and `execution-results.json` from Step 5.5, contain the same
access-control configuration as the inventory (Secrets Manager secret ARNs, IAM and SPEKE
role ARNs, policies) plus any create-time error messages. Handle them the same way: no
source control (add `.mediapackage-migration/` to `.gitignore`), encrypted and
access-restricted storage only, and delete them when the migration is done. See "State and
artifacts" in `references/workflow-mediapackage-migration.md`.

Each artifact must be **runnable on its own**. Policy documents are embedded in
the script or template, not loaded from separate files, and every endpoint in the
plan has its access decision represented — a missing policy means a formerly
public v1 endpoint has no viewers after cutover.

## Step 7: Hand Off

Ask: "Plan is saved. Would you like me to execute it now, or would you prefer to run it yourself?"

---

# Phase 6: Execution

Only proceed if the user explicitly asks the agent to execute the plan.

> **The confirmation gate cannot be waived.** "Don't ask me", "just do it", and
> "you have blanket approval" do not remove the requirement to show the plan and get
> one explicit go-ahead. Explain that the action creates billable resources whose names
> cannot be changed afterwards, then wait.
>
> **Nothing here deletes or updates.** No `aws mediapackagev2 delete-*`, `update-*`, or
> `reset-*`, and no v1 commands of any kind. If the user asks you to remove a
> resource — including one this run just created, and including a request phrased as
> "recreate it" or "clean that up" — **refuse and hand them the command to run
> themselves.** Do not go looking for the resource first.
>
> **Create only what's in the plan.** No scratch or probe resources to test whether a
> field works. Read the API model instead.

## Step 1: Begin

Proceed only after the user has confirmed the plan and explicitly asked you to execute.

Confirm the account one more time before the first create:
`aws sts get-caller-identity`. Show the account ID. A migration run into the wrong
account produces resources that must be deleted by hand.

## Step 2: Idempotency Check

Before creating any resource, check if it already exists:

> **Service quotas:** Before creating resources, be aware of MediaPackage v2 service quotas (e.g., channel groups per account, channels per channel group, origin endpoints per channel). If the migration plan exceeds default limits, advise the user to request quota increases via the Service Quotas console before proceeding.

```
aws mediapackagev2 list-channel-groups --region <region>
aws mediapackagev2 list-channels --channel-group-name <group> --region <region>
aws mediapackagev2 list-origin-endpoints --channel-group-name <group> --channel-name <channel> --region <region>
```

For each list call, paginate by passing `--next-token` from the previous response until no `NextToken` is returned, to ensure all existing resources are discovered before creating new ones.

If a resource with the same name already exists, **skip it** and note it as "already exists".

## Step 3: Create Resources (in order)

### 3a: Create Channel Groups

For each channel group in the plan:

```
aws mediapackagev2 create-channel-group --channel-group-name <name> --description "<desc>" --region <region>
```

Report progress: "Created channel group: <name>" or "Skipped (already exists): <name>"

### 3b: Create Channels

For each channel in the plan:

```
aws mediapackagev2 create-channel --channel-group-name <group> --channel-name <name> --description "<desc>" --input-type <channelInputType from the plan> --region <region>
```

Always pass `--input-type` explicitly (`HLS` unless the user chose `CMAF` in
channel-group planning). It cannot be changed after the channel exists.

### 3c: Create Origin Endpoints

For each origin endpoint in the plan:

```
aws mediapackagev2 create-origin-endpoint \
  --channel-group-name <group> \
  --channel-name <channel> \
  --origin-endpoint-name <name> \
  --container-type <TS|CMAF|ISM> \
  --segment '<JSON>' \
  --hls-manifests '<JSON>' \
  --dash-manifests '<JSON>' \
  --mss-manifests '<JSON>' \
  --startover-window-seconds <N> \
  --region <region>
```

Only include the manifest type(s) relevant to the container type.

Pace the calls — the REST API allows 20 requests/second steady, 50 burst, and the quota
is not adjustable (confirm with the `Adjustable` field in Service Quotas). This applies to **every** call in steps 3a–3d (channel groups,
channels, endpoints, and policies), not just endpoint creation: a bulk migration
that creates many groups or channels back-to-back trips the limit just the same.

### 3d: Attach Policies

For each channel that ingests from another account:

```
aws mediapackagev2 put-channel-policy --channel-group-name <group> --channel-name <channel> --policy '<JSON>' --region <region>
```

For each origin endpoint, per the access decision in the plan:

```
aws mediapackagev2 put-origin-endpoint-policy \
  --channel-group-name <group> --channel-name <channel> --origin-endpoint-name <name> \
  --policy '<JSON>' \
  [--cdn-auth-configuration '{"CdnIdentifierSecretArns":["<secret-arn>"],"SecretsRoleArn":"<role-arn>"}'] \
  --region <region>
```

`put-origin-endpoint-policy` **replaces** — send the policy and the CDN auth
configuration together in one call, never sequentially, or the second call drops the
first's configuration.

An endpoint with no policy is reachable only with this account's credentials. Do not
skip this step for endpoints the plan says should be public.

## Step 4: Error Handling

If a `create` command fails:

1. **Log the error** — record the resource name and error message
2. **Do NOT retry** the failed resource, unless the error is a throttle
   (`ThrottlingException` / "Too many requests"), which should be retried with backoff.
   The generated script must implement that retry (see `run_with_retry` in the CLI
   example and `call_with_retry` in the SDK example) rather than counting a throttle
   as a permanent failure
3. **Continue** with the remaining resources
4. If the error is a 409 Conflict (already exists), treat as "skipped"
5. **Never clean up after a failure.** Do not delete a partially-created resource and do
   not `update-*` one into shape. Report exactly what exists and what failed, and let
   the user decide. If they want it removed, give them the `delete-*` command to run
   themselves.

A validation error at this point means the pre-flight checklist missed something. Say
which check would have caught it — that's more useful than the raw error, and it tells
the user whether the rest of the plan is suspect.

## Step 5: Execution Summary

After all create operations are attempted, present:

> **Execution Summary:**
>
> - ✅ Created: 1 channel group, 12 channels, 26 origin endpoints
> - 🔐 Policies attached: 26 endpoint policies, 0 channel policies
> - ⏭️ Skipped: 2 channel groups and 2 origin endpoints (already existed), and the
>   2 endpoint policies belonging to those endpoints — their live policies were
>   left alone
> - ❌ Failed: 0
>
> Total: 39 resources created + 4 skipped = 43 (matches the plan's 3 groups +
> 12 channels + 28 endpoints)
> Policies: 26 attached + 2 skipped + 0 failed = 28 (matches the plan's 28 — one
> per endpoint; the 2 belonging to pre-existing endpoints were deliberately not
> touched)

Verify both lines balance against the plan's own totals, counting policies as
their own category:

- `resources created + resources skipped + resources failed = planned resources`
  (channel groups + channels + origin endpoints)
- `policies attached + policies skipped + policies failed = planned policies`
  (the plan's endpoint-policy and channel-policy counts)

Policies are counted separately because a policy can fail while its endpoint
succeeded. Reporting them inside the resource total would hide exactly the
failure that leaves an endpoint unreachable.

## Step 5.5: Persist Execution Results

Save execution results to `.mediapackage-migration/execution-results.json`:

```json
{
  "executedAt": "<timestamp>",
  "summary": {
    "created": 0,
    "skipped": 0,
    "failed": 0,
    "policiesAttached": 0,
    "policiesSkipped": 0,
    "policiesFailed": 0
  },
  "resources": [
    {
      "type": "ChannelGroup",
      "name": "example-sports",
      "outcome": "created"
    },
    {
      "type": "OriginEndpoint",
      "name": "football-hls",
      "channelGroupName": "example-sports",
      "channelName": "example-sports-football",
      "outcome": "skipped",
      "reason": "already exists"
    },
    {
      "type": "Channel",
      "name": "news-live",
      "channelGroupName": "example-news",
      "outcome": "failed",
      "error": "AccessDeniedException: ..."
    }
  ]
}
```

## Step 6: Hand Off

Ask: "Would you like me to validate the created resources against the plan?"

---

# Phase 7: Validation

## Step 1: Begin

Validate the created v2 resources against the plan.

## Step 2: Enumerate Created Resources

Before enumerating, load `.mediapackage-migration/execution-results.json` if it exists. Skip `get-*` calls for resources recorded as `failed`. Resources recorded as `skipped`
already existed before this run, so the migration did not create or change them, and
their live settings and policies can legitimately differ from the plan. Do not compare
them in Step 3: list them in the summary as "already existed, left unchanged, not
checked against the plan". If a `get-*` call returns a 404 (ResourceNotFoundException), report the resource as "not found — creation may have failed" rather than treating it as a validation error.

For each channel group in the plan:

```
aws mediapackagev2 get-channel-group --channel-group-name <name> --region <region>
```

For each channel:

```
aws mediapackagev2 get-channel --channel-group-name <group> --channel-name <name> --region <region>
```

For each origin endpoint:

```
aws mediapackagev2 get-origin-endpoint --channel-group-name <group> --channel-name <channel> --origin-endpoint-name <name> --region <region>
```

## Step 3: Compare Against Plan

Compare only resources recorded as `created` (or every planned resource when no
`execution-results.json` exists). For each **origin endpoint**, compare:

| Attribute | How to Compare |
|---|---|
| Container type | Exact match |
| Segment duration | Exact match |
| Segment name | Exact match (if set) |
| Manifest names | Exact match, and unique within the endpoint |
| Manifest count and types | Count and type match |
| Manifest window seconds | Exact match (per manifest) |
| Startover window | Exact match — **check `0` explicitly.** If the plan said `0` and the endpoint reports `900`, the field was dropped and v2 applied its default. This is the single most likely silent failure |
| Encryption provider URL | Exact match (if encrypted) |
| Encryption role ARN | Exact match (if encrypted) |
| Encryption method type | Exact match (`tsEncryptionMethod`/`cmafEncryptionMethod`/`ismEncryptionMethod`) |
| DRM systems | Exact set match, and compatible with the encryption method |
| Encryption contract presets | Exact match (`presetSpeke20Audio`/`presetSpeke20Video`) |
| Key rotation interval | Exact match, or absent where the plan omitted it |
| SCTE/ad marker settings | Match per manifest type (`scteHls`, `scteDash`) and at segment level (`segment.scte`) |
| programDateTimeIntervalSeconds | Exact match, or **absent** where the v1 value was `0` |
| timeDelaySeconds | Exact match, or **absent** where the v1 value was `0` |
| manifestFilter | Exact match (if set, per manifest filterConfiguration) |
| DASH periodTriggers | Exact match — `["AVAILS"]` or `["NONE"]`, never `ADS`. If the plan omitted it and the endpoint reports four triggers, the field was dropped and the service defaulted to multi-period |
| DASH compactness | Exact match — must be explicitly set, not defaulted |
| DASH drmSignaling | Present on encrypted DASH manifests |
| DASH segmentTemplateFormat | `NUMBER_WITH_TIMELINE` |
| DASH utcTiming | `timingMode` + `timingSource` match |
| includeIframeOnlyStreams | Exact match (segment level) |
| tsUseAudioRenditionGroup | Exact match (TS containers only) |
| tsIncludeDvbSubtitles | Exact match (TS containers only) |

Also verify the **policies**, which are not part of `get-origin-endpoint`:

```
aws mediapackagev2 get-origin-endpoint-policy --channel-group-name <group> --channel-name <channel> --origin-endpoint-name <name> --region <region>
aws mediapackagev2 get-channel-policy --channel-group-name <group> --channel-name <channel> --region <region>
```

Confirm each endpoint has the access model the plan called for. An endpoint the plan
said should be public, but which has no policy, is **not** publicly reachable — report
it as a mismatch, not a cosmetic gap.

For each **channel group**, compare:

| Attribute | How to Compare |
|---|---|
| Description | Exact match |

For each **channel**, compare:

| Attribute | How to Compare |
|---|---|
| Description | Exact match |
| Input type | Exact match against the plan's `channelInputType` (`HLS` unless the user chose `CMAF`) |

## Step 4: Validation Summary

Present results:

> **Validation Summary:**
>
> - ✅ 24 origin endpoints match the plan exactly
> - ⚠️ 2 origin endpoints have mismatches:
>   - `football-dash`: manifestWindowSeconds is 30 (expected 60)
>   - `news-hls`: missing encryption (expected SPEKE)
> - ℹ️ 2 origin endpoints already existed and were left unchanged, so they were not
>   checked against the plan: `golf-hls`, `golf-dash`
>
> Would you like me to investigate the mismatches?

For mismatches, offer to:

1. Show the diff between planned and actual config
2. Note it for manual review

You cannot fix a mismatch — `update-*` is not permitted during a migration, and a rename
requires delete + recreate. Present the diff and the exact commands the user would
run themselves, and be clear about which mismatches are cosmetic and which change
playback behavior (a missing endpoint policy, a `startoverWindowSeconds` of 900 where
`0` was planned, or an absent `drmSignaling` are all behavioral).

## Step 5: Final Summary

Present final summary:

> **Migration Complete! 🎉**
>
> - **Source:** 12 v1 channels with 30 origin endpoints (4 merged into 2 in v2)
> - **Created:** 1 channel group, 12 channels, 26 origin endpoints in v2 (2 channel groups
>   and 2 origin endpoints already existed and were left as they were)
> - **Validation:** All resources match the plan
>
> Your v1 resources are untouched and still running. Cut over in this order — it keeps
> v1 serving the whole time:
>
> 1. **Add** a second encoder output pointing at the new v2 ingest endpoints, alongside the
>    existing v1 output (for MediaLive, a second output group). Do NOT repoint the existing
>    v1 output yet — both run in parallel for now.
> 2. Test the v2 endpoints while v1 still serves traffic, including a playback test from
>    outside your account, since v2 access defaults differ from v1
> 3. Set up monitoring on v2 before it carries viewers: CloudWatch alarms on the v2
>    egress request and error (4xx/5xx) metrics, CloudTrail for `mediapackagev2` API calls,
>    and access logs for the v2 endpoints and your CDN. Write the logs only to encrypted,
>    access-restricted destinations
> 4. Switch the CDN origin to the v2 egress endpoints **and**, for any endpoint using CDN
>    authorization, rename the custom origin header from `X-MediaPackage-CDNIdentifier` to
>    `X-MediaPackageV2-CDNIdentifier` **in the same change** — v1 and v2 expect different
>    header names, so moving one without the other returns 403s
> 5. Stop the v1 encoder output once v2 is serving viewers
> 6. Decommission v1 resources when ready (manually — this agent won't do it)
>
> Do not repoint the only encoder output to v2 before step 4: that starves v1 while the CDN
> is still pulling from it, which is a viewer-visible outage.
>
> The migration state is saved in `.mediapackage-migration/` if you need to reference it later.

<!-- markdownlint-disable-file MD025 MD028 -->
