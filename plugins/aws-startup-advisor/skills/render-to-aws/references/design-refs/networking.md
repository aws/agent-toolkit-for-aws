# Networking and identity selectors

## Public ingress

For a public HTTP service, select `Application Load Balancer` when the chosen compute target requires explicit ingress; traditional Elastic Beanstalk may consume ingress as part of its environment. Select `CloudFront` in front of static S3 deterministically and in front of APIs only for established caching, edge, WAF, or global-user requirements. Reject NLB unless protocol evidence requires layer 4 behavior.

## Private ingress

Candidate set: `AWS Cloud Map or ECS Service Connect`, `internal Application Load Balancer`, `internal Network Load Balancer`. Select direct discovery for private HTTP service-to-service calls by default. Select internal ALB only for required HTTP load balancing, path/host routing, health behavior, or multi-client access. Select internal NLB only for required TCP/UDP/TLS pass-through or static addressing. Public ALB/NLB is not a candidate for a private-only Render service.

Missing caller, protocol, port, or load-balancing facts return to Clarify when they can change the winner. Preserve project/environment scope and private DNS evidence; never universalize the one observed Render hostname or port.

## Identity-aware access

When source access protection exists, select ALB OIDC authentication with the customer's existing native OIDC provider when compatible. Select Amazon Cognito only when the user explicitly wants it or no retained provider can meet requirements. Record the rejected identity candidate and reason.

## Isolation and egress

Map project/environment boundaries to an explicit VPC/account/environment strategy. Compliance, residency, and blast-radius requirements decide account separation; no-compliance evidence may select shared-account separate VPCs/stacks. Private subnet egress uses NAT only when outbound internet is required; otherwise prefer endpoints/direct private connectivity. A VPC is no-direct-charge but induced NAT/endpoints/data transfer receive separate estimate lines.

## Domains and TLS

ACM is selected for supported custom domains. Route 53 is selected only when AWS will own DNS; otherwise retain the current DNS provider and emit required records/cutover steps. Every domain maps to its serving CloudFront/ALB endpoint and preserves validation, TTL lowering, overlap, rollback, and source-domain retention.
