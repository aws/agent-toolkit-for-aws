#!/usr/bin/env npx ts-node
/**
 * check-compatibility.ts
 *
 * Checks Cassandra inputs against Amazon Keyspaces feature support and
 * emits a JSON compatibility report.
 *
 * Schema (CQL DDL): reports CREATE INDEX, CREATE TRIGGER, CREATE
 *   MATERIALIZED VIEW, CREATE FUNCTION, and CREATE AGGREGATE as
 *   incompatibilities.
 *
 * Prepared statements (NDJSON / cqlsh `SELECT JSON * FROM
 *   system.prepared_statements`): additionally reports
 *     - LWT inside `BEGIN UNLOGGED BATCH`
 *     - Aggregate calls (COUNT / MIN / MAX / SUM / AVG)
 *     - `USING TTL` per target table (informational; not an issue)
 *
 * Detection delegated to ParsingHelpers.ts.
 *
 * Usage:
 *   npx ts-node --require tsconfig-paths/register --project tsconfig.scripts.json \
 *     scripts/check-compatibility.ts \
 *     [--schema <path>] [--prepared <path>]
 *
 *   # CQL on stdin (only valid with no --prepared flag)
 *   cat schema.cql | npx ts-node --require tsconfig-paths/register --project tsconfig.scripts.json \
 *     scripts/check-compatibility.ts
 */

import fs from 'fs';

import {
  parse_cassandra_schema_compatibility,
  parse_prepared_statements,
  type CompatibilityInfo,
  type QueryPatternsInfo,
} from './calculator/ParsingHelpers';

interface Args {
  schema: string | null;
  prepared: string | null;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { schema: null, prepared: null };
  let i = 0;
  while (i < argv.length) {
    switch (argv[i]) {
      case '--schema':   args.schema   = argv[++i]; break;
      case '--prepared': args.prepared = argv[++i]; break;
    }
    i++;
  }
  return args;
}

function readStdinSync(): string {
  try {
    return fs.readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function summarizeSchema(details: CompatibilityInfo) {
  let total_table_issues = 0;
  let tables_affected = 0;
  const keyspaces_affected = Object.keys(details.keyspaces).length;

  for (const tables of Object.values(details.keyspaces)) {
    for (const issue of Object.values(tables)) {
      const count = issue.indexes.length + issue.triggers.length + issue.materializedViews.length;
      if (count > 0) {
        tables_affected++;
        total_table_issues += count;
      }
    }
  }

  const total_issues = total_table_issues + details.functions + details.aggregates;

  return {
    total_issues,
    keyspaces_affected,
    tables_affected,
    functions: details.functions,
    aggregates: details.aggregates,
  };
}

function summarizeQueryPatterns(p: QueryPatternsInfo) {
  return {
    lwt_in_unlogged_batch: p.lwt_in_unlogged_batch.length,
    aggregations:          p.aggregations.length,
    ttl_tables:            Object.keys(p.ttl_tables).length,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  let schemaContent: string | null = null;
  if (args.schema) {
    try { schemaContent = fs.readFileSync(args.schema, 'utf8'); }
    catch (err: unknown) {
      console.error('Failed to read schema file: file not found or unreadable');
      process.exit(1);
    }
  } else if (!args.prepared && !process.stdin.isTTY) {
    // Backwards compat: stdin = schema CQL (only when no other source given)
    const stdinContent = readStdinSync();
    if (stdinContent) schemaContent = stdinContent;
  }

  let preparedContent: string | null = null;
  if (args.prepared) {
    try { preparedContent = fs.readFileSync(args.prepared, 'utf8'); }
    catch (err: unknown) {
      console.error('Failed to read prepared statements file: file not found or unreadable');
      process.exit(1);
    }
  }

  if (!schemaContent && !preparedContent) {
    console.error('Usage: check-compatibility.ts [--schema <path>] [--prepared <path>]');
    console.error('       cat schema.cql | check-compatibility.ts');
    process.exit(1);
  }

  // Schema-driven findings
  const schemaDetails: CompatibilityInfo | null = schemaContent
    ? parse_cassandra_schema_compatibility(schemaContent)
    : null;

  // Prepared-statement findings
  const queryDetails: QueryPatternsInfo | null = preparedContent
    ? parse_prepared_statements(preparedContent)
    : null;

  const schemaSummary = schemaDetails ? summarizeSchema(schemaDetails) : null;
  const querySummary = queryDetails ? summarizeQueryPatterns(queryDetails) : null;

  const total_issues =
    (schemaSummary?.total_issues ?? 0) +
    (querySummary?.lwt_in_unlogged_batch ?? 0) +
    (querySummary?.aggregations ?? 0);

  const result = {
    source: 'compatibility-check',
    input: { schema: args.schema, prepared: args.prepared },
    has_issues: total_issues > 0,
    summary: {
      total_issues,
      schema: schemaSummary,
      query_patterns: querySummary,
    },
    details: {
      schema: schemaDetails,
      query_patterns: queryDetails,
    },
  };

  console.log(JSON.stringify(result, null, 2));
}

main();
