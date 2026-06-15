export const HOURS_PER_MONTH = (365 / 12) * 24;
export const WRITE_UNIT_SIZE = 1024; // 1KB
export const READ_UNIT_SIZE = 4096; // 4KB

// --- Return types ---

export interface TablestatsData {
  space_used: number;
  compression_ratio: number;
  read_count: number;
  write_count: number;
}

export interface NodetoolInfoResult {
  uptime_seconds: number;
  dc: string;
  id: string;
}

interface KeyspaceSchemaEntry {
  class: string;
  datacenters: Record<string, number>;
  tables: string[];
}

export type SchemaInfo = Record<string, KeyspaceSchemaEntry>;
export type RowSizeInfo = Record<string, Record<string, string>>;
export type TablestatsResult = Record<string, Record<string, TablestatsData>>;

// --- Compatibility types ---

interface TableCompatibilityIssue {
  indexes: string[];
  triggers: string[];
  materializedViews: string[];
}

export interface CompatibilityInfo {
  functions: number;
  aggregates: number;
  keyspaces: Record<string, Record<string, TableCompatibilityIssue>>;
}

// --- Prepared-statement compatibility types ---

export interface QueryPatternIssue {
  prepared_id: string;
  query_string: string;
}

export interface AggregationIssue extends QueryPatternIssue {
  function: string; // e.g. 'COUNT', 'MIN'
}

export interface TtlTableInfo {
  uses_ttl: true;
  ttl_values: number[];
}

export interface QueryPatternsInfo {
  lwt_in_unlogged_batch: QueryPatternIssue[];
  aggregations: AggregationIssue[];
  ttl_tables: Record<string, TtlTableInfo>; // key is "ks.table" (lowercased)
}

interface TcoSingleNode {
  instance: { monthly_cost: number; [key: string]: unknown };
  storage?: { monthly_cost: number; [key: string]: unknown };
  backup?: { monthly_cost: number; [key: string]: unknown };
  network_out?: { monthly_cost: number; [key: string]: unknown };
  network_in?: { monthly_cost: number; [key: string]: unknown };
  license?: { monthly_cost: number; [key: string]: unknown };
}

interface TcoOperations {
  operator_hours: { monthly_cost: number; [key: string]: unknown };
}

export interface TcoData {
  single_node: TcoSingleNode;
  operations: TcoOperations;
}

// --- Parsers ---

export const parseNodetoolStatus = (content: string): Map<string, number> => {
  const lines = content.split('\n');
  const datacenters = new Map<string, number>();
  let currentDC: string | null = null;
  let nodeCount = 0;

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (/Datacenter\s*:/i.test(trimmedLine)) {
      if (currentDC) {
        datacenters.set(currentDC, nodeCount);
      }
      const match = trimmedLine.match(/Datacenter\s*:\s*(.+)/i);
      if (match?.[1]) {
        currentDC = match[1].trim();
        nodeCount = 0;
      }
    } else if (currentDC && (/^UN\b/i.test(trimmedLine) || /^DN\b/i.test(trimmedLine))) {
      nodeCount++;
    }
  }

  if (currentDC) {
    datacenters.set(currentDC, nodeCount);
  }

  return datacenters;
};

export const parse_nodetool_tablestats = (content: string): TablestatsResult => {
  const lines = content.split('\n');
  const data: TablestatsResult = {};
  let currentKeyspace: string | null = null;
  let currentTable: string | null = null;
  let spaceUsed: number | null = null;
  let compressionRatio: number | null = null;
  let writeCount: number | null = null;
  let readCount: number | null = null;

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (trimmedLine.startsWith('Keyspace')) {
      const keyspaceMatch = trimmedLine.match(/Keyspace\s*:\s*(.+)/);
      if (keyspaceMatch?.[1]) {
        currentKeyspace = keyspaceMatch[1].trim();
        if (!data[currentKeyspace]) {
          data[currentKeyspace] = {};
        }
      } else {
        currentKeyspace = null;
      }
      currentTable = null;
    }

    if (currentKeyspace && (trimmedLine.startsWith('Table:') || trimmedLine.startsWith('Table (index):'))) {
      const tableMatch = trimmedLine.match(/Table(?:\s*\(index\))?\s*:\s*(.+)/);
      if (tableMatch?.[1]) {
        currentTable = tableMatch[1].trim();
        spaceUsed = null;
        compressionRatio = null;
        writeCount = null;
        readCount = null;
      }
    }

    if (currentKeyspace && currentTable) {
      if (trimmedLine.includes('Space used (live):')) {
        const match = trimmedLine.match(/Space used \(live\)\s*:\s*(.+)/);
        if (match?.[1]) {
          spaceUsed = parseFloat(match[1].trim()) || 0;
        }
      } else if (trimmedLine.includes('SSTable Compression Ratio:')) {
        const match = trimmedLine.match(/SSTable Compression Ratio\s*:\s*(.+)/);
        if (match?.[1]) {
          const parsed = parseFloat(match[1].trim());
          compressionRatio = (!isNaN(parsed) && parsed > 0) ? parsed : 1;
        }
      } else if (trimmedLine.includes('Local read count:')) {
        const match = trimmedLine.match(/Local read count\s*:\s*(.+)/);
        if (match?.[1]) {
          readCount = parseFloat(match[1].trim()) || 0;
        }
      } else if (trimmedLine.includes('Local write count:')) {
        const match = trimmedLine.match(/Local write count\s*:\s*(.+)/);
        if (match?.[1]) {
          writeCount = parseFloat(match[1].trim()) || 0;
        }

        if (
          spaceUsed !== null &&
          compressionRatio !== null &&
          readCount !== null &&
          writeCount !== null
        ) {
          data[currentKeyspace][currentTable] = {
            space_used: spaceUsed,
            compression_ratio: compressionRatio,
            read_count: readCount,
            write_count: writeCount,
          };
          currentTable = null;
          spaceUsed = null;
          compressionRatio = null;
          writeCount = null;
          readCount = null;
        }
      }
    }
  }

  return data;
};

export const parseNodetoolInfo = (content: string): NodetoolInfoResult => {
  const lines = content.split('\n');
  let uptimeSeconds = 1;
  let id = '';
  let dc = '';

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (/Uptime\s*\(seconds\)/i.test(trimmedLine)) {
      const match = trimmedLine.match(/Uptime\s*\(seconds\)\s*:\s*(.+)/i);
      if (match?.[1]) {
        const parsed = parseFloat(match[1].trim());
        if (isNaN(parsed)) {
          throw new Error(`Error parsing uptime in seconds: ${match[1].trim()}`);
        }
        uptimeSeconds = parsed;
      }
    }

    if (/^ID\s*:/i.test(trimmedLine)) {
      const match = trimmedLine.match(/^ID\s*:\s*(.+)/i);
      if (match?.[1]) {
        id = match[1].trim();
      }
    }

    if (/Data\s+Center\s*:/i.test(trimmedLine)) {
      const match = trimmedLine.match(/Data\s+Center\s*:\s*(.+)/i);
      if (match?.[1]) {
        dc = match[1].trim();
      }
    }
  }

  return { uptime_seconds: uptimeSeconds, dc, id };
};

export const parse_cassandra_schema = (schemaContent: string, datacenter: string): SchemaInfo => {
  const ksPattern = /CREATE KEYSPACE (\w+)\s+WITH replication = \{[^}]*'class': '(\w+)'(?:,\s*)?([^}]*)\}/gi;
  const tablePattern = /CREATE TABLE (\w+)\.(\w+)/gi;

  const keyspaces: Array<{ name: string; class: string; rest: string }> = [];
  let ksMatch: RegExpExecArray | null;
  while ((ksMatch = ksPattern.exec(schemaContent)) !== null) {
    keyspaces.push({ name: ksMatch[1], class: ksMatch[2], rest: ksMatch[3] });
  }

  const tables: Array<{ keyspace: string; table: string }> = [];
  let tableMatch: RegExpExecArray | null;
  while ((tableMatch = tablePattern.exec(schemaContent)) !== null) {
    tables.push({ keyspace: tableMatch[1], table: tableMatch[2] });
  }

  const ksInfo: SchemaInfo = {};
  for (const ks of keyspaces) {
    const dcRepl: Record<string, number> = {};
    if (ks.class === 'NetworkTopologyStrategy') {
      const dcEntries = ks.rest.match(/'([^']+)':\s*'(\d+)'/g);
      if (dcEntries) {
        for (const entry of dcEntries) {
          const entryMatch = entry.match(/'([^']+)':\s*'(\d+)'/);
          if (entryMatch) {
            dcRepl[entryMatch[1]] = parseInt(entryMatch[2], 10);
          }
        }
      }
    } else if (ks.class === 'SimpleStrategy') {
      const rfMatch = ks.rest.match(/'replication_factor':\s*'(\d+)'/);
      if (rfMatch) {
        dcRepl[datacenter] = parseInt(rfMatch[1], 10);
      }
    }
    ksInfo[ks.name] = { class: ks.class, datacenters: dcRepl, tables: [] };
  }

  for (const table of tables) {
    if (ksInfo[table.keyspace]) {
      ksInfo[table.keyspace].tables.push(table.table);
    }
  }

  return ksInfo;
};

/**
 * Scan a CQL schema dump for features unsupported by Amazon Keyspaces:
 *   - CREATE INDEX        → table-level
 *   - CREATE TRIGGER      → table-level
 *   - CREATE MATERIALIZED VIEW → table-level (attached to the base table)
 *   - CREATE FUNCTION     → keyspace-level (counted globally)
 *   - CREATE AGGREGATE    → keyspace-level (counted globally)
 */
export const parse_cassandra_schema_compatibility = (schemaContent: string): CompatibilityInfo => {
  const result: CompatibilityInfo = {
    functions: 0,
    aggregates: 0,
    keyspaces: {},
  };

  const ensureTable = (ks: string, table: string): TableCompatibilityIssue => {
    if (!result.keyspaces[ks]) result.keyspaces[ks] = {};
    if (!result.keyspaces[ks][table]) {
      result.keyspaces[ks][table] = { indexes: [], triggers: [], materializedViews: [] };
    }
    return result.keyspaces[ks][table];
  };

  // CREATE [CUSTOM] INDEX [IF NOT EXISTS] <name> ON <ks>.<table> ...
  const indexPattern = /CREATE\s+(?:CUSTOM\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\.(\w+)/gi;
  let m: RegExpExecArray | null;
  while ((m = indexPattern.exec(schemaContent)) !== null) {
    const [, indexName, ks, table] = m;
    ensureTable(ks, table).indexes.push(indexName);
  }

  // CREATE TRIGGER [IF NOT EXISTS] <name> ON <ks>.<table> ...
  const triggerPattern = /CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\.(\w+)/gi;
  while ((m = triggerPattern.exec(schemaContent)) !== null) {
    const [, triggerName, ks, table] = m;
    ensureTable(ks, table).triggers.push(triggerName);
  }

  // CREATE MATERIALIZED VIEW [IF NOT EXISTS] <ks>.<view> AS SELECT ... FROM <ks>.<base_table>
  const mvPattern = /CREATE\s+MATERIALIZED\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\.(\w+)\s+AS\s+SELECT\s+[\s\S]*?\s+FROM\s+(\w+)\.(\w+)/gi;
  while ((m = mvPattern.exec(schemaContent)) !== null) {
    const [, , viewName, baseKs, baseTable] = m;
    ensureTable(baseKs, baseTable).materializedViews.push(viewName);
  }

  // CREATE [OR REPLACE] FUNCTION [IF NOT EXISTS] <ks>.<name> ...
  const functionPattern = /CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\.(\w+)/gi;
  while ((m = functionPattern.exec(schemaContent)) !== null) {
    result.functions++;
  }

  // CREATE [OR REPLACE] AGGREGATE [IF NOT EXISTS] <ks>.<name> ...
  const aggregatePattern = /CREATE\s+(?:OR\s+REPLACE\s+)?AGGREGATE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\.(\w+)/gi;
  while ((m = aggregatePattern.exec(schemaContent)) !== null) {
    result.aggregates++;
  }

  return result;
};

/**
 * Parse the output of `SELECT JSON * FROM system.prepared_statements` (or
 * the newline-delimited JSON produced by prepared-statements-sampler.sh)
 * and detect Amazon Keyspaces compatibility concerns in the query text:
 *
 *   - LWT inside `BEGIN UNLOGGED BATCH` (not supported)
 *   - Aggregate function calls (COUNT / MIN / MAX / SUM / AVG — not supported)
 *   - `USING TTL <n>` per target table (informational — used to populate
 *     has_ttl for pricing when the base schema has no default TTL)
 *
 * UDF usage is intentionally not detected here — `CREATE FUNCTION` in the
 * schema is the source of truth, surfaced by parse_cassandra_schema_compatibility.
 *
 * Accepts either:
 *   - NDJSON (one JSON object per line), or
 *   - raw cqlsh output containing `{...}` lines mixed with header/footer
 *     noise (non-JSON lines are skipped).
 */
export const parse_prepared_statements = (content: string): QueryPatternsInfo => {
  const result: QueryPatternsInfo = {
    lwt_in_unlogged_batch: [],
    aggregations: [],
    ttl_tables: {},
  };

  const aggNames = ['COUNT', 'MIN', 'MAX', 'SUM', 'AVG'];

  for (const rawLine of content.split('\n')) {
    const line = rawLine.trim();
    if (!line.startsWith('{') || !line.endsWith('}')) continue;

    let stmt: { prepared_id?: string; query_string?: string; logged_keyspace?: string | null };
    try {
      stmt = JSON.parse(line);
    } catch {
      continue;
    }

    const query = stmt.query_string ?? '';
    const preparedId = stmt.prepared_id ?? '';
    if (!query) continue;
    const issueRef: QueryPatternIssue = { prepared_id: preparedId, query_string: query };

    // 1. LWT inside UNLOGGED BATCH
    //    BEGIN UNLOGGED BATCH ... (IF NOT EXISTS | IF EXISTS | IF <col>=) ... APPLY BATCH
    const unloggedBatch = /\bBEGIN\s+UNLOGGED\s+BATCH\b([\s\S]*?)\bAPPLY\s+BATCH\b/i.exec(query);
    if (unloggedBatch && /\bIF\s+(NOT\s+EXISTS\b|EXISTS\b|\w+\s*[=<>!])/i.test(unloggedBatch[1])) {
      result.lwt_in_unlogged_batch.push(issueRef);
    }

    // 2. Aggregations — look in SELECT projection. Simplest: any occurrence
    //    of a supported aggregate name followed by '(' inside a SELECT query.
    //    Guarded with a \b boundary + whitespace-tolerant '(' to avoid
    //    matching column names that happen to contain these words.
    if (/\bSELECT\b/i.test(query)) {
      for (const fn of aggNames) {
        const re = new RegExp(`\\b${fn}\\s*\\(`, 'i');
        if (re.test(query)) {
          result.aggregations.push({ ...issueRef, function: fn });
          break; // one finding per statement is enough
        }
      }
    }

    // 3. USING TTL per target table
    //    Match each USING ... TTL <n> occurrence, then associate it with the
    //    nearest preceding INSERT INTO / UPDATE target table.
    const ttlPattern = /\bUSING\b[\s\S]*?\bTTL\s+(\d+)/gi;
    let tm: RegExpExecArray | null;
    while ((tm = ttlPattern.exec(query)) !== null) {
      const ttlValue = parseInt(tm[1], 10);
      const before = query.substring(0, tm.index);
      // Find the last INSERT INTO / UPDATE before this USING TTL clause.
      const targetPattern = /\b(?:INSERT\s+INTO|UPDATE)\s+(?:"?(\w+)"?\.)?"?(\w+)"?/gi;
      let tgt: RegExpExecArray | null;
      let lastMatch: RegExpExecArray | null = null;
      while ((tgt = targetPattern.exec(before)) !== null) lastMatch = tgt;
      if (!lastMatch) continue;
      const ks = (lastMatch[1] ?? stmt.logged_keyspace ?? '').toLowerCase();
      const tbl = lastMatch[2].toLowerCase();
      if (!ks || !tbl) continue;
      const key = `${ks}.${tbl}`;
      if (!result.ttl_tables[key]) {
        result.ttl_tables[key] = { uses_ttl: true, ttl_values: [] };
      }
      if (!result.ttl_tables[key].ttl_values.includes(ttlValue)) {
        result.ttl_tables[key].ttl_values.push(ttlValue);
      }
    }
  }

  return result;
};

export const parseRowSizeInfo = (content: string): RowSizeInfo => {
  const lines = content.split('\n');
  const result: RowSizeInfo = {};

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (!/=/.test(trimmedLine) || /NoHostAvailable/i.test(trimmedLine)) {
      continue;
    }

    const match = trimmedLine.match(/^(.+?)\s*=\s*(.+)$/);
    if (!match) continue;

    const [, keyName, right] = match;
    const trimmedKeyName = keyName.trim();
    const trimmedRight = right.trim();
    if (!trimmedRight.startsWith('{') || !trimmedRight.endsWith('}')) {
      continue;
    }

    const inner = trimmedRight.slice(1, -1).trim();
    const fields = inner.split(',');
    const valueDict: Record<string, string> = {};
    for (const field of fields) {
      const trimmedField = field.trim();
      if (!/:\s*/.test(trimmedField)) continue;
      const [k, v] = trimmedField.split(':');
      if (!k || !v) continue;
      valueDict[k.trim()] = v.replace('bytes', '').trim();
    }
    result[trimmedKeyName] = valueDict;
  }
  return result;
};

// --- File type detection ---

export type CassandraFileType = 'tablestats' | 'status' | 'info' | 'rowsize' | 'schema' | 'tco' | 'prepared' | 'unknown';

export interface CassandraFileScan {
  tablestats: string[];   // filenames (multiple nodes allowed)
  status: string | null;
  info: string[];         // filenames (one per node)
  rowsize: string | null;
  schema: string | null;
  tco: string | null;
  prepared: string | null;
  unknown: string[];
}

export const isTablestatsFile = (content: string): boolean =>
  /Keyspace\s*:/i.test(content) && /Space used \(live\)/i.test(content);

export const isStatusFile = (content: string): boolean =>
  /Datacenter\s*:/i.test(content) && /^(U|D)(N|L|J|M)\s+/m.test(content);

export const isInfoFile = (content: string): boolean =>
  /^ID\s*:/im.test(content) && /Uptime\s*\(seconds\)/i.test(content);

export const isRowSizeFile = (content: string): boolean =>
  /\w+\.\w+\s*=\s*\{/.test(content) && /average\s*:\s*\d+\s*bytes/i.test(content);

export const isSchemaFile = (content: string): boolean =>
  /CREATE\s+(KEYSPACE|TABLE)/i.test(content);

export const isTcoFile = (content: string): boolean => {
  try {
    const obj = JSON.parse(content);
    return !!(obj?.single_node && obj?.operations);
  } catch {
    return false;
  }
};

// NDJSON (or cqlsh SELECT JSON) output of system.prepared_statements — any
// line containing a JSON object with both `prepared_id` and `query_string`
// keys counts as a match.
export const isPreparedStatementsFile = (content: string): boolean => {
  for (const rawLine of content.split('\n')) {
    const line = rawLine.trim();
    if (!line.startsWith('{') || !line.endsWith('}')) continue;
    try {
      const obj = JSON.parse(line);
      if (obj && typeof obj === 'object' && 'prepared_id' in obj && 'query_string' in obj) {
        return true;
      }
    } catch { /* skip */ }
  }
  return false;
};

export const detectFileType = (content: string): CassandraFileType => {
  if (isPreparedStatementsFile(content)) return 'prepared';
  if (isTablestatsFile(content)) return 'tablestats';
  if (isStatusFile(content)) return 'status';
  if (isInfoFile(content)) return 'info';
  if (isRowSizeFile(content)) return 'rowsize';
  if (isSchemaFile(content)) return 'schema';
  if (isTcoFile(content)) return 'tco';
  return 'unknown';
};

// Classify a set of files (filename → content) into their respective roles.
export const scanCassandraFiles = (files: Record<string, string>): CassandraFileScan => {
  const result: CassandraFileScan = {
    tablestats: [],
    status: null,
    info: [],
    rowsize: null,
    schema: null,
    tco: null,
    prepared: null,
    unknown: [],
  };

  for (const [name, content] of Object.entries(files)) {
    switch (detectFileType(content)) {
      case 'tablestats': result.tablestats.push(name); break;
      case 'status':     result.status  ??= name; break;
      case 'info':       result.info.push(name); break;
      case 'rowsize':    result.rowsize ??= name; break;
      case 'schema':     result.schema  ??= name; break;
      case 'tco':        result.tco     ??= name; break;
      case 'prepared':   result.prepared ??= name; break;
      default:           result.unknown.push(name); break;
    }
  }

  return result;
};

export const parseTCOInfo = (data: string): TcoData => {
  let obj: TcoData;
  try {
    obj = JSON.parse(data) as TcoData;
  } catch (err: unknown) {
    throw new Error(`Invalid JSON: ${(err as Error).message}`);
  }

  if (!obj.single_node || !obj.operations) {
    throw new Error("Invalid structure: expected 'single_node' and 'operations' fields");
  }
  if (!obj.single_node.instance || typeof obj.single_node.instance.monthly_cost !== 'number') {
    throw new Error("Invalid or missing 'instance.monthly_cost'");
  }
  if (!obj.operations.operator_hours || typeof obj.operations.operator_hours.monthly_cost !== 'number') {
    throw new Error("Invalid or missing 'operations.operator_hours.monthly_cost'");
  }

  return obj;
};
