# Configuring Event Destinations

> **Security:** Encrypt SNS topics with KMS; callbacks may contain recipient metadata. See [SKILL.md — Security Considerations](../SKILL.md#security-considerations).

## Contents
- [Overview](#overview)
- [Configure Event Destination](#configure-event-destination)
- [Prerequisites](#prerequisites)
- [Verify Configuration](#verify-configuration)
- [Event Payload Examples](#event-payload-examples)

## Overview

Event destinations deliver real-time notifications for:
- Message delivery status (sent, delivered, read, failed)
- Template status changes (approved, rejected)
- Template reclassification (UTILITY → MARKETING)

Without event destinations, delivery failures and reclassifications are invisible.

## Configure Event Destination

A WABA can only have **one** event destination at a time.

```bash
aws socialmessaging put-whatsapp-business-account-event-destinations \
  --id "waba-XXXXXXXXXXXXXXXXXXXX" \
  --event-destinations '[{"eventDestinationArn":"arn:aws:sns:us-east-1:123456789012:whatsapp-events","roleArn":"arn:aws:iam::123456789012:role/WhatsAppEventDeliveryRole"}]'
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--id` | Yes | WABA ID (format: `waba-XXXX`) |
| `--event-destinations` | Yes | Array with one entry: SNS topic ARN + IAM role ARN |

## Prerequisites

### 1. SNS Topic

Create an SNS topic with KMS encryption:

```bash
aws sns create-topic --name whatsapp-events --attributes '{"KmsMasterKeyId":"alias/aws/sns"}'
```

### 2. IAM Role

The role must:
- Trust `social-messaging.amazonaws.com` in its assume-role policy
- Have `sns:Publish` permission on the SNS topic

Trust policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "social-messaging.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "123456789012"},
      "ArnLike": {"aws:SourceArn": "arn:aws:social-messaging:*:123456789012:*"}
    }
  }]
}
```

Permission policy (attach to the role):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sns:Publish",
    "Resource": "arn:aws:sns:us-east-1:123456789012:whatsapp-events"
  }]
}
```

### 3. SNS Topic Policy

Add a resource policy to allow `social-messaging.amazonaws.com` to publish, with condition keys to prevent confused deputy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowSocialMessagingPublish",
    "Effect": "Allow",
    "Principal": {"Service": "social-messaging.amazonaws.com"},
    "Action": "sns:Publish",
    "Resource": "arn:aws:sns:us-east-1:123456789012:whatsapp-events",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "123456789012"},
      "ArnLike": {"aws:SourceArn": "arn:aws:social-messaging:*:123456789012:*"}
    }
  },
  {
    "Sid": "DenyNonSSL",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "sns:Publish",
    "Resource": "arn:aws:sns:us-east-1:123456789012:whatsapp-events",
    "Condition": {
      "Bool": {"aws:SecureTransport": "false"}
    }
  }]
}
```

## Verify Configuration

Check SNS subscriptions are confirmed:

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn "arn:aws:sns:us-east-1:123456789012:whatsapp-events"
```

Subscriptions must show `"SubscriptionArn"` (not `"PendingConfirmation"`).

Verify SNS subscription endpoints are authorized personnel/systems — use access policies to restrict who can subscribe. Use HTTPS-only endpoints for encryption in transit.

## Event Payload Examples

Delivery receipt:
```json
{
  "eventType": "MESSAGE_STATUS_UPDATE",
  "messageId": "wamid.XXXX",
  "status": "delivered",
  "recipientId": "+14155551234"
}
```

Template reclassification:
```json
{
  "eventType": "TEMPLATE_STATUS_UPDATE",
  "templateName": "order_update",
  "previousCategory": "UTILITY",
  "newCategory": "MARKETING"
}
```

