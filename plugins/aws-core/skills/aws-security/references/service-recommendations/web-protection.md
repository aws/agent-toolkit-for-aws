# Web protection decisions

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
An existing WebACL can need tuning; an absent feature is not automatically an application gap.

## Endpoint coverage and bypass

Request the application's full endpoint set and existing association/origin-restriction metadata,
including relevant AppSync, Cognito, App Runner, Verified Access and non-AWS origins. Verify
current association and mTLS support for each actual resource/protocol; the inventory's narrow
ALB/CloudFront/API reads cannot prove absence on unassessed endpoint types.

CloudFront naming an origin is not bypass protection. Compare the distribution WebACL with
origin access restrictions using bounded evidence. Never collect or quote a secret origin header's
name or value from customer configuration. Verified
restrictions may make an additional origin ACL redundant; unchecked restrictions leave origin
protection UNKNOWN. If direct bypass is demonstrated, report that gap rather than suppressing
an ALB/API finding. For static content without application logic, assess the actual abuse or availability need before recommending WAF; absence alone is not an application gap. For private applications, establish reachable paths, consumers and supported associations before recommending HTTP filtering.
Source: [pinned WAF placement guidance](https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/recommended-http-architecture/docs/index.md).

## Rules and application abuse

| Evidence from the relevant endpoints | Selection consequence / trap |
|---|---|
| Application stack, managed groups, representative Count/log results and version | Match baseline/use-case groups to actual threats and legitimate requests. A fixed group list does not guarantee protection; version changes need compatibility evidence. |
| Bot labels, business harm, legitimate clients and browser/session support | Choose Common/Targeted capability from the abuse need and current versions. Login does not make an endpoint immune to bots, and a verified bot can still violate business policy. |
| Login or signup fields, outcomes and existing controls | Compare ATP for login with ACFP for account creation. Confirm current resource/protocol and response-inspection eligibility before recommending either; do not generalize one supported flow to all Cognito or CloudFront cases. |
| HTTPS browser/SDK token acquisition, API/POST flow, accessibility, token domains and expiry | CAPTCHA/Challenge needs a compatible acquisition/validation flow. APIs can use pre-acquired tokens, but interstitial suitability cannot be assumed. Tokens do not replace authentication. |
| Endpoint rates over matching windows, shared NAT and expensive operations | Base rate controls on observed traffic and business impact. An arbitrary threshold can affect legitimate shared clients while missing the expensive path. |

For example, login abuse with adequate dependency scanning is still an application-abuse
question. It supports evaluating a compatible login control, not replacing the scanner or
assuming ATP is eligible without field/protocol evidence. Sources: [managed rules][WM],
[bots][WB], [fraud][WF], [tokens][WT]; reviewed official [ATP](https://docs.aws.amazon.com/waf/latest/developerguide/waf-atp.html),
[ACFP](https://docs.aws.amazon.com/waf/latest/developerguide/waf-acfp.html) and
[token guidance](https://docs.aws.amazon.com/waf/latest/developerguide/waf-captcha-and-challenge-best-practices.html).

## Evaluation and evidence limits

Trace actual priorities, terminating actions and label producers/consumers before judging a
rule ineffective. A broad allow can bypass later controls; absent labels are inconclusive
when the rule was never evaluated. Review narrow legitimate-traffic exceptions from sanitized
matches without converting them into prohibited security-finding suppression.

The guide conflicts on rate-rule order. Resolve the selected rule's semantics and dependencies
from current documentation; no universal ordering follows from the guide. Its incomplete
integration/monetization sections do not establish capabilities. Current fraud response-inspection,
resource and protocol restrictions remain explicit eligibility checks.

Compare configured logging with delivered records, retention and redaction. Filtering away
needed allowed/blocked/nonterminating evidence can undermine investigation; a lower log bill
alone does not justify it. Existing WAF protection also does not prove application exploitability
was tested; use [application assessment scope](references/service-recommendations/application-security.md#application-fit-and-scope)
only when that separate question is asked. Source: [pinned rule-order guidance](https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/recommended-waf-rule-order/docs/index.md).

[WM]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/aws-managed-rules/docs/index.md
[WB]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/bot-management/docs/index.md
[WF]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/fraud-prevention/docs/index.md
[WT]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/waf/captcha-and-challenge/docs/index.md
