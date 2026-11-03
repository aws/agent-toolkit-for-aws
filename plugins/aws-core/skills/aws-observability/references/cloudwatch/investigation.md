# Investigating a failure from CloudWatch data

Use this when you investigate AWS-related issues from CloudWatch logs: confirming whether a
failure belongs to one entity, reporting counts or totals from logs, and performing root
cause analysis.

Commands use AWS CLI syntax. The AWS MCP server is recommended for sandboxed execution and
audit logging; the same calls work through the CLI without it.

## Completeness and scope

### Search completeness

Before concluding that an event, request, or record doesn't exist, make sure you searched
everywhere it could be:

1. **AWS resources are regional.** If resource names include a region or marketplace marker,
   or the data could be served by more than one regional deployment, list and query the
   matching resources in every plausible region, not just the default one.
2. **Never report "no evidence of X" as a finding** until you have checked every scope. If
   searches across all scopes still find nothing, say exactly which scopes you checked.
3. **For identity or authorization failures**, find and compare the actual values on both
   sides, such as the identity the invitation or grant was issued to and the identity that
   authenticated. Base the root cause and fix on that comparison, not on guesses about
   infrastructure.

### Pagination requirements

When you read logs or list resources through AWS APIs, paginate until the data is exhausted
before you count, aggregate, or state a scope:

1. **For CloudWatch GetLogEvents**, keep following `nextForwardToken` until it returns the
   same token twice.
2. **For FilterLogEvents and List/Describe calls**, keep following `nextToken` until none is
   returned.
3. **Treat any pagination or truncation warning** as proof that the data is incomplete.
4. **If one call returns too much output**, process the pages and return only summaries. Do
   not shrink the read to a single page.
5. **Before you report counts, totals, or "every X" claims**, check that the last event's
   timestamp matches the stream's `lastEventTimestamp`. Also look for entities whose results
   look partial, since that often means a page was cut off.
6. **If you can't confirm the data is complete**, say the figures are partial.

### Scope verification for failures

When asked to confirm from logs whether a failure belongs to a particular entity (store,
account, tenant, resource), do not filter only on that entity. Get the wider context too:

1. **Run an aggregated query**, such as `stats count by entity, sub-ID, and outcome`, across
   the same operation and time window. This shows whether the same error also hits other
   entities, so you can say whether it is specific to this entity or happening everywhere.
2. **For the target entity, list every unit of work in the relevant run**, both successes and
   failures, so you can see the full scope of the batch. Pay particular attention to the
   operation that matters for the root cause.
3. **If a query returns too much output**, narrow it with aggregation, fields/parse, or
   smaller time windows. Do not add filters that would hide the comparison you need.
4. **In the final answer**, state whether the failure is unique to the entity or shared, and
   roughly how widely it is shared. Say which related operations succeeded. Explicitly correct
   any earlier claims in the thread that the logs contradict.

## Root-cause analysis

### Consistency checks

Before reporting a root cause, check that it fits every fact you have already found,
especially your own conclusions about how the system is designed (for example, whether work
is pushed or pulled):

1. **If something expected seems to be missing** (such as a poller, loop, handler or log
   entry), do not treat the gap as proof of a defect. First ask whether the design you already
   found explains why it is absent.
2. **Label any mechanism you could not confirm** from data, configuration or logs as an
   unverified hypothesis, never as the root cause.
3. **If the evidence points elsewhere** (such as a resource whose state changed or a reference
   that now points to a newer record), build the diagnosis on that.

### Missing features as root causes

Treat a missing feature as a root cause only after you confirm the component was meant to
have it:

1. **A missing feature can be** a missing handler, polling loop, subscriber, or log line.
   Before calling its absence a defect, work out from the evidence which component owns that
   responsibility.
2. **In distributed or cross-region systems**, check the data's target or destination fields
   (such as target region, account, or consumer) to see whether a different service or region
   does that work.
3. **If you can't confirm who owns it**, report the absence as an open question and name the
   next system to check. Don't present it as the root cause.

### Bug reports and code defects

When investigating a bug report against code and logs, make sure your final verdict follows
from your evidence:

1. **If your trace shows that a computation gives a wrong or self-inconsistent result** (for
   example, the same quantity is counted twice, or a valid request is rejected even though the
   resource is available), classify it as a code defect.
2. **Do not call it "working as designed"**, and do not offer only workarounds such as process
   changes, extra user steps, or better error messages.
3. **Name the specific faulty expression or line** and propose a concrete code correction that
   would have made the reported case succeed. Workarounds can be listed as extra suggestions
   after that.
4. **Take the intended behavior from the code and from the user's stated expectations**, not
   from your own view of what the system should do. If a code path exists to handle a case
   (such as a fallback, retry, or alternate branch), treat that case as supported unless you
   have clear evidence otherwise.

### Recommendation quality

In root-cause reports:

1. **Do not say the case should be rejected**, or call the failure "working as designed," when
   your own diagnosis shows a defect.
2. **Recommend only the minimal fix** that follows from the evidence, and do not add extra
   policy changes on top of it.
3. **Remove or correct anything that contradicts** your main finding, the user's stated
   expectation, or the purpose of the code.

### Answering the user's question

When a user asks a specific question or names a suspected cause (for example, "why isn't X
being applied?" or "is it enforced per A or per B?"):

1. **Answer that question directly and early**, and back the answer with evidence from the
   system.
2. **Check the actual configuration or enforcement records**, such as limit or quota
   settings, throttle or decision logs, and the keys or dimensions they record.
3. **Say plainly whether the configuration was in effect** during the incident window, what
   scope it applied to, and what value was enforced.
4. **Rule out each competing explanation** the user or other stakeholders raised, using
   evidence rather than assumption.
5. **Don't hedge or offer speculative alternatives** your evidence doesn't support (such as
   limits reverting to defaults or being split across hosts or partitions).
6. **If you can't confirm something**, label it as unverified instead of implying it.

## Closing checklist

Before submitting your analysis:

1. Have you searched all relevant regions and scopes?
2. Have you paginated through all results?
3. Have you verified the scope of failures (entity-specific vs fleet-wide)?
4. Does your root cause fit all the facts you found?
5. Have you labelled every mechanism you could not confirm as unverified, and reported a
   missing component as a defect only if it was meant to exist?
6. Did your claims about live configuration come from the deployed artifact, not the latest
   stored version?
7. Have you answered the user's specific question directly?
8. Before you finish, have you reread your conclusion against each piece of evidence you
   collected and removed any statement that contradicts it?
9. Have you removed any contradictions between your findings and recommendations?
