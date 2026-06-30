# Deciding Between Shield Standard and Shield Advanced

## Overview

Domain expertise for the question that comes before any AWS Shield Advanced setup: does the customer
actually need Shield Advanced, or do AWS Shield Standard plus AWS WAF cover the requirement at lower
cost. Covers what Shield Standard already provides for free, the AWS WAF baseline (rate-based rules
and the Anti-DDoS managed rule group) that does not require a Shield Advanced subscription, the
Advanced-only differentiators that justify the paid tier, and the auto-renewing one-year commitment
the customer takes on by subscribing.

Does not cover the subscription mechanics themselves (see the subscribing reference), automatic
application layer mitigation, health-based detection, SRT setup, event review, or protection groups;
those are separate references and all assume the decision to use Shield Advanced has already been
made. Authoring the AWS WAF rate-based rule or the Anti-DDoS managed rule group is the waf skill.

This reference is advisory only; it runs no AWS commands. It helps choose between Shield Standard
and Shield Advanced, then routes to the subscribing reference (for Advanced) or the waf skill (for
Shield Standard plus AWS WAF) for any execution.

## Table of Contents

- Overview
- Workflow
- What Shield Standard already covers
- The AWS WAF baseline that does not need Shield Advanced
- Decision: Shield Standard plus AWS WAF vs Shield Advanced
- Advanced is a paid auto-renewing commitment
- Troubleshooting
- Procedure
- Security considerations
- Additional Resources

## Workflow

To decide between Shield Standard and Shield Advanced end to end, follow the procedure exactly. See
the Procedure section below.

The procedure covers:

- Establishing what the customer is actually trying to protect and against what
- Confirming whether the free Shield Standard plus AWS WAF baseline already meets the need
- Identifying whether any Advanced-only differentiator (cost protection, SRT, automatic application
  layer mitigation, health-based detection, attack reporting) is genuinely required
- Routing the customer to subscribing (Advanced) or to the waf skill (Standard plus WAF)

## What Shield Standard already covers

Shield Standard is on for every AWS account at no additional cost. Customers often reach for
Advanced without knowing what they already have, and pay for protection they did not need.

**Constraints:**

- You MUST tell the customer that Shield Standard is always on and free, and provides automatic
  protection against common, most frequently occurring network and transport layer (layer 3 and
  layer 4) DDoS attacks for all AWS resources
- You MUST NOT present Shield Advanced as the only source of DDoS protection; the layer 3 and 4
  baseline already exists under Standard

## The AWS WAF baseline that does not need Shield Advanced

For layer 7 (HTTP/HTTPS) flood protection, AWS WAF provides capabilities that do not require a
Shield Advanced subscription. A customer whose concern is HTTP floods may be fully served by WAF
alone.

**Constraints:**

- You MUST present AWS WAF rate-based rules and the AWS WAF Anti-DDoS managed rule group
  (`AWSManagedRulesAntiDDoSRuleSet`) as a layer 7 protection baseline that is available as a standard
  AWS WAF cost and does NOT require a Shield Advanced subscription
- You SHOULD point the customer at the waf skill to author the rate-based rule and add the Anti-DDoS
  managed rule group, rather than treating layer 7 flood protection as Advanced-only
- You SHOULD note that a Shield Advanced subscription does also include access to the Anti-DDoS
  managed rule group, so this rule group is not itself a reason to subscribe

## Decision: Shield Standard plus AWS WAF vs Shield Advanced

| Need | Shield Standard + AWS WAF | Shield Advanced |
| --- | --- | --- |
| layer 3/4 (network/transport) DDoS protection | Included free with Standard | Enhanced, with visibility and reporting |
| layer 7 (HTTP) flood protection | AWS WAF rate-based rules and the Anti-DDoS managed rule group (standard WAF cost) | Automatic application layer mitigation that builds and tunes WAF rules during an attack |
| Attack visibility and event reporting | CloudWatch metrics only | Detailed per-resource DDoS event detail, vectors, and top contributors |
| Expert help during an attack (SRT) | Not available | Shield Response Team access and proactive engagement |
| DDoS cost protection (scaling-charge credits) | Not available | Cost protection credits for attack-driven scaling |
| Health-based detection | Not available | Route 53 health check feeds Shield detection |

**Constraints:**

- You MUST recommend Shield Standard plus AWS WAF when the customer's need is ordinary layer 3/4
  protection or layer 7 flood throttling and none of the Advanced-only differentiators apply, rather
  than defaulting to a subscription
- You MUST recommend Shield Advanced when the customer needs any Advanced-only differentiator: DDoS
  cost-protection credits, Shield Response Team access or proactive engagement, automatic application
  layer mitigation, health-based detection, or detailed attack reporting
- You SHOULD treat cost protection and SRT access as the two differentiators customers most often
  actually need, and confirm whether either applies before recommending the subscription

## Advanced is a paid auto-renewing commitment

Subscribing is not a reversible toggle. A customer who subscribes without knowing the commitment is
surprised at renewal.

**Constraints:**

- You MUST state before recommending a subscription that Shield Advanced is a paid subscription that
  auto-renews by default on a one-year commitment, and that fully unsubscribing requires contacting
  AWS Support
- You MUST NOT invent a dollar figure for the subscription fee or usage rates; point the customer at
  the current Shield pricing page
- You SHOULD note that one subscription fee covers all accounts in the same AWS Organizations
  consolidated billing family, so the decision is per organization, not per account

## Troubleshooting

### Customer only needs to stop an HTTP flood
That is a layer 7 need AWS WAF covers without Advanced. Use rate-based rules and the Anti-DDoS
managed rule group (The AWS WAF baseline that does not need Shield Advanced); route to the waf skill.

### Customer wants attack-driven scaling charges refunded
Cost protection credits are an Advanced-only feature. That need justifies the subscription (Decision:
Shield Standard plus AWS WAF vs Shield Advanced).

### Customer wants AWS experts to act during an attack
SRT access and proactive engagement are Advanced-only. That need justifies the subscription
(Decision: Shield Standard plus AWS WAF vs Shield Advanced).

### Customer already has Shield Advanced and is asking what else to do
The decision is made; route to the subscribing reference to confirm protections are in place, then
to the task the customer actually wants.

## Procedure

### Overview

This procedure establishes the customer's protection need, checks it against the free Standard plus
AWS WAF baseline, identifies any Advanced-only requirement, and routes accordingly. It makes no AWS
changes itself.

### Parameters

- **protection_target** (required): What the customer wants to protect (for example a CloudFront
  distribution, an Application Load Balancer, a Global Accelerator accelerator).
- **threat** (required): What they are protecting against (layer 3/4 volumetric, layer 7 HTTP flood,
  or both).
- **needs** (required): Whether any Advanced-only outcome is wanted — cost-protection credits, SRT
  help, automatic application layer mitigation, health-based detection, or attack reporting.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST NOT recommend a subscription before confirming whether any Advanced-only differentiator
  is actually required

### Steps

#### 1. Establish the need

**Constraints:**

- You MUST confirm what resource is being protected and against which layer of attack before
  recommending a tier
- You MUST confirm whether any Advanced-only differentiator (cost protection, SRT, automatic
  application layer mitigation, health-based detection, attack reporting) is required

#### 2. Check against the free baseline

**Constraints:**

- You MUST confirm whether Shield Standard (free layer 3/4) plus AWS WAF (rate-based rules and the
  Anti-DDoS managed rule group, standard WAF cost) already meets the need
- You MUST recommend the baseline and route to the waf skill when no Advanced-only differentiator
  applies, rather than defaulting to a subscription

#### 3. Recommend and route

**Constraints:**

- You MUST recommend Shield Advanced only when an Advanced-only differentiator is required, and MUST
  state the auto-renewing one-year commitment before doing so
- You MUST route to the subscribing reference when the customer chooses Advanced, and to the waf
  skill when Standard plus AWS WAF is sufficient
- You MUST NOT invent pricing; point the customer at the Shield pricing page

### Example

#### Example input

```json
{
  "protection_target": "CloudFront distribution",
  "threat": "layer 7 HTTP flood",
  "needs": ["none of the Advanced-only outcomes"]
}
```

#### Example output

```
Your need is layer 7 HTTP flood protection on CloudFront, with no requirement for cost-protection
credits, SRT help, automatic mitigation, health-based detection, or attack reporting.
Shield Standard (free, always on) already covers layer 3/4. For the HTTP flood, AWS WAF rate-based
rules plus the Anti-DDoS managed rule group cover it as a standard WAF cost — no Shield Advanced
subscription required.
Recommendation: stay on Shield Standard and use AWS WAF. Routing you to the waf skill for the
rate-based rule and the Anti-DDoS managed rule group.
```

### Troubleshooting

#### The need is only an HTTP flood
AWS WAF covers it without Advanced. Route to the waf skill (Step 2).

#### An Advanced-only outcome is required
Cost protection, SRT, automatic mitigation, health-based detection, or attack reporting justifies the
subscription. State the commitment and route to subscribing (Step 3).

## Security considerations

This reference makes no AWS changes; it advises on tier selection. The security-relevant point is
that the choice determines which controls exist.

- **Do not leave internet-facing resources without layer 7 protection by deciding against Advanced.**
  When the recommendation is Standard plus AWS WAF, you MUST ensure the customer follows through with
  the WAF rate-based rule and Anti-DDoS managed rule group via the waf skill, so declining Advanced
  does not leave the application with layer 3/4 protection only.
- **Right-size the commitment.** Recommend Shield Advanced only when an Advanced-only differentiator
  is genuinely required, so the customer is not committed to a paid auto-renewing subscription beyond
  what they need.
- **Audit trail.** When the customer proceeds to subscribe, the subscribing reference covers enabling
  AWS CloudTrail on `shield:*` calls; no control-plane change is made in this reference.

## Additional Resources

- [Deciding whether to subscribe to AWS Shield Advanced and apply additional protections (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-advanced-summary-deciding.html)
- [How AWS Shield works (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-how-shield-works.html)
- [Advanced Anti-DDoS protection using the AWS WAF Anti-DDoS managed rule group (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-anti-ddos-advanced.html)
- [AWS Shield Advanced pricing](https://aws.amazon.com/shield/pricing/)
