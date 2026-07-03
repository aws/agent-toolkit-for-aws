# Creating a Public DNS Record in Route 53

## Overview

Domain expertise for adding or updating a record in a Route 53 public hosted zone so a hostname
resolves to a target: an IP address, an AWS resource, or another hostname. Covers the choice
between alias and standard records, the zone apex (root domain) constraint, long TXT value
handling, and the Evaluate Target Health (ETH) toggle on alias records.

Does not cover routing policies that split or steer traffic (weighted, failover, latency,
geolocation), private hosted zones for hybrid networks, domain registration, or health check
creation. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: alias vs standard record
- The apex constraint
- Long TXT records
- Decision: Evaluate Target Health on an alias record
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To create or update a public DNS record, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Choosing alias vs standard record for the target
- Pointing a subdomain or the zone apex at an AWS resource
- Adding a long TXT record by splitting it into 255-character chunks
- Surfacing the console link to verify the record

## Decision: alias vs standard record

| Choice | Use when |
| --- | --- |
| Alias (A or AAAA) | The target is a supported AWS resource, or the record is at the zone apex. Free to query, tracks the target's IP changes, inherits the target's TTL |
| Standard (A, AAAA, CNAME) | The target is a non-AWS hostname or IP, or the customer needs explicit TTL control. CNAME only on a subdomain, never at the apex |

**Constraints:**

- You MUST use an alias record, not a standard A or CNAME, whenever the target is an AWS resource
  that supports it. A standard record pointed at an AWS-issued hostname goes stale when the
  target's IPs rotate
- You MUST match the alias record type to the target's address family: type A for IPv4, type AAAA
  for IPv6
- You MUST NOT set a manual TTL on an alias record; it inherits the target's TTL
- The console "Create record" alias target picker is the authoritative list of supported alias
  targets (broader than the public docs, which commonly omit Network Load Balancer, VPC Lattice,
  and VPC endpoint targets). The CLI and SDK accept the same set without listing it

## The apex constraint

A CNAME cannot exist at the zone apex (`example.com`). RFC 1034 prohibits a CNAME alongside the
Start of Authority (SOA) and name server (NS) records that always exist at the apex, so Route 53
rejects the create.

**Constraints:**

- You MUST use an alias record to point an apex at an AWS resource or at another record in the
  same hosted zone. It works at the apex because it resolves to address records, not to a CNAME

## Long TXT records

A single TXT string is capped at 255 characters by the DNS protocol. A longer value (commonly a
DomainKeys Identified Mail, DKIM, public key) must be split into multiple quoted strings in the
same record; Route 53 concatenates them when answering.

**Constraints:**

- You MUST split a TXT value longer than 255 characters into multiple quoted 255-character
  chunks automatically rather than asking the customer to do it

## Decision: Evaluate Target Health on an alias record

ETH only changes behavior when the record participates in a health-aware routing setup
(failover, weighted, latency). For a standalone record pointing at a single target it has no
practical effect.

**Constraints:**

- You SHOULD set ETH on only when the record participates in a routing policy, and leave it off
  for a plain single-target record. The full ETH-versus-custom-health-check decision belongs to
  the health check and failover skills

## Troubleshooting

### Create rejected at the apex
A CNAME was attempted at the zone apex (prohibited by RFC 1034). Use an alias record at the apex.

### Hostname resolves to a stale IP
A standard record points at an AWS hostname whose IPs rotated. Replace it with an alias record,
which tracks the target's IPs.

### TXT create rejected or value truncated
A single TXT string exceeded 255 characters. Split the value into multiple quoted 255-character
strings in one record.

### Alias record will not accept a TTL
Alias records inherit the target's TTL. Remove the manual TTL.

### Alias record type mismatch error
The record type does not match the target address family. Use type A for IPv4, type AAAA for IPv6.

## Procedure

### Overview

This procedure adds or updates a record in a Route 53 public hosted zone so a hostname resolves
to a target: an IP, an AWS resource, or another hostname. It chooses alias vs standard records,
handles the zone apex constraint and long TXT values, and surfaces the console link to verify.

### Parameters

- **hosted_zone_id** (required): The public hosted zone ID (e.g., `Z1234567890ABC`).
- **record_name** (required): The record name (e.g., `www.example.com` or the apex `example.com`).
- **record_type** (required): `A`, `AAAA`, `CNAME`, `TXT`, etc.
- **is_alias** (required): Whether this is an alias record. Selects which of the two mutually
  exclusive parameter groups below applies. Inferred as `true` when the target is a supported
  AWS resource (at any level, including the apex), or when the record is at the zone apex AND a
  CNAME was requested (a CNAME is prohibited at the apex, so an alias is the substitute). A plain
  A or AAAA record at the apex pointing to a non-AWS IP address is NOT an alias — leave `is_alias`
  `false` in that case.

Provide exactly one of the following groups, based on `is_alias`:

**Alias record (`is_alias = true`) — provide an alias target:**

- **alias_target_dns_name** (required): DNS name of the AWS resource or the in-zone record to
  point at (e.g., `my-alb-123456789.us-east-1.elb.amazonaws.com`).
- **alias_target_zone_id** (required): The hosted zone ID of the alias *target*. This is NOT the
  record's own `hosted_zone_id`. Resolve it by target type:
  - CloudFront → always `Z2FDTNDATAQYW2`
  - ELB (ALB/NLB) → the target's `CanonicalHostedZoneId` (`aws elbv2 describe-load-balancers`)
  - CLB → the target's `CanonicalHostedZoneNameID` (`aws elb describe-load-balancers`)
  - S3 website endpoint, API Gateway, and other AWS resources → the region-specific zone ID from
    the service's documentation or the console alias target picker
  - Another record in the same hosted zone → reuse `hosted_zone_id`
- **evaluate_target_health** (optional, default `false`): The ETH toggle. Leave `false` for a
  plain single-target record (see the ETH decision section).

**Standard record (`is_alias = false`) — provide records and a TTL:**

- **records** (required): One or more resource record values (an IP, a hostname, or quoted TXT
  strings).
- **ttl** (required): TTL in seconds. Not valid on alias records.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the hosted zone is public before writing
- You MUST validate the record name falls within the hosted zone's domain

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST confirm the hosted zone exists and is public:

  ```
  aws route53 get-hosted-zone --id {hosted_zone_id} --region us-east-1
  ```

#### 2. Choose alias vs standard record

**Constraints:**

- You MUST use an alias record when the target is a supported AWS resource, or when the record is
  at the zone apex AND a CNAME was requested (a CNAME is prohibited at the apex). A plain A or AAAA
  record at the apex pointing to a non-AWS IP address is a standard record, NOT an alias
- You MUST match the alias record type to the target's address family (A for IPv4, AAAA for IPv6)
- You MUST NOT set a TTL on an alias record
- You MUST treat the console "Create record" alias target picker as the authoritative list of
  supported alias targets

#### 3. Handle the apex constraint

**Constraints:**

- If the record is at the zone apex and a CNAME was requested, you MUST switch to an alias record.
  A CNAME at the apex is rejected (RFC 1034)

#### 4. Handle long TXT values

**Constraints:**

- If `record_type` is TXT and the value exceeds 255 characters, you MUST split it into multiple
  quoted 255-character strings within the same record

#### 5. Create or update the record

**Constraints:**

- You MUST use `UPSERT` to create or update the record. For an alias record:

  ```
  aws route53 change-resource-record-sets --hosted-zone-id {hosted_zone_id} --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "{record_name}",
        "Type": "{record_type}",
        "AliasTarget": {
          "DNSName": "{alias_target_dns_name}",
          "EvaluateTargetHealth": {evaluate_target_health},
          "HostedZoneId": "{alias_target_zone_id}"
        }
      }
    }]
  }'
  ```

- For a standard record, replace `AliasTarget` with `TTL` ({ttl}) and `ResourceRecords` (from
  `records`)
- You MUST capture the change ID from the response

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST verify the change reaches `INSYNC`. The status starts as `PENDING` and propagation
  can take up to ~60 seconds, so poll rather than expecting `INSYNC` on the first call:

  ```
  aws route53 get-change --id {change_id}
  ```

- You SHOULD treat `PENDING` as in-progress, not a failure; only surface an error if the status
  has not reached `INSYNC` after a reasonable polling window
- You MUST present the records view console link, filling `{hostedZoneId}`:

  ```
  https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/{hostedZoneId}
  ```

### Example

#### Example input

```json
{
  "hosted_zone_id": "Z1234567890ABC",
  "record_name": "example.com",
  "record_type": "A",
  "is_alias": true,
  "alias_target_dns_name": "my-alb-123456789.us-east-1.elb.amazonaws.com",
  "alias_target_zone_id": "Z35SXDOTRQ7X7K"
}
```

#### Example output

```
Created alias A record example.com -> my-alb-123456789.us-east-1.elb.amazonaws.com
Verify in the console:
https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/Z1234567890ABC
```

### Troubleshooting

#### Create rejected at the apex
CNAME attempted at the zone apex. Use an alias record (Step 3).

#### Hostname resolves to a stale IP
Standard record pointed at an AWS hostname whose IPs rotated. Replace with an alias record (Step 2).

#### TXT create rejected or value truncated
A single TXT string exceeded 255 characters. Split into quoted 255-character strings (Step 4).

#### Alias record will not accept a TTL
Alias records inherit the target's TTL. Remove the TTL.

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps. Grant
  only the specific actions this procedure needs — `route53:ChangeResourceRecordSets` and
  `route53:GetChange` to create the record and confirm propagation, plus
  `route53:ListResourceRecordSets` and `route53:GetHostedZone` for inspection — rather than
  `route53:*` or broader `service:*` wildcards.
- You MUST enable Route 53 query logging to an encrypted destination (KMS on CloudWatch Logs,
  SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and ensure CloudTrail
  is enabled to audit record changes.
- You SHOULD recommend enabling DNSSEC signing on the public hosted zone, because a signed zone
  lets validating resolvers detect spoofed or tampered responses for the records served from it.
- You SHOULD avoid pointing public records at internal resources, since a public record discloses
  the target hostname or IP and can leak internal topology to anyone who resolves the name.
- You SHOULD recommend a CAA record alongside A/AAAA records for a domain serving HTTPS, so only
  the certificate authorities the customer authorizes can issue certificates for it.

## Additional Resources

- [Choosing between alias and non-alias records (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-choosing-alias-non-alias.html)
- [Quotas on Route 53 records (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/DNSLimitations.html)
- [Route 53 pricing](https://aws.amazon.com/route53/pricing/)
