export const system_keyspaces = new Set([
    'OpsCenter', 'dse_insights_local', 'solr_admin',
    'dse_system', 'HiveMetaStore', 'system_auth',
    'dse_analytics', 'system_traces', 'dse_audit', 'system',
    'dse_system_local', 'dsefs', 'system_distributed', 'system_schema',
    'dse_perf', 'dse_insights', 'system_backups', 'dse_security',
    'dse_leases', 'system_distributed_everywhere', 'reaper_db'
]);

export const REPLICATION_FACTOR = 3;

export const SECONDS_PER_MONTH = (365/12) * (24 * 60 * 60);

export const GIGABYTE = 1024 * 1024 * 1024;


