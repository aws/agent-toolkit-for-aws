# Configuring Health-Based Detection with Route 53 Health Checks

## Overview

Domain expertise for adding health-based detection to an AWS Shield Advanced protection by
associating a Route 53 health check, so Shield Advanced can see whether the application is actually
healthy and detect attacks faster and more accurately. Covers the requirement that the health check
genuinely reflect application health, the requirement that it be healthy at association time, the
one resource type that does not support health-based detection, and the link to proactive
engagement.

Does not cover subscribing and protecting resources, automatic mitigation, SRT setup, event review,
or protection groups; those are separate references. Creating the Route 53 health check itself is
the route53 skill.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Not supported for Route 53 hosted zones
- The health check must reflect real application health
- The health check must be healthy at association time
- Health-based detection is the groundwork for proactive engagement
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To configure health-based detection end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Confirming the resource is protected and the protected resource type supports health-based
  detection
- Confirming a Route 53 health check exists, reflects real application health, and is currently
  healthy
- Associating the health check with the Shield Advanced protection
- Surfacing the console link to verify the association

## Always tell the customer (state all of these)

When advising on health-based detection, you MUST state ALL of the following points together, not a
subset:

1. **Route 53 hosted zones do not support health-based detection** (every other protected resource
   type does); do not try to associate a health check with a hosted zone.
2. The health check **must be healthy at association time**, or the association is rejected.
3. The health check **must reflect real application health** — use a **calculated health check**
   built from the CloudWatch metrics that genuinely indicate the application is unavailable, NOT a
   shallow check (e.g. a TCP or single-endpoint ping) that keeps returning healthy while the
   application is failing, and not a staging or test check for a production protection.

The sections below give the detail behind each point.

## Not supported for Route 53 hosted zones

Health-based detection works for every protected resource type except Route 53 hosted zones.
Customers assume it works everywhere and waste effort wiring a health check to a hosted zone.

**Constraints:**

- You MUST tell the customer that Route 53 hosted zones do not support health-based detection,
  while every other protected resource type does
- You MUST NOT attempt to associate a health check with a protected Route 53 hosted zone

## The health check must reflect real application health

A shallow health check that returns healthy even when the application is failing gives detection no
useful signal. The check has to flip to unhealthy under real stress to add value.

**Constraints:**

- You MUST confirm the health check accurately reflects application health, not just that an
  endpoint responds
- You SHOULD recommend a calculated health check combining the metrics that actually indicate the
  application is unavailable, rather than a single shallow check
- You MUST NOT associate a health check from a staging or test environment with a production
  protection

## The health check must be healthy at association time

Associating a currently unhealthy health check fails or skews the detection baseline, and the
failure reason is not obvious to the customer.

**Constraints:**

- You MUST verify the health check is reporting healthy before associating it
- You SHOULD surface the current health check status to the customer rather than letting them guess
  why an association will not take

## Health-based detection is the groundwork for proactive engagement

Proactive engagement (the SRT reaching out during an attack) requires a Route 53 health check on
the protected resource. Configuring health-based detection now is the prerequisite for enabling
proactive engagement later.

**Constraints:**

- You SHOULD note that this same health check is required for proactive engagement, and point at
  the SRT reference when the customer wants the SRT to reach out
- You MUST NOT delete a Route 53 health check that is associated with a Shield protection while the
  protection still relies on it

## Troubleshooting

### Associating the health check fails for no clear reason
The health check is currently unhealthy. It must be healthy at association time (The health check
must be healthy at association time).

### Detection never reacts even with a health check associated
The check is shallow and never flips to unhealthy under stress, so it adds no signal. Use a check
that reflects real application health (The health check must reflect real application health).

### A health check cannot be associated with a hosted zone
Route 53 hosted zones do not support health-based detection (Not supported for Route 53 hosted
zones).

## Security considerations

Health-based detection feeds an application health signal into Shield's detection, so call out the
risks and the controls that contain them.

- **The health check must reflect real application health.** A shallow check that returns healthy
  while the application is failing gives detection no useful signal and produces false negatives;
  use a check that flips to unhealthy under real stress.
- **No staging or test health checks on production.** Associating a staging or test health check
  with a production protection skews detection; keep production protections wired to production
  health signals only.
- **Protect the health check endpoint.** Restrict the endpoint the Route 53 health check probes from
  unauthorized access, since it is a signal Shield relies on for detection. You SHOULD configure the
  health check to probe over HTTPS/TLS rather than plaintext HTTP so the probe and its response are
  encrypted in transit, and scope network access to the endpoint with security groups or network
  ACLs (for example, allow only the Route 53 health-checker IP ranges) so the signal cannot be
  reached or spoofed by unauthorized callers.
- **Least privilege for the operator.** Scope the caller's IAM permissions to the minimum this
  procedure needs (`shield:ListProtections`, `shield:AssociateHealthCheck`) rather than broad Shield
  or administrator access.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every health check
  association leaves a record, and confirm the CloudTrail trail uses SSE-KMS encryption on its S3 log
  bucket and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata
  (caller identities, resource ARNs, parameters).

## Procedure

### Overview

This procedure associates an existing, healthy Route 53 health check with a Shield Advanced
protection, then surfaces the console link to verify.

### Parameters

- **protection_id** (required): The Shield protection ID for the resource (from
  `list-protections`).
- **health_check_arn** (required): The ARN of the Route 53 health check that reflects the
  resource's real health.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the protected resource type is not a Route 53 hosted zone before proceeding

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:ListProtections`, `shield:AssociateHealthCheck`) rather than broad Shield or
  administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)
- You MUST confirm the resource is protected and get its protection ID:

  ```
  aws shield list-protections --region us-east-1
  ```

- You MUST confirm the protected resource type supports health-based detection (every type except
  Route 53 hosted zones)
- You MUST NOT proceed if the Route 53 health check is a shallow "endpoint responds" check; confirm
  it flips to unhealthy under real application failure (a calculated check over the metrics that
  indicate the app is actually down) before associating it. A shallow check gives detection no
  useful signal (see "The health check must reflect real application health")

#### 2. Confirm the health check is suitable and healthy

**Constraints:**

- You MUST confirm the Route 53 health check reflects real application health, not a shallow check,
  and MUST tell the customer this explicitly: a shallow check (for example a TCP or single-endpoint
  ping) can keep returning healthy while the application is actually failing, which gives Shield's
  detection no real signal. Recommend a calculated health check that combines the CloudWatch metrics
  that genuinely indicate the application is unavailable, rather than a single shallow check
- You MUST confirm the health check is currently reporting healthy before associating it
- You MUST NOT use a staging or test health check for a production protection

#### 3. Associate the health check

**Constraints:**

- You MUST associate the health check with the protection:

  ```
  aws shield associate-health-check \
    --protection-id {protection_id} --health-check-arn {health_check_arn} --region us-east-1
  ```

#### 4. Surface the console link

**Constraints:**

- You MUST present the Shield protected-resources console link and tell the customer to open the
  resource and confirm the health check is associated:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
  ```

#### 5. Recommend an alarm

**Constraints:**

- You SHOULD recommend a CloudWatch alarm on the Shield Advanced `DDoSDetected` detection metric for
  the protected resource so operators are alerted when Shield detects an event, and SHOULD mention
  the attack-volume metrics (`DDoSAttackBitsPerSecond`, `DDoSAttackPacketsPerSecond`,
  `DDoSAttackRequestsPerSecond`) for magnitude. Shield reports these in `us-east-1` for CloudFront
  and Route 53 and in the resource's Region otherwise
- You SHOULD recommend encrypting any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key (SSE-KMS), since the notifications carry sensitive DDoS event data
- You SHOULD confirm that all SNS topic subscribers for these Shield Advanced alarms are authorized
  personnel approved to receive sensitive DDoS event notifications

### Example

#### Example input

```json
{
  "protection_id": "abc123-protection-id",
  "health_check_arn": "arn:aws:route53:::healthcheck/11111111-2222-3333-4444-555555555555"
}
```

#### Example output

```
Verified health check is healthy and reflects application health.
Associated it with protection abc123-protection-id for faster, health-aware detection.
This health check also satisfies the proactive engagement prerequisite.
Open the Shield console and confirm the health check association:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
```

### Troubleshooting

#### The association call fails
The health check is currently unhealthy. Wait for it to report healthy, then associate (Step 2).

#### Detection still does not react
The check is shallow. Replace it with one that flips unhealthy under real stress (Step 2).

#### Cannot associate with a hosted zone
Route 53 hosted zones do not support health-based detection (Not supported for Route 53 hosted
zones).

## Additional Resources

- [Health-based detection using health checks with Shield Advanced and Route 53 (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-advanced-health-checks.html)
- [Configuring health-based detection for your protections with Shield Advanced and Route 53 (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-get-started-health-checks.html)
