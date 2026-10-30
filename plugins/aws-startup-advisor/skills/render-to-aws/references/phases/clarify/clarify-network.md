---
_fragment: network
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify network requirements

Resolve public and private callers, protocol, bind port, health routing, private DNS, client count, load-balancing need, outbound internet access, custom-domain ownership, DNS authority, TLS, identity-aware access, environment isolation, residency, and cutover control.

A private service stays private. Ask whether direct Cloud Map or Service Connect discovery is sufficient, or whether required load balancing, health routing, protocol behavior, or multi-client ingress justifies an internal ALB. Never add a public load balancer by default. If platform access protection exists, ask whether to preserve an existing native OIDC provider; do not default to creating Cognito.

For custom domains, distinguish ACM certificate issuance from optional Route 53 ownership. Only when the inventory contains a public HTTPS web service, ask for the ARN of an already issued ACM certificate in the selected Region; external DNS owners must request the certificate and create its DNS validation records before Generate. Do not ask for a certificate ARN for private-only or non-HTTPS estates. For previews, record DNS, isolation, lifetime, data seeding, and cleanup expectations as delivery behavior.
