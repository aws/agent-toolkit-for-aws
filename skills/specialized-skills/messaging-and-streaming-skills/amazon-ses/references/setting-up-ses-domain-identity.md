# Setting Up SES Domain Identity

> Operations below use AWS CLI syntax. For sandboxed execution, use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html).

## Contents

- [Overview](#overview)
- [Required IAM Permissions](#required-iam-permissions)
- [Parameters](#parameters)
- [Step 1: Verify Prerequisites](#step-1-verify-prerequisites)
- [Step 2: Check Existing Identity State](#step-2-check-existing-identity-state)
- [Step 3: Create Domain Identity with DKIM](#step-3-create-domain-identity-with-dkim)
- [Step 4: Configure Custom MAIL FROM](#step-4-configure-custom-mail-from)
- [Step 5: Build DMARC Record](#step-5-build-dmarc-record)
- [Step 6: Present ALL DNS Records Together](#step-6-present-all-dns-records-together)
- [Step 7: Verify DNS Propagation](#step-7-verify-dns-propagation)
- [Troubleshooting: DKIM Stuck in PENDING](#troubleshooting-dkim-stuck-in-pending)
- [Security Considerations](#security-considerations)

## Overview

Complete workflow for domain-based email authentication in Amazon SES V2. Creates a domain identity with Easy DKIM, configures a custom MAIL FROM subdomain for SPF alignment, and establishes a DMARC monitoring policy — aligned with the SES Guided Onboarding wizard.

## Required IAM Permissions

```
ses:CreateEmailIdentity
ses:GetEmailIdentity
ses:PutEmailIdentityMailFromAttributes
ses:PutEmailIdentityDkimSigningAttributes
ses:DeleteEmailIdentity
```

Scope to the specific domain identity resource:

```
Resource: arn:aws:ses:{region}:{account-id}:identity/{domain}
```

Add `route53:ChangeResourceRecordSets` and `route53:ListHostedZonesByName` if automating DNS in Route 53. Scope to the hosted zone: `Resource: arn:aws:route53:::hostedzone/{hosted-zone-id}`

## Parameters

Collect ALL parameters from user upfront before executing any steps. Present them together with explanations so the user can make informed choices in a single response.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `domain` | Yes | — | Domain to authenticate (e.g., `example.com`) |
| `region` | Yes | from CLI config | AWS region (SES is region-scoped) |
| `mail_from_subdomain` | No | — | Custom MAIL FROM subdomain. **MUST ask user** — suggest `mail.{domain}` or `bounce.{domain}` but let them choose. |
| `behavior_on_mx_failure` | No | `USE_DEFAULT_VALUE` | Fallback behavior if MAIL FROM MX unreachable. |
| `configure_dmarc` | No | `true` | Add DMARC TXT record. |

## Step 1: Verify Prerequisites

```bash
aws sts get-caller-identity
aws sesv2 get-account --region {region}
```

- Confirm AWS CLI v2 installed and configured
- Confirm region supports SES
- Note: account may be in sandbox mode (can only send to verified addresses) — inform user but proceed with identity setup

## Step 2: Check Existing Identity State

```bash
aws sesv2 get-email-identity --email-identity {domain} --region {region}
```

**If `NotFoundException`** → new identity, proceed to Step 3.

**If identity exists** → inspect and add only what's missing:

- `DkimAttributes.Status` is `SUCCESS` → DKIM verified, skip Step 3
- `DkimAttributes.Status` is `PENDING` → DKIM creation done, DNS may be propagating. Check DNS records, skip Step 3.
- `DkimAttributes.Status` is `FAILED` or `TEMPORARY_FAILURE` → first verify DNS records are correct (same steps as Troubleshooting section below). If DNS is correct but status remains FAILED, force re-verification:

  ```bash
  aws sesv2 put-email-identity-dkim-signing-attributes \
    --email-identity {domain} \
    --signing-attributes-origin AWS_SES \
    --region {region}
  ```

  This generates new tokens — present the updated CNAME records to the user.
- `DkimAttributes.Status` is `NOT_STARTED` → DKIM not configured, proceed to Step 3
- `MailFromAttributes.MailFromDomain` populated → MAIL FROM configured, skip Step 4
- Check DMARC: `dig TXT _dmarc.{domain} +short` — if record exists, skip Step 5

## Step 3: Create Domain Identity with DKIM

```bash
aws sesv2 create-email-identity \
  --email-identity {domain} \
  --region {region}
```

This creates the identity with Easy DKIM (2048-bit RSA, SES-managed keys) by default.

**After creation, extract DKIM tokens from the response:**

- `DkimAttributes.Tokens` — array of 3 tokens used to build CNAME records

**Do NOT tell user to wait 72 hours.** In practice, verification usually completes within minutes once DNS records propagate. The 72h figure is the maximum detection window (how long SES keeps polling before giving up) — see [AWS docs](https://docs.aws.amazon.com/ses/latest/dg/troubleshoot-dkim.html). If records are correct after 10 minutes, there is no API to force re-check — just wait briefly and re-query.

## Step 4: Configure Custom MAIL FROM

Use the `mail_from_subdomain` collected in the Parameters step. If user didn't specify one, ask now before proceeding:
> "What subdomain would you like for MAIL FROM? Common choices are `mail.{domain}` or `bounce.{domain}`. This subdomain will appear in the envelope sender (Return-Path) and enables SPF alignment."

```bash
aws sesv2 put-email-identity-mail-from-attributes \
  --email-identity {domain} \
  --mail-from-domain {mail_from_subdomain} \
  --behavior-on-mx-failure {behavior_on_mx_failure} \
  --region {region}
```

**Note:** MAIL FROM can be configured at any time — it does not need to wait for DKIM verification.

## Step 5: Build DMARC Record

Construct the DMARC TXT record for `_dmarc.{domain}`:

```
v=DMARC1; p=none;
```

- `p=none` — monitoring only (reports but doesn't reject). Plan progression to `p=quarantine` → `p=reject` after confirming alignment.
- **DMARC alignment**: MUST DKIM-align (identifier alignment between `d=` in DKIM signature and From header domain). SHOULD also SPF-align via custom MAIL FROM.

## Step 6: Present ALL DNS Records Together

**Present as a single batch** — do not make the user add records one at a time:

```
## DNS Records to Add

### DKIM (3 CNAME records)
{token1}._domainkey.{domain}  CNAME  {token1}.dkim.amazonses.com
{token2}._domainkey.{domain}  CNAME  {token2}.dkim.amazonses.com
{token3}._domainkey.{domain}  CNAME  {token3}.dkim.amazonses.com

### MAIL FROM (2 records)
{mail_from_subdomain}         MX     10 feedback-smtp.{region}.amazonses.com
{mail_from_subdomain}         TXT    "v=spf1 include:amazonses.com ~all"

### DMARC (1 TXT record)
_dmarc.{domain}               TXT    "v=DMARC1; p=none;"
```

**If Route 53 hosts the domain:**

1. Check: `aws route53 list-hosted-zones-by-name --dns-name {domain}`
2. Verify the zone is authoritative (NS records for the domain match the hosted zone's NS records)
3. **MUST ask user for explicit permission before creating DNS records.** Route 53 mutations can affect live traffic. Only proceed if user confirms.
4. If permission granted, create all records via `aws route53 change-resource-record-sets`

**If external DNS provider:**

- Present records clearly and instruct user to add them at their provider
- Warn about common DNS provider quirks: some append the domain name automatically (so `{token}._domainkey` becomes `{token}._domainkey.example.com.example.com`)

## Step 7: Verify DNS Propagation

After user confirms records are added:

```bash
# Check DKIM
dig CNAME {token1}._domainkey.{domain} +short

# Check MAIL FROM MX
dig MX {mail_from_subdomain} +short

# Check MAIL FROM SPF
dig TXT {mail_from_subdomain} +short

# Check DMARC
dig TXT _dmarc.{domain} +short
```

Then confirm SES has picked up the changes:

```bash
aws sesv2 get-email-identity --email-identity {domain} --region {region}
```

Look for `DkimAttributes.Status: SUCCESS` and `MailFromAttributes.MailFromDomainStatus: SUCCESS`.

## Troubleshooting: DKIM Stuck in PENDING

If DKIM remains PENDING after DNS records are added:

1. **Get the expected tokens:**

   ```bash
   aws sesv2 get-email-identity --email-identity {domain} --region {region} \
     --query 'DkimAttributes.Tokens'
   ```

2. **Check each CNAME resolves correctly:**

   ```bash
   dig CNAME {token}._domainkey.{domain} +short
   ```

   Expected: `{token}.dkim.amazonses.com`

3. **Common causes:**
   - DNS provider appended the domain (record is `{token}._domainkey.example.com.example.com` instead of `{token}._domainkey.example.com`)
   - Records in wrong hosted zone (zone exists but isn't authoritative — check NS records)
   - TTL propagation delay (typically resolves within minutes, not hours)
   - Wildcard CNAME conflict overriding the specific DKIM record

4. **If records are correct but SES still shows PENDING:** SES polls DNS periodically. There is no API to force re-verification — wait a few minutes and re-query. In rare cases, SES can take up to 72 hours to detect records ([see docs](https://docs.aws.amazon.com/ses/latest/dg/troubleshoot-dkim.html)), but this typically means minutes, not hours.

## Security Considerations

- Scope IAM to the specific SES actions listed in the Required IAM Permissions section above — never use `ses:*` wildcards
- Use IAM roles (ephemeral credentials via STS) — never long-lived access keys
- DMARC `p=none` is monitoring only — inform user to plan progression to `p=quarantine` after alignment is confirmed
- For senders exceeding 5,000 messages/day to Gmail/Yahoo: DMARC alignment is mandatory per bulk-sender requirements. This workflow establishes the prerequisite.
- Enable CloudTrail for SES API call auditing
