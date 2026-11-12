# Estimators

## What changes for a startup

Price every change at public on-demand list price before credits, keep the floor apart from usage, and pin the price source in the repository. The estimator supplies numbers only; the thresholds and the decision stay in the repository (see `thresholds.md`).

A large company prices a change at its negotiated or commitment-adjusted rates and can use an estimator's own thresholds and approval flow, because its rates are the ones it will keep paying and its cost process sits behind the estimator. A company paying from its own ceiling needs the bill that arrives when credits end, a floor it can read on its own, and thresholds its bill owner sets.

The general mechanics of producing a change and looking up a price live upstream, so this file does not restate them:

| Mechanic                                                                                                     | Where it lives                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Price List service codes, attribute filters, tiered rates (`beginRange`, `endRange`), and the 730-hour month | `Skill("aws-core:aws-billing-and-cost-management")`                                                                                                       |
| `cdk synth` and `cdk diff`                                                                                   | `Skill("aws-core:aws-cdk")`                                                                                                                               |
| Creating and describing change sets                                                                          | `Skill("aws-core:aws-cloudformation")`                                                                                                                    |
| Terraform plan JSON (`terraform show -json`, `resource_changes`, `after_unknown`)                            | No upstream skill reads a plan for cost; use the [Terraform JSON output format](https://developer.hashicorp.com/terraform/internals/json-format) directly |

## What the floor needs from a change

The floor added and the stack floor cap need three things a cost diff does not give by default.

- The floor of the whole stack, not only the changed resources, for the cap. A change set or `cdk diff` lists only what changes. Price the whole stack from Terraform `planned_values`, or from every `resource_changes` entry including those with the `no-op` action. For CDK, price the full synthesized template. For CloudFormation, price the template of the change set, which `GetTemplate` returns when called with the change set name ([GetTemplate](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_GetTemplate.html)).
- A resource that leaves the plan but keeps running is still billed, so it reduces no floor. Credit a floor reduction only for a Terraform `resource_changes` entry whose `change.actions` include `delete`; a `removed` block with `destroy = false` leaves the resource running ([removed block](https://developer.hashicorp.com/terraform/language/block/removed)). In a change set, a `Remove` with `PolicyAction` `Retain`, or a `ReplaceAndRetain`, leaves the old resource running ([ResourceChange](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChange.html)). Otherwise a retained resource offsets a real increase and the comment reports a smaller floor added than the bill will show.
- A value the plan cannot know is unpriced, with the reason, and never zero: a Terraform value in `after_unknown`, or a change set `Action` of `Dynamic`. An `Import` counts toward the stack floor and adds nothing to the floor added.

## Where prices come from

Pick one source for the floor and keep it for the advisory period, so comments stay comparable.

### AWS Price List data in the cost script

This is the default, because it needs no third-party account and keeps every number reproducible from the repository and a dated price file. The script maps each resource type the stack uses to a Price List service code and filter attributes, using `Skill("aws-core:aws-billing-and-cost-management")` for the codes and filters. Two choices follow from the ceiling:

- Drop Free Tier products. Price list data includes perpetual Free Tier offers as zero-priced products next to the paid rate for the same usage ([AWS Price List](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)). In the Lambda file for us-east-1, for example, the requests and GB-seconds Free Tier are separate zero-priced products with a usage type that starts with `Global-`. A script that takes the first product matching its filter can price a Lambda memory change at zero, which a company on Free Tier and credits would read as free.
- Pin the price data. Extract the products the mapping uses from the price list files, which download over plain HTTPS with no AWS credentials ([getting price list files manually](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html)), into a dated file in the repository. Refresh it in its own pull request and print its publication date in the comment, so a change in the numbers is never a side effect of a price update. Some files are large: NAT gateway prices are in the `AmazonEC2` file, which for us-east-1 was about 480 MB on 2026-10-05.

The mapping is code the team owns. Cover the resource types the stack actually uses, and report every unmapped type as unpriced. Extending the mapping is a normal pull request.

### An IaC cost estimator

A third-party estimator can produce the floor without a hand-written mapping. Infracost is one example. Its free CI/CD tier lists cost estimates for Terraform, CloudFormation, and CDK, and it reports baseline costs apart from usage costs ([pricing](https://www.infracost.io/pricing/), [usage costs](https://www.infracost.io/docs/features/usage_based_resources/)). Its thresholds and merge blocking are Cost Guardrails, which the pricing page lists in a paid plan.

If the team uses it, take only the baseline figure for the floor, and keep the per-unit change, the thresholds, and the decision in the repository as this skill describes, so the bill owner sets them rather than a paid plan. Read its data-handling documentation before sending infrastructure code to a third party, and pin the version the job runs.

### Never EstimateTemplateCost

The CloudFormation `EstimateTemplateCost` API returns "an AWS Simple Monthly Calculator URL" ([API reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_EstimateTemplateCost.html)), and the Simple Monthly Calculator is no longer supported ([migration note](https://docs.aws.amazon.com/pricing-calculator/latest/userguide/migrate-SMC.html)). A model asked to price a template tends to reach for it. Do not.

## What the numbers leave out

Print these as not covered in the comment footer, rather than letting a reader assume they are in the number:

- Values known only after apply, and counts that depend on them.
- Resources created outside the plan: by the application at runtime, by an operator in the console, or by another stack.
- Spot prices and time-limited Free Tier offers, which the Price List does not include.
- Usage-priced dimensions with no entry in the usage assumptions file, including most data transfer.
- Credits, Savings Plans, Reserved Instances, and private pricing, by design.

## Test the cost script

The script decides what the comment says, so commit small fixture plans (or synthesized templates, or change set descriptions) with the expected output against a pinned price file. Cover the cases where a wrong answer understates the floor or the cost per unit:

- A resource type the mapping does not know: reported as unpriced, not as zero.
- An update that raises a minimum or provisioned capacity on an existing resource: the floor rises.
- A retained or `removed` resource next to a new one: the floor added is not offset.
- A Lambda memory change against a price file that contains the Free Tier products: requests and GB-seconds are priced at a nonzero paid rate, and the duration assumption is flagged as unverified.

In the setup session, run the script against the current main branch and record the stack floor and cost per unit as the starting point, from the script output only.
