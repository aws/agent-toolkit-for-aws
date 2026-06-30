# Reviewing DDoS Events and Requesting Cost Protection

## Overview

Domain expertise for the post-attack workflow on an AWS Shield Advanced protected resource:
reviewing the DDoS event to understand what happened, and requesting a cost protection credit to
recover the scaling charges the attack caused. Covers reading the event detail, the eligibility
rules customers most often trip on (protection must predate the attack, the rate-based AWS WAF rule
must be in Block mode), and the 15-day filing deadline.

Does not cover subscribing and protecting resources, automatic mitigation, health-based detection,
SRT setup, or protection groups; those are separate references. Authoring the rate-based AWS WAF
rule is the waf skill.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Reading the event
- Eligibility: protection must predate the attack
- Eligibility: rate-based rule in Block mode
- The 15-day filing deadline
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To review an event and request a cost protection credit end to end, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Listing and describing the attack to understand vectors, timing, and top contributors
- Confirming eligibility (protection predated the attack, rate-based rule in Block mode on
  CloudFront and Application Load Balancer resources)
- Filing the billing case with the right subject and within the deadline
- Surfacing the console link to review the event

## Reading the event

After an attack, Shield Advanced reports a separate event per affected resource, with detection
details, any mitigations it applied, and the top traffic contributors. Customers see a bill spike
but cannot tell whether it was an attack or what Shield did, if they only look at CloudWatch graphs.

**Constraints:**

- You SHOULD point the customer at the event detail (detection, applied mitigations, top
  contributors) to interpret the incident, rather than inferring from CloudWatch alone
- You SHOULD capture the attack IDs, vectors, and start and end times from the event before the
  event data ages out, since they are needed for the credit request

## Always tell the customer (state all of these)

When advising on a cost-protection (DDoS credit) request, you MUST state ALL of the following
points together, not a subset:

1. **Protection must predate the attack** — protection added during an active attack does not
   qualify.
2. A **rate-based AWS WAF rule must be in Block mode** (Count mode silently voids the claim), and
   this requirement applies to **both CloudFront AND Application Load Balancer resources** — state
   both, not only CloudFront.
3. File a **billing support case within 15 days after the billing month of the attack closes** (not
   15 days after the attack date), with the words **"DDoS Concession"** in the subject plus the
   affected dates, services, and resources.

The sections below give the detail behind each point.

## Eligibility: protection must predate the attack

Cost protection covers attack-driven scaling only if the resource was protected before the attack
began. A customer who adds protection mid-attack and then files is denied.

**Constraints:**

- You MUST confirm the resource had Shield Advanced protection before the attack began; protection
  added during an active attack does not qualify
- You SHOULD check the protection creation time against the attack start time when confirming
  eligibility

## Eligibility: rate-based rule in Block mode

For CloudFront and Application Load Balancer resources, cost protection eligibility requires a
rate-based AWS WAF rule in Block mode on the resource. A rate-based rule left in Count mode does not
satisfy the requirement and silently voids the claim.

**Constraints:**

- You MUST confirm a rate-based AWS WAF rule is present and in Block mode on CloudFront and
  Application Load Balancer resources before relying on cost protection eligibility
- You MUST NOT treat a Count-mode rate-based rule as sufficient; point at the waf skill's
  rate-based rule workflow to set it to Block
- You SHOULD raise this before an attack, so the rule is already in Block mode when a claim is later
  needed

## The 15-day filing deadline

The credit is not automatic. The customer files a billing support case within 15 days after the
billing month of the attack closes, with the words "DDoS Concession" in the subject.

**Constraints:**

- You MUST track the deadline as 15 days after the billing month closes, not 15 days after the
  attack date
- You MUST tell the customer to include the words "DDoS Concession" in the case subject and the
  affected dates, services, and resources
- You SHOULD note the SRT validates whether an attack occurred and whether the protected resource
  scaled to absorb it, so not every spike qualifies

## Eligible charges and claim evidence

Cost protection credits the attack-driven scaling of protected resources (for example data transfer
out, additional EC2 or ELB capacity, CloudFront request volume), not baseline usage.

**Constraints:**

- You SHOULD tell the customer the credit covers attack-driven scaling of the protected resource,
  not unrelated or baseline charges, so expectations are set before filing
- You MUST tell the customer to attach the attack IDs, the affected resource ARNs, the attack start
  and end times from `describe-attack`, and the specific line items they believe are attack-driven

## Troubleshooting

### Cannot tell whether a bill spike was an attack
Read the Shield event detail (detection, mitigations, top contributors) rather than CloudWatch
graphs (Reading the event).

### Cost credit was denied
Either the protection was added after the attack started, or the rate-based rule was not in Block
mode on a CloudFront or Application Load Balancer resource (Eligibility sections).

### Missed the filing window
The deadline is 15 days after the billing month closes. Calendar it as soon as an attack is
identified (The 15-day filing deadline).

## Security considerations

Reviewing an event exposes sensitive attack data and filing a credit touches billing, so call out
the risks and the controls that contain them.

- **Event details are sensitive.** Attack vectors, client IPs, timing, and top contributors in the
  event detail reveal information about the attack and the application; handle them securely and
  share them only with authorized personnel.
- **Encrypt and audit offline copies.** Encrypt any offline copies of event data captured for the
  credit request and audit access to them, since they carry the same sensitive attack details.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every event review
  leaves a record for audit and reporting purposes, and confirm the CloudTrail trail uses SSE-KMS
  encryption on its S3 log bucket and CloudWatch Logs log group, since CloudTrail records contain
  sensitive API metadata (caller identities, resource ARNs, parameters).
- **Restrict billing case access.** Limit who can file the cost protection case to authorized
  personnel with restricted write access to billing support cases.

## Procedure

### Overview

This procedure reviews a DDoS event, confirms cost protection eligibility, and files the credit
request, then surfaces the console link to review the event.

### Parameters

- **resource_arn** (required): The ARN of the protected resource that was attacked.
- **time_range** (required): The window to search for the attack (from and to timestamps).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the resource was protected before the attack window before advising on a credit

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:ListProtections`, `shield:ListAttacks`, `shield:DescribeAttack`,
  `shield:DescribeProtection`, `wafv2:GetWebACLForResource`) rather than broad Shield or
  administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)
- You MUST confirm the resource is or was protected with `aws shield list-protections --region
  us-east-1`

#### 2. Review the event

**Constraints:**

- You MUST list attacks in the time range for the resource:

  ```
  aws shield list-attacks --resource-arns '["{resource_arn}"]' \
    --start-time FromInclusive={from},ToExclusive={to} --region us-east-1
  ```

- You MUST describe the attack to capture vectors, timing, and top contributors:

  ```
  aws shield describe-attack --attack-id {attack_id} --region us-east-1
  ```

#### 3. Confirm eligibility

**Constraints:**

- You MUST confirm protection predated the attack:

  ```
  aws shield describe-protection --resource-arn {resource_arn} --region us-east-1
  ```

- For CloudFront and Application Load Balancer resources, you MUST confirm a rate-based AWS WAF rule
  is in Block mode on the resource by inspecting the web ACL associated with it for a
  `RateBasedStatement` whose `Action` is `Block`:

  ```
  aws wafv2 get-web-acl-for-resource --resource-arn {resource_arn} --region us-east-1
  ```

  (For Application Load Balancer resources, use the load balancer's own region instead of
  `us-east-1`.)

#### 4. File the credit request

**Constraints:**

- You MUST tell the customer to open a Billing support case with "DDoS Concession" in the subject,
  including the attack IDs, dates and times, and affected resources
- You MUST tell the customer to file within 15 days after the billing month closes

#### 5. Surface the console link

**Constraints:**

- You MUST present the Shield events console link and tell the customer to open it to review the
  event detail:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/events
  ```

### Example

#### Example input

```json
{
  "resource_arn": "arn:aws:cloudfront::111122223333:distribution/EDFDVBD6EXAMPLE",
  "time_range": {"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"}
}
```

#### Example output

```
Found attack a1b2c3d4 on the distribution (May 12, HTTP flood). Captured vectors and top contributors.
Protection predates the attack and a rate-based rule is in Block mode — eligible for cost protection.
File a Billing case with "DDoS Concession" in the subject within 15 days after May billing closes.
Open the Shield console to review the event detail:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/events
```

### Troubleshooting

#### Cost credit was denied
Protection was added after the attack started, or the rate-based rule was in Count mode on a
CloudFront or Application Load Balancer resource (Step 3).

#### Cannot tell what happened from the bill
Review the Shield event detail, not CloudWatch graphs (Step 2).

#### Missed the window
The deadline is 15 days after the billing month closes (Step 4).

## Additional Resources

- [Viewing AWS Shield Advanced events (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-events.html)
- [Viewing AWS Shield Advanced event details (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-event-details.html)
- [Requesting a credit in AWS Shield Advanced after an attack (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-request-service-credit.html)
