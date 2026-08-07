# Sending WhatsApp Messages

> **Security:** Avoid sensitive data in template parameters, freeform message text, and all message content — they appear in CloudTrail logs. See [SKILL.md — Security Considerations](../SKILL.md#security-considerations).

## Contents
- [Template Messages](#template-messages)
- [Freeform Messages (24h Window)](#freeform-messages-24h-window)
- [Parameters](#parameters)
- [Expected Output](#expected-output)
- [Freeform Constraints](#freeform-constraints)

The `--message` parameter is a blob type — base64-encode the JSON.

⚠️ The `"to"` field MUST use E.164 format WITH the `+` prefix (e.g., `"+14155551234"`, NOT `"14155551234"`). Alternatively, recipients can be addressed by Business-Scoped User ID (BSUID) — a username in the format `CC.alphanumeric` (e.g., `US.13491208655302741918`) passed via the `"recipient"` field instead of `"to"`.

**Required JSON body fields (all message types):**
- `"messaging_product": "whatsapp"` — mandatory, always this value
- `"to"` — recipient in E.164 format with `+` prefix
- `"type"` — message type (`"template"`, `"text"`, `"image"`, `"document"`, etc.)

**⚠️ API Version:** Before constructing commands, determine the Meta Graph API version to use by checking [Meta's Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog). The examples below use `v{Major}.{Minor}` as a placeholder — substitute the latest supported version in `v{Major}.{Minor}` format (e.g., `v21.0`).

## Template Messages

### Send Utility Template

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","to":"+14155551234","type":"template","template":{"name":"order_shipment_update","language":{"code":"en_US"},"components":[{"type":"body","parameters":[{"type":"text","text":"ORD-98765"},{"type":"text","text":"https://example.com/track/98765"}]}]}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

### Send Marketing Template (with image header)

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","to":"+14155551234","type":"template","template":{"name":"seasonal_promotion","language":{"code":"en_US"},"components":[{"type":"header","parameters":[{"type":"image","image":{"link":"https://example.com/current-promo.jpg"}}]},{"type":"body","parameters":[{"type":"text","text":"Jane"},{"type":"text","text":"25"},{"type":"text","text":"June 30"}]}]}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

### Send Authentication Template

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","to":"+14155551234","type":"template","template":{"name":"login_verification","language":{"code":"en_US"},"components":[{"type":"body","parameters":[{"type":"text","text":"847293"}]}]}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

## Freeform Messages (24h Window)

### Send Text

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","recipient_type":"individual","to":"+14155551234","type":"text","text":{"body":"Thank you for contacting us. Your issue has been resolved."}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

### Send Image (via Media ID — Recommended for Sensitive Content)

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","recipient_type":"individual","to":"+14155551234","type":"image","image":{"id":"XXXXXXXXXXXXXXXXXXXX","caption":"Your receipt"}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

For non-sensitive images, you may use a public URL instead of a media ID — the URL must remain accessible for the full 30-day message availability window:

**Security:** For sensitive content (receipts, invoices, documents with PII), upload via `post-whatsapp-message-media` and reference by media ID instead of using publicly accessible URLs. See [managing-media.md](managing-media.md#usage-in-messages).

### Send Document (via Media ID)

```bash
MESSAGE=$(printf '%s' '{"messaging_product":"whatsapp","recipient_type":"individual","to":"+14155551234","type":"document","document":{"id":"XXXXXXXXXXXXXXXXXXXX","caption":"Invoice #1234","filename":"invoice-1234.pdf"}}' | base64 | tr -d '\n')

aws socialmessaging send-whatsapp-message \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --message "$MESSAGE" \
  --meta-api-version "v{Major}.{Minor}"
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--origination-phone-number-id` | Yes | Phone number ID (format: `phone-number-id-XXXX`) |
| `--message` | Yes | Base64-encoded WhatsApp Cloud API message JSON |
| `--meta-api-version` | Yes | Meta Graph API version (format: `v{Major}.{Minor}`, e.g., `v21.0`). Check [Meta's Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog) for the latest supported version. |

## Expected Output

```json
{
  "messageId": "wamid.XXXXXXXXXXXXXXXXXXXX"
}
```

A `messageId` confirms queued for delivery — not delivered. Configure event destinations for delivery status.

## Freeform Constraints

- MUST be sent within 24h of customer's last inbound message
- No API to check window status — verify from application logs or event destination history
- Text length limits per [WhatsApp Cloud API reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages)
- Media limits vary by type — consult [WhatsApp Cloud API media reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media) for supported formats and size constraints
- Media URLs must be publicly accessible via HTTPS and remain available for the full 30-day message availability window — Meta can re-fetch media at any time during this period. For sensitive content (receipts, invoices, PII), upload via `post-whatsapp-message-media` and reference by media ID instead — see [managing-media.md](managing-media.md#usage-in-messages). Note: public URLs are logged in CloudTrail and may be cached by intermediaries. Ensure CloudTrail logs are encrypted with a KMS CMK to protect logged URLs and message metadata.
