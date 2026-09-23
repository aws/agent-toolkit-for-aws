# Networking

Pass-2 rubric for every networking type `index.md` routes here. Loaded only when the
inventory contains one.

**Outcome is `confidence: inferred`.** `measured` does not apply — none of these
decisions is backed by utilization data. Never `deterministic`: that tier belongs to
`fast-path-services.json`, and every row here depends on a property of the resource or
of the workload behind it.

Four of Azure's networking primitives are already fast-path rows (VNet, subnet, NSG, DNS
zone) because they are architecture-invariant. The six types below are not, for one
recurring reason: **AWS splits or multiplies what Azure presents as one resource.**

## 1. Eliminators — hard technical blockers

| Candidate                | Eliminated when                                                                                                                                                             |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ALB**                  | the listener carries **non-HTTP traffic** — raw TCP, UDP, or TLS passthrough without termination. ALB is HTTP/HTTPS only, and this is a protocol boundary, not a preference |
| **ALB**                  | the workload needs a **static IP** per listener. ALB's addresses are DNS-resolved and change; NLB supports an Elastic IP per subnet                                         |
| **NLB**                  | routing decisions depend on **path, host header, HTTP method, or query string**. NLB is layer 4 and cannot see any of it                                                    |
| **NLB**                  | **AWS WAF** must inspect the traffic. WAF attaches to ALB, CloudFront, API Gateway and AppSync — never to an NLB                                                            |
| **CloudFront**           | the origin speaks a **non-HTTP protocol**                                                                                                                                   |
| **API Gateway HTTP API** | the source uses **request or response transformation**, usage plans with API keys, or WAF on the API itself. Those are REST API features                                    |
| **API Gateway**          | the source runs a **self-hosted APIM gateway** in a datacentre or another cloud. There is no managed equivalent; this is a finding, not a mapping                           |

## 2. The six criteria, in order, first match wins

Apply in sequence, stop at the first that fires.

### 2.1 Eliminators

Section 1. Whatever survives is the candidate set.

### 2.2 Operational model

| Source                                                                            | Target                                                         | Why                                                                                                                                                                                     |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Network/loadBalancers`                                                 | **NLB**                                                        | Azure Load Balancer is **layer 4 only**. It has no path routing, no host rules, no header inspection, so NLB is the like-for-like. ALB is in the candidate set only for the case in 2.4 |
| `Microsoft.Network/applicationGateways`, SKU `Standard_v2`                        | **ALB**                                                        | App Gateway is Azure's layer-7 balancer. ALB is the direct counterpart                                                                                                                  |
| `Microsoft.Network/applicationGateways`, SKU `WAF_v2`                             | **ALB + AWS WAF**                                              | The WAF tier is not a bigger gateway, it is a different product surface. Dropping the WAF silently removes a control the customer is paying for and may be attesting to                 |
| `Microsoft.Network/natGateways`                                                   | **NAT Gateway**, one **per availability zone**                 | See § 3. This is the row's whole reason for existing                                                                                                                                    |
| `Microsoft.Cdn/profiles`, `Standard_AzureFrontDoor` / `Premium_AzureFrontDoor`    | **CloudFront**                                                 | Front Door is caching plus global anycast load balancing plus (Premium) WAF. CloudFront covers caching and anycast; the WAF half needs AWS WAF attached                                 |
| `Microsoft.Cdn/profiles`, `Standard_Microsoft` / classic Verizon or Akamai SKUs   | **CloudFront**                                                 | Classic CDN is caching only, so the mapping is smaller than it looks — no load balancing to carry over                                                                                  |
| `Microsoft.Network/frontDoors` (deprecated classic)                               | **CloudFront**, plus **AWS WAF** when a WAF policy is attached | Same as above. Flag that the source resource is on Azure's deprecated Front Door surface, since the customer is likely migrating it either way                                          |
| `Microsoft.ApiManagement/service`, `Consumption` tier                             | **API Gateway HTTP API**                                       | Consumption APIM has no VNet integration and a reduced policy surface, which is the shape HTTP API fits                                                                                 |
| `Microsoft.ApiManagement/service`, `Developer` / `Basic` / `Standard` / `Premium` | **API Gateway REST API**                                       | These tiers have the full policy engine, so REST API is the only tier with comparable request/response handling. See § 4 — the policy layer is a rewrite regardless                     |

### 2.3 User preference

`preferences.json` → `design_constraints` overrides 2.2, per-resource beating global.
A recorded answer always wins over a derived one.

**`global.user_geography`** (Clarify Q-A1b) is a second override, for CDN / DNS only:

- `multi-region` or `global` → emit **CloudFront** (and Route 53 latency or geolocation
  routing) for public HTTP edges even when no `Microsoft.Cdn/*` / Front Door resource
  exists. Record `cdn_required_by_geography` on `aws-design.json`.
- `single-region` or absent → do not invent CloudFront from this row; keep 2.2 mappings
  for real Front Door / CDN resources.

### 2.4 Feature parity

- **An internal Azure Load Balancer fronting HTTP-only backends** may map to an internal
  **ALB** instead of an NLB, when the customer's own routing already happens in the
  application and moving it to the balancer would simplify the target. This is the only
  route to ALB from an Azure LB, it is a deliberate capability _increase_, and the
  rationale must say so — never present it as like-for-like.
- **App Gateway with `url_path_map` or multiple `http_listener` host names** confirms ALB
  rather than NLB. If a path map exists, carry its rules into `aws_config` as ALB listener
  rules; an ALB with one default rule where the source had eight is a silent regression.
- **APIM with a developer portal** has no AWS equivalent. API Gateway has no portal.
  Record it in `warnings[]` and name it in the report; do not map it to anything.
- **Front Door with `Premium` SKU and managed rule sets** carries Microsoft-managed WAF
  rules. AWS WAF's managed rule groups are the counterpart but are not rule-for-rule
  equivalent, so the finding is "re-tune, not re-point".

### 2.5 Cluster context

> **The double-balancer trap. Read this before mapping any load balancer.**
>
> An Elastic Beanstalk load-balanced environment **provisions its own ALB**. An ECS
> service behind a target group needs one too. So if an App Gateway's backend pool
> contains a `Microsoft.Web/sites` whose plan mapped to Elastic Beanstalk, mapping the
> gateway to a _second_ ALB double-counts the balancer — one hourly charge and one LCU
> line that the target architecture does not have.
>
> This is the networking analogue of the App Service Plan fan-in (`compute.md` § 3),
> and it fails the same way: quietly, and only in the estimate.
>
> **Rule.** When a balancer's backend pool resolves — through the `hosted_on` or
> `backend_pool` edge — to a compute target that provisions its own balancer:
>
> 1. Emit **one** entry, for the balancer that the compute target creates.
> 2. Record the Azure balancer as consumed, with one `warnings[]` entry naming the
>    compute resource that absorbed it, and carry its listener rules and WAF association
>    into that target's `aws_config`.
> 3. Do **not** emit a standalone ALB.
>
> The exception is a balancer whose backend pool spans **more than one** compute target,
> or is a VMSS/VM pool. There the balancer is genuinely its own resource: an ASG does not
> create a balancer, so an Azure LB in front of a VMSS maps to a real NLB or ALB.

An App Gateway fronting a static site (`staticSites`, or a storage account with
`static_website`) is absorbed by **CloudFront**, not mapped to an ALB.

### 2.6 Simplicity

Where 2.2–2.5 leave two candidates standing, take the one with fewer moving parts in the
target account. A single ALB with listener rules beats an NLB plus a self-managed proxy
tier that reproduces layer-7 routing.

## 3. Azure NAT Gateway is regional; AWS NAT Gateway is zonal

This is the one row here that changes a number rather than a service name.

A single `Microsoft.Network/natGateways` serves every subnet you associate with it across
the region. AWS NAT Gateway lives **in one subnet in one AZ**. A resilient AWS design
places one per AZ, so **one Azure NAT Gateway becomes N AWS NAT Gateways**, where N is the
AZ count of the target design.

- Read the AZ count from the availability answer in `preferences.json`, not from the
  Azure resource.
- `single-az` → 1 NAT Gateway. `multi-az` → one per AZ.
- State the multiplication in the rationale explicitly. An estimate that prices one NAT
  Gateway for a multi-AZ design is wrong, and it is wrong in the direction that looks good.
- A single shared NAT Gateway across AZs is technically possible and is **not** the
  recommendation: it reintroduces a cross-AZ data path and a zonal failure domain. If the
  customer chooses it for cost, that is a workshop decision, recorded.

## 4. APIM's policy layer is a rewrite, and the mapping does not say so

`Microsoft.ApiManagement/service` maps to API Gateway as a _service_. What does not map
is the policy XML: `<inbound>`, `<outbound>`, `<backend>` and `<on-error>` sections
holding rate limits, JWT validation, header rewriting, caching, mock responses and
`<send-request>` callouts.

API Gateway's counterparts are spread across request validators, usage plans, Lambda
authorizers, mapping templates (REST API only) and WAF — several products rather than one
document. So:

- Map the service, and emit **one** `warnings[]` entry stating that policy definitions
  need reauthoring and are not carried over.
- Where the source's policy set is visible in IaC, name the specific capabilities found
  (rate limiting, JWT validation, IP filtering) so the report is concrete rather than a
  generic caveat.
- Do not attempt to translate policy XML into an AWS artifact. Generate does not emit it.

## 5. "Free on AWS", and the places it is the other way round

Report content, not mappings. State only what is structural; verify every rate against
`references/vendored/pricing/aws-infra-pricing.json` before it reaches a dollar figure.

| Finding                                                                                                                                   | Direction                                                                     |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **VNet peering is billed on both ingress and egress** in Azure. VPC peering **within an AZ is free**; cross-AZ traffic is charged one way | **saving**, and often a large one for chatty multi-VNet estates               |
| **Azure Bastion is an hourly priced resource.** Systems Manager Session Manager has no hourly charge and no host                          | **saving** — a whole line item disappears (13.1f)                             |
| **AWS NAT Gateway is per-AZ** (§ 3)                                                                                                       | **increase** — say so in the same breath as the savings                       |
| **Cross-AZ data transfer** is charged on AWS. Azure's zone-redundant frontends bundle more of this into the resource price                | **increase**, and it is easy to miss because there is no resource to point at |

A findings list that only contains savings is a sales document. Both columns go in the report.

## 6. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (listener protocol
and port, target group, WAF association, AZ count for NAT), `confidence: "inferred"`,
`rubric_applied: "networking.md"`, and a `rationale` naming **which criterion fired**.

An absorbed balancer emits no `services[]` entry — it appears in `warnings[]` with the
compute resource that took it over, per § 2.5.

## Status — build step 5b

Implemented for load balancers, application gateways, NAT gateways, CDN and Front Door
profiles, and API Management. VPN and ExpressRoute gateways are not covered: they are
hybrid-connectivity decisions that belong to a network engagement rather than a
per-resource mapping, and no type routes here for them today.
