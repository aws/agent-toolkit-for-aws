---
name: amazon-ses
description: "Configures Amazon SES V2 for production email sending — including domain identity creation, DKIM/SPF/DMARC authentication, one-shot DNS record presentation, and Route 53 automation — for developers setting up or troubleshooting SES domain verification and deliverability. Applicable when developers need to send emails from their domain via SES, verify a domain identity, configure email authentication, troubleshoot DKIM verification issues, or ensure their sending setup follows best practices. Not for email-address-only verification, Mail Manager inbound routing, SNS, Pinpoint, or WorkMail."
version: 1
---

# Amazon SES

> **Recommended**: Use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html) with SES permissions for sandboxed execution and CloudTrail audit logging.
> **Without MCP**: All operations use standard AWS CLI syntax (`aws sesv2 ...`).

## Overview

This skill helps developers and DevOps engineers configure Amazon SES for production email sending. It targets users who are not email authentication experts — guiding them through complete domain setup following AWS best practices without requiring deep knowledge of DKIM, SPF, or DMARC.

## Routing

| If the user wants to... | Read |
|-------------------------|------|
| Set up a domain for sending, configure email authentication, or troubleshoot DKIM | [Setting up SES domain identity](references/setting-up-ses-domain-identity.md) |

## Security

- Use IAM roles with ephemeral credentials (STS) — never long-lived access keys
- Scope IAM permissions to specific SES actions per workflow (see reference files for required permissions)
- Enable CloudTrail for SES API call auditing
- DMARC `p=none` is monitoring only — plan progression to `p=quarantine` after confirming alignment
- Never hardcode credentials, endpoints, or secrets in examples

## Critical Rules

- **MUST** create a domain identity (not email identity) for production sending
- **MUST** configure custom MAIL FROM subdomain for SPF alignment
- **MUST** configure DMARC TXT record (`p=none` minimum) for domain alignment
- **MUST** present all DNS records together in one batch
- **MUST** ask user for preferred MAIL FROM subdomain (do not assume a default)
- **SHOULD** check if Route 53 hosts the domain and offer automatic DNS creation
- **SHOULD NOT** claim 72-hour wait — verification typically completes in minutes once DNS propagates

## Additional Resources

- [SES Domain Verification](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)
- [DKIM in SES](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim.html)
- [Custom MAIL FROM](https://docs.aws.amazon.com/ses/latest/dg/mail-from.html)
- [DMARC Authentication](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dmarc.html)
