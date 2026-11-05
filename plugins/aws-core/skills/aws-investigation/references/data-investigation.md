# Data investigation

Use this when the answer is in the account's data, logs or configuration: counts, breakdowns,
extracts, joins, or why records are failed or unmatched. Whether a finding is complete (pagination,
range coverage, the whole affected population) and whether a root cause holds is in
[completeness-and-root-cause.md](completeness-and-root-cause.md).

## Missing or ambiguous parameters

If a parameter is ambiguous or missing (end of a date range, number of iterations, grouping
convention), discover it from the live environment first: query the available partitions or the
latest dates in the data, list existing resources, and choose the most natural default (for
example consecutive fixed-size windows from the stated start date up to the latest available
data). State the choice in the answer.

## Finding the data source

If a request names data, fields or values without saying where they are stored, find the source
before doing anything else:

1. List likely stores in the account and region: DynamoDB tables, S3 buckets and prefixes,
   Glue and Athena databases and tables, RDS and Redshift, OpenSearch, Bedrock knowledge bases.
2. Look for names that match the request's terms.
3. Sample items, describe schemas or scan with filters to confirm which attributes hold the values
   the user mentioned.

## Configuration plus data: failed, unmatched or exception records

When asked why records are in an exception, unmatched or failed state, investigate the
configuration as well as the data:

1. **Find the rules first.** Search every reachable store: S3 configuration or rule objects outside
   the data prefixes, DynamoDB tables, SSM parameters, Secrets Manager and AppConfig, Lambda, Step
   Functions and Glue job definitions and environment variables, and rule tables in the catalog.
2. For each category and subcategory involved, check whether a matching or processing rule exists
   and is enabled. Report any category without a rule as a candidate root cause.
3. Break the largest contributors down by category and subcategory, outcome or status, and
   secondary dimensions such as currency, with exact counts for each breakdown, not only totals.

## Counting

- **Exact aggregates.** Get numbers with aggregate queries (COUNT or SUM with GROUP BY) run in the
  query engine. Do not pull raw rows and estimate, and never describe counts as approximate
  patterns.
- **Alarms and requests.** Scoping counts to an alarm's dimensions and counting unique failed
  requests are in [multi-service-logs.md](multi-service-logs.md); widening from one failed record
  to the whole affected population is in
  [completeness-and-root-cause.md](completeness-and-root-cause.md).

## Extracting and filtering records

1. **Split the conditions.** Break the request into separate filters (reason or category, current
   state, subset of a reference list).
2. **Map each to the source data.** List the distinct category values, read the registry's own
   category definitions, and check how the current state is recorded (latest event per item,
   reinstatement records).
3. **Use exactly the subsets the user named,** and leave out neighbouring categories they did not
   ask for.
4. **Re-derive, don't copy.** Do not copy filters or row sets from earlier output files without
   deriving them again from the source.
5. **Verify before delivering.** Confirm that a sample of included rows meets every condition, look
   for rows wrongly left out (case or spacing differences, items with several records), and report
   the count after each filtering step.

## Joining tables for complete rows

When the user names one table as the authority for which records count:

1. Use that table to decide which rows are included.
2. If it lacks a requested field, inspect the schemas of related tables, find the shared keys
   (IDs, source identifiers, batch or group IDs, array columns that need unnesting) and join to get
   it.
3. Never output "N/A" or "could not be derived" for a requested field until you have tried those
   joins.
4. Do not collapse rows that share a key: if several entities map to one identifier, list each.
5. Copy identifier values from query results instead of retyping them, and check that every row has
   every requested field before writing the answer.

## Output

- **Literal values.** When the user asks for records, logs or query results rather than an
  analysis, give every value (timestamps, identifiers, URLs, codes, headers) exactly as the source
  produced it, never as categories, prefixes, inferred buckets or paraphrases. If the output is too
  large, write the complete raw rows to a CSV or JSON file and point to it. Collapse only rows that
  are identical on every selected field, showing the full values and a count. Summaries come in
  addition to the raw values, never instead of them.
- **Exact error evidence.** Quote the status code and the error code and message from the failing
  response payload word for word, not a summary such as "HTTP 500".
- **Every requested artifact.** Produce every file or plan asked for (Excel workbooks, CSV files,
  EXPLAIN plans), run every step, and assume any role or credentials you were told to use.
