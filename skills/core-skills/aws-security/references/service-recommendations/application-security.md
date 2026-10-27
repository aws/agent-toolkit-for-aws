# AWS Security Agent (part of AWS Continuum) application suitability

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
Security Agent suitability is application-specific, not an account-wide enabled state.

Current service documentation names the capability this file covers Continuum for penetration
testing. The pinned guide predates that naming, so accept either form from the user and use
the short form "Security Agent" below. The service's other Continuum capabilities are out of
scope here. `pentesting-with-aws-security-agent` is a skill identifier and stays literal.

## Application fit and scope

Compare the requested assurance with existing code/design/supply-chain review and dynamic
testing. A deployed WAF does not prove the application has been tested; a clean test does
not prove comprehensive security or replacement of those other controls. The suitability
questions below cover the penetration testing path, which is the one carrying target,
reachability and authorization constraints.

Request ownership, exact target domains, the login/access-domain redirect chain, permitted
navigation and destructive/auth-mutation exclusions. For private verification, the reviewed
PRIVATE_VPC guidance requires a private address and exact full target-domain match; a parent
domain is not equivalent. An unresolved ownership or redirect boundary leaves suitability
conditional, not permission to verify domains or launch testing.

Separate application exploitability from production WAF effectiveness. If WAF interaction
would obscure the requested test, hand off the controlled-environment/scope decision with a
removal owner and protected-path revalidation requirement; do not add an allow rule here.
Sources: [Security Agent positioning, scope and WAF interaction][SA],
[domain verification](https://docs.aws.amazon.com/securityagent/latest/userguide/enable-test-domain.html).

## Private connectivity

| Evidence to request | Suitability consequence / trap |
|---|---|
| Selected agent-side VPC/subnets/SGs, private DNS and outbound permissions | Confirm the intended path can reach the exact target. A private connection object or generic service role does not prove reachability. |
| Hybrid/TGW target route, return path and service/dependency paths | Evaluate the whole connection, including dependencies. Do not expose a private application publicly to make testing easier. |
| Existing verification state and runtime outcome if supplied | Pre-run UNREACHABLE can precede runtime verification; it is neither success nor conclusive failure. Without runtime evidence, report the unresolved path instead of calling the application untestable or secure. |

The guide's NAT exemption conflicts with the setup devguide. Resolve actual target
and dependency routes with the network owner; neither universal NAT installation nor removal
follows from that conflict. Older models missing private operations or PRIVATE_VPC demonstrate
model drift, not feature absence. Current topology-specific evidence is still required.
Sources: [pinned private application guidance][SA], [setup devguide](https://docs.aws.amazon.com/securityagent/latest/userguide/enable-penetration-test.html).

## Identity and data readiness

Separate operator/admin permissions, the application's agent-space boundary and service-role
trust/access for the intended integrations. A role existing does not prove least privilege
or sufficient access. For authenticated testing, compare realistic user/admin/service roles
with login success steps, MFA and redirect requirements. Request credential-vendor metadata
only (for example the configured vendor type), never credentials, secret values or payloads.

Confirm current region/capability, processing/storage, encryption, activity-log retention and
budget/task-hour constraints for the specific assessment. Do not hardcode preview/GA labels,
pricing or quotas. Missing facts leave a conditional AppSec/network/IAM-owner decision;
use an installed specialist only when suitable under the workflow's handoff rules.
Source: [Security Agent access, authentication and data-handling guidance][SA].

## Interpreting existing results

Compare supplied source/API/architecture context, selected risks and tested paths with the
business question. Non-deterministic runs and cumulative findings do not prove exhaustive
coverage; a clean result with unknown authenticated-path coverage leaves that assurance
unresolved. Preserve verified findings and their severity. The handoff should identify the
remaining scope or validation decision, not automatically initiate another test, export,
feedback submission or remediation. Source: [Security Agent context and result guidance][SA].

[SA]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/security-agent/index.md
