<!-- markdownlint-disable -->

## KEY PRINCIPLES

- Read-only audit. Every change is a proposal for a human to execute.
- Coverage is discovered from the bill, never enumerated from a checklist. The 3.5 inventory defines what Phase 4 must cover, and 4.13 reconciles before it closes.
- The bill is the arbiter, in both directions. It says what must be analysed, and it also overrules any metric that claims a billed resource did no work. A zero metric never outranks a non-zero charge.
- A missing metric is missing data, never zero. Guard every comparison with `absent()` and report `METRICS UNAVAILABLE` rather than an idle verdict.
- A tag nominates a scheduling candidate; only a measured hour-of-day profile qualifies one. That holds for databases as much as for instances, and the stated window is part of the number.
- Native recommendations beat custom detection. Hub and Compute Optimizer first, CloudWatch loops as fallback.
- Clean up and rightsize before committing. The phase order encodes this: waste, sizing, then commitments.
- Anchor commitments on a percentile such as P10, not the absolute minimum hour that one outage can distort. Around 60 to 70 percent of steady-state baseline is the usual landing zone.
- One account per run. In an organization, decide commitment purchases from the management account's view, because discounts are shared across accounts.
- RIs stay right for services no Savings Plan covers and for zonal capacity reservations.
- Check data transfer. Often 5 to 15 percent of the bill, and rarely in native recommendations.
- Every recommendation carries a dollar figure and a confidence level.
- Look up prices, never assume them.
- Treat any resource you cannot classify as production.
- Review findings with finance and engineering before anything in Appendix A runs.

<!-- markdownlint-enable -->
