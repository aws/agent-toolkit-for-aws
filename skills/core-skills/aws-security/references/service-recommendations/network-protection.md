# Network protection selection

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
Start from required flows and trust boundaries, not a checklist of absent services.

## Flow boundaries and endpoints

| Evidence | Decision / false-gap trap |
|---|---|
| Required source/destination/protocol and union of attached SG ingress/egress, including IPv6 | Evaluate aggregate permissions per interface. A restrictive individual group does not negate another group's allow. SG references describe topology-dependent membership, not authenticated workload identity. |
| Ordered NACL ingress/egress and return paths | Evaluate stateless subnet-boundary behavior against required traffic. An allow-all NACL alone is not a gap; do not credit it with same-subnet, Resolver-DNS or IMDS protection. |
| Endpoint routes, private DNS, policy and permitted service/resource scope | Private connectivity does not restrict destinations by itself. Recommend a policy/path review for a demonstrated exfiltration requirement, rather than assuming endpoints prove that requirement met. |
| Protocol, application logic and existing protection at the exposed boundary | Choose HTTP filtering, routed inspection or DNS controls by the traffic each must handle. One layer's presence does not establish the others' required coverage. |

For example, two attached SGs whose combined rules exceed the required flow set warrant
aggregate rule review; adding another restrictive SG would not resolve that mismatch.
Sources: [network fundamentals][NF], [SG rule semantics](https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html),
[NACL semantics](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html).

## Segmentation and identity

Compare intended account/VPC/tier trust zones with TGW/Cloud WAN connectivity and bypass
paths. Connectivity and inspection are separate: a segment label is not evidence that
lateral traffic crosses the intended control.

For VPC Lattice identity boundaries, inspect AWS_IAM authType and policy state at both service
and service network, relevant caller policies, explicit denies and request signing. Policy
attachment alone is insufficient; policies may explicitly allow anonymous requests and do
not create network connectivity. Missing signing evidence can leave identity enforcement
UNKNOWN even when a policy exists.

Do not generalize service-auth guidance to all TCP resources or passthrough paths. That
claim remains unresolved in the reviewed evidence; require topology-specific current
documentation before crediting equivalent authorization. Sources: [segmentation][SG],
[Lattice auth policies](https://docs.aws.amazon.com/vpc-lattice/latest/ug/auth-policies.html),
[resource configuration](https://docs.aws.amazon.com/vpc-lattice/latest/ug/resource-configuration.html).

## DNS path and enforcement

Compare the actual Resolver path with per-VPC rule-group association, managed/Advanced
settings and delivered query logs. Association alone does not prove the intended lists
are active or queries are blocked. Representative existing query evidence distinguishes
ALLOW, ALERT and BLOCK behavior from the intended policy.

SGs cannot block AmazonProvidedDNS; DNS filtering does not cover hardcoded-IP egress.
A requirement to constrain both domains and direct-IP destinations therefore needs separate
path evidence. Do not credit a DNS policy with complete egress enforcement. The existing
fail-open observation remains in [enablement checks](references/service-recommendations/enablement-checks.md); apply it only
under its scoped semantics. Source: [DNS Firewall query logging and policy guidance][DN].

## DDoS and fleet policy

Shield Standard is automatic network/transport protection, never a disabled-service gap.
Its presence is not an application-abuse solution or proof of uniform endpoint resilience.
Compare downtime impact, eligible resource scope and current subscription/bundling terms
before recommending Shield Advanced. Verified protection at one resource does not establish
coverage of all revenue-critical ingress paths.

For Firewall Manager, establish a distributed policy-management need and organization/Config
prerequisites; compare intended targets with applied healthy protection. A central single
firewall and many independently managed deployments have different rollout needs. Policy
existence alone does not establish successful enforcement. If application customization or
ownership is the issue, resolve that before proposing another fleet policy.
Sources: [network fundamentals][NF], [Shield Standard](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-standard-summary.html).

[NF]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/firewall-overview/fundamentals/docs/index.md
[SG]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/firewall-overview/segmentation/docs/index.md
[DN]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/dns-firewall/index.md
