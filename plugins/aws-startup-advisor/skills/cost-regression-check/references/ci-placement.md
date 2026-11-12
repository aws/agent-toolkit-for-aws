# CI Placement

## What changes for a startup

Run the job in the team's own pull request pipeline, before apply, and address the comment to the bill owner, who owns the thresholds file. Start advisory, and judge the estimates against the bill before credits.

A large company usually applies cost policy centrally, against organization-wide thresholds and its own rates, and settles an exceedance in its cost process. When the bill comes out of the company's own ceiling, the cheapest point to stop a new fixed charge is before it is applied, and the person who can accept it reviews the pull request. While credits pay the bill, the invoice net of credits says nothing about whether the estimates are right, so the advisory comparison uses the bill before credits.

Pipeline mechanics are general and live upstream: `Skill("aws-core:aws-deployment")` for CodePipeline and CodeBuild, `Skill("aws-core:aws-cdk")` for synthesis in a pipeline, and `Skill("aws-core:aws-iam")` for the job's role. No upstream skill covers GitHub Actions or GitLab CI, so write those jobs from the CI provider's own documentation. This file keeps what the ceiling changes: where the job sits, what the comment says, and when it may block.

## Placement

- Put the job after the plan, `cdk synth`, or change set exists and before anything is applied. It reads what the IaC tool produced, runs the cost script, and updates one comment. It applies nothing and needs no write access to the account.
- Run it only when infrastructure paths change.
- If changes are applied on push to the production branch with no pull request, there is nowhere to put the job, and no point where the bill owner decides. Require pull requests into that branch first.
- If an IaC automation service runs the plan, read the plan from it if it exposes the plan as an artifact; otherwise run a plan in the pull request pipeline for the job.

## Credentials

Keep the cost job's credentials apart from the deploy credentials. Producing the plan reuses whatever the existing plan step uses. Pricing from the pinned price file in the repository (see `estimators.md`) needs no AWS credentials; pricing through the Price List Query API needs only `pricing:GetProducts` ([Price List actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_pricing.html)), on a role with nothing else.

Pull requests from forks change nothing about the ceiling, so this skill sets only two rules for them. On GitHub a fork run gets a read-only token and no other secrets ([events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)), so it often can neither plan nor comment: make it exit as `on_estimator_failure` says, so a fork pull request never passes the check silently. Never use `pull_request_target` to check out and run code from the fork, which would run it with the base repository's secrets and a write token ([securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)).

## The comment

Post one comment per pull request and update it on every push, so the thread shows the current numbers and not a history of stale ones. Use a fixed layout so the bill owner learns where to look:

```text
Cost check: list price, on demand, before credits, Free Tier, Savings Plans, Reserved Instances and private pricing

Floor added by this change:    <amount>/month   threshold <amount>/month   <within | EXCEEDS>
Stack floor after this change: <amount>/month   cap <amount>/month         <within | EXCEEDS>
Cost per <unit>:               <before> -> <after> (<change>)   threshold <amount>   <within | EXCEEDS>

Largest contributors: <resource, dimension, amount> (up to five)
Unpriced: <resource and reason> | none
Assumptions flagged as unverified: <assumption and the change that touched it> | none
Not covered: values known only after apply, resources outside the plan, Spot, time-limited Free Tier offers, usage not in the assumptions file
Inputs: thresholds <file at commit>, assumptions <file at commit>, prices <source and publication date>
```

Every amount in the comment comes from the script output. When a line shows EXCEEDS, add one sentence naming the three outcomes from `thresholds.md` (change it, accept it in the thresholds file, or move the threshold in a separate pull request), so the author does not have to look them up.

## Advisory first, then blocking

Start advisory: the job comments and never fails the build on an exceedance. A run that produced no number follows `on_estimator_failure`, which is `fail` from setup, so a check that stopped working shows up during the advisory period instead of looking like a run with nothing to report.

During the advisory period, for each merged change that crossed or nearly crossed a threshold, compare the estimated floor with what the bill shows once the change has run for a full billing period. Query Cost Explorer with credits excluded through `Skill("aws-core:aws-billing-and-cost-management")`, since the estimate is before credits, and do the comparison in a script.

Move to blocking when the bill owner agrees the estimates track the bill. Then:

- Make the job a required status check that fails on an exceedance with no matching entry in `accepted` in the thresholds file.
- Leave the override where it is: an `accepted` entry, which needs the bill owner's review because they own the file.
- Review `on_estimator_failure` with the bill owner: keep `fail`, or set `pass` if an estimator or price source outage must not block merges once the check is required. Either way, the comment says the check did not run. A silent pass is the one outcome to rule out.
