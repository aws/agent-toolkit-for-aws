# Network Firewall suitability and enforcement

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
Absence alone is not a gap. The [existing checks](references/service-recommendations/enablement-checks.md) own reads and validated
negative states; use supplied topology/ruleset excerpts for decisions those reads cannot resolve.

## Routed inspection and policy

| Required evidence | Recommendation consequence / trap |
|---|---|
| Inspection intent, deployment mode and both traffic directions through AZ/endpoints | Evaluate inspection-VPC, native TGW, multi-endpoint or Cloud WAN paths against that mode's current constraints. Firewall presence or endpoint count alone does not prove routing; identify bypass paths before claiming enforcement. |
| Routed IPv4/IPv6 ranges, HOME_NET/EXTERNAL_NET and policy/group inheritance | Recommend scope correction only for mismatched intended traffic. Blanket RFC1918 substitutions can misclassify east-west traffic rather than fix it. |
| Stateless forwarding, broad pass actions, intended order and rule dependencies | A pass can bypass later inspection. Compare actual termination with intent before choosing strict order; no universal strategy change follows from firewall presence. |
| Default actions, handshake/fragment behavior and observed final verdicts | Assess application-aware versus custom defaults under the compatible strategy. Do not pair drop/alert defaults universally or infer blocking from strict order plus logs. |
| Allowed domains, wildcard/tenant scope and content threat requirement | Domain/SNI allowlisting does not establish server or content identity. If identity/content inspection is needed, evaluate the separate TLS decision rather than overstating the allowlist. |
| Managed-group threat relevance, capacity, versions and deployment tags | Select groups for relevant threats and growth limits; broad inclusion or zero hits is not proof of value or redundancy. Filtered subsets need version/synchronization ownership. |

For example, correct policy configuration with an unexamined return path leaves enforcement
UNKNOWN. A demonstrated bypass of required inspection supports path remediation advice;
unknown topology does not earn a High gap priority. Sources: [deployment][ND], [policy][NP].

## TLS eligibility and trust

Require a decrypted-content need and data-handling permission before recommending inspection.
Compare inbound certificate/outbound CA metadata, client trust distribution and a narrow scope
with the actual clients and traffic; never request private keys. Pinning, mTLS, QUIC, ECH,
STARTTLS and HTTP/2 WebSocket use require compatibility review, not universal enablement.

The reviewed considerations warn that non-TLS, missing-SNI or mismatched-SNI traffic in scope
can drop and existing flows can be disrupted. Recommend a representative-client validation
plan before broadening scope. Review configured revoked/unknown actions rather than assuming
universal rejection. After decryption, evaluate inner-protocol rules; TLS.SNI is an exception
to the changed TLS-keyword behavior.

TLS/endpoint-association compatibility remains unresolved, as do the guide's exact
per-leg idle timers. Do not turn either into a universal incompatibility or restart
rule. For stream exceptions, compare active connections and NAT/backend idle behavior with
the application's recovery needs; leave unsupported compatibility claims UNKNOWN.
Sources: [pinned TLS guide][NT], [current considerations](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-considerations.html),
[certificate requirements](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-certificate-requirements.html).

## Proxy suitability

Check the proxy feature's preview status in the Network Firewall documentation; its absence is not a missing-proxy finding.
Confirm current availability and supported features for the proposed use. Compare explicit
client proxy configuration, endpoint reachability and bypass paths; a NAT route alone does
not apply proxy inspection. If clients cannot use the proposed proxy path, do not credit it
with their egress coverage. Source: [reviewed AWS Proxy announcement](https://aws.amazon.com/blogs/networking-and-content-delivery/reintroducing-network-firewall-proxy-for-secure-egress-connectivity/)
and [deployment context][ND].

## Verdicts and operational evidence

Interpret delivered ALERT/FLOW/TLS records with direction/flow identifiers, observation window
and flow-end timing. Alert action and final traffic verdict are different evidence; configured
destinations do not prove delivery. Zero rule hits may reflect bypass, a pass rule, insufficient
observation or absent traffic, so do not recommend removing a rule on that basis alone.

Already-produced traffic/domain reports can identify candidate destinations, not establish
that every observed destination is required or safe. Relate logging coverage to incident
history needs before cost advice. Architecture savings need actual payer/region/NAT/TGW paths,
endpoint utilization and current terms, not a copied endpoint ratio. Sources: [policy][NP],
[pinned logging and monitoring](https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/network-firewall/logging-and-monitoring/docs/index.md).

[ND]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/network-firewall/deployment-architecture/docs/index.md
[NP]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/network-firewall/firewall-policy-configuration/docs/index.md
[NT]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/network-firewall/tls-inspection/docs/index.md
