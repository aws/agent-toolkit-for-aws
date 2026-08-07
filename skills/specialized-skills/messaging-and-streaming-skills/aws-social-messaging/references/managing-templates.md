# Managing WhatsApp Message Templates

> **Security:** Template parameters appear in CloudTrail logs — avoid embedding sensitive data. See [SKILL.md — Security Considerations](../SKILL.md#security-considerations).

## Contents

- [Create a Template](#create-a-template)
- [Create from Library](#create-from-library)
- [Check Approval Status](#check-approval-status)
- [Get Template Details](#get-template-details)
- [Update a Template](#update-a-template)
- [Delete a Template](#delete-a-template)

## Create a Template

The `--template-definition` parameter is a blob type — base64-encode the JSON.

### Utility Template (transactional)

```bash
TEMPLATE_DEF=$(printf '%s' '{"name":"order_shipment_update","category":"UTILITY","language":"en_US","parameter_format":"positional","components":[{"type":"BODY","text":"Your order #{{1}} has shipped. Track: {{2}}","example":{"body_text":[["ORD-12345","https://example.com/track/12345"]]}}]}' | base64 | tr -d '\n')

aws socialmessaging create-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --template-definition "$TEMPLATE_DEF"

```

### Marketing Template (with image header)

First, upload the header image using `create-whatsapp-message-template-media` to get a media handle (see [managing-media.md](managing-media.md#upload-media-for-template-headers)). Then use the returned handle in the template:

```bash
TEMPLATE_DEF=$(printf '%s' '{"name":"seasonal_promotion","language":"en_US","category":"MARKETING","parameter_format":"positional","components":[{"type":"HEADER","format":"IMAGE","example":{"header_handle":["4::aW1hZ2UvanBlZw==:ARb..."]}},{"type":"BODY","text":"Hi {{1}}! Get {{2}}% off all items through {{3}}.","example":{"body_text":[["Jane","25","June 30"]]}}]}' | base64 | tr -d '\n')

aws socialmessaging create-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --template-definition "$TEMPLATE_DEF"

```

### Authentication Template (verification codes)

```bash
TEMPLATE_DEF=$(printf '%s' '{"name":"login_verification","language":"en_US","category":"AUTHENTICATION","components":[{"type":"BODY","text":"{{1}} is your verification code.","example":{"body_text":[["847293"]]}},{"type":"FOOTER","text":"This code expires in 10 minutes."},{"type":"BUTTONS","buttons":[{"type":"OTP","otp_type":"COPY_CODE","text":"Copy code"}]}]}' | base64 | tr -d '\n')

aws socialmessaging create-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --template-definition "$TEMPLATE_DEF"

```

Authentication templates do not require `parameter_format` — Meta handles the OTP parameter automatically. The `COPY_CODE` button type lets recipients tap to copy the code.

### Expected Output

```json
{
  "metaTemplateId": "123456789",
  "templateStatus": "PENDING",
  "templateCategory": "UTILITY"
}

```

### Rules

- `parameter_format`: MUST be `"positional"` when using `{{N}}` parameters
- `example`: MUST include sample values for each component — Meta requires this for review
- UTILITY body MUST be clearly transactional; ambiguous text gets reclassified as MARKETING
- Template names: lowercase letters, numbers, underscores only

### Choosing the Right Category

Meta enforces strict categorization rules. Choosing the wrong category causes **reclassification** (UTILITY → MARKETING), which changes pricing and may disrupt sending. Select the correct category upfront:

| Category | Use When | Key Signals |
|----------|----------|-------------|
| **UTILITY** | Confirming or updating an existing transaction the user initiated | Order confirmations, shipping updates, appointment reminders, payment receipts, account alerts |
| **MARKETING** | Promoting products/services, re-engaging users, or any content the user did not explicitly request | Promotions, discounts, product recommendations, back-in-stock alerts, newsletters, upsells |
| **AUTHENTICATION** | Sending one-time passwords or verification codes | Login codes, 2FA, account verification — must use OTP button component |

**Common reclassification triggers (UTILITY → MARKETING):**

- Body text contains promotional language ("Get X% off", "Limited time", "Shop now", "Don't miss")
- Template includes a call-to-action unrelated to the transaction (e.g., "Check out our new products")
- Greeting or introduction without referencing a specific user-initiated action
- Coupon codes or discount offers included alongside transactional content
- Generic "updates" that aren't tied to a specific order, appointment, or account event

**How to avoid reclassification:**

1. Keep UTILITY templates focused on a single transaction — reference the specific order/appointment/account action
2. Do NOT mix promotional content into transactional templates — create a separate MARKETING template for promotions
3. Use explicit transaction references in the body: "Your order #{{1}}", "Your appointment on {{1}}", "Your payment of {{1}}"
4. If in doubt, use MARKETING — it always works; reclassification only happens UTILITY → MARKETING, never the reverse
5. Configure [event destinations](configuring-event-destinations.md) to receive `TEMPLATE_STATUS_UPDATE` events that alert you to reclassifications in real-time

**Detecting reclassification after the fact:**

- Via event destinations: `"eventType": "TEMPLATE_STATUS_UPDATE"` with `previousCategory` and `newCategory`
- Via API: `list-whatsapp-message-templates` — compare `templateCategory` against your expected category
- **Recovery:** Delete the reclassified template and recreate with corrected content or as MARKETING

## Create from Library

Browse and use pre-approved Meta library templates:

```bash
aws socialmessaging list-whatsapp-template-library

aws socialmessaging create-whatsapp-message-template-from-library \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --meta-library-template '{"templateName":"my_order_update","libraryTemplateName":"order_status_update","templateCategory":"UTILITY","templateLanguage":"en_US"}'

```

## Check Approval Status

```bash
aws socialmessaging list-whatsapp-message-templates --id "waba-XXXXXXXXXXXXXXXXXXXX"

```

Response fields are `templateStatus` and `templateCategory` (NOT `status`/`category`):

```json
{
  "templates": [{
    "templateName": "order_shipment_update",
    "metaTemplateId": "123456789",
    "templateStatus": "APPROVED",
    "templateCategory": "UTILITY",
    "templateLanguage": "en_US"
  }]
}

```

- UTILITY: minutes to 24h. MARKETING: hours to 24h.
- MUST NOT send with PENDING or REJECTED status.

## Get Template Details

```bash
aws socialmessaging get-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --meta-template-id "123456789"

```

Use this to retrieve component structure before sending an existing template.

## Update a Template

```bash
aws socialmessaging update-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --meta-template-id "123456789" \
  --template-components "$(printf '%s' '[{"type":"BODY","text":"Your order #{{1}} has shipped. Delivery by: {{2}}","example":{"body_text":[["ORD-12345","July 15"]]}}]' | base64 | tr -d '\n')"

```

The `--template-components` parameter is a blob type — base64-encode the JSON components array. Updated templates go back to PENDING for Meta re-review.

## Delete a Template

⚠️ The delete parameter is `--template-name` (NOT `--meta-template-name`, NOT `--meta-template-id`). There is no `--meta-template-name` parameter — it does not exist.

```bash
aws socialmessaging delete-whatsapp-message-template \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --template-name "order_shipment_update" \
  --delete-all-languages

```

Always include `--delete-all-languages` to avoid `InvalidParametersException`.
