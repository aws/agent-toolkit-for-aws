// application-source-review.ts — production validation for a planned read-only
// Heroku application-source review.
//
// Tests import this zero-dependency implementation directly so the contract,
// filesystem, security, and fail-closed behavior are established before any
// migration phase invokes it.
//
// Later changes add command-line publication and workflow activation.

import {
  lstatSync,
  readdirSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import { relative, resolve, sep } from "node:path";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

/** The 22 approved questions, in contract order. The reviewer cannot add or remove any. */
export const QUESTIONS = [
  "runtime_framework",
  "build_method",
  "build_time_settings",
  "process_commands",
  "runtime_settings",
  "network_listeners",
  "port_host_binding",
  "heroku_runtime_behavior",
  "native_dependencies",
  "release_setup_commands",
  "recurring_jobs",
  "health_routes",
  "local_file_writes",
  "network_protocols",
  "potential_private_endpoints",
  "logs_telemetry",
  "postgresql_extensions",
  "redis_usage",
  "external_services",
  "application_connections",
  "addon_usage",
  "webhooks",
] as const;

export type Question = (typeof QUESTIONS)[number];

/** Runtimes with validated review behavior. Anything else stays UNKNOWN (fail closed). */
export const SUPPORTED_RUNTIMES = ["ruby", "java", "nodejs"] as const;

function normalizeRuntime(value: string): (typeof SUPPORTED_RUNTIMES)[number] | null {
  const runtime = value.trim().toLowerCase();
  if (/^ruby\b/u.test(runtime)) return "ruby";
  if (/^java\b/u.test(runtime)) return "java";
  if (/^node(?:\.?js)?\b/u.test(runtime)) return "nodejs";
  return null;
}

/** The 15 questions requested for every reviewed application. */
export const ALWAYS_QUESTIONS: readonly Question[] = [
  "runtime_framework",
  "build_method",
  "build_time_settings",
  "process_commands",
  "runtime_settings",
  "network_listeners",
  "port_host_binding",
  "heroku_runtime_behavior",
  "native_dependencies",
  "release_setup_commands",
  "recurring_jobs",
  "local_file_writes",
  "network_protocols",
  "logs_telemetry",
  "external_services",
];

/** Inventory-derived signals that add conditional questions to a request. */
export interface SelectionInput {
  hasInboundWebProcess: boolean;
  privateSpaceOrMultiApp: boolean;
  postgresAttached: boolean;
  redisAttached: boolean;
  ambiguousAddons: boolean;
}

/**
 * Select the questions for one application from accepted Heroku inventory. Always the
 * 15 base questions, plus conditionals; returned in canonical order with no
 * duplicates. The reviewer cannot alter this set.
 */
export function selectQuestions(input: SelectionInput): Question[] {
  const enabled = new Set<Question>(ALWAYS_QUESTIONS);
  if (input.hasInboundWebProcess) {
    enabled.add("health_routes");
    enabled.add("webhooks");
  }
  if (input.privateSpaceOrMultiApp) {
    enabled.add("potential_private_endpoints");
    enabled.add("application_connections");
  }
  if (input.postgresAttached) enabled.add("postgresql_extensions");
  if (input.redisAttached) enabled.add("redis_usage");
  if (input.ambiguousAddons) enabled.add("addon_usage");
  return QUESTIONS.filter((question) => enabled.has(question));
}

/** Per-application budgets enforced locally (files, bytes, retained output). */
export const LIMITS = {
  maxSourceFiles: 5000,
  maxTotalBytes: 64 * 1024 * 1024,
  maxFileBytes: 2 * 1024 * 1024,
  maxRetainedBytes: 256 * 1024,
} as const;

export function object(value: Json): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("expected object");
  return value;
}

function same(left: Json, right: Json): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function hasOwn(value: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function validateDefinition(
  schema: JsonObject,
  definition: "request" | "findings",
  value: Json,
  path: string,
): string[] {
  const definitions = object(schema.definitions);
  return validate(object(definitions[definition]), value, schema, path);
}

// --- draft-07 subset validator ------------------------------------------------
// Supports the keywords the application-source contract uses: $ref, allOf, oneOf,
// not, if/then/else, const, enum, type, string/number/array/object constraints.

export function validate(node: JsonObject, value: Json, root: JsonObject = node, path = "$"): string[] {
  if (typeof node.$ref === "string") {
    if (!/^#\//.test(node.$ref)) return [`${path}: unsupported $ref ${node.$ref}`];
    let current: Json = root;
    for (const segment of node.$ref.slice(2).split("/")) current = object(current)[segment];
    return validate(object(current), value, root, path);
  }
  const errors: string[] = [];

  if (Array.isArray(node.allOf)) {
    for (const part of node.allOf) errors.push(...validate(object(part), value, root, path));
  }
  if (Array.isArray(node.oneOf)) {
    const matches = node.oneOf.filter((part) => validate(object(part), value, root, path).length === 0);
    if (matches.length !== 1) errors.push(`${path}: expected exactly one oneOf match, got ${matches.length}`);
  }
  if (node.not && validate(object(node.not), value, root, path).length === 0) {
    errors.push(`${path}: matched forbidden schema`);
  }
  if (node.if) {
    const branch = validate(object(node.if), value, root, path).length === 0 ? node.then : node.else;
    if (branch) errors.push(...validate(object(branch), value, root, path));
  }
  if ("const" in node && !same(node.const, value)) errors.push(`${path}: does not match const`);
  if (Array.isArray(node.enum) && !node.enum.some((entry) => same(entry, value))) {
    errors.push(`${path}: is not in enum`);
  }

  const type = node.type;
  const typeMatches = type === undefined
    || (type === "null" && value === null)
    || (type === "boolean" && typeof value === "boolean")
    || (type === "number" && typeof value === "number")
    || (type === "integer" && typeof value === "number" && Number.isInteger(value))
    || (type === "string" && typeof value === "string")
    || (type === "array" && Array.isArray(value))
    || (type === "object" && value !== null && typeof value === "object" && !Array.isArray(value));
  if (!typeMatches) {
    errors.push(`${path}: expected ${String(type)}`);
    return errors;
  }

  if (typeof value === "string") {
    if (typeof node.minLength === "number" && value.length < node.minLength) errors.push(`${path}: too short`);
    if (typeof node.maxLength === "number" && value.length > node.maxLength) errors.push(`${path}: too long`);
    if (typeof node.pattern === "string" && !new RegExp(node.pattern, "u").test(value)) {
      errors.push(`${path}: pattern mismatch`);
    }
  }
  if (typeof value === "number") {
    if (typeof node.minimum === "number" && value < node.minimum) errors.push(`${path}: below minimum`);
    if (typeof node.maximum === "number" && value > node.maximum) errors.push(`${path}: above maximum`);
  }
  if (Array.isArray(value)) {
    if (typeof node.minItems === "number" && value.length < node.minItems) errors.push(`${path}: too few items`);
    if (typeof node.maxItems === "number" && value.length > node.maxItems) errors.push(`${path}: too many items`);
    if (node.uniqueItems === true && new Set(value.map((entry) => JSON.stringify(entry))).size !== value.length) {
      errors.push(`${path}: duplicate items`);
    }
    if (node.items) {
      value.forEach((entry, index) => errors.push(...validate(object(node.items), entry, root, `${path}[${index}]`)));
    }
  }
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const properties = node.properties ? object(node.properties) : {};
    if (Array.isArray(node.required)) {
      for (const key of node.required) {
        if (typeof key === "string" && !hasOwn(value, key)) errors.push(`${path}: missing ${key}`);
      }
    }
    if (node.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        if (!hasOwn(properties, key)) errors.push(`${path}: undeclared ${key}`);
      }
    }
    for (const [key, childSchema] of Object.entries(properties)) {
      if (hasOwn(value, key)) errors.push(...validate(object(childSchema), value[key], root, `${path}.${key}`));
    }
  }
  return errors;
}

// --- semantic validation ------------------------------------------------------

function recordsByQuestion(findings: JsonObject): Map<string, JsonObject[]> {
  const result = new Map<string, JsonObject[]>();
  for (const rawFinding of findings.findings as Json[]) {
    const finding = object(rawFinding);
    result.set(finding.question as string, Array.isArray(finding.value) ? finding.value.map(object) : []);
  }
  return result;
}

/**
 * Cross-field rules the flat schema cannot express: one finding per requested
 * question, no duplicate/unrequested question, resolvable shared record references,
 * UNKNOWN carries a limitation, absence is not qualified by a source-scope
 * limitation, and source line bounds are ordered.
 */
export function validateSemantics(reviewRequest: JsonObject, answer: JsonObject): string[] {
  const errors: string[] = [];
  const requested = reviewRequest.requested_questions as string[];
  const rawFindings = answer.findings as Json[];
  const findingNames = rawFindings.map((raw) => object(raw).question as string);
  const presentQuestions = new Set(
    rawFindings
      .map(object)
      .filter((finding) => finding.status === "PRESENT")
      .map((finding) => finding.question as string),
  );
  for (const question of requested) {
    if (findingNames.filter((name) => name === question).length !== 1) errors.push(`expected one finding for ${question}`);
  }
  for (const question of findingNames) {
    if (!requested.includes(question)) errors.push(`unrequested finding ${question}`);
  }
  for (const raw of rawFindings) {
    const finding = object(raw);
    const limitations = (finding.limitations ?? []) as JsonObject[];
    const sources = (finding.sources ?? []) as JsonObject[];
    if (
      ["PRESENT", "ABSENT_WITHIN_REVIEWED_SCOPE"].includes(finding.status as string)
      && sources.length === 0
    ) {
      errors.push(`${String(finding.question)}: ${String(finding.status)} needs source evidence`);
    }
    if (finding.status === "UNKNOWN" && limitations.length === 0) {
      errors.push(`${String(finding.question)}: UNKNOWN needs a limitation`);
    }
    if (
      finding.status === "ABSENT_WITHIN_REVIEWED_SCOPE"
      && limitations.some((item) =>
        ["SKIPPED_SOURCE", "UNREADABLE_SOURCE", "TRUNCATED_SOURCE", "DYNAMIC_SOURCE"].includes(item.kind as string)
      )
    ) errors.push(`${String(finding.question)}: absence has an incomplete scope`);
    for (const source of (finding.sources ?? []) as JsonObject[]) {
      if (
        typeof source.line_start === "number"
        && typeof source.line_end === "number"
        && source.line_end < source.line_start
      ) errors.push(`${String(finding.question)}: source line bounds are reversed`);
    }
  }

  const records = recordsByQuestion(answer);
  const ids = (question: string, key: string) => (records.get(question) ?? []).map((item) => item[key] as string);
  const componentIds = ids("runtime_framework", "component_id");
  const processIds = ids("process_commands", "process_id");
  const listenerIds = ids("network_listeners", "listener_id");
  const dependencyIds = ids("external_services", "dependency_id");
  const relationshipIds = ids("application_connections", "relationship_id");
  const components = new Set(componentIds);
  const processes = new Set(processIds);
  const listeners = new Set(listenerIds);
  const dependencies = new Set(dependencyIds);
  const estateApps = new Set(object(reviewRequest.context).selected_estate_application_ids as string[]);
  const addons = new Set(object(reviewRequest.context).addon_ids as string[]);

  for (const [question, questionRecords] of records) {
    for (const record of questionRecords) {
      for (const key of ["component_id", "caller_component_id"]) {
        if (
          presentQuestions.has("runtime_framework")
          && typeof record[key] === "string"
          && !components.has(record[key])
        ) errors.push(`${question}: broken ${key}`);
      }
      for (const key of ["process_id", "process_ids", "caller_process_ids"]) {
        const references = typeof record[key] === "string" ? [record[key]] : (record[key] ?? []) as Json[];
        for (const reference of references) {
          if (
            presentQuestions.has("process_commands")
            && typeof reference === "string"
            && !processes.has(reference)
          ) errors.push(`${question}: broken ${key}`);
        }
      }
      if (
        presentQuestions.has("network_listeners")
        && typeof record.listener_id === "string"
        && !listeners.has(record.listener_id)
      ) {
        errors.push(`${question}: broken listener_id`);
      }
      if (typeof record.callee_application_id === "string" && !estateApps.has(record.callee_application_id)) {
        errors.push(`${question}: broken callee_application_id`);
      }
      if (typeof record.inventory_addon_id === "string" && !addons.has(record.inventory_addon_id)) {
        errors.push(`${question}: broken inventory_addon_id`);
      }
      if (
        presentQuestions.has("external_services")
        && record.reference_kind === "DEPENDENCY"
        && !dependencies.has(record.reference_id as string)
      ) {
        errors.push(`${question}: broken dependency reference_id`);
      }
      if (record.reference_kind === "APPLICATION" && !estateApps.has(record.reference_id as string)) {
        errors.push(`${question}: broken application reference_id`);
      }
    }
  }

  for (
    const [label, valuesToCheck] of [
      ["component", componentIds],
      ["process", processIds],
      ["listener", listenerIds],
      ["dependency", dependencyIds],
      ["relationship", relationshipIds],
    ] as const
  ) {
    if (new Set(valuesToCheck).size !== valuesToCheck.length) errors.push(`duplicate ${label} id`);
  }
  return errors;
}

function validateRuntimeSupport(reviewRequest: JsonObject, answer: JsonObject): string[] {
  const requested = reviewRequest.requested_questions as string[];
  if (!requested.includes("runtime_framework")) return [];

  const raw = (answer.findings as Json[]).find(
    (finding) => object(finding).question === "runtime_framework",
  );
  if (!raw) return ["runtime support could not be established"];

  const finding = object(raw);
  if (finding.status !== "PRESENT" || !Array.isArray(finding.value)) {
    return ["runtime support could not be established"];
  }

  const unsupported = finding.value
    .map((record) => String(object(record).runtime).trim())
    .filter((runtime) => normalizeRuntime(runtime) === null);
  return unsupported.length === 0
    ? []
    : [`unsupported runtime: ${[...new Set(unsupported)].join(", ")}`];
}

// --- disallowed-content scanning ----------------------------------------------
// The reviewer records configuration NAMES, never values. It also never emits a
// target decision, architecture, sizing, or cost. These high-confidence patterns
// catch a submission that leaked a literal credential or a recommendation.

const CREDENTIAL_PATTERNS: RegExp[] = [
  /\bAKIA[0-9A-Z]{16}\b/, // AWS access key id
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/, // PEM private key
  /\bxox[baprs]-[0-9A-Za-z-]{10,}\b/, // Slack token
  /\bgh[pousr]_[0-9A-Za-z]{20,}\b/, // GitHub token
  /\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*\b/i, // bearer token
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/, // JWT
  /\b[a-z][a-z0-9+.-]*:\/\/[^/\s:@]+:[^/\s@]+@/i, // URI userinfo
  /--?(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)(?:=|\s+)["']?(?!<|\*{3,}|\[|\$\{?[A-Z_])[^\s"'<>*\[\]]{8,}/i, // CLI literal
];

const LITERAL_ASSIGNMENT_PATTERN =
  /(?:^|[^A-Za-z0-9_])(?:"([A-Za-z_][A-Za-z0-9_.-]*)"|'([A-Za-z_][A-Za-z0-9_.-]*)'|([A-Za-z_][A-Za-z0-9_.-]*))\s*[:=]\s*["']?(?!<|\*{3,}|\[|\$\{?[A-Z_])[^\s"'<>*\[\]]{8,}/gu;
const CREDENTIAL_KEY_PARTS = new Set(["password", "passwd", "secret", "token", "apikey", "accesskey"]);

function isCredentialKey(key: string): boolean {
  const parts = key.toLowerCase().split(/[._-]+/u).filter(Boolean);
  return parts.some((part, index) =>
    CREDENTIAL_KEY_PARTS.has(part)
    || ((part === "api" || part === "access") && parts[index + 1] === "key")
  );
}

function hasLiteralCredentialAssignment(text: string): boolean {
  for (const match of text.matchAll(LITERAL_ASSIGNMENT_PATTERN)) {
    const key = match[1] ?? match[2] ?? match[3];
    if (key && isCredentialKey(key)) return true;
  }
  return false;
}

const TARGET_PATTERNS: RegExp[] = [
  /\b(?:recommend(?:s|ed)?|should|propos(?:e|ed))\b.{0,80}\b(?:elastic beanstalk|fargate|amazon rds\b|amazon aurora|elasticache|amazon eks|amazon msk|app runner)\b/i,
  /\b(?:target|destination)\s+(?:is|=|:)\s*(?:elastic beanstalk|fargate|amazon rds\b|amazon aurora|elasticache|amazon eks|amazon msk|app runner)\b/i,
  /\b(?:recommend|recommends|recommended)\s+(?:using|use|deploying|deploy|moving|move|migrating|migrate|to|on)\b/i,
  /\b(?:recommended|proposed)\s+architecture\b/i,
  /(?:\$\s?\d[\d,]*(?:\.\d+)?\s*(?:\/|per)\s*(?:mo(?:nth)?|hr|hour|yr|year)\b|\b(?:monthly|hourly|annual) cost\b|\b\d[\d,.]*\s*USD\s*(?:\/|per)\s*(?:mo(?:nth)?|hr|hour|yr|year)\b)/i,
];

function walkStrings(value: Json, visit: (text: string) => void): void {
  const pending: Json[] = [value];
  while (pending.length > 0) {
    const current = pending.pop() as Json;
    if (typeof current === "string") visit(current);
    else if (Array.isArray(current)) pending.push(...current);
    else if (current !== null && typeof current === "object") pending.push(...Object.values(current));
  }
}

function scanCredentialContent(value: Json): string[] {
  const reasons: string[] = [];
  walkStrings(value, (text) => {
    for (const pattern of CREDENTIAL_PATTERNS) {
      if (pattern.test(text)) reasons.push(`high-confidence credential in output: ${pattern.source}`);
    }
    if (hasLiteralCredentialAssignment(text)) {
      reasons.push("high-confidence credential in output: literal assignment");
    }
  });
  return reasons;
}

/** Returns the reasons a submission's string values are disallowed (empty when clean). */
export function scanDisallowedContent(answer: JsonObject): string[] {
  const content = answer.findings ?? null;
  const reasons = scanCredentialContent(content);
  walkStrings(content, (text) => {
    for (const pattern of TARGET_PATTERNS) {
      if (pattern.test(text)) reasons.push(`target/architecture/cost content in output: ${pattern.source}`);
    }
  });
  return reasons;
}

/** Retained output must be at most 256 KiB per application. */
export function retainedBytes(answer: JsonObject): number {
  return new TextEncoder().encode(JSON.stringify(answer)).length;
}

// --- filesystem containment + budgets -----------------------------------------

/** True when `candidateAbs` resolves (through symlinks) to inside `workspaceAbs`. */
export function isContainedPath(workspaceAbs: string, candidateAbs: string): boolean {
  try {
    const workspaceReal = realpathSync(workspaceAbs);
    const candidateReal = realpathSync(candidateAbs);
    return candidateReal === workspaceReal || candidateReal.startsWith(workspaceReal + sep);
  } catch {
    return false;
  }
}

function pathTraversesSymlink(workspaceAbs: string, candidateAbs: string): boolean {
  const lexical = relative(resolve(workspaceAbs), resolve(candidateAbs));
  if (lexical === "" || lexical.startsWith(`..${sep}`) || lexical === "..") return false;
  let current = resolve(workspaceAbs);
  for (const segment of lexical.split(sep)) {
    current = resolve(current, segment);
    try {
      if (lstatSync(current).isSymbolicLink()) return true;
    } catch {
      return false;
    }
  }
  return false;
}

export interface RootMeasurement {
  files: number;
  totalBytes: number;
  maxFileBytes: number;
  unreadableEntries: number;
  withinLimits: boolean;
}

const EXCLUDED_SOURCE_DIRECTORIES = new Set([
  ".git",
  ".gradle",
  ".migration",
  ".next",
  ".nyc_output",
  ".venv",
  "build",
  "coverage",
  "dist",
  "log",
  "logs",
  "node_modules",
  "target",
  "tmp",
]);

function pathUsesExcludedSourceDirectory(path: string, leafIsDirectory: boolean): boolean {
  const segments = path.split(/[\\/]/u).filter((segment) => segment.length > 0);
  const directories = leafIsDirectory ? segments : segments.slice(0, -1);
  return directories.some((segment) => EXCLUDED_SOURCE_DIRECTORIES.has(segment))
    || directories.some(
      (segment, index) => segment === "vendor" && directories[index + 1] === "bundle",
    );
}

/** Walk a source root counting regular files and bytes; never follows symlinked dirs. */
export function measureSourceRoot(rootAbs: string): RootMeasurement {
  let files = 0;
  let totalBytes = 0;
  let maxFileBytes = 0;
  let unreadableEntries = 0;
  const stack = [rootAbs];
  while (stack.length > 0) {
    const dir = stack.pop() as string;
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      unreadableEntries += 1;
      continue;
    }
    for (const entry of entries) {
      const child = resolve(dir, entry);
      let info;
      try {
        info = lstatSync(child);
      } catch {
        unreadableEntries += 1;
        continue;
      }
      if (info.isSymbolicLink()) {
        continue; // never follow or count symlinked source entries
      }
      if (info.isDirectory()) {
        if (pathUsesExcludedSourceDirectory(relative(rootAbs, child), true)) continue;
        stack.push(child);
      } else if (info.isFile()) {
        files += 1;
        totalBytes += info.size;
        if (info.size > maxFileBytes) maxFileBytes = info.size;
        if (
          files > LIMITS.maxSourceFiles
          || totalBytes > LIMITS.maxTotalBytes
          || maxFileBytes > LIMITS.maxFileBytes
        ) {
          return { files, totalBytes, maxFileBytes, unreadableEntries, withinLimits: false };
        }
      }
    }
  }
  const withinLimits = files <= LIMITS.maxSourceFiles
    && totalBytes <= LIMITS.maxTotalBytes
    && maxFileBytes <= LIMITS.maxFileBytes;
  return { files, totalBytes, maxFileBytes, unreadableEntries, withinLimits };
}

function citationResolves(roots: string[], workspaceAbs: string, source: JsonObject): boolean {
  const relPath = source.path;
  if (typeof relPath !== "string") return false;
  const candidate = resolve(workspaceAbs, relPath);
  if (!isContainedPath(workspaceAbs, candidate)) return false;
  const containingRoot = roots.find((root) => isContainedPath(root, candidate));
  if (!containingRoot) return false;
  if (pathUsesExcludedSourceDirectory(relative(containingRoot, candidate), false)) return false;
  if (pathTraversesSymlink(workspaceAbs, candidate)) return false;
  let info;
  try {
    info = lstatSync(candidate);
  } catch {
    return false;
  }
  if (!info.isFile() || info.isSymbolicLink()) return false;
  let text: string;
  try {
    text = readFileSync(candidate, "utf8");
  } catch {
    return false;
  }
  const start = source.line_start;
  const end = source.line_end;
  if (typeof start === "number" || typeof end === "number") {
    const newlineCount = text.match(/\r\n|\r|\n/gu)?.length ?? 0;
    const lineCount = text.length === 0
      ? 0
      : newlineCount + (/(\r\n|\r|\n)$/u.test(text) ? 0 : 1);
    if (typeof start === "number" && start > lineCount) return false;
    if (typeof end === "number" && end > lineCount) return false;
  }
  return true;
}

/** Validate source roots before dispatching a reviewer. */
export function validateSourceRoots(workspaceAbs: string, roots: string[]): string[] {
  const reasons: string[] = [];
  if (roots.length !== 1) return ["exactly one source root is required per application"];
  for (const root of roots) {
    if (!isContainedPath(workspaceAbs, root)) {
      reasons.push(`source root escapes workspace: ${root}`);
      continue;
    }
    if (lstatSync(root).isSymbolicLink()) {
      reasons.push(`source root is a symlink: ${root}`);
      continue;
    }
    if (pathUsesExcludedSourceDirectory(relative(workspaceAbs, root), true)) {
      reasons.push(`source root uses an excluded directory: ${root}`);
      continue;
    }
    const measurement = measureSourceRoot(root);
    if (measurement.unreadableEntries > 0) reasons.push(`source root contains unreadable entries: ${root}`);
    else if (measurement.files === 0) reasons.push(`source root contains no readable files: ${root}`);
    else if (!measurement.withinLimits) reasons.push(`source root exceeds file/byte budget: ${root}`);
  }
  return reasons;
}

// --- deterministic fail-closed replacement ------------------------------------

const VALIDATION_UNKNOWN_DETAIL = "Source review could not be validated.";
const UNKNOWN_REASONS: Record<string, string> = {
  missing_source: "Application source was not available for review.",
  review_interrupted: "Application source review was interrupted.",
  review_unavailable: "Application source review was unavailable.",
  review_over_budget: "Application source review exceeded an execution limit.",
};
const ALLOWED_UNKNOWN_DETAILS = new Set([VALIDATION_UNKNOWN_DETAIL, ...Object.values(UNKNOWN_REASONS)]);

/** One deterministic UNKNOWN finding per requested question — the fail-closed output. */
export function unknownForRequest(requestedQuestions: readonly string[], detail: string): JsonObject {
  return {
    findings: requestedQuestions.map((question) => ({
      question,
      status: "UNKNOWN",
      value: null,
      sources: [],
      limitations: [{ kind: "OTHER", detail }],
    })),
  };
}

function jsonObject(value: Json): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function hasExactKeys(value: JsonObject, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
}

function validRelativeRoot(value: string): boolean {
  if (value === ".") return true;
  if (value.length === 0 || value.length > 500 || value.startsWith("/") || /^[A-Za-z]:/u.test(value)) return false;
  if (value.includes("\\") || value.includes("//")) return false;
  return value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

function validateRequest(schema: JsonObject, request: JsonObject, path: string): string[] {
  const errors = validateDefinition(schema, "request", request, path);
  if (errors.length > 0) return errors;

  errors.push(...scanCredentialContent(request).map((error) => `${path}: ${error}`));
  return errors;
}

/**
 * Validate the final wrapper before it becomes the canonical artifact. This repeats
 * retained-submission validation so the controller cannot change accepted findings.
 */
export function validateReviewArtifact(
  schema: JsonObject,
  artifact: JsonObject,
  workspaceRoot: string,
  expectedRequests: readonly JsonObject[],
): string[] {
  const errors: string[] = [];
  if (!hasExactKeys(artifact, ["reviews"]) || !Array.isArray(artifact.reviews)) {
    return ["artifact must contain only a reviews array"];
  }
  if (artifact.reviews.length !== expectedRequests.length) {
    errors.push(`artifact has ${artifact.reviews.length} reviews; expected ${expectedRequests.length}`);
  }

  const appIds = new Set<string>();
  for (const [index, raw] of artifact.reviews.entries()) {
    const entry = jsonObject(raw);
    const at = `reviews[${index}]`;
    if (!entry || !hasExactKeys(entry, ["findings", "limitations", "request", "source_root", "status"])) {
      errors.push(`${at}: invalid entry shape`);
      continue;
    }
    const request = jsonObject(entry.request);
    const findings = jsonObject(entry.findings);
    if (!request || !findings) {
      errors.push(`${at}: request and findings must be objects`);
      continue;
    }
    const requestErrors = validateRequest(schema, request, `${at}.request`);
    const findingErrors = validateDefinition(schema, "findings", findings, `${at}.findings`);
    errors.push(...requestErrors, ...findingErrors);
    if (requestErrors.length > 0 || findingErrors.length > 0) continue;
    errors.push(...validateSemantics(request, findings).map((error) => `${at}: ${error}`));

    const application = jsonObject(request.application);
    const appId = application?.app_id;
    if (typeof appId !== "string" || appIds.has(appId)) errors.push(`${at}: duplicate or missing app_id`);
    else appIds.add(appId);
    const expected = expectedRequests[index];
    if (!expected || !same(request, expected)) {
      errors.push(`${at}: request content or inventory order does not match`);
    }

    const limitations = Array.isArray(entry.limitations) ? entry.limitations : [];
    if (
      !Array.isArray(entry.limitations)
      || limitations.some((item) => typeof item !== "string" || item.length === 0 || item.length > 500)
    ) errors.push(`${at}: limitations must be concise strings`);
    errors.push(...scanDisallowedContent({ findings: limitations }).map((error) => `${at}: ${error}`));

    const sourceRoot = entry.source_root;
    if (sourceRoot !== null && (typeof sourceRoot !== "string" || !validRelativeRoot(sourceRoot))) {
      errors.push(`${at}: source_root must be workspace-relative or null`);
    }

    if (entry.status === "RETAINED") {
      if (typeof sourceRoot !== "string") errors.push(`${at}: RETAINED requires a source_root`);
      else {
        const result = evaluateSubmission({
          schema,
          request,
          submission: findings,
          workspaceRoot,
          roots: [resolve(workspaceRoot, sourceRoot)],
        });
        errors.push(...result.reasons.map((reason) => `${at}: ${reason}`));
      }
      if (limitations.length !== 0) errors.push(`${at}: RETAINED cannot have limitations`);
    } else if (entry.status === "UNKNOWN") {
      if (limitations.length === 0) errors.push(`${at}: UNKNOWN needs a limitation`);
      const requested = request.requested_questions as string[];
      const findingList = findings.findings as Json[];
      const first = findingList.length > 0 ? jsonObject(findingList[0]) : null;
      const firstLimitation = first && Array.isArray(first.limitations)
        ? jsonObject(first.limitations[0] as Json)
        : null;
      const detail = firstLimitation?.detail;
      if (
        typeof detail !== "string"
        || !ALLOWED_UNKNOWN_DETAILS.has(detail)
        || !same(findings, unknownForRequest(requested, detail))
      ) errors.push(`${at}: UNKNOWN findings must be a canonical fail-closed replacement`);
      if (retainedBytes(findings) > LIMITS.maxRetainedBytes) errors.push(`${at}: findings exceed retained budget`);
      errors.push(...scanDisallowedContent(findings).map((error) => `${at}: ${error}`));
    } else {
      errors.push(`${at}: status must be RETAINED or UNKNOWN`);
    }
  }
  return errors;
}

export interface SubmissionContext {
  schema: JsonObject;
  request: JsonObject;
  submission: JsonObject;
  roots: string[];
  workspaceRoot: string;
}

export interface SubmissionResult {
  retained: boolean;
  findings: JsonObject;
  reasons: string[];
}

/**
 * Validate a COMPLETE reviewer submission for one application and return either the
 * retained findings (when every check passes) or one deterministic UNKNOWN finding
 * per requested question (fail closed). No partial acceptance.
 */
export function evaluateSubmission(ctx: SubmissionContext): SubmissionResult {
  const reasons: string[] = [];
  reasons.push(...validateRequest(ctx.schema, ctx.request, "request").map((error) => `request ${error}`));
  reasons.push(...validateDefinition(ctx.schema, "findings", ctx.submission, "findings").map((error) => `findings ${error}`));
  if (reasons.length === 0) {
    reasons.push(...validateSemantics(ctx.request, ctx.submission));
    reasons.push(...validateRuntimeSupport(ctx.request, ctx.submission));
  }
  reasons.push(...scanDisallowedContent(ctx.submission));

  const bytes = retainedBytes(ctx.submission);
  if (bytes > LIMITS.maxRetainedBytes) reasons.push(`retained output ${bytes} bytes exceeds ${LIMITS.maxRetainedBytes}`);

  reasons.push(...validateSourceRoots(ctx.workspaceRoot, ctx.roots));

  if (reasons.length === 0) {
    for (const raw of ctx.submission.findings as Json[]) {
      const finding = object(raw);
      for (const source of (finding.sources ?? []) as JsonObject[]) {
        if (!citationResolves(ctx.roots, ctx.workspaceRoot, source)) {
          reasons.push(`${String(finding.question)}: cited path does not resolve within workspace`);
        }
      }
    }
  }

  if (reasons.length === 0) return { retained: true, findings: ctx.submission, reasons: [] };
  const rawRequested = ctx.request.requested_questions;
  const requested = Array.isArray(rawRequested)
    ? rawRequested.filter((question): question is string => typeof question === "string")
    : [];
  return {
    retained: false,
    findings: unknownForRequest(requested, VALIDATION_UNKNOWN_DETAIL),
    reasons,
  };
}
