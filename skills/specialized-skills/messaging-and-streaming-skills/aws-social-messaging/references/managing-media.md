# Managing WhatsApp Media

> **Security:** S3 buckets used for media storage should have default encryption enabled (SSE-S3 or SSE-KMS) and enforce `aws:SecureTransport` in the bucket policy. Media files may contain sensitive content (receipts, invoices, PII). See [SKILL.md — Security Considerations](../SKILL.md#security-considerations).

## Upload Media

### Option 1: From S3 Bucket

```bash
aws socialmessaging post-whatsapp-message-media \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --source-s3-file '{"bucketName":"my-media-bucket","key":"images/receipt.png"}'
```

### Option 2: From Presigned URL

```bash
aws socialmessaging post-whatsapp-message-media \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX" \
  --source-s3-presigned-url '{"url":"https://my-bucket.s3.amazonaws.com/image.png","headers":{}}'
```

> **Security:** When generating presigned URLs, set a short expiration (15–30 minutes) to limit the window of access. See [SKILL.md — Security Considerations](../SKILL.md#security-considerations).

Returns a reusable media ID for sending messages without re-uploading.

## Upload Media for Template Headers

```bash
aws socialmessaging create-whatsapp-message-template-media \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --source-s3-file '{"bucketName":"my-media-bucket","key":"templates/promo-header.jpg"}'
```

Use the returned media handle in template `HEADER` component's `header_handle` field.

## Get Media

```bash
aws socialmessaging get-whatsapp-message-media \
  --media-id "XXXXXXXXXXXXXXXXXXXX" \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX"
```

Returns media metadata and a download URL.

> **Sensitive data:** The returned download URL may be logged in CloudTrail and provides temporary access to media content — treat it as sensitive. Similarly, `post-whatsapp-message-media` input parameters (S3 bucket/key, presigned URLs) appear in CloudTrail logs.

## Delete Media

```bash
aws socialmessaging delete-whatsapp-message-media \
  --media-id "XXXXXXXXXXXXXXXXXXXX" \
  --origination-phone-number-id "phone-number-id-XXXXXXXXXXXXXXXXXXXX"
```

## Supported Media Types

Limits per [WhatsApp Cloud API media reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media) — check Meta's documentation for supported formats and size constraints.

## Usage in Messages

Once uploaded, reference media by ID instead of URL:

```json
{"type":"image","image":{"id":"XXXXXXXXXXXXXXXXXXXX","caption":"Your receipt"}}
```

This avoids requiring publicly accessible URLs for each send.
