#!/usr/bin/env node
// Migration telemetry emitter. Invoked by host hooks (Claude Code or Cursor);
// the agent itself only ever runs the consent subcommand:
//   node emit.mjs                    post-write: payload on stdin names the edited file
//   node emit.mjs --reconcile        end-of-turn: re-read state regardless of writer
//   node emit.mjs --session-end      teardown: final sweep for this session's runs
//   node emit.mjs consent <get|grant|revoke|status>
//
// Reads .migration/<id>/.phase-status.json (and .gate-failures.json, where the
// skill records a failed gate), diffs them against the co-located
// .telemetry-snapshot.json, and POSTs one event per transition to the endpoint
// in AWS_STARTUP_ADVISOR_TELEMETRY_ENDPOINT. Everything it needs is on disk:
// the run declares its owner via the owning_skill key in .phase-status.json,
// and a run with no declared owner emits nothing.
//
// Fail-open: every path exits 0 and surfaces nothing to the customer. The one
// deliberate exception to "the snapshot advances regardless" is a disabled
// endpoint (AWS_STARTUP_ADVISOR_TELEMETRY_ENDPOINT set to empty): nothing was
// attempted, so the snapshot is left alone and the run is reported in full
// once sending is re-enabled.

import { promises as fs } from "node:fs";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Identifiers leave here in lower case: the data lake behind the service
// accepts only lower-case UUIDs, while macOS uuidgen (what _init runs) mints
// upper-case ones, and the service itself accepts either and would relay a
// mixed-case id straight into a rejection downstream.
const asUuid = (value) => (UUID_RE.test(value) ? String(value).toLowerCase() : undefined);
const MIGRATION_SKILLS = new Set(["GCP_TO_AWS", "HEROKU_TO_AWS", "LLM_TO_BEDROCK"]);
const LOCK_STALE_MS = 60_000;
const POST_TIMEOUT_MS = 3_000;
// Claude Code gives all SessionEnd hooks one shared 1.5 s budget, and a timeout
// declared by a plugin hook does not raise it (only the customer's own settings
// can). A teardown sweep killed mid-flight would leave sent events unrecorded
// and repeat them later, so the sweep bounds itself: requests get whatever is
// left of the budget minus room to write the snapshot, and a run the deadline
// has already passed is left for the next trigger untouched.
const SESSION_END_BUDGET_MS = 1_500;
const SESSION_END_RESERVE_MS = 400;

// Production endpoint, compiled in so a shipped plugin needs no user setup.
// AWS_STARTUP_ADVISOR_TELEMETRY_ENDPOINT overrides it; setting the variable to
// an empty string disables sending entirely, and in that inert state snapshots
// are never advanced, so nothing is lost.
const DEFAULT_ENDPOINT =
  "https://us-east-1.prod.startup-advisor-extension.saws.activate.aws.dev/v1/plugin-telemetry-event";

function resolveEndpoint() {
  const env = process.env.AWS_STARTUP_ADVISOR_TELEMETRY_ENDPOINT;
  if (env === undefined) return DEFAULT_ENDPOINT;
  return env === "" ? null : env;
}

// How this invocation was triggered: "hook" (default) or "cli" via --via cli,
// the marker for an invocation made from a skill instruction instead of a hook.
function viaMode() {
  const i = process.argv.indexOf("--via");
  return i !== -1 && process.argv[i + 1] === "cli" ? "cli" : "hook";
}

// ---------------------------------------------------------------- utilities

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

// Absent and unreadable are different inputs: a missing snapshot means a new
// run, but a truncated one (a hook killed mid-write) must not, or the run is
// re-reported from RUN_STARTED.
const SNAPSHOT_UNREADABLE = Symbol("snapshot-unreadable");

function readSnapshot(file) {
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return SNAPSHOT_UNREADABLE;
  }
}

// Temp file plus rename, so a hook killed at the host's timeout cannot leave a
// half-written file where readSnapshot would find it.
function writeJson(file, value) {
  mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(value, null, 2));
  renameSync(tmp, file);
}

function pluginRoot() {
  // scripts/telemetry/emit.mjs → plugin root is two levels up.
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
}

function pluginVersion() {
  const manifest = readJson(path.join(pluginRoot(), ".claude-plugin", "plugin.json"));
  return typeof manifest?.version === "string" ? manifest.version : "0.0.0";
}

// Host detection. Cursor is checked first because it also exports Claude
// compatibility aliases (CLAUDE_PROJECT_DIR), so Claude Code markers are only
// trusted once Cursor is ruled out. Anything else reports OTHER rather than
// impersonating a known host: on hosts without hooks the emitter runs as a
// skill-invoked CLI, where a CLAUDE_CODE default would be wrong and undetectable.
function hostSource() {
  if (process.env.CURSOR_VERSION || process.env.CURSOR_PROJECT_DIR) return "CURSOR";
  if (process.env.CLAUDE_PLUGIN_ROOT || process.env.CLAUDECODE) return "CLAUDE_CODE";
  return "OTHER";
}

function stateDir() {
  return process.env.CLAUDE_PLUGIN_DATA || path.join(os.homedir(), ".aws-startups-plugins");
}

// installId is machine-level (one customer, many repos, one install), minted
// lazily on first use because there is no install-time hook to mint it at.
function getInstallId() {
  const file = path.join(stateDir(), "install.json");
  const existing = readJson(file);
  if (existing && UUID_RE.test(existing.installId)) return asUuid(existing.installId);
  const installId = crypto.randomUUID();
  try {
    writeJson(file, { installId, createdAt: new Date().toISOString() });
  } catch {
    /* read-only state dir: still emit under the fresh id */
  }
  return installId;
}

async function readStdin() {
  if (process.stdin.isTTY) return null;
  const chunks = [];
  try {
    for await (const chunk of process.stdin) chunks.push(chunk);
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return null;
  }
}

// -------------------------------------------------------------- run discovery

// A run directory is .migration/<id>/ containing .phase-status.json. Discovery
// starts from a directory and walks up a bounded number of levels; the nearest
// .migration/ tree wins, so runs from parent or sibling projects are not mixed in.
async function findRunDirs(startDir) {
  const runs = [];
  let dir = path.resolve(startDir || process.cwd());
  for (let depth = 0; depth < 4; depth++) {
    const migrationRoot = path.join(dir, ".migration");
    try {
      for (const entry of await fs.readdir(migrationRoot, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const runDir = path.join(migrationRoot, entry.name);
        if (existsSync(path.join(runDir, ".phase-status.json"))) runs.push(runDir);
      }
      break;
    } catch {
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return runs;
}

// --------------------------------------------------------------------- consent

// Consent has two homes. The plugin-wide record, written when the customer
// answers the plugin's single telemetry prompt, lives at
// ~/.aws-startups-plugins/telemetry.json (or the plugin data dir) and covers
// every project. The project-level record beside the runs is written by this
// emitter's own consent command. Across every record found, a recorded "no"
// wins: a plugin-wide no silences every project, and a project's stop-sharing
// command stays effective under a plugin-wide yes. Only then does any
// recorded "yes" count. Nothing is sent without one.
function consentFileFor(runDir) {
  return path.join(path.dirname(runDir), "telemetry.json");
}

function machineConsentFiles() {
  const home = path.join(os.homedir(), ".aws-startups-plugins", "telemetry.json");
  const data = path.join(stateDir(), "telemetry.json");
  return data === home ? [home] : [data, home];
}

// Every consent record on disk, plugin-wide ones first, each with its file.
function consentRecords(projectFile) {
  return [...machineConsentFiles(), projectFile]
    .map((file) => ({ file, record: readJson(file) }))
    .filter(({ record }) => record?.consent);
}

// The record that decides: a "revoked" anywhere, else the earliest "granted",
// since the moment consent was first given is what pre-consent history is
// measured against.
function effectiveConsent(records) {
  const at = ({ record }) => Date.parse(record.consentedAt ?? "") || Infinity;
  return records.find(({ record }) => record.consent === "revoked") ??
    records.filter(({ record }) => record.consent === "granted").sort((a, b) => at(a) - at(b))[0] ??
    null;
}

function consentRecordFor(runDir) {
  return effectiveConsent(consentRecords(consentFileFor(runDir)))?.record ?? null;
}

function consentGrantedFor(runDir) {
  if (process.env.DO_NOT_TRACK === "1") return false;
  if (process.env.AWS_STARTUP_ADVISOR_TELEMETRY === "0") return false;
  return consentRecordFor(runDir)?.consent === "granted";
}

// The state file's mtime, not its agent-written last_updated field, is compared
// with the consent record's timestamp: the mtime is set by the OS and cannot be
// mistyped by the agent. Unknown on either side means "not before". The slack
// absorbs coarse filesystem timestamps and same-moment writes: a state file
// written within two seconds of consent is a live run, and under-reporting a
// live run costs more than reporting two seconds of history.
const PRE_CONSENT_SLACK_MS = 2_000;

function predatesConsent(runDir, statusFile) {
  const consentedAt = Date.parse(consentRecordFor(runDir)?.consentedAt ?? "");
  let mtime;
  try {
    mtime = statSync(statusFile).mtimeMs;
  } catch {
    return false;
  }
  return Number.isFinite(consentedAt) && mtime < consentedAt - PRE_CONSENT_SLACK_MS;
}

// The skills routinely cd into .migration/<id>/ to work with relative paths, so
// the consent command must find the migration root from anywhere inside the
// project, not only from its root.
function findMigrationRoot(startDir) {
  let dir = path.resolve(startDir);
  for (let depth = 0; depth < 6; depth++) {
    if (path.basename(dir) === ".migration") return dir;
    const candidate = path.join(dir, ".migration");
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(".migration"); // nothing found: report against cwd
}

function runConsentCommand(action) {
  const migrationRoot = findMigrationRoot(process.cwd());
  const file = path.join(migrationRoot, "telemetry.json");
  const write = (consent) => {
    if (!existsSync(migrationRoot)) {
      process.stdout.write("no .migration directory here; create the run first\n");
      return;
    }
    writeJson(file, {
      consent,
      installId: getInstallId(),
      consentedAt: new Date().toISOString(),
      version: 1,
    });
    process.stdout.write(`${consent}\n`);
  };
  const decision = effectiveConsent(consentRecords(file));
  switch (action) {
    case "get":
      process.stdout.write(`${decision?.record.consent ?? "unset"}\n`);
      return;
    case "status": {
      const install = readJson(path.join(stateDir(), "install.json"));
      process.stdout.write(
        JSON.stringify(
          {
            consent: decision?.record.consent ?? "unset",
            consentFile: decision?.file ?? file,
            stateDir: stateDir(),
            installId: install?.installId ?? "not yet minted",
            endpoint: resolveEndpoint() ?? "disabled",
          },
          null,
          2,
        ) + "\n",
      );
      return;
    }
    case "grant":
      write("granted");
      return;
    case "revoke":
      // A decline is a decision too: recorded locally so the customer is not
      // asked again. No event is sent for it.
      write("revoked");
      return;
    default:
      process.stdout.write("usage: emit.mjs consent <get|grant|revoke|status>\n");
  }
}

// ------------------------------------------------------------------- the lock

// Steps read-snapshot → POST → write-snapshot span network calls, and the
// post-write and reconcile triggers can overlap. An exclusive per-run lock
// (directory creation as atomic test-and-set) is the one duplication defence
// no downstream layer can substitute for: overlapping invocations would read
// the same "before" state and report the same transitions twice.
function acquireLock(runDir) {
  const lock = path.join(runDir, ".telemetry-lock");
  try {
    mkdirSync(lock);
    return lock;
  } catch (err) {
    if (err?.code !== "EEXIST") return null; // unwritable dir: emit nothing
    try {
      if (Date.now() - statSync(lock).mtimeMs > LOCK_STALE_MS) {
        rmSync(lock, { recursive: true, force: true });
        mkdirSync(lock);
        return lock;
      }
    } catch {
      /* raced or vanished; treat as held */
    }
    return null; // holder is about to report the same transitions
  }
}

function releaseLock(lock) {
  try {
    rmSync(lock, { recursive: true, force: true });
  } catch {
    /* already gone */
  }
}

// ------------------------------------------------------ model vocabularies

// Every value sent is checked against the model's enums before it leaves: the
// service rejects a whole request on one unknown member, so an unmapped value
// is omitted (or, for a phase name, the event is skipped) rather than sent.
const PHASES = new Set(["DISCOVER", "CLARIFY", "DESIGN", "ESTIMATE", "WORKSHOP", "GENERATE", "FEEDBACK"]);

// Statuses that resolve a phase. The DSL lets a skill resolve a phase without
// running it (skipped, not_applicable); those are transitions to report too.
const RESOLVED_STATUS = {
  completed: "SUCCESS",
  skipped: "SKIPPED",
  not_applicable: "NOT_APPLICABLE",
  failed: "FAILED",
};

const RUN_MODE = { decide: "DECIDE", decide_and_execute: "DECIDE_AND_EXECUTE" };

// Mirrors the reason= constants of the interpreter's GATE_FAIL line.
const FAILURE_REASON = { missing: "MISSING", invalid: "INVALID", stale_downstream: "STALE_DOWNSTREAM" };

const mapEnum = (table, value) => (value == null ? undefined : table[String(value).toLowerCase()]);

// The skills write lowercase, hyphenated or spaced values ("multi-az-ha",
// "us-east-1", "elastic_beanstalk"); the model spells the same members in
// UPPER_SNAKE. Normalise, then admit only members the model declares.
const toEnum = (members, value) => {
  if (value == null) return undefined;
  const key = String(value).trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return members.has(key) ? key : undefined;
};

const PRICING_SOURCE = {
  live: "LIVE",
  cached: "CACHED",
  cached_fallback: "CACHED_FALLBACK",
  cached_stale: "CACHED_STALE",
  unavailable: "UNAVAILABLE",
};

// defer_for_evidence is heroku's spelling of the same verdict.
const RECOMMENDATION_OUTCOME = {
  go: "GO",
  conditional_go: "CONDITIONAL_GO",
  defer: "DEFER",
  defer_for_evidence: "DEFER",
  stay: "STAY",
};

// preferences.json metadata.clarify_mode as the clarify phases write it.
// simple_hybrid has no model member and is omitted.
const CLARIFY_MODE = { wizard: "WIZARD", full: "FULL", fast_path: "FAST" };

// Mirrors the `current_costs.source` vocabulary the skills write.
// estimated_from_token_volume is the AI route (it prices tokens, not
// infrastructure); preferences is the spend band the customer stated in
// Clarify (estimate-infra Part 1), so it is the customer's own figure.
const SPEND_BASIS = {
  billing_data: "BILLING_DATA",
  inventory_estimate: "INVENTORY_ESTIMATE",
  live_prices_plus_cache: "LIVE_PRICES_PLUS_CACHE",
  pricing_cache: "PRICING_CACHE",
  user_provided: "USER_PROVIDED",
  preferences: "USER_PROVIDED",
  unavailable: "UNAVAILABLE",
  estimated_from_token_volume: "TOKEN_VOLUME_ESTIMATE",
};

// ai-workload-profile.json summary.ai_source, the source for a run with no
// infrastructure inventory. "both" names two providers and is omitted.
const AI_SOURCE = { openai: "OPENAI", anthropic: "ANTHROPIC", gemini: "GCP", other: "OTHER" };

const COMPLEXITY_TIER = new Set(["SMALL", "MEDIUM", "LARGE"]);
// The discover preview's coarser signal, used before a tiered artifact exists.
const COMPLEXITY_SIGNAL = { likely_simple: "SMALL", standard: "MEDIUM", complex: "LARGE" };
const RECOMMENDATION_CONFIDENCE = new Set(["LOW", "MEDIUM", "HIGH"]);
const VALIDATION_STATUS = new Set(["PASSED", "PASSED_DEGRADED_OFFLINE", "FAILED"]);
const COMPLIANCE = new Set(["NONE", "UNKNOWN", "HIPAA", "PCI", "SOC2", "GDPR", "CCPA", "FEDRAMP"]);
const COMPLIANCE_ALIAS = { PCI_DSS: "PCI", SOC_2: "SOC2", FED_RAMP: "FEDRAMP" };
const COMPLIANCE_ACCEPTED = new Set([...COMPLIANCE, ...Object.keys(COMPLIANCE_ALIAS)]);
const AVAILABILITY = new Set(["SINGLE_AZ", "MULTI_AZ", "MULTI_AZ_HA", "MULTI_REGION"]);
const CUTOVER_STRATEGY = new Set(["MAINTENANCE_WINDOW_WEEKLY", "MAINTENANCE_WINDOW_MONTHLY", "FLEXIBLE", "ZERO_DOWNTIME"]);
const DATABASE_TRAFFIC = new Set(["STEADY", "READ_HEAVY", "WRITE_HEAVY"]);
const COMPUTE_POSTURE = new Set(["EKS_MANAGED", "EKS_OR_ECS", "ECS_FARGATE", "EKS", "ECS", "ELASTIC_BEANSTALK"]);
const TARGET_REGION = new Set([
  "US_EAST_1", "US_EAST_2", "US_WEST_1", "US_WEST_2", "CA_CENTRAL_1",
  "EU_WEST_1", "EU_WEST_2", "EU_WEST_3", "EU_CENTRAL_1", "EU_NORTH_1",
  "AP_SOUTH_1", "AP_SOUTHEAST_1", "AP_SOUTHEAST_2", "AP_NORTHEAST_1", "AP_NORTHEAST_2", "AP_NORTHEAST_3",
  "SA_EAST_1",
]);
// The skills write db_size as a human range ("<10GB", "10-100GB"), not a token.
const DB_SIZE = {
  "<10gb": "DB_UNDER_10GB",
  "10-100gb": "DB_10_100GB",
  "100-500gb": "DB_100_500GB",
  ">500gb": "DB_OVER_500GB",
  unknown: "UNKNOWN",
};
const PROJECTED_COST_MAX = 10_000_000; // model @range

// ------------------------------------------------------ attribute derivation

// Pricing provenance is written either as a bare string or as an object
// { status, fallback_staleness: { is_stale } }; CACHED_STALE is composed from
// the object form.
function toPricingSource(raw) {
  if (raw == null) return undefined;
  const isObject = typeof raw === "object";
  const mapped = mapEnum(PRICING_SOURCE, isObject ? raw.status : raw);
  if (!mapped) return undefined;
  const stale = isObject && raw.fallback_staleness?.is_stale === true;
  return mapped === "CACHED" && stale ? "CACHED_STALE" : mapped;
}

// Matched against resource TYPES only, never the serialised inventory: the
// inventory carries discovery metadata such as classification_source:
// "llm_inference", which would read as "the customer runs AI".
const AI_TYPE =
  /vertex|aiplatform|notebooks|discovery_engine|automl|ml_engine|dialogflow|document_ai|bedrock|sagemaker|comprehend/;
const DB_TYPE =
  /sql|postgres|mysql|mongo|redis|firestore|spanner|bigtable|datastore|memorystore|alloydb|rds|aurora|dynamo|elasticache|documentdb/;

// Heroku records an add-on as resource_type "addon" with the service under
// config.addon_service, so that is part of a resource's type here.
const resourceTypes = (resources) =>
  resources
    .map((r) => `${r?.type ?? r?.resource_type ?? ""} ${r?.config?.addon_service ?? ""}`)
    .join(" ")
    .toLowerCase();

// Monthly spend on the SOURCE platform. The key name varies by skill, phase and
// route: gcp writes current_costs.gcp_monthly, heroku writes
// heroku_monthly_baseline / current_heroku_monthly, the billing-only route
// writes total_monthly_spend for a MEASURED figure.
const SOURCE_SPEND_KEYS = [
  "gcp_monthly_spend",
  "gcp_monthly",
  "gcp_monthly_usd",
  "gcp_monthly_baseline",
  "current_gcp_monthly",
  "total_monthly_spend",
  "gcp_total_monthly",
  "total_monthly",
  "gcp_monthly_ai_spend",
  "total_current_ai_monthly",
  "heroku_monthly",
  "heroku_monthly_estimated",
  "heroku_monthly_baseline",
  "current_heroku_monthly",
];

function toSpendBand(amount) {
  if (typeof amount !== "number" || !Number.isFinite(amount) || amount < 0) return undefined;
  if (amount < 100) return "UNDER_100";
  if (amount < 1000) return "FROM_100_TO_1K";
  if (amount < 10000) return "FROM_1K_TO_10K";
  return "OVER_10K";
}

// Integer USD within the model's range; anything else is omitted rather than
// clamped, since a clamped cost would read as a real figure.
function toProjectedUsd(value) {
  const n = typeof value === "string" ? Number(value) : value;
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0 || n > PROJECTED_COST_MAX) return undefined;
  return Math.round(n);
}

// "±5-10%", "±20-30%+", "±5% (billing)": the upper bound of the first range
// decides the band. HIGH ≤10, MEDIUM ≤20, LOW beyond.
function toAccuracyBand(text) {
  if (typeof text !== "string") return undefined;
  const m = text.match(/±?\s*(\d+)(?:\s*-\s*(\d+))?\s*%/);
  if (!m) return undefined;
  const upper = Number(m[2] ?? m[1]);
  if (upper <= 10) return "HIGH";
  if (upper <= 20) return "MEDIUM";
  return "LOW";
}

// "100%", "97%", 100: FULL at 100, NEAR_COMPLETE from 90, PARTIAL below.
function toCoverage(value) {
  if (value == null || value === "") return undefined;
  const n = typeof value === "number" ? value : Number(String(value).replace("%", "").trim());
  if (!Number.isFinite(n)) return undefined;
  if (n >= 100) return "FULL";
  if (n >= 90) return "NEAR_COMPLETE";
  return "PARTIAL";
}

// A design constraint is an object with the interpreted value under `value`
// (gcp) or `default` (heroku's compute_target); older artifacts hold the bare
// value.
function constraintValue(preferences, key) {
  const raw = preferences?.design_constraints?.[key];
  if (raw == null) return undefined;
  if (typeof raw === "object" && !Array.isArray(raw)) return raw.value ?? raw.default;
  return raw;
}

function toComplianceList(raw) {
  const values = Array.isArray(raw) ? raw : raw == null ? [] : [raw];
  const out = new Set();
  for (const v of values) {
    const key = toEnum(COMPLIANCE_ACCEPTED, v);
    if (key) out.add(COMPLIANCE_ALIAS[key] ?? key);
  }
  return out.size ? [...out] : undefined;
}

const SKILL_INVENTORY = {
  GCP_TO_AWS: { inventory: "gcp-resource-inventory.json", provider: "GCP" },
  HEROKU_TO_AWS: { inventory: "heroku-resource-inventory.json", provider: "HEROKU" },
};

// The platform being left, read from what Discover found rather than from the
// owning skill: a gcp-to-aws run may be an AI-only workload (its own route, or
// delegated from llm-to-bedrock) with no GCP infrastructure at all, and calling
// that GCP would be wrong. Before Discover has written anything it is unknown
// and omitted.
function sourceProvider(runDir, spec) {
  if (spec && existsSync(path.join(runDir, spec.inventory))) return spec.provider;
  const aiProfile = readJson(path.join(runDir, "ai-workload-profile.json"));
  return mapEnum(AI_SOURCE, aiProfile?.summary?.ai_source);
}

// Every estimation artifact present, in preference order: an AI-primary run
// writes both infra and AI files, and each attribute is taken from the first
// artifact that actually supplies it.
const readEstimates = (dir) =>
  ["estimation-infra.json", "estimation-ai.json", "estimation-billing.json"]
    .map((name) => readJson(path.join(dir, name)))
    .filter(Boolean);

// Where a route records the source-platform cost, in preference order: the
// infra and AI routes use current_costs, the billing-only route gcp_baseline,
// and heroku's assembler also rolls it into financial_summary.
const costContainers = (estimate) =>
  [estimate.current_costs, estimate.gcp_baseline, estimate.cost_comparison, estimate.financial_summary].filter(
    (c) => c && typeof c === "object",
  );

// The three cost tiers are written flat (aws_monthly_*), with older shapes
// nesting them under option_*/tiers.
function projectedCost(estimate, tier, option) {
  const pc = estimate.projected_costs ?? {};
  return toProjectedUsd(pc[`aws_monthly_${tier}`] ?? pc[option]?.aws_monthly ?? pc.tiers?.[tier]?.monthly);
}

// The migration's complexity tier: written by generate (gcp) or estimate
// (heroku); before either exists, the discover preview's coarser signal.
function complexityTier(runDir) {
  for (const name of ["generation-infra.json", "generation-billing.json", "generation-ai.json", "estimation-infra.json"]) {
    const artifact = readJson(path.join(runDir, name));
    const tier = toEnum(COMPLEXITY_TIER, artifact?.complexity_tier ?? artifact?.estimation_summary?.complexity_tier);
    if (tier) return tier;
  }
  const preview = readJson(path.join(runDir, "migration-preview.json"));
  return mapEnum(COMPLEXITY_SIGNAL, preview?.complexity_signal);
}

// Attributes are lookups over the run's own artifacts, no inference. Phase
// facts attach only to the PHASE_COMPLETED event of the phase that produced
// them, so a terminal event never restates them and no aggregation double
// counts. complexityTier is the exception: it segments the funnel, so it rides
// every event from DESIGN onward and the terminal, and an abandoned run still
// carries it.
function deriveAttributes(runDir, skill, event) {
  const attributes = {};
  const spec = SKILL_INVENTORY[skill];
  const provider = sourceProvider(runDir, spec);
  if (provider) attributes.sourceProvider = provider;

  const phaseEvent = event.eventName === "PHASE_COMPLETED";
  const phase = event.phase;

  if (phaseEvent && phase === "DISCOVER") {
    const inventory = spec ? readJson(path.join(runDir, spec.inventory)) : null;
    const resources = Array.isArray(inventory) ? inventory : inventory?.resources;
    // App-code AI detection lives only here; it is what lets an AI workload
    // with no AI resource (an SDK called from application code) report hasAi.
    const aiProfile = readJson(path.join(runDir, "ai-workload-profile.json"));
    const aiFromProfile = Array.isArray(aiProfile?.models)
      ? aiProfile.models.length > 0
      : (aiProfile?.summary?.total_models_detected ?? 0) > 0;

    if (Array.isArray(resources)) {
      attributes.resourceCount = Math.min(resources.length, 10000); // model @range
      const types = resourceTypes(resources);
      attributes.hasDatabase = DB_TYPE.test(types);
      attributes.hasAi = AI_TYPE.test(types) || aiFromProfile;
    } else if (aiProfile) {
      attributes.hasAi = aiFromProfile;
    }
    const coverage = toCoverage(inventory?.summary?.classification_coverage);
    if (coverage) attributes.classificationCoverage = coverage;
  }

  if (phaseEvent && phase === "CLARIFY") {
    const preferences = readJson(path.join(runDir, "preferences.json"));
    // The AI-only route is its own mode; within it clarify_mode still records
    // fast_path or full, which AI_ONLY supersedes.
    const metadata = preferences?.metadata;
    const clarifyMode =
      metadata?.migration_type === "ai-only" ? "AI_ONLY" : mapEnum(CLARIFY_MODE, metadata?.clarify_mode);
    if (clarifyMode) attributes.clarifyMode = clarifyMode;

    const compliance = toComplianceList(constraintValue(preferences, "compliance"));
    if (compliance) attributes.compliance = compliance;
    const availability = toEnum(AVAILABILITY, constraintValue(preferences, "availability"));
    if (availability) attributes.availability = availability;
    const cutover = toEnum(CUTOVER_STRATEGY, constraintValue(preferences, "cutover_strategy"));
    if (cutover) attributes.cutoverStrategy = cutover;
    const dbSize = mapEnum(DB_SIZE, String(constraintValue(preferences, "db_size") ?? "").replace(/\s+/g, ""));
    if (dbSize) attributes.dbSize = dbSize;
    const traffic = toEnum(DATABASE_TRAFFIC, constraintValue(preferences, "database_traffic"));
    if (traffic) attributes.databaseTraffic = traffic;
    // gcp asks about kubernetes, heroku about a compute target; same decision.
    const posture = toEnum(
      COMPUTE_POSTURE,
      constraintValue(preferences, "kubernetes") ?? constraintValue(preferences, "compute_target"),
    );
    if (posture) attributes.computePosture = posture;
    const region = toEnum(TARGET_REGION, constraintValue(preferences, "target_region"));
    if (region) attributes.targetRegion = region;
  }

  if (phaseEvent && phase === "ESTIMATE") {
    const estimates = readEstimates(runDir);
    for (const estimate of estimates) {
      if (!attributes.recommendationOutcome) {
        const outcome = mapEnum(RECOMMENDATION_OUTCOME, estimate.recommendation?.outcome);
        if (outcome) attributes.recommendationOutcome = outcome;
      }
      if (!attributes.recommendationConfidence) {
        const confidence = toEnum(RECOMMENDATION_CONFIDENCE, estimate.recommendation?.confidence);
        if (confidence) attributes.recommendationConfidence = confidence;
      }
      if (!attributes.pricingSource) {
        // The billing-only route records provenance under metadata.
        const pricing = toPricingSource(
          estimate.pricing_source ?? estimate.metadata?.pricing_source ?? estimate.projected_costs?.pricing_source,
        );
        if (pricing) attributes.pricingSource = pricing;
      }
      if (!attributes.estimateAccuracyBand) {
        const band = toAccuracyBand(estimate.current_costs?.accuracy ?? estimate.accuracy_confidence);
        if (band) attributes.estimateAccuracyBand = band;
      }
      if (attributes.billingDataAvailable === undefined) {
        const available = estimate.migration_cost_considerations?.billing_data_available;
        if (typeof available === "boolean") attributes.billingDataAvailable = available;
      }
      if (attributes.awsProjectedCostBalanced === undefined) {
        const optimized = projectedCost(estimate, "optimized", "option_c_optimized");
        const balanced = projectedCost(estimate, "balanced", "option_b_balanced");
        const premium = projectedCost(estimate, "premium", "option_a_premium");
        if (optimized !== undefined) attributes.awsProjectedCostOptimized = optimized;
        if (balanced !== undefined) attributes.awsProjectedCostBalanced = balanced;
        if (premium !== undefined) attributes.awsProjectedCostPremium = premium;
      }
    }
    // spendBand and spendBasis travel as a pair: a band without its basis is
    // indistinguishable from a measured figure. The basis comes from the cost
    // container's own `source`; when a route omits it, confirmed billing data
    // is the one case that can still be named. A basis alone is harmless and
    // is still reported.
    for (const estimate of estimates) {
      const containers = costContainers(estimate);
      let basis;
      for (const c of containers) {
        basis = mapEnum(SPEND_BASIS, c.source);
        if (basis) break;
      }
      if (!basis && estimate.migration_cost_considerations?.billing_data_available === true) basis = "BILLING_DATA";
      let band;
      for (const c of containers) {
        for (const key of SOURCE_SPEND_KEYS) {
          band = toSpendBand(typeof c[key] === "string" ? Number(c[key]) : c[key]);
          if (band) break;
        }
        if (band) break;
      }
      if (basis && band) {
        attributes.spendBand = band;
        attributes.spendBasis = basis;
        break;
      }
      if (basis && !attributes.spendBasis) attributes.spendBasis = basis;
    }
  }

  if (phaseEvent && phase === "GENERATE") {
    const report = readJson(path.join(runDir, "validation-report.json"));
    const status = toEnum(VALIDATION_STATUS, report?.status);
    if (status) attributes.validationStatus = status;
  }

  const fromDesignOnward = phaseEvent && ["DESIGN", "ESTIMATE", "WORKSHOP", "GENERATE", "FEEDBACK"].includes(phase);
  if (fromDesignOnward || event.eventName === "RUN_COMPLETED") {
    const tier = complexityTier(runDir);
    if (tier) attributes.complexityTier = tier;
  }

  if (event.runMode) attributes.runMode = event.runMode;
  if (event.failureReason) attributes.failureReason = event.failureReason;

  return Object.keys(attributes).length ? attributes : undefined;
}

// ------------------------------------------------------------------- the diff

// The skill records each failed gate in .gate-failures.json, keyed by phase
// (see INTERPRETER.md, "Recording a failed gate"). Only phases the model knows
// are reportable; the snapshot lists the phases already reported.
function gateFailureEntries(gateFailures) {
  if (!gateFailures || typeof gateFailures !== "object" || Array.isArray(gateFailures)) return [];
  return Object.entries(gateFailures)
    .map(([name, entry]) => ({ phase: String(name).toUpperCase(), entry }))
    .filter(({ phase }) => PHASES.has(phase));
}

// One event per transition between the snapshot and .phase-status.json, plus
// one GATE_FAILED per phase newly present in .gate-failures.json (a repeat
// failure of the same phase is not a new event; its later success is).
// Pending/in_progress churn emits nothing; a phase name outside the model's
// enum emits nothing for that phase. RUN_COMPLETED is gated on the snapshot's
// completed flag, not the transition, so a current_phase that leaves
// "complete" and returns cannot mint a second terminal event.
function diffEvents(status, snapshot, gateFailures) {
  const events = [];
  if (!snapshot || snapshot.started === false) events.push({ eventName: "RUN_STARTED" });
  const reported = new Set(snapshot?.gateFailures ?? []);
  for (const { phase, entry } of gateFailureEntries(gateFailures)) {
    if (reported.has(phase)) continue;
    const failureReason = mapEnum(FAILURE_REASON, entry?.reason);
    events.push({ eventName: "GATE_FAILED", phase, status: "FAILED", ...(failureReason ? { failureReason } : {}) });
  }
  const before = snapshot?.phases ?? {};
  for (const [name, state] of Object.entries(status.phases ?? {})) {
    if (before[name] === state) continue;
    const mapped = RESOLVED_STATUS[String(state).toLowerCase()];
    const phase = String(name).toUpperCase();
    if (!mapped || !PHASES.has(phase)) continue;
    events.push({ eventName: "PHASE_COMPLETED", phase, status: mapped, key: name });
  }
  if (status.current_phase === "complete" && !snapshot?.completed) {
    const runMode = mapEnum(RUN_MODE, status.run_mode);
    events.push({ eventName: "RUN_COMPLETED", status: "SUCCESS", ...(runMode ? { runMode } : {}) });
  }
  return events;
}

// ----------------------------------------------------------------- the envelope

// eventId is not sent: the service mints one per received request for
// SQS-redelivery dedup, and one POST per event with no retries makes that
// equivalent to minting it here.
function buildRequest(event, ctx) {
  const attributes = deriveAttributes(ctx.runDir, ctx.skill, event);
  const migrationActivity = {
    eventName: event.eventName,
    skill: ctx.skill,
    ...(ctx.initiatingSkill ? { initiatingSkill: ctx.initiatingSkill } : {}),
    runId: ctx.runId,
    ...(ctx.sessionId ? { sessionId: ctx.sessionId } : {}),
    ...(event.phase ? { phase: event.phase } : {}),
    ...(event.status ? { status: event.status } : {}),
    ...(attributes ? { attributes } : {}),
  };
  return {
    installId: ctx.installId,
    source: hostSource(),
    pluginVersion: ctx.pluginVersion,
    occurredAt: Date.now(),
    pluginTelemetryEvent: { migrationActivity },
  };
}

// Resolves to the HTTP status; rejects on a network failure or timeout. The
// wait is the shorter of the request timeout and the time left before deadline.
async function post(endpoint, body, deadline) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.min(POST_TIMEOUT_MS, deadline - Date.now()));
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    return response.status;
  } finally {
    clearTimeout(timer);
  }
}

// Statuses that mean the service did not take the event but may later: 403
// (a closed launch gate, or a WAF rate limit), 429 (throttled) and 5xx. Such an
// event is not recorded as reported, so it is sent again on a later trigger,
// exactly as with a disabled endpoint. Anything else, including a 400 the
// event would earn again and a network failure, is the loss the design
// tolerates: a retry queue is what it refuses.
const isHeld = (result) =>
  result.status === "fulfilled" && (result.value === 403 || result.value === 429 || result.value >= 500);

// ------------------------------------------------------------------ per run

async function processRun(runDir, { sessionId, sessionEndMode, endpoint, deadline }) {
  if (Date.now() >= deadline) return; // out of budget: untouched, so the next trigger reports it
  const statusFile = path.join(runDir, ".phase-status.json");
  const status = readJson(statusFile);
  if (!status?.migration_id) return;
  const gateFile = path.join(runDir, ".gate-failures.json");
  const gateFailures = readJson(gateFile);

  // Attribution is read from disk, never from an argument: a run that declares
  // no owner, or an owner outside the migration set, emits nothing (fail closed)
  // rather than emitting under the wrong skill.
  const skill = status.owning_skill;
  if (!MIGRATION_SKILLS.has(skill)) return;

  if (!consentGrantedFor(runDir)) return;

  const snapshotFile = path.join(runDir, ".telemetry-snapshot.json");
  const lock = acquireLock(runDir);
  if (!lock) return;
  try {
    const snapshot = readSnapshot(snapshotFile);
    if (snapshot === SNAPSHOT_UNREADABLE) return; // try again on the next trigger

    // Teardown sweeps only the session that wrote the snapshot; a run last
    // touched by another session is that session's to report.
    if (sessionEndMode && snapshot && sessionId && snapshot.sessionId !== sessionId) return;

    // Identifiers read back from customer-editable files are validated, not
    // trusted: the service rejects the whole event on one malformed UUID.
    // run_id comes from .phase-status.json (seeded at _init); a missing or
    // malformed one falls back to the snapshot's, then to a fresh mint persisted
    // in the snapshot. The emitter never writes the skill's own state file.
    const runId = asUuid(status.run_id) ?? asUuid(snapshot?.runId) ?? crypto.randomUUID();
    const validSessionId = asUuid(sessionId);

    // The snapshot mirrors the state last observed, whether or not anything
    // was sent for it. Written only when the observation changed.
    const observe = (phases, completed, reportedGateFailures) => {
      const same =
        snapshot &&
        JSON.stringify(snapshot.phases ?? {}) === JSON.stringify(phases) &&
        Boolean(snapshot.completed) === completed &&
        JSON.stringify(snapshot.gateFailures ?? []) === JSON.stringify(reportedGateFailures);
      if (same) return;
      writeJson(snapshotFile, {
        runId,
        sessionId: validSessionId ?? snapshot?.sessionId,
        ...(snapshot?.started === false ? { started: false } : {}),
        phases,
        gateFailures: reportedGateFailures,
        completed,
        via: viaMode(),
        updatedAt: new Date().toISOString(),
      });
    };

    // Consent covers what happens from the moment it was given. A file last
    // written before the effective consent record is history the customer
    // never agreed to report: a run that predates the first grant, or
    // transitions made while consent was revoked and then granted again. The
    // state file and the gate-failure record are judged separately, each by
    // its own mtime, so a gate that fails after consent on a run that started
    // before it is still reported. History is recorded as already known and
    // never sent, so only what happens from here on is reported.
    const stateIsHistory = predatesConsent(runDir, statusFile);
    const gatesAreHistory = predatesConsent(runDir, gateFile);
    const recordedGates = gateFailureEntries(gateFailures).map((e) => e.phase);
    const knownGates = (sent) => [
      ...new Set([...(snapshot?.gateFailures ?? []), ...(gatesAreHistory ? recordedGates : sent)]),
    ];
    const completedFromHistory = stateIsHistory && status.current_phase === "complete";

    const events = diffEvents(status, snapshot, gateFailures).filter((e) =>
      e.eventName === "GATE_FAILED" ? !gatesAreHistory : !stateIsHistory,
    );
    if (events.length === 0) {
      // Nothing to send, but the observation may have changed: history to
      // record as known, a phase reset (a confirmed re-entry sets downstream
      // phases back to pending), or a run taken over by this session. Record
      // it, or the phase's next completion would read as already reported and
      // this session's teardown would skip the run.
      observe(status.phases ?? {}, Boolean(snapshot?.completed) || completedFromHistory, knownGates([]));
      return;
    }

    const ctx = {
      runDir,
      skill,
      // Only a known migration skill may be named as the invoker; anything else
      // is dropped rather than risk rejecting the whole event.
      initiatingSkill: MIGRATION_SKILLS.has(status.initiated_by) ? status.initiated_by : undefined,
      runId,
      sessionId: validSessionId,
      installId: getInstallId(),
      pluginVersion: pluginVersion(),
    };

    // Concurrently, under one budget: sent serially, a reconcile catching a
    // whole run could outlive the host's hook timeout and never reach the
    // snapshot write, so the next trigger would repeat the batch. No retries by
    // design: a retry queue is unbounded local state for data that is
    // loss-tolerant in aggregate.
    const results = await Promise.allSettled(
      events.map((event) => post(endpoint, buildRequest(event, ctx), deadline)),
    );
    const held = new Set(events.filter((_, i) => isHeld(results[i])));
    if (held.size === events.length) return; // nothing taken: nothing recorded

    // The snapshot records exactly what the service took. A held phase keeps
    // its previous state so only that transition is re-sent; a held RUN_STARTED
    // or RUN_COMPLETED is re-sent alone. Accepted events are never repeated,
    // even when a later trigger replays the held ones.
    const phases = { ...(status.phases ?? {}) };
    for (const event of held) {
      if (event.eventName !== "PHASE_COMPLETED") continue;
      if (event.key in (snapshot?.phases ?? {})) phases[event.key] = snapshot.phases[event.key];
      else delete phases[event.key];
    }
    const runStarted = events.find((e) => e.eventName === "RUN_STARTED");
    const runCompleted = events.find((e) => e.eventName === "RUN_COMPLETED");

    // via/updatedAt are the hook-liveness tag: an instruction-driven caller can
    // read them to skip its call when a hook reported recently, and the
    // idempotent diff keeps the two paths safe even without that check.
    // A held GATE_FAILED is not recorded either, so it is re-sent alone.
    const sentGates = events.filter((e) => e.eventName === "GATE_FAILED" && !held.has(e)).map((e) => e.phase);

    writeJson(snapshotFile, {
      runId,
      sessionId: ctx.sessionId ?? snapshot?.sessionId,
      started: !(runStarted && held.has(runStarted)),
      phases,
      gateFailures: knownGates(sentGates),
      completed: Boolean(snapshot?.completed) || completedFromHistory || Boolean(runCompleted && !held.has(runCompleted)),
      via: viaMode(),
      updatedAt: new Date().toISOString(),
    });
  } finally {
    releaseLock(lock);
  }
}

// ---------------------------------------------------------------------- main

async function main() {
  const args = process.argv.slice(2);

  if (args[0] === "consent") {
    runConsentCommand(args[1]);
    return;
  }

  if (process.env.DO_NOT_TRACK === "1") return;
  if (process.env.AWS_STARTUP_ADVISOR_TELEMETRY === "0") return;

  const endpoint = resolveEndpoint();
  if (!endpoint) return; // explicitly disabled: nothing attempted, snapshots untouched

  const sessionEndMode = args.includes("--session-end");
  const deadline = sessionEndMode ? Date.now() + SESSION_END_BUDGET_MS - SESSION_END_RESERVE_MS : Infinity;
  const payload = await readStdin();
  // Claude Code sends session_id on every hook; Cursor sends conversation_id
  // on tool, file and stop hooks.
  const sessionId = payload?.session_id ?? payload?.conversation_id;

  // Post-write fast path: if the edited file is not under a .migration tree,
  // this invocation has no possible work.
  const editedPath = payload?.tool_input?.file_path ?? payload?.file_path;
  if (!sessionEndMode && !args.includes("--reconcile") && editedPath && !editedPath.includes(".migration")) {
    return;
  }

  // Start discovery at the directory that owns the .migration tree, so an
  // edit deep inside a run's artifacts still resolves to its run.
  const marker = editedPath ? editedPath.indexOf(`${path.sep}.migration${path.sep}`) : -1;
  const startDir =
    (marker !== -1 ? editedPath.slice(0, marker) : undefined) ??
    payload?.cwd ??
    payload?.workspace_roots?.[0] ??
    process.cwd();

  for (const runDir of await findRunDirs(startDir)) {
    await processRun(runDir, { sessionId, sessionEndMode, endpoint, deadline });
  }
}

main()
  .catch(() => {})
  .finally(() => process.exit(0));
