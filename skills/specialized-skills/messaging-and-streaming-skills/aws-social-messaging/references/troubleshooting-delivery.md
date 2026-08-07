# Troubleshooting WhatsApp Message Delivery

> **Security:** See [SKILL.md — Security Considerations](../SKILL.md#security-considerations) for encryption, IAM, and audit logging guidance.

## Diagnostic Flow

### Step 1: Check WABA Status

```bash
aws socialmessaging get-linked-whatsapp-business-account --id "waba-XXXXXXXXXXXXXXXXXXXX"

```

- Registration status MUST be `COMPLETE`
- Check `qualityRating` — LOW restricts sending capacity
- If not COMPLETE, finish registration in the AWS Console (cannot be done via CLI)

### Step 2: Check Phone Number Health

```bash
aws socialmessaging get-linked-whatsapp-business-account-phone-number \
  --id "phone-number-id-XXXXXXXXXXXXXXXXXXXX"

```

- Phone must be verified and active
- Quality rating affects sending limits

### Step 3: Inspect Templates

```bash
aws socialmessaging list-whatsapp-message-templates --id "waba-XXXXXXXXXXXXXXXXXXXX"

```

Look for:

- `REJECTED` templates — recreate with compliant content
- `PENDING` > 24h — create a new template
- Category mismatch (submitted UTILITY, now shows MARKETING) — reclassified by Meta

### Step 4: Verify Event Destinations

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn "arn:aws:sns:us-east-1:123456789012:whatsapp-events"

```

- All subscriptions must be `Confirmed`
- Verify subscription endpoints are authorized personnel/systems; use HTTPS-only endpoints
- If no event destination configured, delivery failures are invisible

### Step 5: Check Service Quotas

```bash
aws service-quotas get-service-quota \
  --service-code social-messaging \
  --quota-code L-XXXXXXXX

```

Review [service quotas](https://docs.aws.amazon.com/social-messaging/latest/userguide/quotas.html) for quota codes and defaults. New WABAs have lower limits that increase with quality rating.

### Step 6: Check CloudTrail for API Errors

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=social-messaging.amazonaws.com \
  --max-results 20

```

CloudTrail records all `social-messaging` API calls. Look for `SendWhatsAppMessage` events with error details not visible in the CLI response. Verify CloudTrail is enabled for the account/region. Ensure CloudTrail logs are encrypted with a KMS CMK (see [SKILL.md — Security Considerations](../SKILL.md#security-considerations)).

## Common Error Patterns

| Symptom | Cause | Fix |
|---------|-------|-----|
| Send returns error | Invalid `--origination-phone-number-id` | Use the ID (`phone-number-id-XXXX`), not the phone number |
| Send returns error | Invalid recipient format | Must be E.164 with `+` prefix (e.g., `+14155551234`) |
| Send succeeds but not delivered | Recipient not on WhatsApp | Messages silently dropped; no fix |
| Send succeeds but not delivered | 24h window expired (freeform) | Use template message instead |
| Send succeeds but not delivered | Rate limited | Check quotas; quality rating must improve |
| Template REJECTED | Non-compliant content | Recreate with correct category-matching language |
| Template reclassified | Ambiguous body text | Delete, recreate with clearly transactional language |
| No delivery callbacks | Event destination missing | Configure via `put-whatsapp-business-account-event-destinations` |
| No delivery callbacks | SNS subscription pending | Confirm the subscription endpoint |

## Meta Error Codes

Common codes — see [Meta's error reference](https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes) for the full list.

| Code | Meaning |
|------|---------|
| 131026 | Recipient phone number not on WhatsApp. Verify E.164 format with `+` prefix, confirm number has active WhatsApp, retry after a brief delay for transient failures, and check if your phone number quality rating has degraded |
| 131049 | Message failed — requires recent user engagement (marketing templates) |
| 131047 | Re-engagement message — more than 24h since last reply |
| 131051 | Unsupported message type |
| 130472 | Number deregistered from WhatsApp |

## Quick Checklist

1. ✅ WABA registration COMPLETE
2. ✅ Phone number verified and active
3. ✅ Template APPROVED (not PENDING/REJECTED)
4. ✅ Template category matches content (not reclassified)
5. ✅ Event destinations configured + SNS subscriptions confirmed
6. ✅ Recipient has WhatsApp on that number
7. ✅ Within 24h window (freeform only)
8. ✅ Not exceeding rate limits
