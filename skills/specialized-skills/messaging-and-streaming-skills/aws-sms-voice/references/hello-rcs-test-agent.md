# Hello AWS End User Messaging: Create an RCS test agent and send your first message

> By the end of this task, a branded RCS agent exists in the user's AWS account, their phone is a
> verified test device, and they have received a rich, branded message from the agent — plus sent
> one back. About 5 minutes of working time; the tester invitation adds a 2–20 minute wait that
> happens in the background. No carrier registration, no phone number purchase, no infrastructure.
> This unlocks the entire SMS and RCS control and data plane for everything you build next.

You run every command yourself. The user provides inputs and confirms what they see on their
phone. Stop and consult the Failure modes table on any error.

## Session state

Track these values as you collect them. They carry across all steps.

| Value | Format | Source |
|---|---|---|
| `REGION` | e.g. `us-east-1` | ask the user (default `us-east-1`) |
| `PROFILE` | AWS CLI profile name | credential bootstrap (may be empty) |
| `BRAND_NAME` | 2–65 chars | ask the user |
| `AGENT_ID` | `rcs-` + 32 hex | CreateRcsAgent response |
| `REG_ID` | `registration-...` | CreateRegistration response |
| `LOGO_ID`, `BANNER_ID` | `attachment-...` (ID prefix is `attachment-` even though the parameter is `--registration-attachment-id`) | CreateRegistrationAttachment responses |
| `PHONE` | E.164, e.g. `+12065550123` | ask the user (their real test device) |
| `VDN_ID` | `vdn-` + 32 hex | CreateVerifiedDestinationNumber response (needed for cleanup) |

## Prerequisites

1. **AWS CLI capability — probe, don't trust the version.** A current-looking CLI can bundle
   a stale or partial service model that predates some `pinpoint-sms-voice-v2` operations
   (observed live on CLI v2.33.15: `Invalid choice 'create-rcs-agent'`). No single probe is
   authoritative — a partial model can include some operations while omitting others. Treat any
   `Invalid choice '<operation>'` at ANY step as a stale/partial model and resolve it per
   prerequisite 3 (check for a stale `~/.aws/models/` override first, otherwise give the user the
   AWS CLI v2 upgrade commands; boto3 fallback for locked environments). Separately note v1 vs v2:
   v1 changes the URL-field behavior in the registration steps (handled where it matters below).
2. **Credentials** — run `aws sts get-caller-identity --region <REGION>`. Pass `--region` so
   STS uses the regional endpoint (`sts.<region>.amazonaws.com`); the global endpoint
   (`sts.amazonaws.com`) is legacy and best avoided. If it fails, ask the user how they
   authenticate and follow the matching branch:
   - **Named profile**: ask for the profile name; from now on append `--profile <PROFILE>` to
     EVERY aws command in this task. Missing it on even one command causes
     `NoCredentials`/`ExpiredTokenException`.
   - **IAM Identity Center (SSO)**: `aws sso login --profile <PROFILE>`, then treat as named profile.
   - **Access keys**: `aws configure` (or `aws configure --profile <PROFILE>`).
     Prefer IAM Identity Center (SSO) or assumed-role ephemeral credentials over long-lived access keys.
     If access keys are used, rotate them regularly and never embed them in code.
   Re-run `aws sts get-caller-identity --region <REGION>` until it succeeds. Ensure AWS CloudTrail
   is enabled in the account so all `pinpoint-sms-voice-v2` API calls (agent creation, registration
   submission, message sends) are logged for auditing and abuse detection.
3. **Service access AND RCS capability in one probe** — `describe-spend-limits` is the WRONG
   canary (it exists in old CLIs too). Probe with an RCS-specific read-only call:

   ```bash
   aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> >/dev/null && echo "RCS APIs: OK"
   ```

   - `AccessDeniedException` → the identity needs the required `sms-voice:` permissions,
     scoped to the specific actions these steps use rather than the `sms-voice:*` wildcard (see Failure modes).
   - `Invalid choice '<operation>'` on this probe OR on ANY `pinpoint-sms-voice-v2` operation at
     any later step (a stale or partial local model can carry some operations while omitting
     others, e.g. the RCS agent control-plane present but `send-rcs-message` absent) → the local
     client's service model is stale or partial, not a permissions or account problem. Resolve it:
     1. **Check for a stale local model override first** — a leftover file shadows the SDK's
        bundled model, so even a current CLI stays broken:

        ```bash
        ls ~/.aws/models/pinpoint-sms-voice-v2/
        ```

        If present, rename it away (e.g. `mv ~/.aws/models/pinpoint-sms-voice-v2 ~/.aws/models/pinpoint-sms-voice-v2.archive`) and retry the operation.
     2. **Otherwise the installed CLI is too old** — tell the user their AWS CLI predates this
        operation and **give them the commands to upgrade** to the latest AWS CLI v2 (run
        `aws --version`, then follow the
        [AWS CLI install/update guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).
        You do NOT need to determine which CLI version introduced the operation — upgrading to
        the latest v2 and retrying is sufficient; don't research CLI version history.
        Do not run the upgrade yourself — a CLI upgrade is a privileged system change the user
        should perform. Retry the operation after upgrading.
     3. **Locked environment that cannot upgrade** → boto3 fallback (it often carries the
        operations even when the CLI does not). Probe for the SPECIFIC operation that failed,
        expressed in boto3 PascalCase (e.g. `create-rcs-agent` → `CreateRcsAgent`,
        `send-rcs-message` → `SendRcsMessage`) — do not assume one operation's presence implies
        another's, since a partial model can carry some while omitting others:

        ```bash
        python3 -c "import boto3; c=boto3.client('pinpoint-sms-voice-v2', region_name='<REGION>'); print('<PascalCaseOp>' in c.meta.service_model.operation_names)"
        ```

        `True` → run the RCS-agent steps through boto3 (parameters are PascalCase:
        `RegistrationId`, `SelectChoices=[...]`, `AttachmentBody=<bytes>` — vs the CLI's
        `--kebab-case`). `False` → `pip install -U boto3` (AWS software) and re-check; if STILL
        false, apply the same stale-override check to `~/.aws/models/` and rename it away.

     Any resources already created before the failure (agent, registration, verified tester) remain
     valid — once the client is fixed, resume the flow; nothing needs recreating.
4. **Image tooling — nothing to install.** If you will GENERATE brand assets (step 1, option B),
   the primary path is a Python-stdlib PNG generator (zlib + struct — already present with
   `python3`). Optionally run `which rsvg-convert`: if it is ALREADY installed you may render a
   nicer SVG design instead, but do NOT install it — the stdlib generator is sufficient for this
   quickstart. Skip this check if the user provides their own images.
5. **The user's phone** — an Android phone with RCS enabled, or an iPhone on iOS 18+, with the
   number in `PHONE`. Confirm the user has it in hand; they will tap an invitation later.
6. **Input validation** — validate user-provided values (E.164 for phones, URL scheme allowlist, length checks) before passing to APIs.
7. **Inputs to collect** — ask the user:
   - Brand name.
   - **Registration details.** By default you fill these with synthetic placeholder values
     (`.example.com` contacts, an invented description, a safe accent color). Do NOT open by
     interviewing the user for each field or by running live field discovery to decide what to
     ask — go straight to the synthetic defaults. Be explicit that the
     data is synthetic: **show the user the full set of values you will use and let them opt out** —
     "these are placeholder values for a test agent; tell me if you'd rather provide your own for
     any field." Get their confirmation (or their replacements) before submitting; never submit
     invented data silently. If the user supplies real values (contact names, emails, phone
     numbers, business details), treat them as sensitive business-identifying PII: use them only
     to populate the registration and to confirm back, and do not repeat them in responses or
     write them to logs beyond what confirmation requires.
   - **Do they have their own logo and banner images?** If yes, get the file paths — you will
     validate them in step 1 (option A). If no, generate placeholder assets (option B, quick mode),
     which fall under the same synthetic-data disclosure above.

## Steps

### 1. Brand assets — validate the user's own, or generate them

The registration requires a logo (query dimensions from `describe-registration-field-definitions`; expected 224×224 px, under 50 KB, PNG or JPEG) and a banner
(query dimensions from `describe-registration-field-definitions`; expected 1440×448 px, under 200 KB, PNG or JPEG). The registration API rejects anything outside
these constraints, so verify BEFORE uploading either way. Both images are uploaded with
`create-registration-attachment` and then referenced by their returned attachment IDs in the
`agentDetails.logoImage` and `agentDetails.bannerImage` registration field values (see the
attachment upload and field-value steps below).

#### Option A — the user provides their own images

Copy their files to `brand-assets/logo.png` and `brand-assets/banner.png` (or `.jpg`), then
validate format, dimensions, and size with this stdlib-only check:

```bash
# Dimensions per describe-registration-field-definitions (Step 5).
python3 - brand-assets/logo.png 224 224 51200 <<'EOF' && echo "logo OK"
import struct, sys
path, w, h, maxb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
data = open(path, 'rb').read()
if len(data) > maxb: sys.exit(f"FAIL: {len(data)} bytes exceeds {maxb}")
if data[:8] == b'\x89PNG\r\n\x1a\n':
    iw, ih = struct.unpack('>II', data[16:24])
elif data[:2] == b'\xff\xd8':
    i, iw, ih = 2, None, None
    while i < len(data) - 9:
        if data[i] != 0xFF: i += 1; continue
        m = data[i+1]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            ih, iw = struct.unpack('>HH', data[i+5:i+9]); break
        i += 2 + struct.unpack('>H', data[i+2:i+4])[0]
    if iw is None: sys.exit("FAIL: could not parse JPEG dimensions")
else:
    sys.exit("FAIL: not PNG or JPEG (SVG and other formats are rejected)")
sys.exit(0 if (iw, ih) == (w, h) else f"FAIL: {iw}x{ih}, need exactly {w}x{h}")
EOF
python3 - brand-assets/banner.png 1440 448 204800 <<'EOF' && echo "banner OK"
import struct, sys
path, w, h, maxb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
data = open(path, 'rb').read()
if len(data) > maxb: sys.exit(f"FAIL: {len(data)} bytes exceeds {maxb}")
if data[:8] == b'\x89PNG\r\n\x1a\n':
    iw, ih = struct.unpack('>II', data[16:24])
elif data[:2] == b'\xff\xd8':
    i, iw, ih = 2, None, None
    while i < len(data) - 9:
        if data[i] != 0xFF: i += 1; continue
        m = data[i+1]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            ih, iw = struct.unpack('>HH', data[i+5:i+9]); break
        i += 2 + struct.unpack('>H', data[i+2:i+4])[0]
    if iw is None: sys.exit("FAIL: could not parse JPEG dimensions")
else:
    sys.exit("FAIL: not PNG or JPEG (SVG and other formats are rejected)")
sys.exit(0 if (iw, ih) == (w, h) else f"FAIL: {iw}x{ih}, need exactly {w}x{h}")
EOF
```

If a check FAILs, tell the user exactly what's wrong and offer fixes:

- **Wrong dimensions** — resize (do not stretch a mismatched aspect ratio without asking; offer
  to pad instead): with rsvg-convert unavailable, `sips -z 224 224 logo.png` works on macOS, or
  regenerate at the right size from their source file.
- **Too large** — re-export as PNG with fewer colors, or as JPEG quality ~85.
- **Wrong format** (SVG, WebP, HEIC...) — convert to PNG first.

Also pick the accent color to complement their images (ask, or sample a dominant dark color) —
the contrast rule below still applies.

#### Option B — generate the assets

Work in a fresh directory (e.g. `mkdir -p ~/hello-eum-<brand-slug> && cd` into it) — a shared
`brand-assets/` dir may hold leftovers from previous runs for a different brand; don't reuse
or blindly overwrite files you didn't create this run without checking them first.

Pick an accent color with at least **4.5:1 contrast against white**. Safe choices:
`#0D47A1` `#1B5E20` `#BF360C` `#B71C1C` `#4A148C`. Never light or pastel colors — the review
rejects them with `ACCENT_COLOR_CONTRAST_INSUFFICIENT`.

Generate both images with this stdlib-only script (nothing to install — zlib + struct only):
a solid accent-color background with simple white geometry (centered disc on the logo, a
horizontal band on the banner). Substitute the accent hex you picked:

```bash
mkdir -p brand-assets
python3 - brand-assets "<ACCENT_HEX>" <<'EOF'
import os, struct, sys, zlib
outdir, accent = sys.argv[1], sys.argv[2].lstrip('#')
bg = tuple(int(accent[i:i + 2], 16) for i in (0, 2, 4))
fg = (255, 255, 255)
def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))
def write_png(path, w, h, pixel):
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter type None for this scanline
        for x in range(w):
            rows += bytes(pixel(x, y))
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                + chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b''))
    print(f'{path}: {w}x{h}, {os.path.getsize(path)} bytes')
# Dimensions per describe-registration-field-definitions (Step 5).
write_png(os.path.join(outdir, 'logo.png'), 224, 224,
          lambda x, y: fg if (x - 112) ** 2 + (y - 112) ** 2 <= 64 ** 2 else bg)
write_png(os.path.join(outdir, 'banner.png'), 1440, 448,
          lambda x, y: fg if 200 <= y < 248 else bg)
EOF
ls -la brand-assets/*.png
```

Middle tier — **if Pillow is already installed** (`python3 -c "import PIL"` succeeds; do NOT
install it), it renders proper brand-name text, which the stdlib generator cannot. Two traps
observed live: font paths vary by distro — never hardcode; discover with
`fc-list : file | grep -iE "sans|noto|dejavu" | head` and pass a discovered `.ttf` to
`ImageFont.truetype(path, size)`. And if the font fails to load, Pillow silently falls back to
a tiny bitmap font — the banner text renders tiny and off-scale; validate visually or check
the font loaded before trusting the output.

IF `rsvg-convert` is already installed (`which rsvg-convert` from the prerequisites), you may
instead write logo/banner SVGs (solid accent-color background, a basic shape icon, brand name
text, Arial font) and render them for a nicer design:
`rsvg-convert -w 224 -h 224 brand-assets/logo.svg -o brand-assets/logo.png` and
`rsvg-convert -w 1440 -h 448 brand-assets/banner.svg -o brand-assets/banner.png`. Do NOT
install it — the stdlib generator above is sufficient for the quickstart.

Checkpoint (both options): files exist, logo under 50 KB, banner under 200 KB, dimensions exact.
Generated assets can be validated with the option A script too. If a generated file is over the
size limit, simplify the design (fewer distinct colors/shapes) and regenerate.

### 2. Create the agent

The agent is an empty container — its name, colors, and images all come from the registration
in the next steps, not from this call.

```bash
aws pinpoint-sms-voice-v2 create-rcs-agent \
  --deletion-protection-enabled \
  --region <REGION>
```

Save `RcsAgentId` as `AGENT_ID`.

### 3. Create the test registration and link it to the agent

```bash
aws pinpoint-sms-voice-v2 create-registration \
  --registration-type TEST_RCS_LAUNCH_REGISTRATION \
  --region <REGION>
```

Save `RegistrationId` as `REG_ID`. Link it (this must happen before submitting):

```bash
aws pinpoint-sms-voice-v2 create-registration-association \
  --registration-id <REG_ID> \
  --resource-id <AGENT_ID> \
  --region <REGION>
```

### 4. Upload the brand images

`--attachment-body` and `--attachment-url` cannot be combined; use `--attachment-body` with a
local `fileb://` path:

```bash
aws pinpoint-sms-voice-v2 create-registration-attachment \
  --attachment-body fileb://brand-assets/logo.png --region <REGION>
```

Save `RegistrationAttachmentId` as `LOGO_ID`. Repeat for `banner.png`, save as `BANNER_ID`.

### 5. Fill every registration field

Each field has a type that determines the CLI parameter. Using the wrong one fails:

| Field type | CLI parameter |
|---|---|
| TEXT | `--text-value "<value>"` |
| SELECT | `--select-choices "<value>"` |
| ATTACHMENT | `--registration-attachment-id "<id>"` |

(`--field-values` does not exist. Do not invent it.)

**Query the field definitions FIRST and drive your field-setting from that output** — the
table below is illustrative defaults, not the source of truth (field sets and SELECT choices
can drift by service version):

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type TEST_RCS_LAUNCH_REGISTRATION --region <REGION>
```

Inspect the full response — each `FieldDefinition` object contains the field requirement,
type, path, validation constraints, and any conditional dependencies. Do not filter this
output; conditional field requirements depend on context from the complete definition shape.

SELECT options live under `SelectValidation.Options` as a list of plain strings (not objects) —
a parser expecting `{OptionName: ...}` will throw. If any command below fails on an unknown
field or the submit step reports a missing one, the definitions output wins.

Set every TEXT field (one `put-registration-field-value` call each, same shape):

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.brandName" --text-value "<BRAND_NAME>" --region <REGION>
```

Repeat for each row (quick-mode defaults shown). If you batch these with a shell loop or
function, inline `--region` (and `--profile`) literally in the command — passing multi-word
flag strings through a variable (`R="--region us-east-1"`) breaks on word-splitting:

| FieldPath | Value | Constraint |
|---|---|---|
| `agentDetails.brandName` | brand name | 2–65 chars |
| `agentDetails.serviceName` | `<BRAND_NAME> RCS Agent` | 1–100 chars |
| `agentDetails.senderDisplayName` | brand name | 1–40 chars |
| `agentDetails.agentDescription` | one-liner you invent | **max 100 chars** |
| `agentDetails.accentColor` | the hex from step 1 | `#RRGGBB`, 4.5:1 vs white |
| `agentDetails.contactPhoneNumber` | `+12065550100` | E.164 |
| `agentDetails.contactPhoneLabel` | `Call Us` | 1–25 chars |
| `agentDetails.contactEmailAddress` | `hello@<brand-slug>.example.com` | email |
| `agentDetails.contactEmailLabel` | `Email Us` | 1–25 chars |
| `agentDetails.contactWebsite` | `https://www.<brand-slug>.example.com` | URL |
| `agentDetails.contactWebsiteLabel` | `Visit Website` | 0–25 chars |
| `agentDetails.privacyPolicyUrl` | `https://www.example.com/privacy` | URL |
| `agentDetails.privacyPolicyLabel` | `Privacy Policy` | 0–25 chars |
| `agentDetails.termsAndConditionsUrl` | `https://www.example.com/terms` | URL |
| `agentDetails.termsAndConditionsLabel` | `Terms and Conditions` | 0–25 chars |
| `agentDetails.monthlyRcsVolume` | `1000` | 1–6 digits |
| `complianceKeywords.helpResponse` | `Reply STOP to opt out. For help, contact <email>` | 1–160 chars |
| `complianceKeywords.stopResponse` | `You have been unsubscribed. No more messages will be sent.` | 1–160 chars |

Note on the three URL fields (`contactWebsite`, `privacyPolicyUrl`, `termsAndConditionsUrl`):
on **AWS CLI v2** the plain `--text-value "https://..."` form works. On **AWS CLI v1**, a legacy
"paramfile" feature fetches `https://` parameter values as remote files, so the command fails —
either client-side ("Unable to retrieve ... parameter file" / usage error) or server-side
(`ValidationException: INVALID_PARAMETER Fields="textValue"` when the CLI fetched the page and
sent its HTML), depending on whether the URL resolves. If you see that error (or you
detected CLI v1 in prerequisites), use the JSON form, which bypasses paramfile:

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --region <REGION> --cli-input-json \
  '{"RegistrationId":"<REG_ID>","FieldPath":"agentDetails.contactWebsite","TextValue":"https://www.example.com"}'
```

Set the SELECT fields (note `--select-choices`, not `--text-value`):

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.useCase" --select-choices "MULTI_USE" --region <REGION>
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.averageMonthlyRcsFrequency" --select-choices "10" --region <REGION>
```

Set the remaining SELECT field — easy to miss because older references omit it:

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.billingCategory" --select-choices "CONVERSATIONAL" --region <REGION>
```

Set the ATTACHMENT fields:

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.logoImage" --registration-attachment-id "<LOGO_ID>" --region <REGION>
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "agentDetails.bannerImage" --registration-attachment-id "<BANNER_ID>" --region <REGION>
```

### 6. Audit, then submit and poll for approval

Do not trust your own count of fields set — audit against the service before submitting.
Compare what is SET against what is REQUIRED:

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-values \
  --registration-id <REG_ID> --region <REGION> \
  --query 'RegistrationFieldValues[].FieldPath' --output text | tr '\t' '\n' | sort > /tmp/set.txt
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type TEST_RCS_LAUNCH_REGISTRATION --region <REGION> \
  --query "RegistrationFieldDefinitions[].FieldPath" --output text | tr '\t' '\n' | sort > /tmp/req.txt
comm -13 /tmp/set.txt /tmp/req.txt
```

Do not hardcode a filter on the requirement value — derive the field set from the full
definition and let the live schema decide applicability. Any line printed is a defined field you
have not set; confirm from the field's own definition whether it applies before continuing.
Then submit:

```bash
aws pinpoint-sms-voice-v2 submit-registration-version \
  --registration-id <REG_ID> --region <REGION>
```

Poll BOTH statuses every 15 seconds — they move independently:

```bash
aws pinpoint-sms-voice-v2 describe-registrations --registration-ids <REG_ID> \
  --query 'Registrations[0].RegistrationStatus' --region <REGION>
aws pinpoint-sms-voice-v2 describe-rcs-agents \
  --query "RcsAgents[?RcsAgentId=='<AGENT_ID>'].TestingAgent.Status" --region <REGION>
```

Expected: registration `SUBMITTED → REVIEWING → COMPLETE`, and `TestingAgent.Status: ACTIVE`.
Typically under 5 minutes; don't worry before 10. If the registration lands in
`REQUIRES_UPDATES`, see Failure modes — do not create a new version blindly.

Checkpoint: tell the user the agent is live. To let them **visually see the branding they just
configured** (logo, banner, accent color, contact details as they render), give them the
console link to the agent page:
`https://<REGION>.console.aws.amazon.com/sms-voice/home?region=<REGION>#/rcs-agents?agent-id=<AGENT_ID>`

If they are not already signed in, tell them to sign in to the AWS console first, then open the
link. (This is view-only confirmation; no changes are needed here.)

### 7. Add the user's phone as a verified tester

Wait at least **120 seconds after agent creation** before this call, or it can fail silently.

```bash
aws pinpoint-sms-voice-v2 create-verified-destination-number \
  --destination-phone-number <PHONE> \
  --rcs-agent-id <AGENT_ID> \
  --region <REGION>
```

Tell the user, verbatim enough that they can act on it:

- "You'll get a tester invitation on your phone in 2–20 minutes, from a sender called
  **RBM Tester Management**."
- "On iPhone, it may land in the **Unknown Senders** folder in Messages."
- "Tap **Make me a tester** when it arrives, then tell me."

While waiting, verify the invitation went out:

```bash
aws pinpoint-sms-voice-v2 describe-verified-destination-numbers \
  --filters Name=rcs-agent-id,Values=<AGENT_ID> --region <REGION> \
  --query 'VerifiedDestinationNumbers[].{Phone:DestinationPhoneNumber,Status:Status}'
```

Wait for the user to confirm they tapped it (status becomes `VERIFIED`).

### 8. Clear send blockers, then send the first message

Two account-level settings can block the send. Check both first:

```bash
# Is the destination country blocked by a protect configuration?
aws pinpoint-sms-voice-v2 describe-protect-configurations --region <REGION>
# Is the phone on the opt-out list (e.g. from a previous STOP)?
aws pinpoint-sms-voice-v2 describe-opted-out-numbers \
  --opt-out-list-name Default --region <REGION>
```

Interpreting the protect output: a protect configuration only applies to this send if it is
the **account default** (`AccountDefault: true`), associated with a configuration set you pass
on the send, or passed explicitly as `ProtectConfigurationId`. Other protect configurations in
the account are inert for this quickstart — do not "fix" them.

Fixes, only if needed (each modifies **account-wide** state — confirm with the user first).
⚠️ These are not scoped to this agent or send: a protect-configuration country-rule change and
an opt-out-list deletion affect **every origination identity in the account** (all agents, phone
numbers, and pools), and opt-out removal re-enables messaging to a number that previously sent
STOP. Change them only when you own the account-level policy and understand the blast radius:

- Country blocked: `aws pinpoint-sms-voice-v2 update-protect-configuration-country-rule-set --protect-configuration-id <ID> --number-capability SMS --country-rule-set-updates '{"US":{"ProtectStatus":"ALLOW"}}' --region <REGION>` (the SMS capability governs RCS sends too)
- Opted out: `aws pinpoint-sms-voice-v2 delete-opted-out-number --opt-out-list-name Default --opted-out-number <PHONE> --region <REGION>`

Send:

```bash
aws pinpoint-sms-voice-v2 send-rcs-message \
  --destination-phone-number <PHONE> \
  --origination-identity <AGENT_ID> \
  --rcs-message-content '{"Content":{"TextMessage":{"Body":"Hello from <BRAND_NAME>! This is your first RCS message."}}}' \
  --message-traffic-type TRANSACTIONAL \
  --region <REGION>
```

> The message text goes in `--rcs-message-content` as JSON (`Content.TextMessage.Body`); there is
> no `--message-body` flag. `--message-traffic-type` takes `TRANSACTIONAL` or `PROMOTIONAL`.
>
> **Confirm the current shape against your CLI, don't trust these flags blindly.** The
> `pinpoint-sms-voice-v2` request shape has changed across versions. Before sending, generate the
> skeleton from the installed CLI and fill it in, so you use whatever shape *your* CLI expects
> rather than a possibly-stale example:
>
> ```bash
> aws pinpoint-sms-voice-v2 send-rcs-message --generate-cli-skeleton input > send-rcs.json
> # edit send-rcs.json (DestinationPhoneNumber, OriginationIdentity,
> # RcsMessageContent.Content.TextMessage.Body, MessageTrafficType), then:
> aws pinpoint-sms-voice-v2 send-rcs-message --cli-input-json file://send-rcs.json --region <REGION>
> ```
>
> If a documented flag is rejected (`Unknown options` / `Invalid choice`), regenerate the skeleton
> and use its fields — this is the same reactive stale-model handling as prerequisite 3, applied to
> parameter shape instead of operation existence.

<!-- -->

> **Production note:** For production, add `--configuration-set-name <CONFIG_SET_NAME>` to
> enable delivery telemetry (create a configuration set with an event destination first).
> Pass message bodies via `--cli-input-json` from a file to avoid sensitive content
> persisting in shell history.

Save `MessageId` — and know what it means: **`MessageId` proves the service ACCEPTED the
message, not that it was delivered.** This quickstart sends without a configuration set, which
means there is NO delivery telemetry — you cannot look up what happened to a message
downstream. Set delivery expectations accordingly:

1. Ask the user: "Check your phone — you should see a branded message from <BRAND_NAME> with
   your logo. On iPhone, check Unknown Senders. Give it up to 2 minutes."
2. If nothing arrives: **resend the same command once** before any deeper diagnosis. This is
   the cheapest test and frequently resolves it.
3. If the resend also doesn't arrive, check the device, not the account (the API accepted
   both sends): Android — Messages → Settings → RCS chats → status must be "Connected";
   iPhone — Settings → Apps → Messages → RCS Messaging enabled (iOS 18+, carrier support).
4. Do NOT build logging infrastructure mid-quickstart — but enabling CloudTrail and a
   configuration set with event destinations (SNS with SSE/KMS, CloudWatch Logs with CMK,
   or Kinesis Firehose with server-side encryption) is REQUIRED before production use.
   Encrypt CloudTrail logs and CloudWatch Log groups with a KMS CMK, as message
   bodies and delivery metadata may contain sensitive information.
   Create CloudWatch alarms on send failure rates, throttling events, and spend
   limit utilization to detect anomalous activity before it impacts production. If the user wants real delivery
   telemetry, that is a configuration set + event destination — finish this task first, then
   follow the configuration-sets-and-event-destinations guide.

### 9. Prove inbound works — no infrastructure needed

Set up an auto-response keyword:

```bash
aws pinpoint-sms-voice-v2 put-keyword \
  --origination-identity <AGENT_ID> \
  --keyword HELLOEUM \
  --keyword-action AUTOMATIC_RESPONSE \
  --keyword-message "Inbound works! Your message reached AWS and this reply came back automatically." \
  --region <REGION>
```

If the auto-response doesn't come back, check these IN ORDER before anything else — this
step fails silently, and without a configuration set there is no inbound telemetry to inspect:

1. **Keyword match is exact.** The message must be ONLY the keyword — autocorrect adding
   punctuation (`HELLOEUM.`), predictive text, or leading/trailing words all miss silently.
2. **It must arrive over RCS, not SMS.** An SMS from the device won't route to the agent's
   keyword handler. Confirm the thread shows RCS before blaming configuration.
3. **Allow ~60s** on a freshly activated agent.
4. The console deep link below is the DETERMINISTIC path — it pre-fills the exact keyword over
   the right channel, removing all three ambiguities. Prefer it for the first test.

Walk the user through the console inbound test:

1. Open the agent's **Testing** tab in the console (sign in first if needed):
   `https://<REGION>.console.aws.amazon.com/sms-voice/home?region=<REGION>#/rcs-agents?agent-id=<AGENT_ID>&tab=testing`
2. Click **Inbound deep link**, enter `HELLOEUM` as the message body, generate the link.
3. Scan the QR code with the phone — the message is pre-filled. Send it.
4. The auto-response should arrive within seconds.

## Verify

All three must be true, confirmed by the user and by API:

1. `TestingAgent.Status` is `ACTIVE` and the verified number shows `VERIFIED`.
2. The user received the branded outbound message (step 8).
3. The user sent `HELLOEUM` and received the auto-response (step 9).

Print a summary table for the user: brand, `AGENT_ID`, region, console link.

## Next steps

- **Send rich messages** — cards, carousels, suggestion buttons, webviews: the send-apis guide.
  When a message includes media (`SendRcsMessage` FileMessage or card media), the `FileUrl`
  and `ThumbnailUrl` fields accept **either an `https://` URL or an `s3://` URI**
  (pattern `^(https://|s3://).+$`) pointing to a supported media file — image, video, audio, or
  PDF (see the [RCS file messages guide](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-file-messages.html)
  for the current supported media types and limits). If the media is already reachable at a URL, pass that URL directly — **do NOT create
  an S3 bucket to re-host media you already have a URL for.** Use `s3://` only when the media
  already lives in S3 (the service then downloads, rehosts, and presigns it; the bucket needs a
  resource policy granting `sms-voice.amazonaws.com` read access, scoped with `aws:SourceAccount`
  — and `aws:SourceArn` when a specific resource is known — to prevent cross-account
  confused-deputy access, default encryption at rest enabled (SSE-S3 or SSE-KMS), and a
  deny-non-TLS statement (`"Condition":{"Bool":{"aws:SecureTransport":"false"}}`) so media is only
  retrieved over HTTPS). Do NOT guess or hand-construct
  a media URL (e.g. inventing a CDN path) — use a URL the user provides or one you have verified
  resolves to the file.
- **React to inbound messages with code** — wire an SNS topic (with SSE/KMS, `aws:SourceArn`/`aws:SourceAccount` condition keys, and authorized subscriptions only) and Lambda: the two-way-inbound-lambda guide
- **Rate-limit outbound sends**: Implement application-side throttling on message sends
  (e.g., per-recipient and per-minute caps) to prevent abuse and stay within service quotas.
- **Go to production** — a test agent only reaches verified testers. To message real customers you
  need a production agent launch registration: mechanics in [references/customer-go-to-production-guide.md](customer-go-to-production-guide.md),
  per-country requirements (always discovered live) in the registration-requirements-by-country guide
- Raise the account's monthly spend limit before serious testing (check the current default
  via `aws pinpoint-sms-voice-v2 describe-spend-limits --region <REGION>`):
  request quota `L-2325465C`, then `set-text-message-spend-limit-override`.

## Security Considerations

- **Ephemeral credentials**: Prefer IAM Identity Center (SSO)/assumed-role over long-lived access keys.
- **Input validation**: Validate all user inputs (E.164, URL allowlist, length) before API calls.
- **Encryption**: Encrypt CloudTrail logs and CloudWatch Log groups with KMS CMK.
- **SNS topics**: Enable SSE with KMS, restrict with `aws:SourceArn`/`aws:SourceAccount`, authorize subscriptions.
- **Rate limiting**: Throttle outbound sends per-recipient and per-minute.
- **Deletion protection**: Enabled by default; confirm with user before cleanup.

## Failure modes

| Error / symptom | Cause | Fix |
|---|---|---|
| `AccessDeniedException` on any call | Missing IAM permissions or expired session | Re-auth (`aws sso login --profile <PROFILE>` or `aws configure`); identity needs the required scoped `sms-voice:` actions (not the `sms-voice:*` wildcard) |
| `ExpiredTokenException` | Session expired mid-task | Re-auth, retry the same command |
| `Invalid choice '<operation>'` (any `pinpoint-sms-voice-v2` op, at any step) | Local client's service model is stale or partial — a partial model can carry some ops (e.g. control-plane `describe-rcs-agents`) while omitting others (e.g. data-plane `send-rcs-message`) | Not permissions/account. First check for a stale local override: `ls ~/.aws/models/pinpoint-sms-voice-v2/` — rename it away if present (it shadows the SDK) and retry. If no override, the CLI is too old — give the user the commands to upgrade to the latest AWS CLI v2 (`aws --version`, then the install/update guide); do not run the upgrade yourself. Locked environment → boto3 fallback; if boto3 is also stale, apply the same override check. Resources already created remain valid — resume after fixing |
| Registration `REQUIRES_UPDATES` | A field was denied | `describe-registration-field-values --registration-id <REG_ID>` → find `DeniedReason` → fix the cause → `create-registration-version` → **re-set ALL fields (new versions start empty)** → resubmit |
| `ACCENT_COLOR_CONTRAST_INSUFFICIENT` | Color too light | Pick a darker hex from step 1's list; full re-populate as above |
| Unknown/missing field errors at submit | Field set drifts by CLI/service version | Reconcile against `describe-registration-field-definitions` output; set what it lists |
| No tester invitation after 20 min | Too fast after creation, or agent not ACTIVE | Confirm 120 s elapsed post-creation and `TestingAgent.Status: ACTIVE`; delete and re-create the verified number |
| `DESTINATION_COUNTRY_BLOCKED_BY_PROTECT_CONFIGURATION` | Country rule set blocks destination | Step 8 protect-configuration fix |
| `DESTINATION_PHONE_NUMBER_OPTED_OUT` | Number previously sent STOP | Step 8 opt-out fix, then resend |
| `MONTHLY_SPEND_LIMIT_REACHED` | Default spend limit exhausted (check current default with `describe-spend-limits`) | Quota increase `L-2325465C`, then `set-text-message-spend-limit-override` |
| Message arrives as SMS, not RCS | Agent not ACTIVE, device lacks RCS, or wrong origination identity | Verify agent status; confirm device RCS support; `--origination-identity` must be the `rcs-…` ID or its full ARN |
| Message doesn't arrive at all | Not a verified tester | Test agents ONLY deliver to `VERIFIED` destination numbers — check step 7 |
| `MessageId` returned but nothing arrives (number IS verified) | No delivery telemetry exists without a configuration set; cause is usually device-side | Wait up to 2 min → resend once → check device RCS state (Android: RCS chats "Connected"; iPhone: RCS Messaging on). Don't build logging infra mid-task; for telemetry see the configuration-sets-and-event-destinations guide |

## Cleanup (destructive — confirm with the user first)

```bash
# <VDN_ID> came from the create-verified-destination-number response (or describe-verified-destination-numbers)
aws pinpoint-sms-voice-v2 delete-verified-destination-number --verified-destination-number-id <VDN_ID> --region <REGION>
aws pinpoint-sms-voice-v2 delete-registration --registration-id <REG_ID> --region <REGION>
aws pinpoint-sms-voice-v2 delete-registration-attachment --registration-attachment-id <LOGO_ID> --region <REGION>
aws pinpoint-sms-voice-v2 delete-registration-attachment --registration-attachment-id <BANNER_ID> --region <REGION>
aws pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id <AGENT_ID> --no-deletion-protection-enabled --region <REGION>
aws pinpoint-sms-voice-v2 delete-rcs-agent --rcs-agent-id <AGENT_ID> --region <REGION>
```

If `delete-rcs-agent` fails with `ConflictException RESOURCE_NOT_EMPTY` right after the
registration delete, the testing agent is still tearing down asynchronously — wait ~20-30s and
retry. Attachment deletes can hit the same lag (`RESOURCE_DELETION_NOT_ALLOWED`); same fix.
