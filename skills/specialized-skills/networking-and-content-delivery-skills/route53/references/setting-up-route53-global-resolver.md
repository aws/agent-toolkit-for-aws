# Setting Up Route 53 Global Resolver

## Overview

Domain expertise for setting up a Route 53 Global Resolver instance: an anycast DNS endpoint
that on-premises and remote clients use to resolve both public domains and Route 53 private
hosted zones, without per-location DNS infrastructure. Covers the resource hierarchy and
ordering, the multi-Region requirement, the per-DNS-view authentication choice, optional DNS
firewall, and private hosted zone access.

Does not cover integration with resolver endpoints for hybrid networks (a separate skill) or
hosted zone and record management.

All Global Resolver API calls are made in `us-east-2` regardless of which Regions the resolver
itself is deployed to. The control plane runs in US East (Ohio); calls without `--region us-east-2`
fail with a confusing endpoint or authorization error.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Resource hierarchy and order
- Decision: which Regions to deploy to
- Decision: token-based vs IP-based access (per DNS view)
- Token expiration and protocol scope
- Decision: one DNS view vs many
- Decision: firewall rule shape
- Decision: block action mode
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To build a Global Resolver instance, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Creating the resolver with the right Region set, observability Region, and IP address type
- Creating one DNS view per client group that needs distinct policy
- Adding access sources, access tokens, or both, per DNS view
- Adding firewall rules per view: domain-list rules (custom or AWS-managed lists) or advanced
  threat protection rules (domain generation algorithm (DGA) detection, including dictionary
  DGA, and DNS tunneling detection)
- Associating private hosted zones to a DNS view
- Pointing clients at the two anycast IPs and surfacing the console link to verify

## Resource hierarchy and order

Global Resolver resources are nested. Create them outside-in:

```
Global Resolver
  +-- DNS View
  |     +-- Access Source         (IP-based access; one CIDR + protocol per source)
  |     +-- Access Token          (token-based access; DoT/DoH only, not Do53)
  |     +-- Firewall Rule         (priority-ordered on this view; references a domain list
  |                                  below, or uses an advanced threat detector)
  |     +-- Hosted Zone Association (private hosted zone reachable through this view)
  +-- Firewall Domain List        (custom list, scoped to the resolver, referenced by rules
                                   on any DNS view; AWS-managed lists are pre-existing)
```

Firewall domain lists live at the Global Resolver level, not on a DNS view. One custom list can
be referenced from rules on multiple views. AWS-managed lists are pre-existing and do not need
to be created; reference them by ID directly from a rule. Two types are available:

- `THREAT`: Malware, Botnet command-and-control, Spam, Phishing, Amazon GuardDuty threat
  intelligence
- `CONTENT`: content categories such as social media and gambling

**Constraints:**

- You MUST create resources in this order: Global Resolver, then any custom firewall domain
  lists, then DNS views, then per-view access sources and tokens (and any firewall rules or
  hosted zone associations), then point clients at the anycast IPs. A domain-list firewall rule
  cannot be created until both its DNS view and the firewall domain list it references exist
- You MUST add at least one access source or one access token to each DNS view that needs to
  serve clients. A view with neither authorizes nothing
- `create-global-resolver` returns two anycast IPv4 addresses (and two IPv6 addresses if
  `--ip-address-type DUAL_STACK` was set). You MUST configure clients with both, not just one
- Each Create call returns `status: CREATING`. You MUST poll the corresponding `get-*` call
  until status is `OPERATIONAL` before using the resource downstream

## Decision: which Regions to deploy to

| Choice | Use when |
| --- | --- |
| 2-3 Regions close to the client population | Default. Survives a Region-level outage with the smallest footprint |
| Broader Region set (4+) | Globally distributed clients with strict latency targets, or compliance reasons to keep traffic in-Region |
| Single Region | Not recommended. A single-Region resolver loses availability during a Regional event |

**Constraints:**

- You MUST select at least two Regions for any production setup
- You MUST set `--observability-region` at create time. It names the Region that query logs are
  delivered from, and is needed even if logging is not configured yet, so the customer can
  enable it later without recreating the resolver
- `update-global-resolver` accepts a new `--regions` set, but adding a Region is a time-consuming
  operation because the new Region has to provision and replicate state before serving traffic.
  Pick the initial set deliberately

## Decision: token-based vs IP-based access (per DNS view)

Authentication is configured on the DNS view, not on the resolver as a whole. A view can have
access sources, access tokens, or both, so a single resolver can serve roaming clients (token)
on one view and branch offices (IP) on another, or mix both kinds on the same view.

| Choice | Use when |
| --- | --- |
| Access source (IP-based) | Fixed-location clients (branch offices, data centers) where the source IP is stable |
| Access token | Roaming clients (laptops, remote workers) where the source IP is not stable |
| Both on the same view | A population that includes some fixed-location and some roaming clients |

**Constraints:**

- You MUST help the customer pick correctly per population. IP-based for roaming clients behind
  shared network address translation (NAT) leaks access to anyone sharing the NAT IP;
  token-based for a large fixed fleet creates token-rotation pain across thousands of devices
- Access source `--protocol` is `DO53`, `DOT`, or `DOH` (uppercase). For multiple CIDRs or
  multiple protocols on one view, create one access source per (CIDR, protocol) pair
- You SHOULD recommend DoT or DoH over Do53 for every client population that can support it, to
  encrypt queries in transit. Do53 transmits queries and responses in plaintext, exposing the
  queried domain names to on-path observers; reserve it for clients that genuinely cannot use an
  encrypted protocol

## Token expiration and protocol scope

Two access-token traps surface as silent or partial failures.

**Constraints:**

- Access tokens authenticate DoT and DoH connections only, not Do53. A client resolving over
  Do53 will fail no matter what token it presents. For a Do53 population on the view, you MUST
  add an IP-based access source instead
- Access token expiration is bounded between 30 and 365 days from creation. You MUST set
  `--expires-at` within that window. The token `value` returned in the create response is the
  secret the client uses and is not retrievable later, so capture it at create time

## Decision: one DNS view vs many

| Choice | Use when |
| --- | --- |
| Multiple DNS views | Client groups need different resolution behavior, different firewall policy, or different private hosted zone access |
| One DNS view | Every client group should resolve identically and see the same private hosted zones |

**Constraints:**

- You SHOULD set up DNS views during initial configuration. Retrofitting a second view after a
  flat policy is in production, with clients already pointed at it, requires re-issuing tokens
  or re-allocating CIDRs and is much more expensive

## Decision: firewall rule shape

A firewall rule on a DNS view is one of two shapes. The shape decides what the rule matches and
which actions are valid.

| Shape | Use when |
| --- | --- |
| Domain-list rule | The threat is a known set of bad domains. Match against a custom or AWS-managed firewall domain list. Action is `ALLOW`, `BLOCK`, or `ALERT` |
| Advanced threat protection rule | The threat is algorithmic: short-lived DGA names or DNS tunneling for data exfiltration. Match against `DGA`, `DNS_TUNNELING`, or `DICTIONARY_DGA`. Action is `ALERT` or `BLOCK` only |

**Constraints:**

- Rules within a view are evaluated in priority order, lowest first; first match wins
- Advanced threat protection rules reject `ALLOW`. The API enforces this; algorithmic detection
  cannot definitively classify benign traffic
- Advanced rules carry `--confidence-threshold` (`LOW`, `MEDIUM`, `HIGH`). You SHOULD start at
  `HIGH` in `ALERT` mode, measure false positives, then lower or move to `BLOCK` from there

## Decision: block action mode

A blocked query can be answered three ways. The wrong choice creates support cases that look
like generic resolution failures.

| Mode | Use when |
| --- | --- |
| `NXDOMAIN` (the client is told the domain does not exist) | The application should fail fast |
| `NODATA` (the client gets an empty answer) | The failure should be quiet (can resemble a network issue) |
| `OVERRIDE` (the client gets a chosen CNAME target) | Traffic should be redirected to a sinkhole or inspection host |

**Constraints:**

- You MUST confirm the block mode with the customer rather than defaulting silently. The mode
  changes application behavior on a block
- For `OVERRIDE`, you MUST also supply `--block-override-domain`, `--block-override-dns-type`
  (the API only supports `CNAME`), and `--block-override-ttl`. The API rejects an OVERRIDE rule
  without all three

## Troubleshooting

### CLI command fails with an endpoint or authorization error
Missing `--region us-east-2`. Every Global Resolver API call goes to US East (Ohio) regardless
of where the resolver is deployed.

### DNS view exists but rejects every query
No access source and no access token on the view. A view authorizes nothing until at least one
of either is created.

### Token works for some clients but not others
Tokens authenticate DoT and DoH only, not Do53. Add an IP-based access source for the Do53
population, or move them to DoT or DoH.

### Roaming clients intermittently lose access
IP-based access source used for clients with changing IPs. Switch the roaming population to a
token-based access token; IP and token can coexist on the same view for a mixed population.

### Clients cannot connect over the chosen protocol
The access source's `--protocol` does not match the client operating system. Update with
`update-access-source --protocol DO53|DOT|DOH`, or recreate if you also need to change the CIDR
or IP address type. For DoT and DoH clients, also check the SNI entry below; a TLS handshake
failure surfaces here too.

### Private hosted zone records do not resolve
No hosted zone association on the DNS view. Associate the hosted zone to the view's ARN and
wait for status `OPERATIONAL`.

### Firewall rule does not block the expected domains
A higher-priority rule on the same view halted inspection first, the rule references the wrong
domain list, or the rule is on a different DNS view than the queries are coming through. Read
the rule and the list contents to confirm:

```
aws route53globalresolver get-firewall-rule --region us-east-2 --firewall-rule-id {rule_id}
aws route53globalresolver list-firewall-domains --region us-east-2 \
  --firewall-domain-list-id {list_id}
```

### DoT or DoH client fails to connect with a TLS error
The client is connecting to the anycast IP without setting the resolver's `dnsName` as TLS
server name indication (SNI). The certificate is bound to `dnsName`, not to the anycast IP.
Set the SNI to the value of `dnsName` returned by `get-global-resolver`.

### Application breaks confusingly after a firewall block
Block mode does not match how the application should fail. Recreate with `NXDOMAIN`,
`NODATA`, or `OVERRIDE` per the block-mode decision.

### IPv6 anycast addresses missing
The resolver was created without `--ip-address-type DUAL_STACK`. Update via
`update-global-resolver --ip-address-type DUAL_STACK` to add the IPv6 anycast addresses.

## Procedure

### Overview

This procedure sets up a Route 53 Global Resolver instance: an anycast DNS endpoint for
on-premises and remote clients. It creates the resolver, selects Regions and the observability
Region, creates one or more DNS views, adds access sources and access tokens per view,
optionally adds firewall rules and private hosted zone associations, points clients at the two
anycast IPs, and surfaces the console link to verify.

### Parameters

- **resolver_name** (required): A name for the Global Resolver instance.
- **regions** (required): The AWS Regions the resolver runs in. At least two for production.
- **observability_region** (required): The Region that query logs are delivered from. Must be
  one of the Regions in `regions`.
- **ip_address_type** (optional, default: `IPV4`): `IPV4` or `DUAL_STACK`. `DUAL_STACK` adds
  two anycast IPv6 addresses alongside the two IPv4 addresses.
- **dns_views** (required): One or more DNS views, each with:
  - `name`
  - `dnssec_validation`: `ENABLED` or `DISABLED`
  - `edns_client_subnet`: `ENABLED` or `DISABLED`
  - `firewall_rules_fail_open`: `ENABLED` or `DISABLED`
  - `access_sources`: zero or more `{cidr, protocol}` pairs
  - `tokens`: zero or more `{name, expires_at}`
  - `firewall_rules` (optional): domain-list or advanced-threat rules, each with a priority
  - `hosted_zone_associations` (optional): private hosted zone IDs

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the Regions list, observability Region, and IP address type before any write
  operation
- You MUST confirm, per DNS view, which client populations it serves and whether each one needs
  IP-based access, token-based access, or both

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST set `--region us-east-2` for every Global Resolver call in this procedure, or
  configure it for the session (`aws configure set region us-east-2`)

#### 2. Create the Global Resolver

**Constraints:**

- You MUST set `--regions`, `--observability-region`, and `--ip-address-type`. The observability
  Region must be one of the Regions in `--regions`:

  ```
  aws route53globalresolver create-global-resolver \
    --region us-east-2 \
    --name {resolver_name} \
    --regions {region_1} {region_2} \
    --observability-region {observability_region} \
    --ip-address-type {IPV4|DUAL_STACK}
  ```

- You MUST capture both `ipv4Addresses` (and `ipv6Addresses` if dual-stack) from the response;
  clients are configured with all of them
- You MUST poll `get-global-resolver` until `status` is `OPERATIONAL` before creating
  downstream resources

#### 3. Create the DNS view(s)

Each view has three options that have to be set explicitly:

- `--dnssec-validation`: when `ENABLED`, the resolver verifies DNSSEC signatures. Use `ENABLED`
  unless the customer has a known broken signer they cannot avoid.
- `--edns-client-subnet`: when `ENABLED`, the resolver forwards (or injects, if absent) the
  client subnet to authoritative nameservers. Improves geographic CDN routing at the cost of
  leaking subnet info; the customer's privacy posture decides this.
- `--firewall-rules-fail-open`: when `ENABLED`, queries are allowed through if the firewall
  cannot be evaluated. `DISABLED` (fail closed) is safer for security-critical setups;
  `ENABLED` (fail open) avoids broad outages if the firewall has a problem.

**Constraints:**

- You MUST create at least one DNS view; a Global Resolver with no view authorizes nothing
- You MUST set all three options per view based on customer requirements:

  ```
  aws route53globalresolver create-dns-view \
    --region us-east-2 \
    --global-resolver-id {global_resolver_id} \
    --name {view_name} \
    --dnssec-validation {ENABLED|DISABLED} \
    --edns-client-subnet {ENABLED|DISABLED} \
    --firewall-rules-fail-open {ENABLED|DISABLED}
  ```

#### 4. Add access sources and access tokens per DNS view

**Constraints:**

- For each fixed-location population on the view, you MUST create one access source per
  (CIDR, protocol) pair:

  ```
  aws route53globalresolver create-access-source \
    --region us-east-2 \
    --dns-view-id {dns_view_id} \
    --cidr {cidr} \
    --protocol {DO53|DOT|DOH} \
    --name {access_source_name}
  ```

- For each roaming population on the view, you MUST create an access token:

  ```
  aws route53globalresolver create-access-token \
    --region us-east-2 \
    --dns-view-id {dns_view_id} \
    --name {token_name} \
    --expires-at {iso8601_timestamp}
  ```

- You MUST store the token `value` from the create response in AWS Secrets Manager rather than in
  plaintext configuration; it is the client secret and is not retrievable after creation

#### 5. Add firewall rules per DNS view (optional)

A domain-list rule references a firewall domain list; an advanced rule uses an algorithmic
detector and skips the list. Custom domain lists are scoped to the resolver and reusable across
views; AWS-managed lists do not need to be created.

**Constraints:**

- For a custom domain list, create at the resolver level and add domains. `update-firewall-domains`
  accepts up to 1000 domains per call (`ADD`, `REMOVE`, or `REPLACE`); for larger lists use
  `import-firewall-domains` with a domain file in S3:

  ```
  aws route53globalresolver create-firewall-domain-list \
    --region us-east-2 \
    --global-resolver-id {global_resolver_id} \
    --name {list_name}
  aws route53globalresolver update-firewall-domains \
    --region us-east-2 \
    --firewall-domain-list-id {list_id} \
    --operation ADD --domains {domain_1} {domain_2}
  aws route53globalresolver import-firewall-domains \
    --region us-east-2 \
    --firewall-domain-list-id {list_id} \
    --operation ADD \
    --domain-file-url s3://{bucket}/{key}
  ```

- To find AWS-managed list IDs, list by type. The type is `THREAT` or `CONTENT`:

  ```
  aws route53globalresolver list-managed-firewall-domain-lists \
    --region us-east-2 \
    --managed-firewall-domain-list-type {THREAT|CONTENT}
  ```

- Create a domain-list rule on the view. For `BLOCK`, set `--block-response`; for `OVERRIDE`,
  also supply the override target fields (see the block-mode decision):

  ```
  aws route53globalresolver create-firewall-rule \
    --region us-east-2 \
    --dns-view-id {dns_view_id} \
    --firewall-domain-list-id {list_id} \
    --priority {priority} \
    --action {ALLOW|BLOCK|ALERT} \
    --block-response {NXDOMAIN|NODATA|OVERRIDE} \
    --name {rule_name}
  ```

- For an advanced threat protection rule, omit the domain list and set the detector and
  threshold. Action is `ALERT` or `BLOCK` only:

  ```
  aws route53globalresolver create-firewall-rule \
    --region us-east-2 \
    --dns-view-id {dns_view_id} \
    --priority {priority} \
    --action {ALERT|BLOCK} \
    --dns-advanced-protection {DGA|DNS_TUNNELING|DICTIONARY_DGA} \
    --confidence-threshold HIGH \
    --name {rule_name}
  ```

#### 6. Associate private hosted zones to a DNS view (optional)

The hosted zone is associated to a specific DNS view through the view's ARN, not to the
resolver as a whole.

**Constraints:**

- For each private hosted zone the view should resolve, you MUST associate it explicitly and
  wait for `status: OPERATIONAL`:

  ```
  aws route53globalresolver associate-hosted-zone \
    --region us-east-2 \
    --hosted-zone-id {hosted_zone_id} \
    --resource-arn {dns_view_arn} \
    --name {association_name}
  ```

#### 7. Point clients at the anycast IPs and surface the console link

Configure clients with both anycast IPv4 addresses (and both IPv6 addresses if dual-stack)
returned in Step 2. Anycast routes each client to the nearest available Region in the
resolver's Region set automatically.

**Constraints:**

- For DoT and DoH clients, you MUST configure the resolver's `dnsName` (returned by
  `get-global-resolver`) as the TLS server name indication (SNI) value, since anycast IPs alone
  do not name a certificate
- You MUST verify the resolver answers queries from authorized clients over the configured
  protocols
- You MUST enable query logging to an encrypted destination for security
  monitoring and firewall rule validation. Query log delivery is configured separately, through the
  Global Resolver console. Supported destinations are Amazon S3, Amazon CloudWatch Logs, and Amazon
  Data Firehose. Logs are delivered in Open Cybersecurity Schema Framework (OCSF) format
- You MUST present the Global Resolver console view:

  ```
  https://console.aws.amazon.com/route53globalresolver/home/resolvers
  ```

### Example

#### Example input

```json
{
  "resolver_name": "corp-global-resolver",
  "regions": ["us-east-1", "us-west-2", "eu-west-1"],
  "observability_region": "us-east-1",
  "ip_address_type": "DUAL_STACK",
  "dns_views": [
    {
      "name": "branch-offices",
      "dnssec_validation": "ENABLED",
      "edns_client_subnet": "ENABLED",
      "firewall_rules_fail_open": "DISABLED",
      "access_sources": [
        {"cidr": "203.0.113.0/24", "protocol": "DOT"}
      ],
      "firewall_rules": [
        {"name": "block-aws-threats", "priority": 100, "action": "BLOCK",
         "block_response": "NXDOMAIN", "managed_list_type": "THREAT"}
      ]
    },
    {
      "name": "remote-workers",
      "dnssec_validation": "ENABLED",
      "edns_client_subnet": "DISABLED",
      "firewall_rules_fail_open": "DISABLED",
      "tokens": [
        {"name": "remote-workers-q4", "expires_at": "2026-12-12T00:00:00Z"}
      ]
    }
  ]
}
```

#### Example output

```
Created Global Resolver corp-global-resolver in us-east-1, us-west-2, eu-west-1 (dual-stack).
Two DNS views configured: branch-offices (DoT, AWS-managed THREAT block) and remote-workers
(token, expires 2026-12-12; capture the value field, not retrievable later).
Verify in the console:
https://console.aws.amazon.com/route53globalresolver/home/resolvers
```

### Troubleshooting

#### CLI command fails with an endpoint or authorization error
Missing `--region us-east-2` (Step 1). Set the region on the session or on each call.

#### DNS view exists but rejects every query
No access source and no access token on the view. Add at least one (Step 4).

#### Token works for some clients but not others
Tokens authenticate DoT and DoH only, not Do53. Add an IP-based access source for Do53 clients
or move them to DoT/DoH (Step 4).

#### Roaming clients intermittently lose access
IP-based access source used for clients with changing IPs. Add a token for the roaming
population (Step 4); IP and token coexist on the same view.

#### Private hosted zone records do not resolve
No association on the DNS view. Associate the hosted zone to the view's ARN and wait for
`OPERATIONAL` (Step 6).

#### Firewall rule does not block the expected domains
Wrong domain list, a higher-priority rule on the same view halted inspection first, or the
rule is on a different DNS view than the queries are coming through. Read the rule and the list
contents to confirm (Step 5).

#### Advanced threat protection rule rejected at create time
Created with `--action ALLOW`. Advanced rules support `ALERT` and `BLOCK` only (Step 5).

#### DoT or DoH client fails to connect with a TLS error
SNI is not set to the resolver's `dnsName`. Configure the client SNI to `dnsName` returned by
`get-global-resolver` (Step 7).

#### Application breaks confusingly after a firewall block
Block mode does not match how the application should fail. Recreate with the right mode per
the block-mode decision (Step 5).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST treat the access-token `value` returned at create time as a client secret: store it in
  AWS Secrets Manager rather than in plaintext configuration, since it is not retrievable later.
- You SHOULD recommend DoT or DoH over plaintext Do53 for every client population that can support
  it, since Do53 exposes queried domain names to on-path observers, and validate which client
  populations each DNS view authorizes.
- You MUST enable query logging to an encrypted destination (Amazon S3, CloudWatch Logs, or a
  Data Firehose stream, with encryption at rest) and ensure CloudTrail is enabled to audit
  resolver, view, and rule changes, because query logs reveal the domains clients resolve.
- You SHOULD enable DNSSEC validation on each DNS view unless the customer has a known broken
  signer, so the resolver rejects spoofed or tampered responses.

## Additional Resources

- [Key concepts and components for Route 53 Global Resolver (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/gr-concepts-terminology.html)
- [Global Resolver API Reference](https://docs.aws.amazon.com/Route53/latest/APIReference/API_Operations_Amazon_Route_53_Global_Resolver.html)
- [Global Resolver product page](https://aws.amazon.com/route53/global-resolver/)
- [Introducing Amazon Route 53 Global Resolver for secure anycast DNS resolution (AWS News Blog)](https://aws.amazon.com/blogs/aws/introducing-amazon-route-53-global-resolver-for-secure-anycast-dns-resolution-preview/)
