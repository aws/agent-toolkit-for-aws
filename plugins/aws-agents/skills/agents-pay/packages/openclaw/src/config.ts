import { lstat, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export interface X402Config {
  region: string;
  paymentManagerArn: string;
  paymentInstrumentId: string;
  userId: string;
  payment_session_id: string;
  networkPreferences?: string[];
  allowedOrigins?: string[];
  allowedRecipients: string[];
  allowedAssetsByNetwork?: Record<string, string[]>;
  maxPaymentAmountAtomic?: string;
}

const CONFIG_DIR = join(homedir(), ".x402");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");

let cachedConfig: X402Config | null = null;

function isNotFound(error: unknown): boolean {
  return Boolean(
    error &&
    typeof error === "object" &&
    "code" in error &&
    (error as { code?: string }).code === "ENOENT",
  );
}

async function assertProtectedPath(
  path: string,
  kind: "directory" | "file",
): Promise<void> {
  const stat = await lstat(path);
  const expectedType =
    kind === "directory" ? stat.isDirectory() : stat.isFile();
  if (stat.isSymbolicLink() || !expectedType) {
    throw new Error(`${path} must be a regular ${kind}, not a symlink`);
  }
  if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
    throw new Error(`${path} must be owned by the current user`);
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error(`${path} must not be accessible by group or other users`);
  }
}

async function readProtectedConfig(): Promise<string> {
  await assertProtectedPath(CONFIG_DIR, "directory");
  await assertProtectedPath(CONFIG_PATH, "file");
  return readFile(CONFIG_PATH, "utf-8");
}

function requireString(
  config: Partial<X402Config>,
  key: keyof X402Config,
): string {
  const value = config[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Missing required x402 configuration field: ${key}`);
  }
  return value;
}

function normalizeConfig(config: Partial<X402Config>): X402Config {
  const allowedRecipients = config.allowedRecipients;
  if (!Array.isArray(allowedRecipients) || allowedRecipients.length === 0) {
    throw new Error(
      "x402 configuration must contain at least one allowed recipient",
    );
  }

  return {
    region: config.region ?? "us-east-1",
    paymentManagerArn: requireString(config, "paymentManagerArn"),
    paymentInstrumentId: requireString(config, "paymentInstrumentId"),
    userId: requireString(config, "userId"),
    payment_session_id: requireString(config, "payment_session_id"),
    networkPreferences: config.networkPreferences,
    allowedOrigins: config.allowedOrigins,
    allowedRecipients,
    allowedAssetsByNetwork: config.allowedAssetsByNetwork,
    maxPaymentAmountAtomic: config.maxPaymentAmountAtomic,
  };
}

/**
 * Load immutable runtime configuration from trusted plugin settings or a
 * user-owned, non-group/world-accessible ~/.x402/config.json.
 */
export async function loadConfig(
  pluginConfig?: Partial<X402Config>,
): Promise<X402Config> {
  if (cachedConfig) return cachedConfig;

  if (pluginConfig?.paymentManagerArn) {
    cachedConfig = normalizeConfig(pluginConfig);
    return cachedConfig;
  }

  try {
    const fileConfig = JSON.parse(
      await readProtectedConfig(),
    ) as Partial<X402Config>;
    cachedConfig = normalizeConfig(fileConfig);
    return cachedConfig;
  } catch (error) {
    if (isNotFound(error)) {
      throw new Error(
        "x402 config not found in trusted plugin settings or ~/.x402/config.json",
      );
    }
    throw new Error(
      `x402 configuration refused: ${error instanceof Error ? error.message : "invalid config"}`,
    );
  }
}

export function getConfig(): X402Config {
  if (!cachedConfig) {
    throw new Error("Config not loaded. Call loadConfig() first.");
  }
  return cachedConfig;
}
