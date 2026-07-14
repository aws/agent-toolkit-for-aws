# Identifying the Effective DNS Firewall Rule for a Domain

## Overview

Domain expertise for working out which single Route 53 Resolver DNS Firewall rule decides the
outcome for a domain when a VPC has several rule groups associated and more than one rule could
match. Covers the two-layer evaluation order (rule group association priority, then rule priority
within a group), the first-match-wins behavior that makes a high-priority Allow or Alert shadow a
lower-priority Block, and how to read the live configuration to name the winning rule.

This is a read and diagnostic workflow. It inspects configuration and explains the result; it does
not create or change rules. For authoring blocking rules see the blocking-malicious-domains
reference, and for fanning rule groups across accounts see the centralizing-dns-firewall reference.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- How DNS Firewall picks the winning rule
- Decision: is a rule actually reachable?
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To identify the effective rule for a domain, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Listing the rule groups associated with the VPC and sorting them by association priority
- Listing the rules in each candidate group and sorting them by rule priority
- Finding the first rule whose domain list matches the domain, in evaluation order
- Reporting the winning rule, its action, and any lower-priority rules it shadows
- Surfacing the console link so the customer can see the rule group and its rules

## How DNS Firewall picks the winning rule

DNS Firewall evaluates in a fixed order and stops at the first match:

1. **Across rule groups:** the VPC's rule group associations are processed by association
   priority, lowest number first. Each association on a VPC has a unique priority (valid range
   100 to 9900; the console help panel uses 101 to 9899).
2. **Within a rule group:** rules are processed by rule priority, lowest number first.
3. **First match wins and halts inspection.** A rule matches when the query satisfies all of:
   - The query name matches the rule's domain list (or the rule is an Advanced rule that detects
     the query by behavior)
   - The query type (Qtype) matches the rule's Qtype filter. If the rule has no Qtype set, it
     matches all query types. If a Qtype is set (e.g., A, AAAA, MX, TXT), only queries of that
     type match that rule.
   When a match occurs the resolver applies the rule's action and stops. All three actions are
   terminating:
   - **Allow** — permit the query, stop inspecting.
   - **Alert** — permit the query, log an alert, stop inspecting.
   - **Block** — block the query, respond per the block mode (`NODATA`, `NXDOMAIN`, or
     `OVERRIDE`), log the block, stop inspecting.

Because every action halts inspection, a broad Allow or Alert in a higher-priority group prevents
a Block in a lower-priority group from ever running for that domain. That shadowing is the usual
reason a domain the customer expected to be blocked is not.

**Constraints:**

- You MUST combine both layers in order (association priority, then rule priority within the
  group) rather than reasoning about one rule group in isolation
- You MUST treat the first matching rule as the effective one and report that an Allow or Alert
  halts inspection, so any matching rule in a lower-priority position never applies
- You MUST evaluate domain matching from most specific to least specific: a rule matches when its
  domain list contains the exact query name or a parent the list covers via a `*.` wildcard.
  Wildcard semantics: the `*` can only appear as the leftmost label; `*.example.com` matches any
  subdomain (e.g., `sub.example.com`, `deep.sub.example.com`) but does NOT match the apex
  `example.com` itself. Check the query name and each parent label, not just an exact string
- You MUST account for query type (Qtype) filtering: a rule with a Qtype set (e.g., A, AAAA, MX)
  only matches queries of that type. A rule with no Qtype set matches all query types. When
  debugging "why didn't my rule match," verify the rule's Qtype matches the query type
- You MUST account for AWS-managed domain lists, whose contents cannot be listed or downloaded.
  The domain may be in a managed list the customer did not author; determine a managed-list match
  from Resolver query logs or AWS-provided test domains, not by enumerating the list
- You MUST account for DNS Firewall Advanced rule types (DGA, DNS tunneling, threat categories,
  content categories), which have no customer domain list and match by detection or categorization
  rather than list membership; such a rule can be the effective or shadowing rule, and the Allow
  action is not available for Advanced rules
- You MUST account for domain redirection behavior: a rule's `FirewallDomainRedirectionAction`
  setting determines whether CNAME/DNAME chain targets are also inspected against firewall rules
  (`INSPECT_REDIRECTION_DOMAIN`) or trusted without further inspection
  (`TRUST_REDIRECTION_DOMAIN`). When a query follows a CNAME chain, this setting affects which
  domains in the chain are evaluated against rules

## Decision: is a rule actually reachable?

| Situation | What applies |
| --- | --- |
| Domain matches one rule only | That rule's action applies |
| Domain matches rules in several groups | The match in the lowest-association-priority group wins; lower groups are not consulted |
| Domain matches several rules in one group | The lowest-rule-priority match in that group wins |
| A high-priority Allow or Alert matches the domain | It wins and halts inspection; any lower Block is shadowed and never runs |

## Troubleshooting

### A domain the customer expected to be blocked is allowed
A higher-priority Allow or Alert rule matches the domain first and halts inspection. Find the
first matching rule in evaluation order; the Block sits below it and never runs.

### Behavior changed after adding a rule group
A newly associated group took a lower (higher-priority) association number, or a Profile-managed
group was added, changing which group is evaluated first. Re-sort the associations by priority.

### Two associations appear to have the same priority
Each association on a VPC must have a unique priority. If a tool reports a clash, an association
was just changed; re-read the associations before concluding.

### The matching rule is not one the customer wrote
The domain is in an AWS-managed domain list referenced by a rule. Check managed-list rules, not
just custom lists.

### A rule with the right domain does not match
The rule has a Qtype filter (e.g., A only) that does not match the query type (e.g., the query is
AAAA or MX). Check the rule's Qtype setting; if it is set, only queries of that type trigger it.

## Procedure

### Overview

This procedure determines which DNS Firewall rule decides the outcome for a domain on a VPC that
has one or more rule groups associated. It reads the rule group associations and their priorities,
reads the rules and their priorities within each candidate group, finds the first match in
evaluation order, and reports the effective rule and what it shadows. It changes nothing.

### Parameters

- **vpc_id** (required): The VPC whose effective rule you want to determine (e.g., `vpc-0abc123`).
- **region** (required): The AWS Region the VPC is in (e.g., `us-east-1`).
- **domain** (required): The domain name to evaluate (e.g., `example.com`).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You SHOULD prefer read-only or least-privilege credentials; this workflow only reads

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You SHOULD use read-only credentials; no step here writes

#### 2. List the rule group associations on the VPC and sort by association priority

**Constraints:**

- You MUST list the associations for the VPC and order them by `Priority`, lowest first:

  ```
  aws route53resolver list-firewall-rule-group-associations \
    --vpc-id {vpc_id} --region {region}
  ```

- The lowest `Priority` association is evaluated first. Note each association's
  `FirewallRuleGroupId` in that order
- A VPC can have one Route 53 Profile, and rule groups applied through that Profile may not appear
  in `list-firewall-rule-group-associations`. You MUST also check for a Profile on the VPC and
  enumerate its rule group resource associations, folding them into the same priority-ordered walk
  as the directly associated rule groups:

  ```
  aws route53profiles list-profile-associations --resource-id {vpc_id} --region {region}
  aws route53profiles list-profile-resource-associations \
    --profile-id {profile_id} --region {region}
  ```

#### 3. List the rules in each candidate group and sort by rule priority

**Constraints:**

- For each associated rule group, in association-priority order, you MUST list its rules ordered
  by rule `Priority`, lowest first:

  ```
  aws route53resolver list-firewall-rules \
    --firewall-rule-group-id {rule_group_id} --region {region}
  ```

- For a rule that references a `FirewallDomainListId`, resolve whether `{domain}` (or a parent the
  list matches via a `*.` wildcard) is in that list. Custom lists can be enumerated:

  ```
  aws route53resolver list-firewall-domains \
    --firewall-domain-list-id {domain_list_id} --region {region}
  ```

- AWS-managed domain lists CANNOT be enumerated or downloaded; `list-firewall-domains` does not
  return their contents. For a rule backed by a managed list, determine a match from Resolver
  query logs (see Step 3a) or by testing an AWS-provided test domain, not by listing the list
- Advanced rule types (DGA, DNS tunneling) have no `FirewallDomainListId`; they match by
  detection. Treat such a rule as a potential match by its rule type and confirm from query logs

#### 3a. Confirm the match from Resolver query logs (authoritative)

When Resolver query logging is enabled on the VPC, the logs name the rule that acted on a query
and are the authoritative way to confirm the effective rule, especially for managed-list and
Advanced rules whose contents you cannot enumerate.

**Constraints:**

- You SHOULD use query logs when available. The log record reports `firewall_rule_group_id`,
  `firewall_rule_action`, and the matched `firewall_domain_list_id` for the query
- You MUST account for one caveat: these firewall fields populate for `ALERT` and `BLOCK` actions
  but NOT for `ALLOW`. A query permitted by a shadowing Allow rule will not name that rule in the
  logs, so a domain that resolves with no firewall fields may still have matched an Allow. Fall
  back to the configuration walk (Step 4) to find a shadowing Allow

#### 4. Find the first match in evaluation order

**Constraints:**

- You MUST walk the rules in combined order (association priority, then rule priority within the
  group) and stop at the first rule that matches `{domain}` AND the query type — by exact name,
  by a parent wildcard in its domain list, or by detection for an Advanced rule. A rule with a
  Qtype filter that does not match the query's type is skipped even if the domain matches
- You MUST report that rule as the effective one, with its action (`ALLOW`, `ALERT`, or `BLOCK`
  plus the block response mode), and explain that the match halts inspection
- You MUST list any lower-priority rules that also match `{domain}` and note they are shadowed and
  never apply, so the customer sees why a Block below an Allow or Alert has no effect

#### 5. Surface the console link

**Constraints:**

- You MUST present the rule group detail view for the winning rule's group, filling `{region}`
  with the VPC's Region and `{ruleGroupId}` with the matched rule group's ID. The fragment is
  `RulegroupId` (lowercase `g`):

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#DNSFirewallRuleGroupDetails:RulegroupId={ruleGroupId}
  ```

- If no rule matches `{domain}` in any associated group, you MUST say so plainly: DNS Firewall
  takes no action and the query resolves normally
- You SHOULD note that this "resolves normally" outcome assumes the firewall is healthy. If the
  firewall cannot be reached, the VPC's DNS Firewall fail-open setting decides the result; the
  default is fail-closed (the query is blocked), unless fail-open is enabled

### Example

#### Example input

```json
{
  "vpc_id": "vpc-0abc123",
  "region": "us-east-1",
  "domain": "ads.example.com"
}
```

#### Example output

```
Effective rule for ads.example.com on vpc-0abc123:
- Rule group "corp-allowlist" (association priority 100), rule "allow-partners" (rule priority 10)
  ACTION: ALLOW — matches ads.example.com, halts inspection.
Shadowed (never reached):
- Rule group "threat-block" (association priority 200), rule "block-adtech" (rule priority 10)
  would BLOCK/NXDOMAIN, but the ALLOW above wins.
Verify in the console:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#DNSFirewallRuleGroupDetails:RulegroupId=rslvr-frg-0123456789abcdef0
```

### Troubleshooting

#### A domain expected to be blocked is allowed
A higher-priority Allow or Alert matched first and halted inspection (Step 4). The Block sits in a
lower-priority position and never runs.

#### Behavior changed after adding a rule group
A new association took a higher-priority (lower-numbered) slot, or a Profile-managed group was
added. Re-sort the associations (Step 2).

#### The matching rule is a managed-list rule
The domain is in an AWS-managed domain list, not a custom one. Resolve managed lists too (Step 3).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys. This workflow only reads, so read-only credentials suffice.
- Where you read Resolver query logs to confirm the effective rule, you SHOULD ensure the log
  destination is encrypted at rest (KMS on CloudWatch Logs, SSE-S3/SSE-KMS on S3, or server-side
  encryption on a Data Firehose stream), because query logs reveal the domains a VPC resolves.
- You SHOULD report the effective rule and any shadowed rules accurately rather than assuming a
  Block applies, since a shadowing Allow or Alert silently changes the security outcome for a
  domain the customer believes is blocked.

## Additional Resources

- [Rule actions in DNS Firewall (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-dns-firewall-rule-actions.html)
- [Define priority (Route 53 Console help panel)](https://docs.aws.amazon.com/help-panel/Route53/latest/console/profile-firewall-rule-groups-priority.html)
- [Filter DNS traffic using Route 53 Resolver DNS Firewall (VPC User Guide)](https://docs.aws.amazon.com/vpc/latest/userguide/resolver-dns-firewall.html)
