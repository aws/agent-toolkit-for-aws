# Networking Services Design Rubric

**Applies to:** VPC, Firewall, Load Balancing, DNS, Cloud Interconnect, Cloud Armor

**Quick lookup (no rubric):** Check `fast-path.md` first (VPC → VPC, Firewall → Security Groups, etc.)

## Eliminators (Hard Blockers)

| GCP Service          | AWS            | Blocker                                                                                                                       |
| -------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Cloud Interconnect   | Direct Connect | Dedicated connection (4-12 weeks setup) → use VPN as temp                                                                     |
| Cloud Load Balancing | ALB            | SSL certificate passthrough → NLB (L4, pass-through)                                                                          |
| Cloud Load Balancing | NLB            | Host/path-based routing required → ALB (L7)                                                                                   |
| Firewall Rules       | Security Group | Ingress on port 22, 3389, or 5900 with source `0.0.0.0/0` or `::/0` → **BLOCKED** — see Administrative Port Safety Rule below |

## Signals (Decision Criteria)

### VPC Network

- Always → AWS VPC (1:1 deterministic)
- Preserve CIDR blocks, subnets, routing tables

### Firewall Rules

- Always → AWS Security Groups (1:1 deterministic)
- Convert direction (ingress/egress) and IP ranges

### Cloud Load Balancing

- **HTTP/HTTPS + hostname/path routing** → ALB (Layer 7)
- **TCP/UDP + high throughput** → NLB (Layer 4)
- **TLS passthrough** → NLB (Layer 4, no termination)
- For internet-facing ALB: terminate TLS on 443 and configure 80 as redirect-only to HTTPS (no direct HTTP forwarding).

### Cloud DNS

- Always → Route 53 (1:1 deterministic)
- Preserve zone name, record types, TTLs

### Cloud Interconnect

- **Dedicated connection** → AWS Direct Connect
- **Temporary/dev connectivity** → AWS Site-to-Site VPN (quicker, lower cost)

### Cloud Armor

- **DDoS protection + WAF rules** → AWS WAF + AWS Shield Standard (Shield Standard is automatic, no extra cost)
- **Rate limiting** → AWS WAF rate-based rules
- **Bot management** → AWS WAF Bot Control
- **IP allowlist/denylist** → AWS WAF IP set rules

## 6-Criteria Rubric

Apply in order:

1. **Eliminators**: Does GCP config require AWS-unsupported features? If yes: switch
2. **Operational Model**: Managed (ALB, Route 53) vs Custom (VPN, custom routing)?
   - Prefer managed
3. **User Preference**: From `preferences.json`: `design_constraints.compliance`?
   - **PCI or HIPAA:** Neither framework mandates Direct Connect. **Bias toward documented private connectivity** between sites and AWS (e.g. **AWS Direct Connect** or **Site-to-Site VPN** with encryption, monitoring, and change control) — choose with your **QSA / BAA / security team**; many compliant designs use VPN-only or no hybrid link when all workloads stay in AWS.
   - **FedRAMP:** GovCloud and federal boundary requirements dominate; **private connectivity** is often part of the approved architecture — still **confirm with your authorizing official / security team**, not this advisor alone.
   - If `compliance` includes `"ccpa"` (CCPA / CPRA) → VPN or Direct Connect both acceptable; prioritize **documented data paths**, retention controls, and logging for consumer privacy workflows — not a forced Direct Connect gate.
   - If none of the above: VPN or public-internet paths are commonly acceptable when encrypted and documented.
4. **Feature Parity**: Does GCP config require AWS-unsupported features?
   - Example: GCP policy-based routing → Custom route table rules (AWS does this)
5. **Cluster Context**: Are other resources in cluster using specific load balancers? Match
6. **Simplicity**: Fewer resources = higher score

## Examples

### Example 1: VPC Network

- GCP: `google_compute_network` (auto_create_subnetworks=false, routing_mode=REGIONAL)
- Signals: Explicit subnets, regional routing
- Criterion 1 (Eliminators): PASS
- → **AWS: VPC (us-east-1 region)**
- Confidence: `deterministic`

### Example 2: Firewall Rules

- GCP: `google_compute_firewall` (allow=[tcp:443], source_ranges=[0.0.0.0/0])
- Signals: HTTPS ingress, public
- → **AWS: Security Group (ingress rule: 443/tcp from 0.0.0.0/0)**
- Confidence: `deterministic`

### Example 3: Cloud Load Balancing (HTTP + path-based)

- GCP: `google_compute_forwarding_rule` + `google_compute_backend_service` (path_matcher=["/api/*" → api-backend])
- Signals: Path-based routing, HTTP/HTTPS
- Criterion 1 (Eliminators): PASS
- Criterion 2 (Operational Model): ALB (managed, L7)
- → **AWS: ALB with target groups + listener rules (path-based)**
- Confidence: `inferred`

### Example 4: Cloud DNS Zone

- GCP: `google_dns_managed_zone` (dns_name="example.com.")
- Signals: Public DNS zone
- → **AWS: Route 53 Hosted Zone (example.com)**
- Confidence: `deterministic`

## Output Schema

```json
{
  "gcp_type": "google_compute_forwarding_rule",
  "gcp_address": "global-https-lb",
  "gcp_config": {
    "load_balancing_scheme": "EXTERNAL",
    "protocol": "HTTPS"
  },
  "aws_service": "Application Load Balancer",
  "aws_config": {
    "load_balancer_type": "application",
    "scheme": "internet-facing",
    "listener": {
      "protocol": "HTTPS",
      "port": 443
    },
    "region": "us-east-1"
  },
  "confidence": "inferred",
  "rationale": "Rubric: GCP global HTTPS LB → AWS ALB (L7, host/path routing)"
}
```
