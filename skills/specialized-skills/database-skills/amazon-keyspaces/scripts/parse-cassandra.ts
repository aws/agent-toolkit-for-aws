#!/usr/bin/env npx ts-node
/**
 * parse-cassandra.ts
 *
 * Parses Cassandra diagnostic files and outputs a Keyspaces pricing estimate
 * as JSON (same shape as calculate.js), suitable for piping to generate-pdf.js.
 *
 * Imports directly from ParsingHelpers.ts and PricingFormulas.ts — no duplication.
 *
 * Usage:
 *   npx ts-node --require tsconfig-paths/register --project tsconfig.scripts.json \
 *     scripts/parse-cassandra.ts \
 *     --region    us-east-1 \
 *     --tablestats tablestats.txt \
 *     [--status   status.txt] \
 *     [--info     node1-info.txt] \
 *     [--rowsize  rowsize.txt] \
 *     [--schema   schema.cql] \
 *     [--pitr]
 *
 * Multiple --info flags accepted (one per node).
 */

import fs from 'fs';
import path from 'path';

import {
  parseNodetoolStatus,
  parseNodetoolInfo,
  parse_nodetool_tablestats,
  parse_cassandra_schema,
  parse_cassandra_schema_compatibility,
  parse_prepared_statements,
  parseRowSizeInfo,
  scanCassandraFiles,
  type CompatibilityInfo,
  type QueryPatternsInfo,
} from './calculator/ParsingHelpers';

import {
  buildCassandraLocalSet,
  getKeyspaceCassandraAggregate,
  calculatePricingEstimate,
  aggregatePricingTotals,
  type Samples,
  type DatacenterRef,
  type EstimateResults,
  type KeyspaceAggregate,
  type PricingEstimateResult,
} from './calculator/PricingFormulas';

const regionsMap: Record<string, string> = require('../assets/data/regions.json');

// ─── CLI arg parsing ──────────────────────────────────────────────────────────

interface Args {
  region: string;
  info: string[];
  status: string | null;
  tablestats: string | null;
  rowsize: string | null;
  schema: string | null;
  prepared: string | null;
  pitr: boolean;
  dir: string | null;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { region: 'us-east-1', info: [], status: null, tablestats: null, rowsize: null, schema: null, prepared: null, pitr: false, dir: null };
  let i = 0;
  while (i < argv.length) {
    switch (argv[i]) {
      case '--region':     args.region = argv[++i]; break;
      case '--info':       args.info.push(argv[++i]); break;
      case '--status':     args.status = argv[++i]; break;
      case '--tablestats': args.tablestats = argv[++i]; break;
      case '--rowsize':    args.rowsize = argv[++i]; break;
      case '--schema':     args.schema = argv[++i]; break;
      case '--prepared':   args.prepared = argv[++i]; break;
      case '--dir':        args.dir = argv[++i]; break;
      case '--pitr':       args.pitr = true; break;
    }
    i++;
  }
  return args;
}

// Read all files in a directory and classify them using ParsingHelpers detectors.
function resolveArgsFromDir(dir: string, args: Args): void {
  const entries = fs.readdirSync(dir).filter(f => fs.statSync(path.join(dir, f)).isFile());
  const fileMap: Record<string, string> = {};
  for (const entry of entries) {
    try { fileMap[path.join(dir, entry)] = fs.readFileSync(path.join(dir, entry), 'utf8'); }
    catch { /* skip unreadable */ }
  }
  const scan = scanCassandraFiles(fileMap);
  if (!args.tablestats && scan.tablestats.length > 0) args.tablestats = scan.tablestats[0];
  if (scan.tablestats.length > 1) {
    console.warn(`Warning: ${scan.tablestats.length} tablestats files found in --dir. Only the first is used. Multi-node tablestats aggregation is not currently supported.`);
  }
  if (!args.status && scan.status)   args.status  = scan.status;
  if (args.info.length === 0)        args.info.push(...scan.info);
  if (!args.rowsize && scan.rowsize) args.rowsize = scan.rowsize;
  if (!args.schema  && scan.schema)  args.schema  = scan.schema;
  if (!args.prepared && scan.prepared) args.prepared = scan.prepared;
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.dir) resolveArgsFromDir(args.dir, args);

  if (!args.tablestats) {
    console.error('Usage: parse-cassandra.ts --tablestats <file> [--status <file>] [--info <file>] [--rowsize <file>] [--schema <file>] [--region us-east-1] [--pitr]');
    console.error('       parse-cassandra.ts --dir <directory> [--region us-east-1] [--pitr]');
    console.error('');
    console.error('Note: --dir reads all files at the specified path using the invoking user\'s permissions.');
    process.exit(1);
  }

  // ── Parse files using ParsingHelpers.ts ──────────────────────────────────

  const tablestats = parse_nodetool_tablestats(fs.readFileSync(args.tablestats, 'utf8'));
  
  const statusData = args.status
    ? parseNodetoolStatus(fs.readFileSync(args.status, 'utf8'))
    : new Map<string, number>();
  const rowSizeData = args.rowsize
    ? parseRowSizeInfo(fs.readFileSync(args.rowsize, 'utf8'))
    : {};

  // Group info files by DC
  const nodesByDc = new Map<string, Array<{ id: string; uptime_seconds: number }>>();
  for (const infoFile of args.info) {
    const { dc, id, uptime_seconds } = parseNodetoolInfo(fs.readFileSync(infoFile, 'utf8'));
    if (!nodesByDc.has(dc)) nodesByDc.set(dc, []);
    nodesByDc.get(dc)!.push({ id, uptime_seconds });
  }

  // Fall back to status DCs or placeholder if no info files
  if (nodesByDc.size === 0) {
    const dcNames = statusData.size > 0 ? [...statusData.keys()] : ['datacenter1'];
    const SECONDS_PER_MONTH = (365 / 12) * 86400;
    for (const dc of dcNames) {
      nodesByDc.set(dc, [{ id: 'node0', uptime_seconds: SECONDS_PER_MONTH }]);
    }
  }
  if (statusData.size === 0) {
    for (const [dc, nodes] of nodesByDc.entries()) statusData.set(dc, nodes.length);
  }

  const dcNames = [...nodesByDc.keys()];
  const schemaContent = args.schema ? fs.readFileSync(args.schema, 'utf8') : null;
  const schema = schemaContent ? parse_cassandra_schema(schemaContent, dcNames[0]) : null;
  const compatibility: CompatibilityInfo | null = schemaContent
    ? parse_cassandra_schema_compatibility(schemaContent)
    : null;
  const preparedContent = args.prepared ? fs.readFileSync(args.prepared, 'utf8') : null;
  const queryPatterns: QueryPatternsInfo | null = preparedContent
    ? parse_prepared_statements(preparedContent)
    : null;
  const preparedTtlTables = queryPatterns
    ? new Set(Object.keys(queryPatterns.ttl_tables))
    : undefined;

  // Convert SchemaInfo → NodePayload schema shape (drop 'class' and 'tables', keep 'datacenters')
  const nodeSchema = schema
    ? Object.fromEntries(Object.entries(schema).map(([ks, v]) => [ks, { datacenters: v.datacenters }]))
    : undefined;

  // ── Build Samples structure for PricingFormulas.ts ────────────────────────

  const samples: Samples = {};
  for (const [dc, nodes] of nodesByDc.entries()) {
    samples[dc] = {};
    for (const node of nodes) {
      samples[dc][node.id] = {
        tablestats_data: tablestats,
        schema: nodeSchema,
        info_data: { uptime_seconds: node.uptime_seconds },
        row_size_data: rowSizeData,
      };
    }
  }

  // ── Aggregate using PricingFormulas.ts ────────────────────────────────────

  const cassandraSet = buildCassandraLocalSet(samples, statusData, { preparedTtlTables });

  const estimateResults: EstimateResults = {};
  for (const dc of dcNames) {
    const aggregates = getKeyspaceCassandraAggregate(cassandraSet, dc);
    // Apply use_backup flag per keyspace
    for (const agg of Object.values(aggregates)) {
      (agg as KeyspaceAggregate & { use_backup: boolean }).use_backup = args.pitr;
    }
    estimateResults[dc] = aggregates;
  }

  // ── Price using calculatePricingEstimate from PricingFormulas.ts ──────────

  const longRegion = regionsMap[args.region] ?? args.region;
  const datacenters: DatacenterRef[] = dcNames.map(name => ({ name, nodeCount: statusData.get(name) ?? 0 }));
  const regions: Record<string, string> = Object.fromEntries(dcNames.map(dc => [dc, longRegion]));

  const pricing: PricingEstimateResult | null = calculatePricingEstimate(datacenters, regions, estimateResults);
  if (!pricing) { console.error('Failed to calculate pricing — check region and input files.'); process.exit(1); }

  // ── Build summary output (same shape as calculate.js) ────────────────────

  const {
    reads_on_demand: sumOdRead, writes_on_demand: sumOdWrite,
    ttl_deletes: sumTtl, storage: sumStorage, backup: sumBackup,
    reads_provisioned: sumProvRead, writes_provisioned: sumProvWrite,
  } = aggregatePricingTotals(pricing);

  let compatibilityReport: {
    has_issues: boolean;
    summary: {
      total_issues: number;
      schema: {
        total_issues: number;
        keyspaces_affected: number;
        tables_affected: number;
        functions: number;
        aggregates: number;
      } | null;
      query_patterns: {
        lwt_in_unlogged_batch: number;
        aggregations: number;
        ttl_tables: number;
      } | null;
    };
    details: {
      schema: CompatibilityInfo | null;
      query_patterns: QueryPatternsInfo | null;
    };
  } | null = null;
  if (compatibility || queryPatterns) {
    let schemaSummary: {
      total_issues: number;
      keyspaces_affected: number;
      tables_affected: number;
      functions: number;
      aggregates: number;
    } | null = null;
    if (compatibility) {
      let total_table_issues = 0;
      let tables_affected = 0;
      for (const tables of Object.values(compatibility.keyspaces)) {
        for (const issue of Object.values(tables)) {
          const count = issue.indexes.length + issue.triggers.length + issue.materializedViews.length;
          if (count > 0) { tables_affected++; total_table_issues += count; }
        }
      }
      schemaSummary = {
        total_issues: total_table_issues + compatibility.functions + compatibility.aggregates,
        keyspaces_affected: Object.keys(compatibility.keyspaces).length,
        tables_affected,
        functions: compatibility.functions,
        aggregates: compatibility.aggregates,
      };
    }
    const querySummary = queryPatterns
      ? {
          lwt_in_unlogged_batch: queryPatterns.lwt_in_unlogged_batch.length,
          aggregations:          queryPatterns.aggregations.length,
          ttl_tables:            Object.keys(queryPatterns.ttl_tables).length,
        }
      : null;
    const total_issues =
      (schemaSummary?.total_issues ?? 0) +
      (querySummary?.lwt_in_unlogged_batch ?? 0) +
      (querySummary?.aggregations ?? 0);
    compatibilityReport = {
      has_issues: total_issues > 0,
      summary: { total_issues, schema: schemaSummary, query_patterns: querySummary },
      details: { schema: compatibility, query_patterns: queryPatterns },
    };
  }

  const result = {
    region: { short: args.region, long: longRegion },
    source: 'cassandra-diagnostic-files',
    datacenters,
    on_demand: {
      reads_strong: sumOdRead, reads_eventual: sumOdRead / 2,
      writes: sumOdWrite, ttl_deletes: sumTtl,
      storage: sumStorage, backup: sumBackup,
      total: pricing.total_monthly_on_demand_cost,
    },
    provisioned: {
      reads_strong: sumProvRead, reads_eventual: sumProvRead / 2,
      writes: sumProvWrite, ttl_deletes: sumTtl,
      storage: sumStorage, backup: sumBackup,
      total: pricing.total_monthly_provisioned_cost,
    },
    savings_plan_available: pricing.total_monthly_provisioned_cost_savings !== pricing.total_monthly_provisioned_cost,
    on_demand_savings_plan: {
      total: pricing.total_monthly_on_demand_cost_savings,
    },
    provisioned_savings_plan: {
      total: pricing.total_monthly_provisioned_cost_savings,
    },
    per_datacenter: pricing.total_datacenter_cost,
    compatibility: compatibilityReport,
    report_data: {
      datacenters,
      regions,
      estimateResults,
      pricing,
    },
  };

  console.log(JSON.stringify(result, null, 2));
}

main();
