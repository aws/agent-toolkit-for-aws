# Configuring Route 53 Profiles

## Overview

Domain expertise for defining a DNS configuration once with a Route 53 Profile and applying it
across many VPCs and accounts. Covers attaching DNS resources to a Profile, associating it with
VPCs, sharing it cross-account through AWS Resource Access Manager (RAM), and the four things
customers get wrong: the sharing prerequisite, the per-association cost, the admin-sharing
injection risk, and the owner-side visibility gap.

Does not cover authoring DNS Firewall rules, the hybrid resolver setup, or the org-wide DNS
Firewall fan-out. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Four things customers get wrong
- Decision: Profile vs manual per-VPC associations
- Decision: read-only vs admin sharing
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To configure and share a Profile, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Attaching DNS resources (private hosted zones, resolver rules, DNS Firewall rule groups, Resolver query logging configurations, interface VPC endpoints) to a Profile
- Associating the Profile with target VPCs (each association binds one VPC; a Profile can be associated with up to 1,000 VPCs per Region, a default quota AWS can raise on request)
- Sharing the Profile cross-account through RAM with the correct managed permission
- Setting expectations on cost and owner-side visibility

## Four things customers get wrong

**The sharing prerequisite.** Cross-account sharing requires a RAM resource share with the correct
managed permission. If sharing outside the Organization, the recipient must also accept the RAM
share invitation. These steps are frequently missed, and the recipient then cannot associate.

**The admin-sharing injection risk.** A recipient with admin on a shared Profile can associate
any resource, including its own private hosted zone, and that association applies to every other
account consuming the Profile. Default to read-only. When the recipient genuinely needs to
contribute resources, prefer a scoped IAM condition-key policy on the RAM share (for example,
only hosted zones whose name ends in `test.com`) over blanket admin.

**The cost tradeoff.** Profiles are billed per account, not per Profile: $0.75/hour covers up to
100 Profile-VPC associations across all Profiles the account owns in a Region, then $0.0014 per
association per hour. The Profile owner pays for every association, including those created by RAM
recipients in their own accounts. For a small, stable set of VPCs, manual associations can be
cheaper. Surface this before rollout, not after.

**The owner-side visibility gap.** From the owner account, the agent cannot enumerate which
consumer accounts associated their VPCs to a shared Profile. The owner sees the RAM share, not
the resulting associations.

**Constraints:**

- You MUST default to read-only sharing and explain the injection risk before granting admin
- You MUST use the correct RAM managed permission and ensure non-Organization recipients accept
  the share invitation
- You MUST surface the per-association cost when the VPC set is small and stable
- You MUST remember a VPC can have only one Profile associated at a time; associating a second
  Profile to a VPC that already has one fails
- You MUST be explicit about the owner-side visibility gap rather than implying the owner can
  see the full association list. Fuller visibility requires org-level access (an organization
  CloudTrail trail, an AWS Config aggregator, or per-account role assumption); frame that as a
  conditional path, not the default

## Decision: Profile vs manual per-VPC associations

| Choice | Use when |
| --- | --- |
| Profile | The fleet is large or growing; a Profile scales to up to 1,000 VPCs per Region and avoids drift |
| Manual associations | The VPC set is small and stable, where the per-association charge makes a Profile more expensive |

## Decision: read-only vs admin sharing

| Choice | Use when |
| --- | --- |
| Read-only | Default. The recipient only needs to associate the shared Profile with its VPCs |
| Admin | The recipient must contribute its own resources (e.g., a distributed zone hierarchy), accepting that it can inject configuration into every consumer |
| Scoped contribution via IAM condition keys | The recipient must contribute resources but the owner wants to bound what it can add. RAM sharing supports IAM condition keys, so the policy can allow, for example, only private hosted zones whose name ends in `test.com`. Prefer this over blanket admin when contribution must be limited |

## Troubleshooting

### Recipient account cannot associate the shared Profile
The RAM share is missing, the wrong permission was used, or the recipient has not accepted the
share invitation. Verify the share exists with the correct managed permission and that the
recipient accepted the invitation (automatic within an Organization with RAM sharing enabled).

### Recipient cannot contribute its own hosted zones
Only VPC-association rights were granted. Grant the broader permission for two-way contribution,
weighing the injection risk.

### Owner cannot see which accounts use the Profile
The owner account sees the share, not the associations. Use an org CloudTrail trail, a Config
aggregator, or per-account roles.

### Unexpected charges after Profile rollout
Per-account Profile pricing: $0.75/hour covers the first 100 Profile-VPC associations across all
the account's Profiles in a Region, then $0.0014 per association per hour, and the owner pays for
associations made by RAM recipients. Compare against manual associations for small, stable fleets.

### One account's DNS config appears in others
Admin sharing let a recipient inject a resource. Default to read-only; reserve admin for genuine
need.

## Procedure

### Overview

This procedure defines a DNS configuration once with a Route 53 Profile and applies it across
many VPCs and accounts. It attaches DNS resources to the Profile, associates the Profile with
VPCs, shares it cross-account through AWS Resource Access Manager (RAM) with the correct managed
permission, and sets expectations on cost and owner-side visibility.

### Parameters

- **region** (required): The AWS Region for the Profile (e.g., `us-east-1`).
- **dns_resources** (required): The resources to attach, each an ARN: private hosted zones,
  resolver rules, DNS Firewall rule groups, Resolver query logging configurations, or interface
  VPC endpoints.
- **vpc_ids** (required): The VPC IDs to associate the Profile with.
- **share_principals** (optional): Account IDs or AWS Organizations OU ARNs for cross-account sharing.
- **share_permission** (optional, default: read-only): `read-only` or `admin`.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST default `share_permission` to read-only and confirm before using admin
- You MUST surface the per-association cost when `vpc_ids` is small and stable

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You SHOULD prefer least-privilege credentials for read steps
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.

#### 2. Create the Profile and attach DNS resources

**Constraints:**

- You MUST create one Profile and attach each resource to it:

  ```
  aws route53profiles create-profile --name {profile_name} --region {region}
  aws route53profiles associate-resource-to-profile \
    --profile-id {profile_id} \
    --resource-arn {resource_arn} \
    --name {association_name} --region {region}
  ```

- When the resource is a DNS Firewall rule group, you MUST include a priority via
  `--resource-properties`; the call fails for a rule group without it. The priority sets the rule
  group's processing order (allowed range 100-9900, lowest evaluated first):

  ```
  aws route53profiles associate-resource-to-profile \
    --profile-id {profile_id} \
    --resource-arn {firewall_rule_group_arn} \
    --resource-properties '{"priority": 101}' \
    --name {association_name} --region {region}
  ```

- You SHOULD move query logging to the Profile level so the configuration propagates
  automatically rather than being re-done per VPC

#### 3. Associate the Profile with VPCs

**Constraints:**

- You MUST associate the Profile with each target VPC. Each call binds one VPC; a Profile can be
  associated with up to 1,000 VPCs per Region (a default quota AWS can raise on request). A VPC
  can have only one Profile associated at a time, so this fails if the VPC already has one:

  ```
  aws route53profiles associate-profile \
    --profile-id {profile_id} \
    --resource-id {vpc_id} \
    --name {association_name} --region {region}
  ```

- The association returns `UPDATING` and is not in effect until it reaches `COMPLETE`. You MUST
  poll `get-profile-association` until the status is `COMPLETE` before reporting success:

  ```
  aws route53profiles get-profile-association \
    --profile-association-id {association_id} --region {region}
  ```

#### 4. Share the Profile cross-account (optional)

**Constraints:**

- You MUST create the RAM resource share with the appropriate managed permission. The built-in
  `AWSRAMPermissionRoute53ProfileAllowAssociation` grants association-only (read-only) access:

  ```
  aws ram create-resource-share \
    --name {share_name} \
    --resource-arns {profile_arn} \
    --principals {share_principals} \
    --permission-arns {ram_permission_arn} \
    --region {region}
  ```

- If sharing outside the AWS Organization (or if organizational sharing is not enabled), the
  recipient MUST accept the resource share invitation before they can use the shared Profile:

  ```
  aws ram get-resource-share-invitations --region {region}
  aws ram accept-resource-share-invitation \
    --resource-share-invitation-arn {invitation_arn} --region {region}
  ```

  Shares within an Organization that has RAM sharing enabled are accepted automatically.
- You MUST default to read-only. Before granting admin, you MUST explain that a recipient with
  admin can associate a resource that applies to every consumer of the Profile
- You SHOULD use a custom RAM managed permission to scope what a contributing recipient may add
  (for example, only private hosted zones whose name ends in `test.com`) rather than granting
  blanket resource-association access

#### 5. Set expectations on cost and visibility

**Constraints:**

- You MUST tell the customer that Profiles are billed per account ($0.75/hour for up to 100
  Profile-VPC associations across all the account's Profiles in a Region, then $0.0014 per
  association per hour), that the Profile owner pays for all associations including those made by
  RAM recipients, and that manual associations can be cheaper for a small, stable set of VPCs
- You MUST be explicit that from the owner account you cannot enumerate which consumer accounts
  associated their VPCs to a shared Profile. For the full picture, use an organization CloudTrail
  trail, an AWS Config aggregator, or per-account role assumption

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST present the Profile detail console view, filling `{region}` and `{profileId}` from
  the API response:

  ```
  https://{region}.console.aws.amazon.com/route53profiles/home?region={region}#/profiles/{profileId}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "dns_resources": ["arn:aws:route53resolver:us-east-1:111122223333:firewall-rule-group/rslvr-frg-0123456789abcdef0"],
  "vpc_ids": ["vpc-0abc123"],
  "share_principals": ["ou-abcd-1234abcd"],
  "share_permission": "read-only"
}
```

#### Example output

```
Created Profile rp-0a1b2c3d4e5f, attached 1 resource, associated with vpc-0abc123.
- Shared read-only with ou-abcd-1234abcd via RAM (association-only permission)
Verify in the console:
https://us-east-1.console.aws.amazon.com/route53profiles/home?region=us-east-1#/profiles/rp-0a1b2c3d4e5f
```

### Troubleshooting

#### Recipient account cannot associate the shared Profile
RAM share missing, wrong permission used, or the recipient has not accepted the share invitation.
Re-check the share exists with the correct managed permission and that the recipient accepted
(Step 4).

#### Owner cannot see which accounts use the Profile
The owner account sees the share, not the associations. Use an org CloudTrail trail, a Config
aggregator, or per-account roles (Step 5).

#### Unexpected charges after rollout
Per-account Profile pricing ($0.75/hour for the first 100 Profile-VPC associations in a Region,
then $0.0014 each per hour; owner pays for RAM-recipient associations). Compare against manual
associations for small, stable fleets.

#### One account's DNS config appears in others
Admin sharing let a recipient inject a resource. Default to read-only.

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST default RAM shares to read-only (association-only) and explain the injection risk
  before granting admin, because a contributing recipient can associate a resource that then
  applies to every account consuming the Profile. Prefer a scoped IAM condition-key policy over
  blanket admin when a recipient must contribute resources.
- You MUST move Resolver query logging to the Profile level and send it to an encrypted
  destination (KMS on CloudWatch Logs, SSE-S3/SSE-KMS on S3, or server-side encryption on a Data
  Firehose stream), and ensure CloudTrail is enabled to audit Profile and association changes,
  because query logs reveal the domains the fleet resolves.

## Per-Profile resource quotas

| Resource type | Default quota | Adjustable |
| --- | --- | --- |
| DNS Firewall rule groups per Profile | 5 | No |
| Resolver rules per Profile | 1,000 | Yes |
| Private hosted zones per Profile | 5,000 | Yes |
| Resolver query logging configurations per Profile | 2 | No |

These are in addition to the 1,000 VPC associations per Profile (adjustable) and 5 Profiles per
account per Region.

## Additional Resources

- [Creating Route 53 Profiles (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/profile-create.html)
- [Working with shared Route 53 Profiles (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/sharing-profiles.html)
- [Route 53 Profiles quotas (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/DNSLimitations.html#limits-api-entities-route53-profiles)
- [Route 53 pricing](https://aws.amazon.com/route53/pricing/)
- [Using Amazon Route 53 Profiles for scalable multi-account AWS environments (Networking & Content Delivery blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/using-amazon-route-53-profiles-for-scalable-multi-account-aws-environments/)
