---
name: networkfirewall
description: >
  Configures AWS Network Firewall, the managed stateful VPC firewall: deploying a firewall and
  routing traffic through its endpoints; centralizing inspection for many VPCs with a transit
  gateway-attached firewall that keeps stateful flows symmetric across Availability Zones;
  filtering outbound traffic by domain name; logging and
  rule tuning; TLS inspection with ACM certificates; writing Suricata rules; managing rules as
  CloudFormation/IaC; blocking an indicator mid-incident; migrating off a third-party firewall appliance;
  and diagnosing dropped traffic. Applicable when the user wants to inspect or
  filter VPC traffic at Layer 3 and 4, allow or block outbound domains, manage firewall rules as
  IaC, or decrypt TLS. Not applicable for AWS WAF Layer 7 rules (waf skill), Gateway Load
  Balancer appliance inspection (gatewayloadbalancer skill), Route 53 Resolver DNS Firewall (route53
  skill), or transit gateway route tables and appliance-mode attachments (transitgateway skill).
version: 1
---

# Network Firewall

## Overview

Domain expertise for configuring AWS Network Firewall, the managed stateful firewall and intrusion
prevention service that filters traffic at the perimeter of a VPC using the Suricata inspection
engine. Covers placing a firewall in the traffic path and routing traffic through its endpoints,
centralizing inspection across VPCs with a transit gateway-attached firewall, filtering outbound
traffic by domain name, logging and rule tuning, TLS inspection of encrypted traffic, and
diagnosing why traffic is dropped, passed, or unmatched.

This skill is a router. Each customer task maps to a reference file under `references/`. Read the
matching reference in full before acting, then follow its constraints and steps. The reference
files are self-contained: each carries its own decision tables, constraints, procedure, and
troubleshooting.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Network Firewall is regional; pass `--region`
matching the firewall's Region on every `aws network-firewall` command. Firewall creation,
deletion, and several operations are asynchronous: poll the resource until it reaches the expected
state before depending on it.

## Which Network Firewall task do you need?

| Goal | Reference |
| --- | --- |
| Place a firewall in the path and route VPC traffic through its endpoints | [deploying a firewall and routing traffic through it](references/deploying-a-firewall-and-routing-traffic-through-it.md) |
| Inspect traffic across many VPCs from one place using a transit gateway-attached firewall | [centralizing inspection with a transit gateway-attached firewall](references/centralizing-inspection-with-a-transit-gateway-attached-firewall.md) |
| Allow or block outbound connections by destination domain name | [filtering outbound traffic by domain name](references/filtering-outbound-traffic-by-domain-name.md) |
| Turn on alert, flow, and TLS logging and tune rules from what they show | [enabling firewall logging and tuning rules](references/enabling-firewall-logging-and-tuning-rules.md) |
| Decrypt and inspect TLS traffic with ACM certificates | [inspecting encrypted traffic with TLS inspection](references/inspecting-encrypted-traffic-with-tls-inspection.md) |
| Write custom stateful Suricata rules and fix rules that do not match | [writing and troubleshooting stateful Suricata rules](references/writing-and-troubleshooting-stateful-suricata-rules.md) |
| Block a specific indicator immediately during an active security incident | [responding to an active security incident](references/responding-to-an-active-security-incident.md) |
| Manage the firewall, policy, and rules in CloudFormation or the CDK | [managing firewall rules as IaC](references/managing-firewall-rules-as-infrastructure-as-code.md) |
| Replace a third-party firewall appliance with Network Firewall | [migrating from a third-party firewall appliance](references/migrating-from-a-third-party-firewall.md) |
| Find out why traffic is dropped, passed, or not matching a rule | [diagnosing dropped or unmatched traffic](references/diagnosing-dropped-or-unmatched-traffic.md) |

## Routing notes

- **Deploy before rules.** A firewall does nothing until VPC route tables redirect traffic to its
  endpoints, and nothing reports an error when the routing is missing. Route to the deploying
  reference first when the firewall is new or traffic is not reaching it, before assuming a rule
  problem.
- **Transit gateway-attached vs inspection VPC.** The centralizing reference uses the native
  transit gateway-attached firewall, which removes the hand-built inspection VPC and its route
  tables. Route there for multi-VPC or multi-account inspection rather than building an inspection
  VPC by hand.
- **Domain filtering matches the handshake, not the IP.** The domain filtering reference matches on
  the TLS SNI and HTTP host header, not on a DNS lookup, and an allow list silently drops
  non-matching traffic of the same protocol. Route there for outbound domain control, and reach for
  TLS inspection when the customer needs the full URL path rather than the domain.
- **TLS inspection changes what rules match.** The TLS inspection reference is the precondition for
  any rule that needs to act on decrypted payload. After TLS termination the decrypted traffic is
  plain HTTP to the stateful engine, so port-443 and `tls` rules stop matching. Route there before
  the customer writes rules against encrypted traffic.
- **Diagnose by symptom, not by guess.** The diagnosing reference reads the endpoint status message
  (error vs non-recoverable failure), tests routing symmetry, and checks `HOME_NET`, evaluation
  order, and rule layer before any rewrite. Route there for "traffic is dropped," "traffic passes
  when it should not," or "my rule does not match." When the symptom is "traffic dropped with no
  alert log at all," suspect post-quantum ClientHello fragmentation, covered in the diagnosing and
  logging references.
- **Incident now vs configuration.** The responding reference is for an active incident on an
  already-deployed firewall: block one indicator immediately, confirm it, and back it out. Route
  there for "I am under attack, block this now," not through the deploying or rule-authoring
  references, which are slower configuration workflows.
- **Rule authoring vs domain filtering.** The writing-Suricata reference covers custom stateful
  rules (flow keywords, rule order, Suricata engine constraints). Route there for IPS or IDS rule
  authoring; route to the domain filtering reference when the customer only needs to allow or block
  domains.
- **IaC vs console changes.** The managing-as-code reference is for
  CloudFormation or CDK ownership, where immutable properties (capacity, rule order) make the wrong
  structure a replacement. Route there when the customer manages the firewall in templates.
- **Migration vs first-time setup.** The migrating reference is for replacing a third-party firewall
  appliance with a live rule set and traffic path. Route there for "move off Palo Alto or FortiGate," not the
  deploying reference, which assumes a greenfield firewall.

## Security Considerations

This skill manages network perimeter security, so a misconfiguration weakens the security posture
of every VPC behind the firewall. Carry these into each task:

- **Default-drop posture.** You MUST configure a stateful default action of drop (an allow list of
  permitted traffic) rather than default-allow, so traffic that no rule matches is blocked rather
  than passed uninspected. For a network firewall a fail-closed default is a fundamental security
  control, not an option, and an overly permissive rule set degrades the firewall to a passthrough.
- **No silent inspection gaps.** You MUST confirm traffic is actually routed through the firewall
  endpoints and forwarded to the stateful engine; misconfigured route tables or a stateless
  default action other than `aws:forward_to_sfe` leave traffic uninspected with no error.
- **Ephemeral, least-privilege credentials.** You MUST use ephemeral, least-privilege credentials (a
  time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources
  each operator needs (e.g., `network-firewall:UpdateRuleGroup`, `network-firewall:DescribeFirewall`),
  never long-lived access keys or broad administrative access, since these permissions can change what
  traffic is allowed.
- **Encrypt logs and firewall data at rest.** You MUST encrypt every destination that receives
  firewall logs (alert, flow, or TLS), using a customer-managed AWS KMS key on Amazon CloudWatch Logs
  log groups (`aws logs associate-kms-key`), either SSE-S3 or a customer-managed AWS KMS key on
  Amazon S3 buckets, and a customer-managed AWS
  KMS key on Amazon Data Firehose delivery streams, because these logs expose
  sensitive network metadata (source and destination IPs, domain names, and SNI values). You SHOULD
  also encrypt the firewall's data at rest with a customer-managed AWS KMS key.
- **Scope log-destination resource policies with condition keys.** You SHOULD scope the resource
  policy on each log destination (the Amazon S3 bucket policy, the Amazon CloudWatch Logs resource
  policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn` (the firewall's
  ARN) and `aws:SourceAccount` condition keys, so only this firewall in the expected account can
  write to the destination and another account or service cannot (confused-deputy prevention).
- **Record API changes with CloudTrail.** You SHOULD enable AWS CloudTrail on the account so
  firewall, policy, rule group, and logging-configuration API changes are recorded for audit and
  incident review.
- **Alarm on critical firewall events.** You SHOULD configure CloudWatch alarms to alert on critical
  firewall events (endpoint failures, policy changes, capacity warnings) so issues are detected and
  escalated promptly. You MUST encrypt any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key and restrict alarm notification recipients to authorized operations and
  security personnel, since alarm messages can expose sensitive firewall metadata (endpoint status,
  traffic patterns, and capacity).
- **Per-task detail.** Each reference carries its own Security Considerations for its workflow;
  read the matching reference before acting.

## Additional Resources

- [What is AWS Network Firewall? (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html)
- [How AWS Network Firewall works (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/how-it-works.html)
- [AWS Network Firewall pricing](https://aws.amazon.com/network-firewall/pricing/)
