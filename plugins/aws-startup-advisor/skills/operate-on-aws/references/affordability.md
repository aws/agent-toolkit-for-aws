# Affordability — is this a good use of their money?

Relevance is not the bar. **The startups that need DevOps Agent most can least afford it.**

A pre-seed team with no operations engineer needs it badly and may hold $1,000 in credits — which five
investigations a week would consume in under two months. A Series A team can absorb the cost comfortably
and may already run PagerDuty.

So after establishing that DevOps Agent *fits*, establish whether it is a good use of what they have. This
is the one judgement no enterprise tool would make on a customer's behalf, and it is only credible because
we can see the numbers.

## What you need, and what to do without it

You need AWS credentials in the environment. You do **not** need the user signed into AWS Startup
Advisor — this runs on whatever `aws configure`, `AWS_PROFILE`, or SSO session is already there.

| State | Do |
|---|---|
| Credits readable | Full arithmetic below |
| Credentials present, billing access off | Say why you cannot read it (root-user setting), then use the **qualitative** version |
| No credentials at all | Qualitative version only |

**The stance does not require the data.** Even with no numbers you can say: *"If you're pre-seed and
watching runway, the thing to know is that each investigation is about $3–4 and this is easy to leave
running. Point it at production only, and check back after a week."* That is still more useful than a
price list.

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

## Where the line sits

| Runway | Say |
|---|---|
| **> 6 months** | Straightforwardly affordable. Recommend it. |
| **2–6 months** | Recommend it, and say plainly when it will run out and what happens then. |
| **< 2 months** | **Say so before they enable it.** *"At that rate this would use most of your remaining credits inside a month. That may still be worth it — you decide — but you should know before, not after."* |
| **< 3 weeks** | **Recommend against, and mean it.** Offer the alternatives below. |

That last row is the point of this file. Saying *"you'd get more from spending this on compute"* to
someone who could be sold something is what makes the rest of the recommendation trustworthy.

**It is still their call.** Recommend against; do not refuse. A founder who has just lost a day to an
outage may reasonably decide four dollars is cheap. Give them the number and let them weigh it.

## The "instead" path — this has to be genuinely useful

Declining without an alternative is not advice, it is a shrug. In descending order of value:

**1. Release-readiness review, which is free during preview.** The strongest answer by some distance. It
costs nothing today, works with zero production traffic, and prevents a share of the incidents they cannot
currently afford to investigate. If someone fails the affordability test for investigations, route them
here — same product, no cost, real value.

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
