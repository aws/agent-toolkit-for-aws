# Setting Up SRT Support and Proactive Engagement

## Overview

Domain expertise for letting the AWS Shield Response Team (SRT) help during a Distributed Denial of
Service (DDoS) attack, in two parts: granting the SRT access to act on the account's behalf, and
enabling proactive engagement so the SRT contacts the team directly when an attack affects the
application. Covers the Business or Enterprise Support plan precondition, the IAM role the SRT
assumes, the Route 53 health check that proactive engagement requires, and the emergency contact
guidance.

Does not cover subscribing and protecting resources, automatic mitigation, event review, or
protection groups; those are separate references. Creating the Route 53 health check is the route53
skill, and configuring health-based detection has its own reference.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Precondition: Business or Enterprise Support plan
- Part 1: granting SRT access
- Part 2: proactive engagement and its health check
- Emergency contacts
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To set up SRT support and proactive engagement end to end, follow the procedure exactly. See the
Procedure section below.

The procedure covers:

- Confirming the account is on the Business or Enterprise Support plan
- Granting SRT access through an IAM role with the managed policy and the right trust
- For proactive engagement: confirming a Route 53 health check is associated and setting emergency
  contacts
- Enabling proactive engagement and surfacing the console link

## Precondition: Business or Enterprise Support plan

Both SRT access and proactive engagement require the Business or Enterprise Support plan. A Shield
Advanced subscription alone does not grant SRT access. Customers on Developer or Basic plans
configure access that cannot be used.

**Constraints:**

- You MUST confirm the account is on the Business or Enterprise Support plan before configuring SRT
  access or proactive engagement
- You MUST NOT lead the customer through SRT setup on a Developer or Basic plan; the access will
  not work

## Part 1: granting SRT access

SRT access is an IAM role the SRT assumes. The role needs the `AWSShieldDRTAccessPolicy` managed
policy and a trust policy that allows `drt.shield.amazonaws.com` to assume it.

**Constraints:**

- You MUST attach the `AWSShieldDRTAccessPolicy` managed policy to the role
- You MUST configure the role's trust policy to allow the `drt.shield.amazonaws.com` service
  principal to assume it, scoped with an `aws:SourceAccount` condition equal to the customer's
  account ID to prevent confused-deputy assumption:

  ```json
  {
    "Effect": "Allow",
    "Principal": { "Service": "drt.shield.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "aws:SourceAccount": "111122223333" } }
  }
  ```

- You SHOULD grant the SRT access to the relevant log buckets (AWS WAF logs, load balancer access
  logs) so it can analyze traffic during an event, and MUST confirm those buckets have
  server-side encryption enabled before sharing them (SSE-KMS recommended for this sensitive
  third-party-accessed DDoS audit data, SSE-S3 at minimum) and that no sensitive PII or secrets are
  logged in clear text, since WAF and access logs capture request URIs, headers, and client IPs
- You SHOULD confirm the shared log bucket's bucket policy includes a Deny statement with condition
  `{"Bool": {"aws:SecureTransport": "false"}}` to enforce TLS for all access, so log data is
  protected in transit as well as at rest when the SRT or other principals access it
- You SHOULD set this up before an attack, not during one, so the SRT can act when minutes matter
- You SHOULD periodically audit the SRT role and `describe-drt-access` output and revoke it with
  `disassociate-drt-role` when no longer needed, since the role lets a third-party principal act in
  the account

## Part 2: proactive engagement and its health check

Proactive engagement lets the SRT reach out when Shield detects an event affecting availability. It
requires a Route 53 health check on each protected resource so the SRT has a health signal to act
on.

**Constraints:**

- You MUST confirm a Route 53 health check is associated with each protected resource before
  enabling proactive engagement; without it, proactive engagement does not work
- You SHOULD point at the health-based detection reference to associate the health check if it is
  not already in place
- You SHOULD note proactive engagement supports layer 3/4 events on Elastic IP addresses and Global
  Accelerator accelerators, and layer 7 web floods on CloudFront distributions and Application Load
  Balancers

## Emergency contacts

A single email contact is not enough; an attack can arrive outside business hours with no one
watching the inbox. The customer can configure up to ten contacts with notes.

**Constraints:**

- You SHOULD configure more than one emergency contact, including a phone number, so the SRT can
  reach someone during an event
- You SHOULD use the contact notes to guide the SRT on routing (for example, which contact to page
  first), especially for teams without a 24/7 operations center
- You MUST keep contacts current; outdated contacts mean the SRT cannot reach the team during an
  attack
- You MUST confirm that all emergency contacts are authorized personnel approved to receive and act
  on DDoS incident notifications before configuring them

## Troubleshooting

### SRT does not respond to an engagement
The account is on the wrong support plan. Business or Enterprise Support is required (Precondition).

### Proactive engagement cannot be enabled
No Route 53 health check is associated with the protected resource. Associate one first (Part 2).

### The SRT could not reach anyone during an attack
Emergency contacts are missing or stale. Configure multiple current contacts with a phone number
(Emergency contacts).

### The SRT cannot act on resources during an event
SRT access was never granted. Create the role with the managed policy and trust, and associate it
(Part 1).

## Security considerations

Setting up SRT support creates an IAM trust relationship with a third party and can expose log data,
so call out the risks and the controls that contain them.

- **SRT role is a third-party principal.** Granting SRT access creates an IAM role that
  `drt.shield.amazonaws.com` assumes to act in the account. Scope its trust policy with an
  `aws:SourceAccount` condition equal to the account ID to prevent confused-deputy assumption, and
  grant it only the actions it needs.
- **Log buckets shared with the SRT can leak data.** AWS WAF and access logs capture request URIs,
  headers, PII, and client IPs. Confirm those buckets have server-side encryption and carry no
  clear-text PII or secrets before sharing them with the SRT.
- **Keep emergency contacts current and authorized.** Outdated contacts mean the SRT cannot reach
  the team during an attack; confirm all emergency contacts are authorized personnel approved to
  receive and act on DDoS incident notifications.
- **Audit and revoke SRT access.** Periodically audit the SRT role and `describe-drt-access` output
  and revoke it with `disassociate-drt-role` when no longer needed, since the role lets a
  third-party principal act in the account.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every SRT and
  proactive engagement configuration change leaves a record, and confirm the CloudTrail trail uses
  SSE-KMS encryption on its S3 log bucket and CloudWatch Logs log group, since CloudTrail records
  contain sensitive API metadata (caller identities, resource ARNs, parameters).

## Procedure

### Overview

This procedure grants SRT access and, optionally, enables proactive engagement with emergency
contacts, then surfaces the console link to verify.

### Parameters

- **srt_role_arn** (required): The ARN of the IAM role the SRT will assume (with
  `AWSShieldDRTAccessPolicy` and the `drt.shield.amazonaws.com` trust).
- **log_buckets** (optional): S3 buckets holding AWS WAF or access logs to grant the SRT.
- **enable_proactive** (optional): Whether to enable proactive engagement.
- **emergency_contacts** (required when enabling proactive engagement): Up to ten contacts, each
  with an email, ideally a phone number, and a contact note.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the support plan and (for proactive engagement) the health check before changing
  anything

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You MUST confirm the account is on the Business or Enterprise Support plan
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:AssociateDRTRole`, `shield:AssociateDRTLogBucket`, `shield:DescribeDRTAccess`,
  `shield:UpdateEmergencyContactSettings`, `shield:EnableProactiveEngagement`) rather than broad
  Shield or administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)
- For proactive engagement, you MUST confirm a Route 53 health check is associated with each
  protected resource

#### 2. Grant SRT access

**Constraints:**

- You MUST associate the SRT role:

  ```
  aws shield associate-drt-role --role-arn {srt_role_arn} --region us-east-1
  ```

- You SHOULD grant access to the log buckets where present:

  ```
  aws shield associate-drt-log-bucket --log-bucket {log_bucket} --region us-east-1
  ```

- You MUST confirm each shared log bucket has server-side encryption enabled (SSE-S3 at minimum,
  SSE-KMS preferred), and when SSE-KMS is used the KMS key policy MUST grant the
  `drt.shield.amazonaws.com` service principal `kms:Decrypt` so the SRT can read the logs
- You SHOULD confirm the shared log bucket's bucket policy includes a Deny statement with condition
  `{"Bool": {"aws:SecureTransport": "false"}}` to enforce TLS for all access, so log data is
  protected in transit as well as at rest when the SRT or other principals access it
- You MUST confirm the configuration:

  ```
  aws shield describe-drt-access --region us-east-1
  ```

#### 3. (Optional) Set contacts and enable proactive engagement

**Constraints:**

- You MUST set the emergency contacts before enabling proactive engagement:

  ```
  aws shield update-emergency-contact-settings \
    --emergency-contact-list '[{"EmailAddress":"oncall@example.com","PhoneNumber":"+15555555555","ContactNotes":"24/7 NOC - page first"}]' \
    --region us-east-1
  ```

- You MUST enable proactive engagement only after a health check is associated:

  ```
  aws shield enable-proactive-engagement --region us-east-1
  ```

#### 4. Surface the console link

**Constraints:**

- You MUST present the Shield overview console link and tell the customer to open it and confirm
  SRT access and, if enabled, proactive engagement status:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/overview
  ```

### Example

#### Example input

```json
{
  "srt_role_arn": "arn:aws:iam::111122223333:role/ShieldDRTRole",
  "log_buckets": ["app-waf-logs"],
  "enable_proactive": true,
  "emergency_contacts": [
    {"email": "oncall@example.com", "phone": "+15555555555", "notes": "24/7 NOC - page first"}
  ]
}
```

#### Example output

```
Confirmed Business Support plan.
Granted SRT access via role ShieldDRTRole and log bucket app-waf-logs.
Health check present, so enabled proactive engagement with 1 emergency contact.
Open the Shield console and confirm SRT access and proactive engagement:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/overview
```

### Troubleshooting

#### SRT does not respond
Wrong support plan. Business or Enterprise Support is required (Step 1).

#### Proactive engagement will not enable
No Route 53 health check is associated. Associate one first (Step 1).

#### The SRT could not reach anyone
Emergency contacts are stale or missing. Set multiple current contacts with a phone number (Step 3).

## Additional Resources

- [Setting up AWS Shield Response Team (SRT) support for DDoS event response (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/authorize-srt.html)
- [Setting up proactive engagement for the SRT to contact you directly (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-srt-proactive-engagement.html)
