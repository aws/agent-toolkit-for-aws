#!/usr/bin/env npx ts-node
/**
 * calculate.ts
 *
 * Keyspaces Pricing Calculator — manual inputs mode.
 * Delegates all pricing logic to PricingFormulas.ts.
 *
 * Usage:
 *   npx ts-node --require tsconfig-paths/register --project tsconfig.scripts.json \
 *     scripts/calculate.ts <region> <reads/s> <writes/s> <rowSizeBytes> <storageGB> [ttl/s] [pitr]
 */

import {
  calculatePricingEstimate,
  calculateWriteUnitsPerOperation,
  calculateReadUnitsPerOperation,
  calculateTtlUnitsPerOperation,
  type DatacenterRef,
  type EstimateResults,
  type PricingEstimateResult,
} from './calculator/PricingFormulas';

const regionsMap: Record<string, string> = require('../assets/data/regions.json');

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  if (args.length < 5) {
    console.error('Usage: calculate.ts <region> <reads/s> <writes/s> <rowSizeBytes> <storageGB> [ttl/s] [pitr]');
    process.exit(1);
  }

  const [regionArg, readsArg, writesArg, rowSizeArg, storageArg, ttlArg = '0', pitrArg = 'false'] = args;

  const longRegion = regionsMap[regionArg] ?? regionArg;
  const reads_per_second       = Number(readsArg);
  const writes_per_second      = Number(writesArg);
  const avg_row_size_bytes     = Number(rowSizeArg);
  const storage_gb             = Number(storageArg);
  const ttls_per_second        = Number(ttlArg);
  const pitr_enabled           = pitrArg === 'true';

  // Input validation
  if (isNaN(reads_per_second) || reads_per_second < 0) { console.error('reads_per_second must be a non-negative number'); process.exit(1); }
  if (isNaN(writes_per_second) || writes_per_second < 0) { console.error('writes_per_second must be a non-negative number'); process.exit(1); }
  if (isNaN(avg_row_size_bytes) || avg_row_size_bytes <= 0) { console.error('avg_row_size_bytes must be a positive number'); process.exit(1); }
  if (isNaN(storage_gb) || storage_gb < 0) { console.error('storage_gb must be a non-negative number'); process.exit(1); }
  if (isNaN(ttls_per_second) || ttls_per_second < 0) { console.error('ttls_per_second must be a non-negative number'); process.exit(1); }

  // Build inputs for calculatePricingEstimate
  const datacenters: DatacenterRef[] = [{ name: regionArg, nodeCount: 0 }];
  const regions: Record<string, string> = { [regionArg]: longRegion };
  const estimateResults: EstimateResults = {
    [regionArg]: {
      default: {
        keyspace_name: 'default',
        keyspace_type: 'user',
        replication_factor: 3,
        total_live_space_gb: storage_gb,
        uncompressed_single_replica_gb: storage_gb,
        avg_read_row_size_bytes: avg_row_size_bytes,
        avg_write_row_size_bytes: avg_row_size_bytes,
        reads_per_second,
        writes_per_second,
        ttls_per_second,
        use_backup: pitr_enabled,
      },
    },
  };

  const pricing: PricingEstimateResult | null = calculatePricingEstimate(datacenters, regions, estimateResults);
  if (!pricing) {
    console.error(`Region not found: ${longRegion}`);
    process.exit(1);
  }

  // Extract per-keyspace costs from the result
  const dcCost = pricing.total_datacenter_cost[regionArg];
  const kc = dcCost.keyspaceCosts['default'];

  const odTotal   = pricing.total_monthly_on_demand_cost;
  const provTotal = pricing.total_monthly_provisioned_cost;
  const odTotalSP   = pricing.total_monthly_on_demand_cost_savings;
  const provTotalSP = pricing.total_monthly_provisioned_cost_savings;
  const savingsPlanAvailable = odTotalSP !== odTotal || provTotalSP !== provTotal;

  const result = {
    region: { short: regionArg, long: longRegion },
    inputs: {
      reads_per_second,
      writes_per_second,
      avg_row_size_bytes,
      storage_gb,
      ttls_per_second,
      pitr_enabled,
    },
    units_per_operation: {
      write: calculateWriteUnitsPerOperation(avg_row_size_bytes),
      read:  calculateReadUnitsPerOperation(avg_row_size_bytes),
      ttl:   calculateTtlUnitsPerOperation(avg_row_size_bytes),
    },
    on_demand: {
      reads_strong:   kc.reads_on_demand,
      reads_eventual: kc.reads_on_demand / 2,
      writes:         kc.writes_on_demand,
      ttl_deletes:    kc.ttlDeletes,
      storage:        kc.storage,
      backup:         kc.backup,
      total:          odTotal,
    },
    provisioned: {
      reads_strong:   kc.reads_provisioned,
      reads_eventual: kc.reads_provisioned / 2,
      writes:         kc.writes_provisioned,
      ttl_deletes:    kc.ttlDeletes,
      storage:        kc.storage,
      backup:         kc.backup,
      total:          provTotal,
    },
    savings_plan_available: savingsPlanAvailable,
    on_demand_savings_plan: savingsPlanAvailable ? {
      reads_strong:   kc.reads_on_demand_savings,
      reads_eventual: kc.reads_on_demand_savings / 2,
      writes:         kc.writes_on_demand_savings,
      ttl_deletes:    kc.ttlDeletes,
      storage:        kc.storage,
      backup:         kc.backup,
      total:          odTotalSP,
    } : null,
    provisioned_savings_plan: savingsPlanAvailable ? {
      reads_strong:   kc.reads_provisioned_savings,
      reads_eventual: kc.reads_provisioned_savings / 2,
      writes:         kc.writes_provisioned_savings,
      ttl_deletes:    kc.ttlDeletes,
      storage:        kc.storage,
      backup:         kc.backup,
      total:          provTotalSP,
    } : null,
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
