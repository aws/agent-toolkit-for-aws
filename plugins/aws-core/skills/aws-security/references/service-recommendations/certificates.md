# Certificate and private PKI decisions

Use the parent skill’s focused-recommendation rules. Load the [full workflow](../service-recommendations.md) only for collection, broad review or cost reduction.
The [certificate checks](enablement-checks.md) own collection and adequate-monitoring semantics.
Use issuance, chain, policy and client metadata only; no private-key retrieval or issuance.

## Renewal and monitoring

| Evidence | Recommendation consequence / overlap trap |
|---|---|
| Imported, ACM-requested or direct Private CA issuance, renewal eligibility/status and deployed certificate | Judge renewal responsibility, observed renewal and deployment independently. ACM does not renew imports; PRIVATE type alone does not prove renewal failure. Direct CA issuance needs its own renewal/monitoring ownership and ACM/event applicability check. |
| Fleet completeness, chosen CloudWatch/EventBridge/issuer-side checks, delivery and required lead time | Adequate alternative monitoring passes; do not prescribe duplicate EventBridge routing. Unknown delivery or scope stays UNKNOWN, while a demonstrated unmet need supports closing that specific gap. |
| DNS validation ownership and persistence, SAN/domain changes and application owner | Compare validation continuity with renewal needs; a validation setting alone does not prove future DNS ownership or successful deployment. Verify current change semantics before proposing replacement/cutover. |

For example, effective issuer-side checks covering directly issued certificates meet monitoring
needs without proving those certificates emit applicable ACM events. Retain the functioning
method; investigate renewal ownership separately if missing. ACM is always available, not
an enablement gap. Source: [certificate considerations and monitoring patterns][CE].

## Trust domains and root isolation

Compare hierarchy and issuing policy with assurance and trust domains. Require concrete root
isolation, issuer permissions and chain/end-entity usage evidence: the root must not issue
end-entity certificates. A CA list or a particular hierarchy depth does not prove isolation.
No universal numerical depth gate applies; missing evidence is UNKNOWN and requirements-only
design review is ADVISORY without a gap priority.

If chains show direct root-issued workload certificates, address that demonstrated issuing
boundary rather than adding an arbitrary intermediate count. If the root's issuing use is
unknown, request chain/permission metadata rather than asserting compromise or isolation.
Source: [Private CA hierarchy and root-use guidance][CE].

## Sharing and client compatibility

| Relevant requirement and metadata | Decision |
|---|---|
| Cross-account shares, allowed principals, IAM/resource policies and admin/issuer separation | Evaluate sharing and issuance authorization separately. A share alone does not prove that only intended issuers can act; include regional trust and key-custody ownership. |
| Issuance policy, chain validity, templates, permitted names/usages and client algorithms | Compare client and policy constraints before recommending templates or validity. Verify current algorithm/validity limits; do not inherit universal periods from guide examples. |
| CRL/OCSP configuration, client reachability/caching and rotation dependencies | Configured revocation does not prove clients can consume it. Match failure/recovery behavior with the required assurance before proposing retirement or rotation. |
| Kubernetes, SCEP/device or directory integration and trust distribution | Select connectors by actual identity/enrollment need and renewal owner. Connector presence alone cannot establish client trust or renewal coverage. |
| Export capability, key-access/grant metadata and pinning behavior | Review issuer-specific exportability and rollover compatibility without keys. Do not assume a universal ACM export ban. |

Sources: [certificate sharing, revocation, connectors and access guidance][CE].

## Disclosure and source limits

For sensitive hostnames in public certificates, compare CT preference and issuance/renewal
phase with relying-client trust. CT opt-out cannot erase already-published data and should
not be recommended without client-trust review. Current certificate dates, validity policies,
feature regions/quotas, exportability and pricing need current authoritative evidence.
Pinned guide recipes (including imported-renewal status automation) are implementation patterns,
not proof that the customer's issuer implements them. Source: [certificate guidance][CE].

[CE]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/certificate-services/index.md
