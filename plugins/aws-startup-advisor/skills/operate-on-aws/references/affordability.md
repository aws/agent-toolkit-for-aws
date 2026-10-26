# Affordability — when they ask what it would cost them

Use this only when the user asks — *"how long would our credits last?"*, *"can we afford this?"*. It is
not a gate: the setup notice gives the trial, credits, and rate, and whether to go ahead is their
decision. Do not volunteer a runway estimate or recommend against setup on cost.

**The trial comes first.** New DevOps Agent customers get a two-month free trial with up to 20 hours of
investigations per trial month. No check reliably says whether a given account is still in it, so say
any estimate below applies to usage beyond the trial allowance, or after the trial ends.

## What you need, and what to do without it

You need AWS credentials in the environment. You do **not** need the user signed into AWS Startup
Advisor — this runs on whatever `aws configure`, `AWS_PROFILE`, or SSO session is already there.

| State | Do |
|---|---|
| Credits readable | Full arithmetic below |
| Credentials present, billing access off | Use the **qualitative** version; explain the root-user setting only if asked |
| No credentials at all | Qualitative version only |

**The answer does not require the data.** Even with no numbers you can say: *"Each investigation is
about $3–4 after the trial, and it's easy to leave running. Point it at production only, and check back
after a week."* That is still more useful than a price list.

## The arithmetic

```
runway_weeks  =  remaining_balance  /  (investigations_per_week × $4)
```

$4 is the top of the per-investigation range and the right number to plan against.

**Estimating investigations per week.** Best evidence first:

1. **Operational alerts already firing** in Startup Advisor — `lambda-throttled`, `asg-health-check`,
   `route53-failover`. These are real, current, and countable.
2. **Ask, in their terms:** *"Roughly how often does something break badly enough that you drop what
   you're doing?"* Founders answer that accurately; they do not answer "what's your incident rate."
3. **Default to 3 a week** if there is nothing to go on. Low enough not to alarm, high enough to be honest.

## Saying the result

Give the number plainly — *"after the trial, at about three investigations a week (about $12), your $200
in credits would last roughly four months, unless they expire sooner or other AWS usage draws on them"* —
and say what happens when credits run out (usage bills to their payment method). If it is short, they may want the lower-cost options below; mention them, but do not
recommend against setup. A founder who has just lost a day to an outage may reasonably decide four dollars
is cheap.

Never assume a trial is active, and never invent a balance or runway the data does not support.

## Lower-cost options, if they want them

In descending order of value:

**1. Release-readiness review, which is free during preview.** The strongest answer by some distance. It
costs nothing today, works with zero production traffic, and prevents a share of the incidents they cannot
currently afford to investigate — same product, no cost, real value.

**2. CloudWatch alarms.** If Startup Advisor is reporting `scalability.no-cloudwatch-alarms`, that is the
gap to close first and it is nearly free — the AWS free tier covers ten alarms. An alarm that pages them at
2 a.m. beats an agent they cannot afford to run.

**3. Structured logging and log retention.** `cost.cloudwatch-no-retention` often shows up alongside. Being
able to search logs is the prerequisite for diagnosing anything by hand.

**4. The resiliency baseline and architecture assessment prompts**, already in Startup Advisor and free.

**5. Come back at the first incident they cannot diagnose in thirty minutes.** Concrete, and it is their
own threshold rather than a sales trigger.

## Timing traps worth flagging

- **Activate credits expiring inside the two-month trial.** If credits lapse before the trial ends, free
  becomes paid and the balance vanishes at roughly the same moment. Check `endDate` against the trial and
  say so if they collide.
- **A launch is coming.** Product Hunt, demo day, a big customer going live — incident rate and cost both
  spike exactly when the founder is least able to think about it. Worth raising *before* the launch, not
  during.
- **The first 24 hours after connecting** are the weakest. The agent is still learning topology.
  Investigations get sharper; the first one is not the one to judge it on.
