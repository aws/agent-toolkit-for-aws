# Thresholds

## What changes for a startup

Set two absolute thresholds, one for the floor and one for the cost per unit, plus a cap on the total floor of the stack. Derive all three from the company's own monthly ceiling at list price before credits, keep them in a reviewed file in the repository, and let the bill owner change them.

A large company sets a percentage of a stable baseline, priced at its own rates. That works when last month is a reliable base and the rates are the ones it will keep paying. Against a small ceiling that the company pays itself, often from credits, neither holds: last month is small, new, or credit-funded, and the amount billed today is not the one that applies when the credits end.

## Start from the ceiling

The ceiling is the monthly AWS amount, at list price and before credits, that the bill owner is prepared to pay. Ask the bill owner for it and write it down with the date. If the team has no ceiling, the bill owner sets one before this check is useful. Deriving a ceiling from runway, funding, or credits is a business question for AWS Startup Advisor, not for this skill.

Use the list-price, pre-credit ceiling even while credits pay the bill. The check exists to catch the change that makes the post-credit bill unaffordable, and a ceiling net of credits would wave that change through.

## Floor threshold

The floor threshold is the amount a single pull request may add to the monthly floor without an explicit decision. The bill owner chooses it as the share of the ceiling one change may take without a conversation.

Anchor the choice on the floors the team wants to discuss. Have the cost script price, from current Price List data, the fixed resources the team most often adds (a NAT gateway, a load balancer, an interface endpoint in each Availability Zone, a database minimum) and show the bill owner where each lands against a candidate threshold. Set the threshold so that the resources the bill owner wants to hear about cross it. Never quote those prices from memory; take them from the script output.

## Stack floor cap

Several changes can each stay under the floor threshold and together double the floor. Set a cap on the estimated total floor of the stack, also from the ceiling, and have the job report the total on every pull request. Crossing the cap is an exceedance even when the change itself is small.

## Per-unit threshold

The per-unit threshold is the increase in cost per unit that needs a decision, as an amount per unit, not a percentage. Anchor it on what one unit earns if the bill owner knows that, or on the current cost per unit that the script computes on the main branch.

If the team has more than one unit (requests and tenants, for example), give each its own threshold. Do not combine them into one number.

## Why not a percentage

The upstream cost audit compares each service with the previous month and flags increases above 20 percent ([cost-audit.md](https://github.com/aws/agent-toolkit-for-aws/blob/main/plugins/aws-core/skills/aws-billing-and-cost-management/references/cost-audit.md)). That is the right answer for a running account with history. Against a small, company-paid ceiling it fails in three ways:

- On a small bill, a large percentage can be a few dollars, so the check fires on noise and the team learns to ignore it.
- A first resource of a new kind has no previous month, so the percentage is undefined or infinite.
- While credits pay the bill, the billed amount says nothing about the cost the ceiling must absorb later.

An absolute amount derived from the ceiling means the same thing in month one and month twelve.

## The thresholds file

Keep one file in the repository, for example `cost/thresholds.yaml`, with:

- `ceiling_monthly`: the ceiling, with currency.
- `floor_threshold_monthly`: the floor threshold per pull request.
- `stack_floor_cap_monthly`: the cap on the total floor.
- `unit`: the unit name, matching the usage assumptions file.
- `per_unit_threshold`: the per-unit threshold.
- `owner`: the bill owner.
- `set_on`: the date each value was last changed.
- `accepted`: a list of accepted exceedances, each with the pull request number, the amount, the reason, and the date.
- `on_estimator_failure`: what the job does if it cannot produce a number, `pass` or `fail`. Set it to `fail` at setup; it applies in advisory mode too, and is reviewed when the check becomes blocking (see `ci-placement.md`).

Make the bill owner the code owner of this file, so any change to it needs their review. Do not keep thresholds in CI variables, where they change without review and without history.

## Who decides on an exceedance

The author and the bill owner decide in the pull request, because the ceiling is the company's own money and the bill owner is the person who can accept a new fixed charge against it. There are three outcomes:

1. Change it. The author reduces the cost, for example by sharing an existing NAT gateway or lowering a minimum, and the next run shows the new numbers.
2. Accept it. The author adds an entry to `accepted` in the same pull request with the reason. Because that edits the thresholds file, the bill owner's review is required, and the approval is recorded where the change is.
3. Move the threshold. If the threshold itself is wrong, the bill owner changes it in a separate pull request, so the change to policy is reviewed on its own.

If the bill owner is also the author, the decision is still recorded in the file, which is what makes it visible later.

## List price, on purpose

Report list price: public on-demand rates, before credits, Free Tier, Savings Plans, Reserved Instances, and private pricing. A Free Tier allowance is shared with everything else on the bill, so a change priced against it reads as free while the allowance lasts; the cost script drops Free Tier products for that reason (see `estimators.md`). Where a price list file and a service pricing page differ, AWS charges the price on the pricing page ([AWS Price List](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)).

List price overstates the bill for a team with commitments or private pricing. The comment labels every number as list price so nobody mistakes it for the invoice. For a floor decision against a small ceiling, the overstatement is the safe direction.
