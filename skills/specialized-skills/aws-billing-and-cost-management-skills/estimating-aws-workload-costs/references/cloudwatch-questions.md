# CloudWatch questions

CloudWatch lines are sized by a few amounts the owner usually knows as a rough
figure but that the description rarely states: how much goes into CloudWatch
Logs, how long it is kept, and how many custom metrics there are. Assumed from
request counts, these amounts often come out an order of magnitude low, while
an owner asked plainly can usually give them as a magnitude. Use this file for
every workload with CloudWatch lines.

## Ask only what is missing and relevant

Before asking, check each question below against the description and the
user's earlier answers:

- **Already answered.** If they give the amount, even as a range or a
  magnitude ("about 20 GB of logs a month", "tens of TB", "a few hundred
  metrics"), don't ask. Size the line from it as the section on reading
  answers says.
- **Not relevant.** Ask a question only when its trigger below matches the
  design. If nothing in the design writes the logs or metrics it asks about,
  leave it out and size the line, if there is one, as `ASSUMED`.

## The questions

Ask each as one numbered question, in the user's terms, offering magnitudes
to choose from. Rank them with the round's other questions by impact, within
SKILL.md's limit of four per turn and eight per round.

1. **Log volume.** Trigger: the design writes application or access logs to
   CloudWatch Logs at volume. That covers Lambda, containers or instances
   serving steady traffic, API Gateway or load balancer access logs, Step
   Functions logging, and WAF or VPC flow logs sent to CloudWatch Logs. It
   also applies when the user says the service "logs a lot" or "logs heavily"
   without giving an amount. Ask for the total, on its own:
   "Roughly how much goes into CloudWatch Logs a month: a few GB, hundreds of
   GB, a few TB, tens of TB, or more?" This question is mandatory when its
   trigger matches, and it ranks with SKILL.md's mandatory questions. Only if
   the user doesn't know the total, ask which logs each request writes and how
   chatty they are: a line per request, several lines, or full request and
   response bodies. Then size the volume from that.
2. **Retention.** Trigger: log volume is asked or given, and the stored-log
   line could be large, which happens when retention is long or the log groups
   never expire. Ask: "How long do you keep logs (never expire, or a set
   retention), and roughly how long have the log groups been filling?"
3. **Custom metrics.** Trigger: the design publishes custom metrics. That
   includes the embedded metric format (EMF), an agent or SDK publishing
   metrics, or log metric filters with dimensions. Ask: "Roughly how many
   custom metrics does the service publish: tens, hundreds, thousands, or tens
   of thousands?" Note that each combination of dimension values is its own
   metric.
4. **Logs Insights.** Trigger: the design mentions Logs Insights or
   dashboards that query logs, or log volume is a TB a month or more. Ask:
   "Roughly how many Logs Insights queries does the team run a month (tens,
   hundreds or thousands), and how far back does a typical query look (an
   hour, a day or a week)? Do any dashboards have Logs Insights widgets that
   auto-refresh?" Owners rarely know how much their queries scan, so don't ask
   for scanned GB. Each refresh of a widget scans the data range it covers
   again.
5. **Dashboards, alarms and canaries.** Trigger: the description says there
   are dashboards, alarms or canaries but gives no count. Ask for the number
   of dashboards, alarms and composite alarms, and how many Synthetics canaries
   run and how often.

Ask about these only when the description names them: whether Container
Insights runs in standard or enhanced mode, how many tables or rules have
Contributor Insights, whether WAF or flow logs capture every request or only
some, and whether this account is a monitoring account that receives other
accounts' metrics and logs.

## Reading the answers

A magnitude the user gives, such as "tens of TB" or "several thousand", is a
range: put Low and High at its ends and tag the line `DERIVED`. Don't place
Mid by a fixed rule. Work out what the description implies and put Mid where
that lands inside the range:

- **Log volume:** the requests or events a month, times the log groups each
  one writes to, times a typical size for those lines. A JSON access log or
  a Step Functions history event is about a KB; a JVM application log with
  stack traces can be several KB per request.
- **Custom metrics:** the operations or handlers, times the dimension values
  each metric is split by, such as status codes, callers or hosts.
- **Logs Insights scanned:** the queries a month, times the days each query
  looks back, times the daily ingestion of the log groups it queries (the
  month's ingested GB divided by 30). Add each auto-refreshing widget's
  refreshes a month times its range in days times the same daily ingestion.
  When the user can't say which log groups the queries cover, use the largest
  one. When they can't give the look-back, tag the line `ASSUMED` with Low an
  hour, Mid a day and High a week, and name that in the assumption.

If what the description implies falls outside the range, put Mid at the
nearer end and say so in the assumption. Then confirm the amount with the
user as SKILL.md's rule on vague amounts says. Name the user's words and
your working in the line's assumption.
