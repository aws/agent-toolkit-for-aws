/**
 * x402 protocol helpers: hardened URL access, challenge extraction, policy
 * validation, and replay with payment headers.
 */

import { createHash } from "node:crypto";
import { lookup } from "node:dns";
import { request } from "node:https";
import { isIP } from "node:net";
import type { X402Config } from "./config.js";

export interface ProbeResult {
  status: number;
  headers: Record<string, string>;
  body: string;
  contentType: string;
  bodySha256: string;
  bodyBytes: number;
  truncated: boolean;
}

const MAX_RESPONSE_BYTES = 65536; // 64KB
const REQUEST_TIMEOUT_MS = 15_000;
const MAX_REDIRECTS = 5;
const DEFAULT_NETWORKS = ["eip155:84532", "base-sepolia"];
const DEFAULT_ASSETS_BY_NETWORK: Record<string, string[]> = {
  "eip155:84532": ["0x036cbd53842c5426634e7929541ec2318f3dcf7e"],
  "base-sepolia": ["0x036cbd53842c5426634e7929541ec2318f3dcf7e"],
};
const DEFAULT_MAX_AMOUNT_ATOMIC = "100000"; // 0.10 USDC with 6 decimals.

class HttpError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HttpError";
  }
}

function ipv4ToNumber(ip: string): number {
  return ip.split(".").reduce((acc, octet) => (acc << 8) + Number(octet), 0) >>> 0;
}

function inRange(value: number, cidrBase: string, bits: number): boolean {
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return (value & mask) === (ipv4ToNumber(cidrBase) & mask);
}

function isBlockedIPv4(ip: string): boolean {
  const value = ipv4ToNumber(ip);
  return [
    ["0.0.0.0", 8],
    ["10.0.0.0", 8],
    ["100.64.0.0", 10],
    ["127.0.0.0", 8],
    ["169.254.0.0", 16],
    ["172.16.0.0", 12],
    ["192.0.0.0", 24],
    ["192.0.2.0", 24],
    ["192.168.0.0", 16],
    ["198.18.0.0", 15],
    ["198.51.100.0", 24],
    ["203.0.113.0", 24],
    ["224.0.0.0", 4],
    ["240.0.0.0", 4],
  ].some(([base, bits]) => inRange(value, base as string, bits as number));
}

function expandIPv6(ip: string): string[] {
  const [head, tail = ""] = ip.toLowerCase().split("::");
  const headParts = head ? head.split(":") : [];
  const tailParts = tail ? tail.split(":") : [];
  const missing = 8 - headParts.length - tailParts.length;
  return [...headParts, ...Array(Math.max(missing, 0)).fill("0"), ...tailParts].map((part) =>
    part.padStart(4, "0")
  );
}

function isBlockedIPv6(ip: string): boolean {
  if (ip.includes(".")) {
    const mapped = ip.substring(ip.lastIndexOf(":") + 1);
    return isBlockedIPv4(mapped);
  }
  const parts = expandIPv6(ip);
  const first = parseInt(parts[0], 16);
  const second = parseInt(parts[1] ?? "0", 16);
  return (
    ip === "::" ||
    ip === "::1" ||
    (first & 0xfe00) === 0xfc00 || // fc00::/7 unique local
    (first & 0xffc0) === 0xfe80 || // fe80::/10 link local
    (first & 0xff00) === 0xff00 || // ff00::/8 multicast
    (first === 0x2001 && second === 0x0db8) // documentation range
  );
}

function assertPublicAddress(address: string): void {
  const family = isIP(address);
  if (family === 4 && isBlockedIPv4(address)) {
    throw new HttpError(`Blocked unsafe IPv4 destination: ${address}`);
  }
  if (family === 6 && isBlockedIPv6(address)) {
    throw new HttpError(`Blocked unsafe IPv6 destination: ${address}`);
  }
  if (!family) {
    throw new HttpError(`Invalid resolved address: ${address}`);
  }
}

function assertHttpsUrl(rawUrl: string): URL {
  const parsed = new URL(rawUrl);
  if (parsed.protocol !== "https:") {
    throw new HttpError("Only HTTPS URLs are allowed for payment requests");
  }
  if (!parsed.hostname) {
    throw new HttpError("URL must include a hostname");
  }
  if (parsed.username || parsed.password) {
    throw new HttpError("URL credentials are not allowed");
  }
  if (isIP(parsed.hostname)) {
    assertPublicAddress(parsed.hostname);
  }
  return parsed;
}

async function hardenedGet(rawUrl: string, headers: Record<string, string> = {}, redirects = 0): Promise<ProbeResult & { url: string }> {
  const parsed = assertHttpsUrl(rawUrl);
  if (redirects > MAX_REDIRECTS) {
    throw new HttpError("Too many redirects");
  }

  return new Promise((resolve, reject) => {
    const req = request(
      parsed,
      {
        method: "GET",
        headers,
        timeout: REQUEST_TIMEOUT_MS,
        lookup(hostname, options, callback) {
          lookup(hostname, options, (err, address, family) => {
            if (err) {
              callback(err, address, family);
              return;
            }
            try {
              if (Array.isArray(address)) {
                for (const entry of address) assertPublicAddress(entry.address);
              } else {
                assertPublicAddress(address);
              }
              callback(null, address as any, family as any);
            } catch (validationErr) {
              callback(validationErr as Error, address as any, family as any);
            }
          });
        },
      },
      (response) => {
        const status = response.statusCode ?? 0;
        const location = response.headers.location;
        if (status >= 300 && status < 400 && location) {
          response.resume();
          const redirectUrl = new URL(location, parsed);
          if (headers["X-PAYMENT"] && redirectUrl.origin !== parsed.origin) {
            reject(new HttpError("Refusing to forward payment header across origins"));
            return;
          }
          hardenedGet(redirectUrl.toString(), headers, redirects + 1).then(resolve, reject);
          return;
        }

        const chunks: Buffer[] = [];
        let total = 0;
        let truncated = false;
        const hash = createHash("sha256");

        response.on("data", (chunk: Buffer) => {
          total += chunk.length;
          hash.update(chunk);
          if (total <= MAX_RESPONSE_BYTES) {
            chunks.push(chunk);
          } else {
            truncated = true;
            req.destroy(new HttpError(`Response exceeded ${MAX_RESPONSE_BYTES} byte limit`));
          }
        });

        response.on("end", () => {
          const outputHeaders: Record<string, string> = {};
          for (const [key, value] of Object.entries(response.headers)) {
            outputHeaders[key.toLowerCase()] = Array.isArray(value) ? value.join(", ") : String(value ?? "");
          }
          const body = Buffer.concat(chunks).toString("utf-8");
          resolve({
            status,
            headers: outputHeaders,
            body,
            bodyBytes: total,
            bodySha256: hash.digest("hex"),
            contentType: outputHeaders["content-type"] ?? "",
            truncated,
            url: rawUrl,
          });
        });
      }
    );

    req.on("timeout", () => req.destroy(new HttpError("Request timed out")));
    req.on("error", reject);
    req.end();
  });
}

/**
 * Probe a URL to check if it returns a 402 with an x402 challenge
 */
export async function probeUrl(url: string): Promise<ProbeResult> {
  return hardenedGet(url, { Accept: "application/json" });
}

export interface X402Challenge {
  version: string;
  /** The full decoded challenge object (contains x402Version, resource, accepts, extensions) */
  challenge: Record<string, unknown>;
  /** The chosen accepts entry (first one that matches our supported networks) */
  accepted: Record<string, unknown>;
  /** Resource info from the challenge */
  resource: Record<string, unknown>;
}

/**
 * Extract the x402 challenge from a 402 response.
 * Looks in headers (payment-required or x-payment-required) first,
 * then falls back to parsing the response body.
 *
 * Returns the full parsed challenge with the chosen accepts entry.
 */
export function extractChallenge(probe: ProbeResult): X402Challenge {
  let parsed: Record<string, unknown> | null = null;

  // Try headers first — base64 encoded JSON
  const challengeHeader = probe.headers["payment-required"] ?? probe.headers["x-payment-required"];

  if (challengeHeader) {
    try {
      const decoded = Buffer.from(challengeHeader, "base64").toString("utf-8");
      parsed = JSON.parse(decoded) as Record<string, unknown>;
    } catch {
      // If base64 decode fails, try it as raw JSON
      try {
        parsed = JSON.parse(challengeHeader) as Record<string, unknown>;
      } catch {
        // Fall through to body parsing
      }
    }
  }

  // Try body if header didn't work
  if (!parsed) {
    try {
      const bodyParsed = JSON.parse(probe.body) as Record<string, unknown>;
      if (bodyParsed.x402Version || bodyParsed.version || bodyParsed.accepts) {
        parsed = bodyParsed;
      } else if (bodyParsed.challenge) {
        parsed = bodyParsed.challenge as Record<string, unknown>;
      }
    } catch {
      // Can't parse body
    }
  }

  if (!parsed) {
    throw new Error(
      `Could not extract x402 challenge from response. Status: ${probe.status}, Body: ${probe.body.slice(0, 200)}`
    );
  }

  const version = String(parsed.x402Version ?? parsed.version ?? "1");
  const accepts = parsed.accepts as Record<string, unknown>[] | undefined;

  if (!accepts || accepts.length === 0) {
    throw new Error("x402 challenge has no accepts entries");
  }

  const accepted = accepts[0];
  const resource = (parsed.resource ?? {}) as Record<string, unknown>;

  return { version, challenge: parsed, accepted, resource };
}

function normalizeAddress(value: unknown): string {
  return String(value ?? "").toLowerCase();
}

function parseAmount(value: unknown): bigint {
  const amount = String(value ?? "");
  if (!/^[0-9]+$/.test(amount)) {
    throw new Error("Payment amount must be a positive integer in atomic units");
  }
  const parsed = BigInt(amount);
  if (parsed <= 0n) {
    throw new Error("Payment amount must be positive");
  }
  return parsed;
}

export function validateChallengePolicy(challenge: X402Challenge, requestUrl: string, config: X402Config): void {
  const parsedUrl = assertHttpsUrl(requestUrl);
  const accepted = challenge.accepted;
  const scheme = String(accepted.scheme ?? "");
  const network = String(accepted.network ?? "");
  const amount = parseAmount(accepted.amount ?? accepted.maxAmountRequired);
  const asset = normalizeAddress(accepted.asset);
  const payTo = normalizeAddress(accepted.payTo);

  if (scheme !== "exact") {
    throw new Error(`Unsupported payment scheme: ${scheme}`);
  }

  const allowedNetworks = config.networkPreferences?.length ? config.networkPreferences : DEFAULT_NETWORKS;
  if (!allowedNetworks.includes(network)) {
    throw new Error(`Payment network ${network} is not in the configured allowlist`);
  }

  const defaultAssets = allowedNetworks.flatMap((allowedNetwork) => DEFAULT_ASSETS_BY_NETWORK[allowedNetwork] ?? []);
  const allowedAssets = (config.allowedAssets?.length ? config.allowedAssets : defaultAssets).map(normalizeAddress);
  if (allowedAssets.length > 0 && !allowedAssets.includes(asset)) {
    throw new Error(`Payment asset ${asset} is not in the configured allowlist`);
  }

  const maxAmount = BigInt(config.maxPaymentAmountAtomic ?? DEFAULT_MAX_AMOUNT_ATOMIC);
  if (amount > maxAmount) {
    throw new Error(`Payment amount ${amount.toString()} exceeds configured maximum ${maxAmount.toString()}`);
  }

  const allowedRecipients = (config.allowedRecipients ?? []).map(normalizeAddress);
  if (allowedRecipients.length === 0) {
    throw new Error("No approved payment recipients configured");
  }
  if (!allowedRecipients.includes(payTo)) {
    throw new Error(`Payment recipient ${payTo} is not approved for this runtime`);
  }

  const resourceUrl = String((challenge.resource as any)?.url ?? (challenge.challenge as any)?.resourceUrl ?? "");
  if (resourceUrl) {
    const resourceOrigin = assertHttpsUrl(resourceUrl).origin;
    if (resourceOrigin !== parsedUrl.origin) {
      throw new Error("Payment challenge resource origin does not match requested URL origin");
    }
  }
}

/**
 * Build the ProcessPayment payload from the accepted challenge entry.
 * AgentCore expects the accepts object fields (scheme, network, amount, asset, payTo, etc.)
 */
export function buildProcessPaymentPayload(accepted: Record<string, unknown>): Record<string, unknown> {
  return {
    scheme: accepted.scheme,
    network: accepted.network,
    amount: accepted.amount ?? accepted.maxAmountRequired,
    asset: accepted.asset,
    payTo: accepted.payTo,
    maxTimeoutSeconds: accepted.maxTimeoutSeconds,
    extra: accepted.extra,
  };
}

/**
 * Build the x402 v2 PaymentPayload envelope from the signed payment output.
 * This is what goes into the X-PAYMENT header (base64 encoded).
 *
 * Per x402 v2 spec, the PaymentPayload structure is:
 * {
 *   x402Version: 2,
 *   resource: { url, description, mimeType },
 *   accepted: { scheme, network, amount, asset, payTo, maxTimeoutSeconds, extra },
 *   payload: { authorization: {...}, signature: "0x..." }
 * }
 */
export function buildPaymentPayloadEnvelope(
  resource: Record<string, unknown>,
  accepted: Record<string, unknown>,
  signedPayload: Record<string, unknown>
): string {
  const envelope = {
    x402Version: 2,
    resource,
    accepted,
    payload: signedPayload,
  };
  return Buffer.from(JSON.stringify(envelope)).toString("base64");
}

/**
 * Inspect the signed payment output and sleep past validAfter if needed.
 * This prevents EVM clock skew issues where the signature is used before it's valid.
 */
export async function sleepPastValidAfter(signedPayload: Record<string, unknown>): Promise<void> {
  try {
    const authorization = signedPayload.authorization as Record<string, unknown> | undefined;
    if (!authorization) return;

    const validAfter = authorization.validAfter as string | number | undefined;
    if (!validAfter) return;

    const validAfterSec = typeof validAfter === "string" ? parseInt(validAfter, 10) : validAfter;
    const validAfterMs = validAfterSec * 1000;
    const now = Date.now();

    if (validAfterMs > now) {
      const sleepMs = validAfterMs - now + 1000; // +1s buffer
      await new Promise((resolve) => setTimeout(resolve, Math.min(sleepMs, 10000))); // Cap at 10s
    }
  } catch {
    // Non-fatal — skip sleep on any decode error
  }
}

/**
 * Replay a request to the URL with the payment header attached.
 * For x402 v2, uses X-PAYMENT header with base64-encoded PaymentPayload.
 */
export async function replayWithHeader(
  url: string,
  headerName: string,
  headerValue: string
): Promise<{ status: number; contentType: string; bodySha256: string; bodyBytes: number; url: string }> {
  const result = await hardenedGet(url, { [headerName]: headerValue });
  return {
    status: result.status,
    contentType: result.contentType,
    bodySha256: result.bodySha256,
    bodyBytes: result.bodyBytes,
    url: result.url,
  };
}
