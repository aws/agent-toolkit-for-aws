# Blocking Malicious Domains with Route 53 DNS Firewall

## Overview

Domain expertise for filtering DNS queries leaving a VPC against known-malicious domains and
blocking matches at the Amazon-provided resolver using Route 53 Resolver DNS Firewall (also
called Route 53 DNS Firewall). Covers the precondition that decides whether the firewall sees
any traffic at all, building rule groups from AWS-managed and custom domain lists, choosing the
block action mode, and reusing one rule group across a customer's VPCs.

Does not cover fanning the same protection across many accounts with Route 53 Profiles, or
general Profile configuration. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Critical precondition: the firewall must see the VPC's queries
- Decision: block action mode
- Beyond static domain lists: DNS Firewall Advanced
- Cost to expect
- Reuse, do not duplicate
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To block malicious domains for a VPC, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Confirming the VPC uses the Amazon-provided resolver so the firewall can see its queries
- Creating a rule group and populating it with AWS-managed and custom domain lists
- Choosing the block action mode
- Associating one rule group across all the customer's VPCs
- Surfacing the console link to verify the result

## Critical precondition: the firewall must see the VPC's queries

DNS Firewall only inspects queries that reach the Amazon-provided resolver (the `.2` resolver,
shown as `AmazonProvidedDNS`). If the VPC's Dynamic Host Configuration Protocol (DHCP) option set
points DNS at a custom resolver, the firewall sees nothing and has no effect, with no error.

**Constraints:**

- You MUST check the VPC's DHCP option set before building any rule groups
- If the VPC uses a custom resolver, you MUST tell the customer plainly that DNS Firewall will not
  filter this VPC's traffic, and MUST NOT proceed to create rule groups as if protection were in
  place. The console does not flag this precondition, so the customer will otherwise assume the VPC
  is protected when it is not

## Decision: block action mode

A blocked query can be answered three ways. The right choice depends on how the customer wants
the application to fail, because the wrong choice creates support cases that look like generic
resolution failures.

| Mode | What the client sees | Use when |
| --- | --- | --- |
| `NXDOMAIN` | The domain does not exist | The application should fail fast, as if the name is unregistered |
| `NODATA` | An empty answer | The failure should be quiet (can resemble a network issue) |
| `OVERRIDE` | A CNAME to a domain you supply | Traffic should be redirected to a sinkhole or inspection host (DNS Firewall returns a CNAME, not an IP) |

**Constraints:**

- You MUST confirm the desired mode with the customer rather than defaulting silently, because the
  mode changes application behavior on a block

## Beyond static domain lists: DNS Firewall Advanced

Static managed and custom lists catch known-bad domains. DNS Firewall Advanced extends protection
with four additional rule types that do not use customer domain lists:

| Rule type | Detection method | Use when |
| --- | --- | --- |
| **DGA (Domain Generation Algorithm)** | ML-based behavioral detection | Malware that generates random-looking domains for command-and-control |
| **DNS Tunneling** | ML-based behavioral detection | Data exfiltration via DNS query/response payloads |
| **Threat categories** | Rule-based categorization | Blocking domains by threat type (e.g., malware, ransomware, spyware, C2) — broader than the Foundational managed lists |
| **Content categories** | Rule-based categorization | Blocking domains by content type (e.g., gambling, adult content, streaming) for acceptable-use enforcement |

DGA and DNS tunneling rules support confidence thresholds (HIGH, MEDIUM, LOW) that control the
sensitivity of detection. Higher confidence means fewer false positives but may miss some threats.

**Constraints:**

- You SHOULD recommend DNS Firewall Advanced rules when the customer's concern is malware that
  uses DGA command-and-control, DNS tunneling, or when they need category-based filtering that
  static lists cannot reliably cover
- You MUST note that all Advanced rule types carry an additional hourly charge (see Cost to
  expect) and that the Allow action is not available for Advanced rules
- You SHOULD recommend HIGH confidence for BLOCK actions and MEDIUM or LOW confidence for ALERT
  actions when using DGA or DNS tunneling rules, to minimize false positives on blocking

## Cost to expect

DNS Firewall billing has three dimensions a customer should know before rollout:

- **Queries:** $0.60 per million queries from VPCs with a rule group association (first 1 billion
  per month), then $0.40 per million. Queries that follow CNAMEs are also charged.
- **Custom domains:** $0.0005 per domain per month for domains in custom lists. AWS-managed domain
  lists are free (you still pay for the queries inspected against them).
- **DNS Firewall Advanced:** $0.16 per hour per rule group containing one or more Advanced rules,
  per VPC association.

**Constraints:**

- You SHOULD surface these costs when the customer adds custom domains in bulk or enables Advanced
  rules, because both add charges beyond the per-query fee

## Reuse, do not duplicate

Rule groups are reusable. You SHOULD associate one rule group with all of the customer's VPCs
rather than creating a separate rule group per VPC. Per-VPC duplication drifts over time as new
domains land in some rule groups but not others, leaving inconsistent protection.

## Troubleshooting

### Rules created but nothing is blocked
The VPC sends DNS to a custom resolver, not `AmazonProvidedDNS`. Confirm the DHCP option set
uses the `.2` resolver before building rules. This is the most common cause and surfaces no error.

### Application breaks in a confusing way after a block
The block action mode does not match the desired client behavior. Choose `NXDOMAIN`, `NODATA`,
or `OVERRIDE` based on how the application should fail. See the decision table above.

### Protection differs between VPCs
A separate rule group was created per VPC. Associate one reusable rule group across all VPCs.

### Threat coverage has gaps
Domain lists were hand-curated without an AWS-managed list. Start from a managed list (malware,
botnet command-and-control, or the aggregate threat list) and add custom lists on top.

## Procedure

### Overview

This procedure filters DNS queries leaving a VPC against known-malicious domains and blocks
matches at the Amazon-provided resolver using Route 53 Resolver DNS Firewall. It verifies the
precondition that decides whether the firewall sees any traffic, creates and populates a rule
group, sets the block action mode, associates the rule group across the customer's VPCs, and
surfaces the console link to verify the result.

### Parameters

- **vpc_ids** (required): One or more VPC IDs to protect (e.g., `vpc-0abc123`). All VPCs in a
  single run should share the Region.
- **region** (required): The AWS Region the VPCs are in (e.g., `us-east-1`).
- **managed_domain_list** (optional, default: the AWS-managed aggregate threat list): Which
  AWS-managed domain list to start from.
- **custom_domains** (optional): Additional domains to block beyond the managed list.
- **block_action** (required): One of `NXDOMAIN`, `NODATA`, or `OVERRIDE`. Must be confirmed with
  the customer before creating rules (see Step 4); do not default it silently.
- **override_target** (required only when `block_action` is `OVERRIDE`): The domain name to
  return as a CNAME for blocked queries. OVERRIDE supports a CNAME target only, not an IP.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST confirm the Region and the full VPC list before any write operation
- You MUST NOT default the block action silently; confirm it with the customer (see Step 4)
- You MUST confirm successful acquisition of all parameters before proceeding

### Steps

#### 1. Verify dependencies

Check for required tooling and credentials before starting.

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You SHOULD prefer read-only or least-privilege credentials for the inspection steps and only
  use write-capable credentials for the create and associate steps
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST inform the customer if required tooling is missing and ask whether to proceed

#### 2. Confirm the firewall will see the VPC's queries (precondition)

DNS Firewall only inspects queries that reach the Amazon-provided resolver. If the VPC's DHCP
option set points DNS at a custom resolver, the firewall inspects nothing.

**Constraints:**

- You MUST retrieve each VPC's associated DHCP option set:

  ```
  aws ec2 describe-vpcs --vpc-ids {vpc_id} --region {region} --query 'Vpcs[0].DhcpOptionsId'
  ```

- You MUST inspect the option set's `domain-name-servers` value:

  ```
  aws ec2 describe-dhcp-options --dhcp-options-ids {dhcp_options_id} --region {region}
  ```

- A `domain-name-servers` value of `AmazonProvidedDNS` means the firewall will see the queries.
  Any other value (a custom resolver IP) means it will not
- If a VPC uses a custom resolver, you MUST tell the customer plainly that DNS Firewall will not
  filter that VPC's traffic, and MUST NOT continue building rules for it as though it were
  protected. The console surfaces no error for this case

#### 3. Create the rule group and populate domain lists

Create one rule group and reference an AWS-managed domain list as the foundation, adding custom
lists on top only as needed.

**Constraints:**

- You MUST create a single rule group for reuse, not one per VPC:

  ```
  aws route53resolver create-firewall-rule-group --name {rule_group_name} --region {region}
  ```

- You SHOULD start from one or more AWS-managed domain lists. The four publicly available managed
  lists are:
  - `AWSManagedDomainsMalwareDomainList` — domains associated with malware distribution and hosting
  - `AWSManagedDomainsBotnetCommandandControl` — domains used for botnet command-and-control
  - `AWSManagedDomainsAggregateThreatList` — combined multi-threat list (superset of malware,
    ransomware, botnet, spyware, DNS tunneling domains; includes domains from the other lists)
  - `AWSManagedDomainsAmazonGuardDutyThreatList` — domains from Amazon GuardDuty DNS security
    findings (internally generated threat intelligence)
  List the managed lists in the Region to find their IDs:

  ```
  aws route53resolver list-firewall-domain-lists --region {region}
  ```

- The managed list is referenced by its `Id`, not its friendly name. You MUST resolve the friendly
  name to its `Id` from `list-firewall-domain-lists` output before creating the rule
- You MUST treat custom domain lists as additive, not as the foundation. If the customer supplied
  `custom_domains`, create a custom list and add the domains with `update-firewall-domains`
  (inline domains use `update-firewall-domains`, not `import-firewall-domains`):

  ```
  aws route53resolver create-firewall-domain-list --name {custom_list_name} --region {region}
  aws route53resolver update-firewall-domains --firewall-domain-list-id {list_id} \
    --operation ADD --domains {domain1} {domain2} --region {region}
  ```

- For a bulk list, `import-firewall-domains` loads domains from an Amazon S3 file and supports only
  `--operation REPLACE` (it overwrites the list); it does not accept inline `--domains`:

  ```
  aws route53resolver import-firewall-domains --firewall-domain-list-id {list_id} \
    --operation REPLACE --domain-file-url s3://{bucket}/{key} --region {region}
  ```

#### 4. Set the block action mode

Add a rule to the rule group that references each domain list with the confirmed block action.

**Constraints:**

- You MUST confirm the block action with the customer before creating the rule, because the mode
  changes application behavior on a block:
  - `NXDOMAIN` — the client is told the domain does not exist (fail fast)
  - `NODATA` — the client gets an empty answer (quiet failure)
  - `OVERRIDE` — the client is returned a CNAME to a domain you supply (redirect to a sinkhole)
- You SHOULD offer an ALERT-first rollout for an unfamiliar managed list: create the rule with
  `--action ALERT` first, confirm from query logs that legitimate domains are not caught, then
  switch the rule to `--action BLOCK`. ALERT logs the match and permits the query, avoiding an
  outage from a false positive on a list the customer has not validated
- For `NXDOMAIN` or `NODATA`:

  ```
  aws route53resolver create-firewall-rule \
    --firewall-rule-group-id {rule_group_id} \
    --firewall-domain-list-id {list_id} \
    --priority {priority} --action BLOCK --block-response {NXDOMAIN|NODATA} \
    --name {rule_name} --region {region}
  ```

- For `OVERRIDE`, you MUST supply `override_target`, a DNS record type, and a TTL:

  ```
  aws route53resolver create-firewall-rule \
    --firewall-rule-group-id {rule_group_id} \
    --firewall-domain-list-id {list_id} \
    --priority {priority} --action BLOCK --block-response OVERRIDE \
    --block-override-domain {override_target} --block-override-dns-type CNAME \
    --block-override-ttl {ttl} --name {rule_name} --region {region}
  ```

#### 4a. Add ALLOW rules for false-positive mitigation (optional)

If legitimate domains are caught by a managed list or a broad custom list, create a higher-priority
ALLOW rule for those specific domains. Because DNS Firewall evaluates rules by priority (lowest
number first) and stops at the first match, an ALLOW rule with a lower priority number than the
BLOCK rule overrides the block for that domain.

**Constraints:**

- You SHOULD create a custom domain list of known-good domains and an ALLOW rule at a priority
  lower (higher precedence) than the BLOCK rule:

  ```
  aws route53resolver create-firewall-domain-list --name {allowlist_name} --region {region}
  aws route53resolver update-firewall-domains --firewall-domain-list-id {allowlist_id} \
    --operation ADD --domains {legitimate_domain1} {legitimate_domain2} --region {region}
  aws route53resolver create-firewall-rule \
    --firewall-rule-group-id {rule_group_id} \
    --firewall-domain-list-id {allowlist_id} \
    --priority {priority_lower_than_block} --action ALLOW \
    --name {allow_rule_name} --region {region}
  ```

- You MUST set the ALLOW rule's priority to a lower number than the BLOCK rule it overrides

#### 4b. Enable query logging for monitoring (required)

Query logging is required to monitor ALERT rules, detect false positives, and confirm rules are
matching expected traffic.

**Constraints:**

- You MUST enable Resolver query logging on each protected VPC (this is the security-required
  control stated in Security Considerations; the log destination MUST have encryption at rest):

  ```
  aws route53resolver create-resolver-query-log-config \
    --name {log_config_name} \
    --destination-arn {destination_arn} \
    --region {region}
  aws route53resolver associate-resolver-query-log-config \
    --resolver-query-log-config-id {config_id} \
    --resource-id {vpc_id} --region {region}
  ```

  The destination can be a CloudWatch Logs log group, an S3 bucket, or a Data Firehose
  delivery stream.
- You MUST enable encryption at rest on the query log destination, because query logs contain the
  domain names a VPC's workloads resolve: a KMS key on the CloudWatch Logs log group
  (`aws logs associate-kms-key`), SSE-S3 or SSE-KMS on the S3 bucket, or server-side encryption on
  the Data Firehose stream
- Query log records include `firewall_rule_group_id`, `firewall_rule_action`, and
  `firewall_domain_list_id` for ALERT and BLOCK actions — use these to verify rules are
  matching expected traffic before switching from ALERT to BLOCK

#### 5. Associate the rule group across all the customer's VPCs

Associate the single rule group with every VPC that passed the Step 2 precondition.

**Constraints:**

- You MUST associate the same rule group with each protected VPC rather than creating new rule
  groups:

  ```
  aws route53resolver associate-firewall-rule-group \
    --firewall-rule-group-id {rule_group_id} \
    --vpc-id {vpc_id} --priority {priority} \
    --name {association_name} --region {region}
  ```

- You MUST skip any VPC flagged in Step 2 as using a custom resolver, and remind the customer why

#### 6. Confirm and surface the console link

Confirm the associations and hand the customer the console link to verify.

**Constraints:**

- You MUST verify each association reached `COMPLETE`:

  ```
  aws route53resolver list-firewall-rule-group-associations \
    --firewall-rule-group-id {rule_group_id} --region {region}
  ```

- You MUST present the rule group detail console view, filling `{region}` with the VPCs' Region
  and `{ruleGroupId}` with the rule group ID returned by `create-firewall-rule-group` in Step 3.
  Note the fragment is `RulegroupId` (lowercase `g`):

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#DNSFirewallRuleGroupDetails:RulegroupId={ruleGroupId}
  ```

### Example

#### Example input

```json
{
  "vpc_ids": ["vpc-0abc123", "vpc-0def456"],
  "region": "us-east-1",
  "managed_domain_list": "AWSManagedDomainsMalwareDomainList",
  "block_action": "NXDOMAIN"
}
```

#### Example output

```
Created rule group rslvr-frg-0123456789abcdef0 referencing AWSManagedDomainsMalwareDomainList
with a BLOCK/NXDOMAIN rule.
- Associated with vpc-0abc123 (COMPLETE)
- Associated with vpc-0def456 (COMPLETE)
Verify in the console:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#DNSFirewallRuleGroupDetails:RulegroupId=rslvr-frg-0123456789abcdef0
```

### Troubleshooting

#### Rules created but nothing is blocked
The VPC sends DNS to a custom resolver, not `AmazonProvidedDNS`. Re-check the DHCP option set
(Step 2). DNS Firewall surfaces no error for this case.

#### Application breaks in a confusing way after a block
The block action mode does not match the desired client behavior. Re-create the rule with the
mode that matches how the application should fail (Step 4).

#### Protection differs between VPCs
A separate rule group was created per VPC. Consolidate onto one reusable rule group and
re-associate (Steps 3 and 5).

#### Association stuck or failed
Check the association status with `list-firewall-rule-group-associations`. A VPC can have a
limited number of associated rule groups; remove an unused association before adding another.

#### Verifying rules are matching (test domains)
AWS provides test domains for each managed list. Query these from within a protected VPC to
confirm the firewall is active and rules are matching. The format is:

```
controldomain1.{listname}.firewall.route53resolver.{region}.amazonaws.com
```

For example:

```
dig controldomain1.botnetlist.firewall.route53resolver.us-east-1.amazonaws.com
```

A successful block returns the configured block response (NXDOMAIN, NODATA, or OVERRIDE).
If the query resolves normally, the firewall is not inspecting the VPC's traffic.

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST enable Resolver query logging to an encrypted destination (KMS on CloudWatch Logs,
  SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and ensure CloudTrail
  is enabled to audit rule and association changes.
- You SHOULD prefer an ALERT-first rollout on an unvalidated managed list and confirm matches from
  query logs before switching to BLOCK, so a false positive does not cause an outage.
- You MUST confirm the block action mode with the customer, since the wrong mode changes how
  applications fail on a block.

## Additional Resources

- [Filter DNS traffic using Route 53 Resolver DNS Firewall (VPC User Guide)](https://docs.aws.amazon.com/vpc/latest/userguide/resolver-dns-firewall.html)
- [Resolver DNS Firewall domain lists (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-dns-firewall-domain-lists.html)
