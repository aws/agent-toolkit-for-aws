---
name: amazon-ses
description: "Guides domain-based email sending setup with Amazon SES, including the recommended default setup, identity and DNS authentication, a test send, production access, and troubleshooting. Use when a customer asks to set up email sending, SES, or AWS email; resume incomplete onboarding; or leave the sandbox. Does not cover inbound email or Mail Manager, SMS/voice, WhatsApp, SNS, Pinpoint, or WorkMail."
version: 3
---

# Amazon SES

## Overview

> **Recommended**: Use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html) with SES permissions for sandboxed execution and CloudTrail audit logging.
> **Without MCP**: All operations use standard AWS CLI syntax (`aws sesv2 ...`).

Takes a user who is not an email authentication expert from a new SES account to a complete
default sending setup and an SES-accepted test message, and on request to a real inbox and
production access. Read account and identity state first, complete only what is missing, and
request production access only after domain setup is complete and the user consents.

## Routing

| If the user wants to... | Read |
|-------------------------|------|
| Set up email sending (including when the request says only "email", "AWS email", or "SES"), send a first or test email, leave the sandbox, resume onboarding, or diagnose `MessageRejected: Email address is not verified` | [SES onboarding](references/onboarding.md) |
| Set up a domain choosing the authentication details yourself, configure email authentication, or troubleshoot DKIM | [Setting up SES domain identity](references/setting-up-ses-domain-identity.md) |

## Guardrail — where this skill's own files live (MCP vs local install)

- **Loaded through the AWS MCP `retrieve_skill` tool:** the skill is not on the local filesystem. **You MUST fetch each reference** via `retrieve_skill` with the `file` parameter (e.g. `file="references/onboarding.md"`). Do NOT `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `~/.kiro/skills/amazon-ses/`, `.kiro/skills/amazon-ses/`, or `~/.claude/skills/amazon-ses/`): read files from the local skill directory using the relative paths above.

This applies only to the skill's own files. User data and session artifacts are always read from and written to the user's working directory — never fetch or write customer data through `retrieve_skill`.

## Critical Rules

- **MUST** use the SES v2 API (`aws sesv2 ...`), never v1 `aws ses ...`: a v1 command gives no
  sign that it is the wrong API, and production-access requests plus DKIM and MAIL FROM in one
  identity read exist only in v2.
- **MUST NOT** volunteer API mechanics, internal limit figures, or other plumbing. Explain only
  what the user must decide, consent to, pay for, or act on, unless they ask or a reference
  requires the disclosure.
- **MUST** ask for missing inputs in ONE question set, and only for inputs the requested scope
  needs; if nothing is missing, ask nothing. A progress update such as "I'll create it next" is
  not a stopping point: continue until the scope is complete or a conflict, service error,
  timeout, or missing reference-owned consent blocks it. Ask setup questions once, upfront:
  after the read-only discovery and before any write, put every missing input and the Route 53
  permission (`CREATE` only the missing SES records in the named zone, nothing replaced or
  deleted) in one question; skip what the request already gave, and do not ask for it again; record collisions still need the user.
  The full journey keeps its separate consent for production access and for a real send.
- **MUST NOT** ask for the AWS CLI profile or Region while either resolves. Honour `--profile`
  only if the user names one. Region order: user-named; `AWS_REGION`; `AWS_DEFAULT_REGION`;
  `aws configure get region` (with `--profile` when named; it does not read the environment).
  State the Region and the `aws sts get-caller-identity` account before any mutation. Ask only
  when no Region resolves, or when credentials fail (then ask which account and Region to use once
  refreshed), folded into the one question set.
- **MUST** pass request payloads as inline JSON strings, never `file://` paths, which do not
  resolve through the AWS MCP server.
- **MUST** read state before each step and skip satisfied steps: never `create-email-identity` an
  existing identity (`AlreadyExistsException`), and never re-run
  `put-email-identity-dkim-signing-attributes` when `DkimAttributes.Status` is `SUCCESS` (it can
  change the tokens). Gate that recovery on status, not on whether CNAMEs resolve;
  `setting-up-ses-domain-identity.md` owns it.
- **For domain setup, create a domain identity.** Create an email-address identity only when the
  user explicitly chooses to verify that address.

## Invariants

These hold everywhere; references may add step detail but never contradict or relax them.

- **Domain setup complete** means one `get-email-identity` response shows
  `VerifiedForSendingStatus: true`, `DkimAttributes.Status: SUCCESS`, and
  `MailFromAttributes.MailFromDomainStatus: SUCCESS`. While MAIL FROM is unresolved, SES uses the
  fallback: `USE_DEFAULT_VALUE` sends from an `amazonses.com` subdomain (SPF does not align, so
  DMARC needs DKIM), and `REJECT_MESSAGE` returns `MailFromDomainNotVerified` without delivery.
- **Sandbox recipient rule.** While `ProductionAccessEnabled` is `false` — whatever
  `Details.ReviewDetails.Status` says — you can only send **to** (1) an address verified as its
  own email identity, (2) the Amazon SES mailbox simulator, or (3) any address at any verified
  domain in the account. The restriction is on the recipient, not the sender; never work around
  it. When explaining it, name all three options in that numbering before proposing production
  access, and never say "each recipient must be individually verified".
- **The sender must be verified in every account state**, so `MessageRejected: Email address is
  not verified` can mean an unpermitted sandbox recipient or an unverified sender; read the
  address in the error before choosing a fix.
- **DKIM `SUCCESS` is this skill's bar**, above the SES minimum of a verified sender: required
  before claiming setup or authentication complete and before sending. The default setup's
  simulator `MessageId` proves SES acceptance only.
- **Validate every substituted value, then quote it for its context.** Single-quote a value
  substituted into a shell command; JSON-encode a value inside inline JSON and single-quote only
  the whole blob. Reject any value containing a quote, backtick, `$`, `;`, backslash, or
  whitespace and ask again; never escape it into shape. Shapes: `DOMAIN` and the MAIL FROM
  subdomain — DNS labels only, letters, digits, hyphens and dots; From and every recipient a single address with one `@` (several recipients go in the
  `ToAddresses` array); `MAIL_TYPE` `TRANSACTIONAL` or `MARKETING`; `WEBSITE_URL` an `http(s)` URL
  of 1–1000 characters, not necessarily at the domain; `REGION` a Region code; `PROFILE` a profile
  name. JSON-encode subject and body text with a serializer.

## IAM Permissions

Grant only the actions the workflow being run calls — never `ses:*` or `*FullAccess`. Each
reference lists its actions under `Required IAM actions`. Scope per-identity actions to
`arn:aws:ses:{region}:{account-id}:identity/{domain}` or `.../identity/{address}` for every
identity actually read, created, or sending; a send is authorized by the identity covering its
From address. Scope Route 53 zone actions to `arn:aws:route53:::hostedzone/{bare_zone_id}` (strip
the `/hostedzone/` prefix). Only `sts:GetCallerIdentity`, `ses:GetAccount`,
`ses:ListEmailIdentities`, `ses:ListConfigurationSets`, `route53:ListHostedZones`,
`route53:ListHostedZonesByName`, `route53:TestDNSAnswer` and the account-level SES writes need
`*`. Grant `ses:PutAccountDetails` deliberately, only for a production-access request.

## Security Considerations

- **Ephemeral credentials.** Use IAM roles with STS — never long-lived access keys.
- **Consent gates.** A production-access review, a real send, and a Route 53 change commit the
  user in ways no API can undo. Each gate is owned by the reference that performs the action;
  never pass one because this file summarizes it.
- **Delivery TLS is opportunistic by default.** The default configuration set uses
  `TlsPolicy: OPTIONAL`: SES attempts TLS and may send without it when the receiver cannot
  establish it — an interoperability trade-off. Requiring TLS rejects mail to such receivers, so
  it is an explicit later decision the user makes.
- **Redact before sharing.** Remove credentials, recipient addresses and message content from logs,
  CLI output or Support case text before quoting or sharing it.
- **Never place message bodies or recipient lists in logs**, and never hardcode credentials,
  endpoints, or secrets; keep application credentials in Secrets Manager or Parameter Store.
- **Enable CloudTrail** for SES API auditing, alarm on repeated `AccessDeniedException` and
  unusual send volume, and encrypt the trail and its CloudWatch Logs group with KMS — SES entries
  carry email addresses, domain names, and account details.

## Additional Resources

- [Request production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html)
- [SES Domain Verification](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)
- [DKIM in SES](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim.html)
- [Custom MAIL FROM](https://docs.aws.amazon.com/ses/latest/dg/mail-from.html)
- [DMARC Authentication](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dmarc.html)
- [SESv2 API Reference](https://docs.aws.amazon.com/ses/latest/APIReference-V2/Welcome.html)
- [Security in Amazon SES](https://docs.aws.amazon.com/ses/latest/dg/security.html)
- [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
