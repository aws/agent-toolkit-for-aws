import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_INPUT_BYTES = 128 * 1024;
const MAX_OUTPUT_BYTES = 128 * 1024;
const MAX_STDERR_BYTES = 16 * 1024;
const BRIDGE_TIMEOUT_MS = 30_000;

type BridgeRequest =
  | {
      operation: "get_payment_session";
      region: string;
      payment_manager_arn: string;
      payment_session_id: string;
      user_id: string;
      agent_name: string;
    }
  | {
      operation: "process_payment";
      region: string;
      payment_manager_arn: string;
      payment_session_id: string;
      payment_instrument_id: string;
      user_id: string;
      agent_name: string;
      client_token: string;
      version: string;
      payload: Record<string, unknown>;
    };

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const bridgePath = path.join(
  packageRoot,
  "runtime",
  "agentcore_bridge.py",
);
const pythonPath =
  process.platform === "win32"
    ? path.join(
        packageRoot,
        "skills",
        "agents-pay",
        ".venv",
        "Scripts",
        "python.exe",
      )
    : path.join(
        packageRoot,
        "skills",
        "agents-pay",
        ".venv",
        "bin",
        "python",
      );

export function parseBridgeResponse(serialized: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(serialized);
  if (
    !parsed ||
    typeof parsed !== "object" ||
    Array.isArray(parsed) ||
    !("ok" in parsed) ||
    parsed.ok !== true ||
    !("result" in parsed) ||
    !parsed.result ||
    typeof parsed.result !== "object" ||
    Array.isArray(parsed.result)
  ) {
    throw new Error("AgentCore bridge returned an invalid response");
  }
  return parsed.result as Record<string, unknown>;
}

export async function invokeAgentCoreBridge(
  request: BridgeRequest,
): Promise<Record<string, unknown>> {
  const serialized = JSON.stringify(request);
  if (Buffer.byteLength(serialized) > MAX_INPUT_BYTES) {
    throw new Error("AgentCore bridge request exceeded its size limit");
  }

  await Promise.all([
    access(bridgePath, constants.R_OK),
    access(pythonPath, constants.X_OK),
  ]);

  return new Promise((resolve, reject) => {
    const child = spawn(pythonPath, [bridgePath], {
      cwd: packageRoot,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONNOUSERSITE: "1",
      },
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const stdout: Buffer[] = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let settled = false;

    const clearStdout = () => {
      for (const chunk of stdout) chunk.fill(0);
      stdout.length = 0;
    };

    const finishWithError = (message: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.kill("SIGKILL");
      clearStdout();
      reject(new Error(message));
    };

    const timer = setTimeout(() => {
      finishWithError("AgentCore bridge timed out");
    }, BRIDGE_TIMEOUT_MS);

    child.on("error", () => {
      finishWithError("AgentCore bridge could not start");
    });
    child.stdout.on("data", (chunk: Buffer) => {
      stdoutBytes += chunk.length;
      if (stdoutBytes > MAX_OUTPUT_BYTES) {
        finishWithError("AgentCore bridge response exceeded its size limit");
        return;
      }
      stdout.push(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderrBytes += chunk.length;
      if (stderrBytes > MAX_STDERR_BYTES) {
        finishWithError("AgentCore bridge diagnostics exceeded their size limit");
      }
    });
    child.stdin.on("error", () => {
      finishWithError("AgentCore bridge input failed");
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        clearStdout();
        reject(new Error("AgentCore bridge request failed"));
        return;
      }
      const combined = Buffer.concat(stdout);
      try {
        resolve(parseBridgeResponse(combined.toString("utf8")));
      } catch {
        reject(new Error("AgentCore bridge returned an invalid response"));
      } finally {
        combined.fill(0);
        clearStdout();
      }
    });

    child.stdin.end(serialized);
  });
}
