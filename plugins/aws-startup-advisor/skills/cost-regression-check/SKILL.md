---
name: cost-regression-check
description: "This skill should be used when a company that pays its AWS bill from a fixed monthly ceiling, often funded by credits, asks what a pull request or other infrastructure-as-code change (Terraform, AWS CDK, or AWS CloudFormation) will add to that bill before apply, or wants that cost on every pull request, including through Infracost or another estimator in CI. It reports two numbers at list price before credits: the fixed monthly floor added at zero traffic, and the change in cost per unit of the team's own usage, against absolute thresholds derived from the ceiling and kept in the repository. It sets up a CI job and a repository-owned script so the author and the bill owner decide on each pull request. Not for spend that already happened (aws-core:aws-billing-and-cost-management), price lookups with no change under review, advice on infrastructure code as it stands, general release risk, or choosing services that avoid a floor."
license: Apache-2.0
metadata:
  audience: startup
---

# Cost Regression Check

Report the cost a change adds on the pull request that adds it, before apply, measured against the fixed monthly ceiling the company pays from its own money. That ceiling is what changes the answer. In a large bill, a new NAT gateway, load balancer, or database minimum is noise, prices are negotiated, and last month is a stable baseline. Against a small ceiling, often funded by credits that end, the same charge can take a visible share before the product has users, and the bill shows it a month later, after the money is spent. A team inside a large company has the same tooling but not that ceiling, so it keeps its company's rates, baselines, and cost process.

Set this up once, in a working session: add a CI job and a cost script to the repository, which owns and reviews both like any other code. On each pull request the job runs the cost script, which reads the resource changes, prices them, computes both numbers, and comments. No model runs per pull request, so the check costs nothing to attend to until a threshold is crossed.

## Decisions, and why the startup answer differs

| Decision                              | Large-company default                            | This skill                                                                                   | Reason                                                                                                                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Report the floor apart                | One blended monthly delta at an assumed volume   | Two numbers: floor added, and change in cost per unit                                        | A fixed charge that is noise in a large bill can be a material share of a small ceiling. A blended number hides which of the two moved.                                                                                                                                           |
| Per-unit threshold from unit earnings | Unit cost reviewed on a dashboard after the bill | A per-unit threshold, set from what one unit earns where known, checked on each pull request | The ceiling stays fixed while usage grows, so a change that pushes cost per unit above what a unit earns turns growth into a bill the ceiling cannot hold. That number can double while every price stays flat, for example after a Lambda memory increase at unchanged duration. |
| Absolute thresholds                   | A percentage of a stable baseline                | Two amounts derived from the ceiling, kept in the repository                                 | A small or credit-funded bill has no stable base for a percentage. A large percentage on a near-zero bill is noise; a new fixed floor that takes a visible share of the ceiling is not.                                                                                           |
| List price                            | Negotiated or commitment-adjusted rates          | Public on-demand price, labelled as such on every comment                                    | Credits hide the bill that arrives when they run out, and the post-credit bill is the one the ceiling has to survive.                                                                                                                                                             |

## Scope

Apply this skill when all of these hold:

- The company pays its AWS bill from a fixed monthly ceiling of its own, whether cash or credits cover it today, and one person owns that ceiling and can state it.
- Infrastructure is defined in Terraform, AWS CDK, or AWS CloudFormation, and changes reach production through pull requests, or the team is willing to make them do so.
- The team can name a usage unit it already counts or can count from logs or metrics.

Do not apply it to spend that already happened (use `Skill("aws-core:aws-billing-and-cost-management")`), to resources the application creates at runtime outside the plan, to optimization advice on infrastructure code as it stands, or to choosing services without a floor. This skill detects that a change added a floor; it does not decide which services have one.

## Workflow

1. Read **`references/thresholds.md`**. Get the ceiling from the bill owner, derive the floor threshold and the per-unit threshold, and write the thresholds file with an owner.
2. Read **`references/floor-and-unit.md`**. Choose the unit, classify each price dimension the stack uses as floor or usage, and write the usage assumptions file with a source for every value.
3. Read **`references/estimators.md`**. Choose where prices come from, then write the cost script and its tests.
4. Read **`references/ci-placement.md`**. Add the job after plan, synth, or change set and before apply, in advisory mode, with the comment format defined there.
5. Run advisory for a set period. After merged changes have run for a billing period, compare estimates with the bill before credits through `Skill("aws-core:aws-billing-and-cost-management")`, then decide with the bill owner whether an exceedance blocks a merge.

## Required deliverables

- A thresholds file in the repository with the ceiling, the floor threshold, the stack floor cap, the per-unit threshold, the unit, the owner, the date each value was set, the `accepted` list of approved exceedances, and `on_estimator_failure`.
- A usage assumptions file mapping each usage-priced dimension to a quantity per unit, each with a source and a date.
- A cost script with tests and committed fixture plans, owned by the repository.
- A CI job that runs on every pull request touching infrastructure code and updates one comment in place.
- A short record of the advisory period: estimated against billed floor for each merged change that crossed or nearly crossed a threshold.

## Rules

- Take every number from a tool: the cost script, an estimator whose output it reads, or AWS Price List data. In the setup session, follow the deterministic-calculation rule in `Skill("aws-core:aws-billing-and-cost-management")` for any arithmetic, and never state a price from memory.
- Label every reported number as list price, on demand, before credits, Free Tier, Savings Plans, Reserved Instances, and private pricing.
- Report a resource the job cannot price by name, as unpriced. Never count it as zero.
- Never use the CloudFormation `EstimateTemplateCost` API. It returns a link to the Simple Monthly Calculator, which AWS no longer supports.
- Start advisory. Make the check blocking only after the advisory record shows the estimates track the bill.

## Upstream skills

The general estimator and CI mechanics live upstream. Invoke these for what they own, and use the reference files here only for what the ceiling changes. The `aws-core:` skills ship in the separate `aws-core` plugin. If it is not installed, tell the user, recommend installing it, and continue with the steps that do not depend on it. Do not reproduce its content from memory.

- **`Skill("aws-core:aws-billing-and-cost-management")`**: Price List service codes, attribute filters, tiered rates and the 730-hour month, the deterministic-calculation rule, Cost Explorer with credits excluded to compare estimates with the bill, and Budgets and Cost Anomaly Detection for spend after merge.
- **`Skill("aws-core:aws-cdk")`**: `cdk synth` and `cdk diff`. It prices nothing.
- **`Skill("aws-core:aws-cloudformation")`**: change sets and pre-deployment validation. It prices nothing.
- **`Skill("aws-core:aws-database")`** and **`Skill("aws-core:aws-compute")`**: the minimums and hourly charges of the services they own, such as Aurora serverless minimum capacity and public IPv4 addresses.
- **`Skill("aws-core:aws-deployment")`**: CodePipeline and CodeBuild, when the job runs there. It does not cover GitHub Actions or GitLab CI.
- **`Skill("aws-core:aws-iam")`**: the CI role and its read-only pricing permission.
- **`Skill("aws-startup-advisor:agent-advisor")`**: only if a team later adds a model to the job and its output may block a merge.

## Reference files

- **`references/thresholds.md`**: Read before setting any threshold. Derives both thresholds and the stack floor cap from the ceiling at list price before credits, explains why a percentage of last month fails on a small bill, defines the thresholds file, and records who decides on an exceedance and how.
- **`references/floor-and-unit.md`**: Read before writing the usage assumptions file. Defines the floor and the per-unit change and why they stay apart against a small ceiling, classifies price dimensions rather than resources, shows where floors hide in a plan, and explains how a usage assumption goes wrong.
- **`references/estimators.md`**: Read before choosing a price source or writing the cost script. Covers what the floor and the stack floor cap need from a plan, pricing at list price from pinned Price List data or the baseline of a third-party estimator, and the tests that keep unpriced resources and Free Tier rates from reading as zero.
- **`references/ci-placement.md`**: Read before adding the job. Covers placement before apply, credentials for a pricing-only job, the comment format addressed to the bill owner, and the move from advisory to blocking after comparing estimates with the bill before credits.

## Anti-patterns

- One blended monthly number at an assumed volume, which hides whether the floor or the unit moved.
- A percentage threshold against last month's bill on a bill that is small, new, or paid by credits.
- Prices looked up or summed by a model in the pull request instead of by the job.
- An unpriced resource silently counted as zero.
- Reporting after credits, Free Tier, or discounts, so the comment describes a bill that ends when the credits do.
- A usage assumption with no source, or one left unchanged by a change that alters it, such as Lambda duration after a memory change.
- Thresholds that live in CI settings instead of a reviewed file the bill owner owns.
- Blocking merges from the first day, before anyone knows whether the estimates match the bill.
- Many changes each under the floor threshold, with no cap on the total floor of the stack.
