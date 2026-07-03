# Centralizing DNS Firewall with Route 53 Profiles

## Overview

Domain expertise for applying one Route 53 Resolver DNS Firewall configuration across many VPCs
and accounts. DNS Firewall supplies the rules. There are two distinct fan-out mechanisms, and you
pick one: Route 53 Profiles (shared cross-account with AWS Resource Access Manager) bundle the
rule groups with other DNS config and associate them to VPCs; AWS Firewall Manager centrally
creates and manages DNS Firewall rule group associations across an organization's accounts and
flags non-compliant accounts. Firewall Manager is not a layer on top of Profiles — using both for
the same rule groups double-associates them to the same VPCs.

Does not cover authoring DNS Firewall rules for a single VPC, or general Profile configuration.
Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Rules, and two ways to fan them out
- Decision: RAM share permission level
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To centralize DNS Firewall across the fleet, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Bundling DNS Firewall rule groups into a Route 53 Profile rather than configuring per VPC
- Sharing the Profile cross-account through RAM at the right permission level
- Associating the Profile with VPCs in each account
- Optionally using AWS Firewall Manager instead, for org-wide association management and compliance detection
- Surfacing the console links to verify the result

## Rules, and two ways to fan them out

DNS Firewall supplies the rules. To apply them across a fleet you choose one of two fan-out
mechanisms — they are alternatives, not layers.

| Component | Job |
| --- | --- |
| DNS Firewall | Supplies the rules (rule groups, managed and custom domain lists) |
| Route 53 Profiles | Bundle the rule groups with other DNS config and associate them to VPCs; shared cross-account with RAM. The Profile owner pays for every VPC association |
| AWS Firewall Manager | Centrally creates and manages DNS Firewall rule group associations across an organization's accounts, and flags (and optionally remediates) non-compliant accounts |

### Choosing the right centralization approach

| Approach | Prerequisites | Best for | Limitations |
| --- | --- | --- | --- |
| **Direct RAM sharing of rule groups** | RAM enabled | Small number of accounts; each account manages its own VPC associations | Each recipient must associate the rule group to each VPC individually; no bundling with other DNS config; no compliance detection |
| **Route 53 Profiles + RAM** | RAM enabled | Distributing rule groups bundled with other DNS config (PHZs, resolver rules) to many VPCs | One Profile per VPC; Profile owner pays for all associations; no org-wide compliance enforcement |
| **AWS Firewall Manager** | AWS Organizations, Firewall Manager administrator designated, AWS Config enabled in target accounts | Org-wide enforcement with compliance detection and optional auto-remediation | Requires Organizations; manages rule group associations only (not PHZs or resolver rules); additional Firewall Manager pricing |

Use **Direct RAM sharing** when you have a few accounts and want minimal overhead. Use **Profiles**
when you need to distribute a coherent DNS configuration (rule groups + PHZs + resolver rules) at
scale. Use **Firewall Manager** when you need org-wide compliance guarantees and auto-remediation.

**Constraints:**

- You SHOULD introduce a fan-out mechanism together with DNS Firewall for org-wide use rather than
  configuring DNS Firewall per VPC, which does not scale across a fleet
- You MUST treat Profiles and Firewall Manager as alternatives for fan-out. Using both for the
  same rule groups associates them to the same VPCs twice, causing duplicate rule evaluation,
  duplicate management, and duplicate query/association charges. If both are used, scope each to a
  disjoint set of VPCs
- You MUST surface that with Profiles the owner account pays for every Profile-VPC association,
  including associations made by RAM recipients in their own accounts
- When the customer is in a regulated industry or under a security mandate, you SHOULD surface
  Firewall Manager, because it provides org-wide compliance detection that customers frequently do
  not know exists until they have to prove compliance

## Decision: RAM share permission level

Sharing a Profile through RAM grants one of two permission levels. The wrong choice either
blocks the recipient or over-grants.

| Permission | What the recipient can do | Use when |
| --- | --- | --- |
| Built-in allow-association (read-only) | Associate the shared Profile with its own VPCs | Default. The recipient only needs to apply the protection |
| Custom managed permission with resource-association | Associate resources into the shared Profile, affecting every consumer | Only when a recipient must contribute to or modify the shared Profile |

The default RAM managed permission for a shared Profile is association-only — it does not include
`route53profiles:AssociateResourceToProfile`. Letting a recipient add resources into the shared
Profile is not a built-in toggle; it requires creating a custom RAM managed permission that grants
that action.

**Constraints:**

- You MUST default to the built-in association-only permission
- You MUST explain, before granting a resource-association permission, that a recipient who can
  associate resources into the shared Profile can add a resource (including its own private hosted
  zone) that then applies to every other account consuming the Profile. In an environment where
  the owner does not control all recipients, this lets one account inject DNS configuration into
  others
- Granting resource-association requires a custom RAM managed permission; the default permission
  cannot do it

## Troubleshooting

### DNS Firewall config does not scale across the fleet
It was set up per VPC instead of through a Profile. Bundle the rule groups into a Profile and
fan out (procedure step 2).

### Cannot prove org-wide compliance
No org-wide compliance mechanism is in place. AWS Firewall Manager centrally manages DNS Firewall
rule group associations across the organization and flags non-compliant accounts (procedure step
5). Use it as an alternative to Profiles for fan-out, or scope it to VPCs that Profiles do not
cover, to avoid double-association.

### Recipient cannot associate, or can change shared rules
Wrong RAM permission. The built-in permission lets a recipient associate the shared Profile with
its own VPCs only; adding or changing resources in the shared Profile requires a custom managed
permission and exposes every consumer to that change. See the decision table above.

## Procedure

### Overview

This procedure applies one DNS Firewall configuration across many VPCs and accounts. It bundles
DNS Firewall rule groups into a Route 53 Profile, shares the Profile cross-account through AWS
Resource Access Manager (RAM) at the right permission level, associates it with VPCs in each
account, and optionally adds AWS Firewall Manager for org-wide enforcement and compliance
detection.

### Parameters

- **rule_group_ids** (required): The DNS Firewall rule group IDs to centralize. Author these
  first with the blocking-malicious-domains-with-route53-dns-firewall skill.
- **frg_priority** (required): The processing priority for each rule group attached to the
  Profile (100-9900, lowest evaluated first). Required for DNS Firewall rule group resource
  associations.
- **region** (required): The AWS Region for the Profile and rule groups (e.g., `us-east-1`). The
  Profile, its rule groups, and every associated VPC MUST be in this same Region. For multi-Region
  deployments, repeat this entire procedure in each target Region — Profiles and rule groups do not
  replicate across Regions.
- **share_principals** (required for cross-account): The account IDs or AWS Organizations
  organizational unit (OU) ARNs to share the Profile with.
- **share_permission** (optional, default: read-only): `read-only` (built-in association-only
  permission) or `admin` (requires a custom RAM managed permission granting
  `route53profiles:AssociateResourceToProfile`; not a built-in level).
- **use_firewall_manager** (optional, default: false): Whether to add AWS Firewall Manager for
  org-wide enforcement.
- **vpc_ids** (required for association): The VPC IDs to associate the Profile with in each
  recipient account (Step 4). Each recipient account supplies its own VPC IDs; a VPC can have only
  one Profile associated.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the share principals and permission level before sharing
- You MUST default `share_permission` to read-only and confirm explicitly before using admin

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You SHOULD prefer least-privilege credentials for read steps and use write-capable
  credentials only for create, share, and associate steps
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST confirm the rule groups in `rule_group_ids` exist:

  ```
  aws route53resolver get-firewall-rule-group --firewall-rule-group-id {rule_group_id} --region {region}
  ```

#### 2. Bundle the rule groups into a Profile

**Constraints:**

- You MUST create one Profile and attach the rule groups to it, rather than configuring DNS
  Firewall per VPC. Attaching a DNS Firewall rule group REQUIRES a priority via
  `--resource-properties` (allowed range 100-9900, lowest evaluated first); the call fails for a
  rule group without it:

  ```
  aws route53profiles create-profile --name {profile_name} --region {region}
  aws route53profiles associate-resource-to-profile \
    --profile-id {profile_id} \
    --resource-arn {rule_group_arn} \
    --resource-properties '{"priority": {frg_priority}}' \
    --name {association_name} --region {region}
  ```

- If the same VPCs are also managed by AWS Firewall Manager, you MUST keep this priority clear of
  the priority ranges Firewall Manager reserves: priorities 1-99 for "first" rule groups (evaluated
  before account-local rules) and 9901-10000 for "last" rule groups (evaluated after account-local
  rules). Account-local and Profile-associated rule groups use priorities 100-9900
- You MUST enable Resolver query logging across the protected fleet so rule matches and false
  positives are visible org-wide. Bundle a query log config into the Profile (associate a
  `resolverquerylogconfig` resource to the Profile alongside the rule groups) so every VPC the
  Profile reaches logs consistently, rather than configuring logging VPC-by-VPC. You MUST encrypt
  the log destination at rest: a KMS key on the CloudWatch Logs log group, SSE-S3/SSE-KMS on the S3
  bucket, or server-side encryption on the Data Firehose stream, because query logs reveal the
  domains the fleet resolves

#### 3. Share the Profile through RAM

**Constraints:**

- You MUST default to a read-only RAM permission for association-only recipients
- You MUST explain the admin-sharing risk before using an admin permission (a recipient can
  inject configuration that applies to every consumer of the Profile)
- Create the resource share:

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

  Shares within an Organization that has RAM sharing enabled are accepted automatically

#### 4. Associate the Profile with VPCs in each account

**Constraints:**

- In each recipient account, you MUST associate the shared Profile with each VPC in `{vpc_ids}`. A
  VPC can have only one Profile associated, so this fails if the VPC already has one:

  ```
  # Repeat for each VPC in {vpc_ids}
  aws route53profiles associate-profile \
    --profile-id {profile_id} \
    --resource-id {vpc_id} \
    --name {association_name} --region {region}
  ```

- The association returns `UPDATING`; you MUST poll until it reaches `COMPLETE` before reporting
  success:

  ```
  aws route53profiles get-profile-association \
    --profile-association-id {association_id} --region {region}
  ```

#### 5. Add Firewall Manager for org-wide enforcement (optional)

**Constraints:**

- If `use_firewall_manager` is true, you MUST create a Firewall Manager DNS Firewall policy that
  creates and manages the rule group associations across the organization's accounts. This is an
  alternative to Profile-based fan-out: you MUST NOT point Firewall Manager at the same VPCs the
  Profile already associates these rule groups to, or they will be associated twice
- You MUST confirm the account is a Firewall Manager administrator account before creating the
  policy:

  ```
  aws fms get-admin-account --region {region}
  ```

- You SHOULD inform the customer that auto-remediation is opt-in: a Firewall Manager policy detects
  non-compliant accounts by default and only remediates them when configured to do so

#### 6. Confirm and surface the console links

**Constraints:**

- You MUST verify the Profile associations and present the console links, filling `{region}`
  and `{profileId}`:
  - Profile detail:

    ```
    https://{region}.console.aws.amazon.com/route53profiles/home?region={region}#/profiles/{profileId}
    ```

  - DNS Firewall rule groups (VPC console):

    ```
    https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#DNSFirewallRuleGroups:
    ```

### Example

#### Example input

```json
{
  "rule_group_ids": ["rslvr-frg-0123456789abcdef0"],
  "frg_priority": 101,
  "region": "us-east-1",
  "share_principals": ["ou-abcd-1234abcd"],
  "share_permission": "read-only",
  "vpc_ids": ["vpc-0abc1234def567890"],
  "use_firewall_manager": false
}
```

#### Example output

```
Bundled rule group rslvr-frg-0123456789abcdef0 (priority 101) into Profile rp-0a1b2c3d4e5f.
- Shared read-only with ou-abcd-1234abcd via RAM
- Associated the Profile to target VPCs (all COMPLETE)
Verify in the console:
https://us-east-1.console.aws.amazon.com/route53profiles/home?region=us-east-1#/profiles/rp-0a1b2c3d4e5f
```

### Troubleshooting

#### DNS Firewall config does not scale across the fleet
Set up per VPC instead of through a Profile. Bundle the rule groups into a Profile and fan out
(Step 2).

#### Recipient cannot associate the shared Profile
The RAM share is missing or the recipient was granted the wrong permission. Re-check the share
principals and permission level (Step 3).

#### Cannot prove org-wide compliance
No org-wide compliance mechanism is in place. Use AWS Firewall Manager — as an alternative to
Profiles for fan-out, or scoped to VPCs Profiles do not cover (Step 5).

#### Recipient can change shared rules unexpectedly
A custom resource-association permission was granted where the built-in association-only
permission would do. Re-share with the built-in permission unless the recipient genuinely needs
to contribute resources.

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST default RAM shares to the built-in association-only permission and explain the
  injection risk before granting a resource-association permission, because a contributing
  recipient can inject configuration that applies to every consumer of the Profile.
- You MUST enable Resolver query logging fleet-wide to an encrypted destination (KMS on
  CloudWatch Logs, SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and
  ensure CloudTrail is enabled to audit Profile and rule group changes.
- You MUST treat Profiles and Firewall Manager as alternatives for the same rule groups to avoid
  double-association, duplicate evaluation, and duplicate charges.

## Additional Resources

- [Filter DNS traffic using Route 53 Resolver DNS Firewall (VPC User Guide)](https://docs.aws.amazon.com/vpc/latest/userguide/resolver-dns-firewall.html)
- [Unify DNS management using Amazon Route 53 Profiles with multiple VPCs and AWS accounts (AWS News Blog)](https://aws.amazon.com/blogs/aws/unify-dns-management-using-amazon-route-53-profiles-with-multiple-vpcs-and-aws-accounts/)
- [Working with shared Route 53 Profiles (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/sharing-profiles.html)
