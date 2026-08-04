import { chmod, lstat, mkdir, open, readFile, rename } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export interface X402Config {
  region: string;
  paymentManagerArn: string;
  paymentInstrumentId: string;
  userId: string;
  networkPreferences?: string[];
  allowedRecipients?: string[];
  allowedAssets?: string[];
  maxPaymentAmountAtomic?: string;
  payment_session_id?: string;
}

const CONFIG_DIR = join(homedir(), ".x402");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");
const CONFIG_FILE_MODE = 0o600;
const CONFIG_DIR_MODE = 0o700;

let cachedConfig: X402Config | null = null;

/**
 * Load config from plugin config (passed in) or fallback to ~/.x402/config.json
 */
export async function loadConfig(pluginConfig?: Partial<X402Config>): Promise<X402Config> {
  if (cachedConfig) return cachedConfig;

  // Try plugin config first
  if (pluginConfig && pluginConfig.paymentManagerArn && pluginConfig.paymentInstrumentId && pluginConfig.userId) {
    cachedConfig = {
      region: pluginConfig.region ?? "us-east-1",
      paymentManagerArn: pluginConfig.paymentManagerArn,
      paymentInstrumentId: pluginConfig.paymentInstrumentId,
      userId: pluginConfig.userId,
      networkPreferences: pluginConfig.networkPreferences,
      allowedRecipients: pluginConfig.allowedRecipients,
      allowedAssets: pluginConfig.allowedAssets,
      maxPaymentAmountAtomic: pluginConfig.maxPaymentAmountAtomic,
      payment_session_id: pluginConfig.payment_session_id,
    };

    // Try to load session ID from file if not in plugin config
    if (!cachedConfig.payment_session_id) {
      try {
        const fileConfig = JSON.parse(await readProtectedConfig());
        if (fileConfig.payment_session_id) {
          cachedConfig.payment_session_id = fileConfig.payment_session_id;
        }
      } catch {
        // File doesn't exist or is invalid — that's fine
      }
    }

    return cachedConfig;
  }

  // Fallback: load from ~/.x402/config.json
  try {
    const raw = await readProtectedConfig();
    const fileConfig = JSON.parse(raw) as X402Config;
    cachedConfig = {
      region: fileConfig.region ?? "us-east-1",
      paymentManagerArn: fileConfig.paymentManagerArn,
      paymentInstrumentId: fileConfig.paymentInstrumentId,
      userId: fileConfig.userId,
      networkPreferences: fileConfig.networkPreferences,
      allowedRecipients: fileConfig.allowedRecipients,
      allowedAssets: fileConfig.allowedAssets,
      maxPaymentAmountAtomic: fileConfig.maxPaymentAmountAtomic,
      payment_session_id: fileConfig.payment_session_id,
    };
    return cachedConfig;
  } catch (err) {
    throw new Error(
      `x402 config not found. Provide config via OpenClaw plugin settings or create ~/.x402/config.json. Error: ${err}`
    );
  }
}

async function ensureConfigDir(): Promise<void> {
  await mkdir(CONFIG_DIR, { recursive: true, mode: CONFIG_DIR_MODE });
  await chmod(CONFIG_DIR, CONFIG_DIR_MODE);
}

async function assertSafeConfigPath(): Promise<void> {
  try {
    const st = await lstat(CONFIG_PATH);
    if (!st.isFile()) {
      throw new Error(`${CONFIG_PATH} is not a regular file`);
    }
    if (st.isSymbolicLink()) {
      throw new Error(`${CONFIG_PATH} must not be a symbolic link`);
    }
    if (typeof process.getuid === "function" && st.uid !== process.getuid()) {
      throw new Error(`${CONFIG_PATH} is not owned by the current user`);
    }
    await chmod(CONFIG_PATH, CONFIG_FILE_MODE);
  } catch (err: any) {
    if (err?.code === "ENOENT") return;
    throw err;
  }
}

async function readProtectedConfig(): Promise<string> {
  await assertSafeConfigPath();
  return readFile(CONFIG_PATH, "utf-8");
}

async function writeProtectedConfig(config: Record<string, unknown>): Promise<void> {
  await ensureConfigDir();
  await assertSafeConfigPath();

  const tmpPath = join(CONFIG_DIR, `config.json.${process.pid}.${Date.now()}.tmp`);
  const handle = await open(tmpPath, "wx", CONFIG_FILE_MODE);
  try {
    await handle.writeFile(JSON.stringify(config, null, 2) + "\n", "utf-8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await chmod(tmpPath, CONFIG_FILE_MODE);
  await rename(tmpPath, CONFIG_PATH);
  await chmod(CONFIG_PATH, CONFIG_FILE_MODE);
}

/**
 * Get the current config (must be loaded first)
 */
export function getConfig(): X402Config {
  if (!cachedConfig) {
    throw new Error("Config not loaded. Call loadConfig() first.");
  }
  return cachedConfig;
}

/**
 * Save the full config to ~/.x402/config.json (used after setup)
 */
export async function saveFullConfig(config: X402Config): Promise<void> {
  cachedConfig = config;
  try {
    await writeProtectedConfig(config as unknown as Record<string, unknown>);
  } catch (err) {
    console.error(`Warning: could not write config to ${CONFIG_PATH}: ${err}`);
  }
}

/**
 * Update the payment session ID in memory and persist to disk
 */
export async function setPaymentSessionId(sessionId: string): Promise<void> {
  if (!cachedConfig) {
    throw new Error("Config not loaded. Call loadConfig() first.");
  }

  cachedConfig.payment_session_id = sessionId;

  // Persist to ~/.x402/config.json
  try {
    let fileConfig: Record<string, unknown> = {};
    try {
      fileConfig = JSON.parse(await readProtectedConfig());
    } catch {
      // File doesn't exist yet — start fresh
    }

    fileConfig.payment_session_id = sessionId;
    await writeProtectedConfig(fileConfig);
  } catch (err) {
    // Non-fatal: we still have it in memory
    console.error(`Warning: could not persist session ID to ${CONFIG_PATH}: ${err}`);
  }
}
