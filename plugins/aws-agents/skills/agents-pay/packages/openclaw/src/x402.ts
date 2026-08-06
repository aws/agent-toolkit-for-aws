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
}

export interface X402Challenge {
  version: "2";
  challenge: Record<string, unknown>;
  accepts: Record<string, unknown>[];
  resource: Record<string, unknown>;
}

export interface AuthorizedChallenge extends X402Challenge {
  accepted: Record<string, unknown>;
}

const MAX_RESPONSE_BYTES = 65_536;
const REQUEST_TIMEOUT_MS = 15_000;
const DEFAULT_NETWORKS = ["eip155:84532"];
const DEFAULT_ASSETS_BY_NETWORK: Record<string, string[]> = {
  "eip155:84532": ["0x036cbd53842c5426634e7929541ec2318f3dcf7e"],
};

const MAX_VALID_AFTER_WAIT_MS = 15_000;

export class PaymentBlocked extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PaymentBlocked";
  }
}

function ipv4ToNumber(ip: string): number {
  const octets = ip.split(".").map(Number);
  if (
    octets.length !== 4 ||
    octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)
  ) {
    throw new PaymentBlocked("Payment URL resolved to an invalid IPv4 address");
  }
  return octets.reduce((acc, octet) => (acc << 8) + octet, 0) >>> 0;
}

function inRange(value: number, cidrBase: string, bits: number): boolean {
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return (value & mask) === (ipv4ToNumber(cidrBase) & mask);
}

export function isBlockedIPv4(ip: string): boolean {
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
    ["192.88.99.0", 24],
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
  return [
    ...headParts,
    ...Array(Math.max(missing, 0)).fill("0"),
    ...tailParts,
  ].map((part) => part.padStart(4, "0"));
}

export function isBlockedIPv6(ip: string): boolean {
  const parts = expandIPv6(ip);
  if (parts.length !== 8 || parts.some((part) => !/^[0-9a-f]{4}$/.test(part))) {
    return true;
  }

  const first = Number.parseInt(parts[0], 16);
  const second = Number.parseInt(parts[1], 16);
  const isMappedIPv4 =
    parts.slice(0, 5).every((part) => part === "0000") && parts[5] === "ffff";
  if (isMappedIPv4) {
    const high = Number.parseInt(parts[6], 16);
    const low = Number.parseInt(parts[7], 16);
    const mapped = `${high >> 8}.${high & 0xff}.${low >> 8}.${low & 0xff}`;
    return isBlockedIPv4(mapped);
  }

  return (
    parts.every((part) => part === "0000") ||
    (parts.slice(0, 7).every((part) => part === "0000") &&
      parts[7] === "0001") ||
    (first & 0xfe00) === 0xfc00 ||
    (first & 0xffc0) === 0xfe80 ||
    (first & 0xff00) === 0xff00 ||
    (first === 0x2001 && second === 0x0db8)
  );
}

export function assertPublicAddress(address: string): void {
  const family = isIP(address);
  if (
    (family === 4 && isBlockedIPv4(address)) ||
    (family === 6 && isBlockedIPv6(address))
  ) {
    throw new PaymentBlocked("Payment URL resolves to a non-public address");
  }
  if (!family) {
    throw new PaymentBlocked("Payment URL resolved to an invalid address");
  }
}

export function assertHttpsUrl(rawUrl: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new PaymentBlocked("Payment URL is invalid");
  }
  if (parsed.protocol !== "https:") {
    throw new PaymentBlocked(
      "Only HTTPS URLs are allowed for payment requests",
    );
  }
  if (!parsed.hostname || parsed.username || parsed.password) {
    throw new PaymentBlocked(
      "Payment URL must have a hostname and no embedded credentials",
    );
  }
  if (isIP(parsed.hostname)) {
    assertPublicAddress(parsed.hostname);
  }
  return parsed;
}

function outputHeaders(
  headers: NodeJS.Dict<string | string[]>,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    result[key.toLowerCase()] = Array.isArray(value)
      ? value.join(", ")
      : String(value ?? "");
  }
  return result;
}

async function hardenedGet(
  rawUrl: string,
  headers: Record<string, string> = {},
): Promise<ProbeResult & { url: string }> {
  const parsed = assertHttpsUrl(rawUrl);

  return new Promise((resolve, reject) => {
    const req = request(
      parsed,
      {
        method: "GET",
        headers,
        timeout: REQUEST_TIMEOUT_MS,
        lookup(hostname, options, callback) {
          lookup(hostname, options, (error, address, family) => {
            if (error) {
              callback(error, address, family);
              return;
            }
            try {
              if (Array.isArray(address)) {
                for (const entry of address) assertPublicAddress(entry.address);
              } else {
                assertPublicAddress(address);
              }
              callback(null, address as any, family as any);
            } catch (validationError) {
              callback(validationError as Error, address as any, family as any);
            }
          });
        },
      },
      (response) => {
        const status = response.statusCode ?? 0;
        if (status >= 300 && status < 400) {
          response.resume();
          reject(
            new PaymentBlocked("Redirects are disabled for payment requests"),
          );
          return;
        }

        const chunks: Buffer[] = [];
        let total = 0;
        const hash = createHash("sha256");

        response.on("data", (chunk: Buffer) => {
          total += chunk.length;
          if (total > MAX_RESPONSE_BYTES) {
            req.destroy(
              new PaymentBlocked(
                `Response exceeded ${MAX_RESPONSE_BYTES} byte limit`,
              ),
            );
            return;
          }
          hash.update(chunk);
          chunks.push(chunk);
        });

        response.on("end", () => {
          const headersOut = outputHeaders(response.headers);
          resolve({
            status,
            headers: headersOut,
            body: Buffer.concat(chunks).toString("utf-8"),
            bodyBytes: total,
            bodySha256: hash.digest("hex"),
            contentType: headersOut["content-type"] ?? "",
            url: parsed.toString(),
          });
        });
      },
    );

    req.on("timeout", () =>
      req.destroy(new PaymentBlocked("Payment request timed out")),
    );
    req.on("error", reject);
    req.end();
  });
}

export async function probeUrl(url: string): Promise<ProbeResult> {
  return hardenedGet(url, { Accept: "application/json" });
}

function decodeChallenge(probe: ProbeResult): Record<string, unknown> {
  const header =
    probe.headers["payment-required"] ?? probe.headers["x-payment-required"];
  if (header) {
    for (const candidate of [
      () => Buffer.from(header, "base64").toString("utf-8"),
      () => header,
    ]) {
      try {
        const parsed = JSON.parse(candidate()) as unknown;
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>;
        }
      } catch {
        // Try the next supported encoding.
      }
    }
  }

  try {
    const body = JSON.parse(probe.body) as unknown;
    if (body && typeof body === "object" && !Array.isArray(body)) {
      const object = body as Record<string, unknown>;
      const nested = object.challenge;
      if (nested && typeof nested === "object" && !Array.isArray(nested)) {
        return nested as Record<string, unknown>;
      }
      return object;
    }
  } catch {
    // Refuse below with a non-sensitive error.
  }
  throw new PaymentBlocked("402 response contains no parseable x402 challenge");
}

export function extractChallenge(probe: ProbeResult): X402Challenge {
  const parsed = decodeChallenge(probe);
  const version = String(parsed.x402Version ?? parsed.version ?? "");
  if (version !== "2") {
    throw new PaymentBlocked("Only x402 v2 payment challenges are supported");
  }
  const accepts = parsed.accepts;
  if (!Array.isArray(accepts) || accepts.length === 0) {
    throw new PaymentBlocked("x402 challenge is missing its accepts array");
  }
  const entries = accepts.filter((entry): entry is Record<string, unknown> =>
    Boolean(entry && typeof entry === "object" && !Array.isArray(entry)),
  );
  if (entries.length === 0) {
    throw new PaymentBlocked(
      "x402 challenge contains no valid payment options",
    );
  }
  const resource =
    parsed.resource &&
    typeof parsed.resource === "object" &&
    !Array.isArray(parsed.resource)
      ? (parsed.resource as Record<string, unknown>)
      : {};
  return { version: "2", challenge: parsed, accepts: entries, resource };
}

function normalize(value: unknown): string {
  return String(value ?? "").toLowerCase();
}

function parseAmount(value: unknown): bigint {
  const amount = String(value ?? "");
  if (!/^[0-9]+$/.test(amount)) {
    throw new PaymentBlocked(
      "Payment amount must be a plain integer in atomic units",
    );
  }
  const parsed = BigInt(amount);
  if (parsed <= 0n) {
    throw new PaymentBlocked("Payment amount must be positive");
  }
  return parsed;
}

function configuredAssets(config: X402Config, network: string): string[] {
  const byNetwork = config.allowedAssetsByNetwork?.[network];
  if (byNetwork?.length) return byNetwork.map(normalize);
  return (DEFAULT_ASSETS_BY_NETWORK[network] ?? []).map(normalize);
}

function sameResource(left: URL, right: URL): boolean {
  return left.origin === right.origin && left.pathname === right.pathname;
}

export function validateChallengePolicy(
  challenge: X402Challenge,
  requestUrl: string,
  config: X402Config,
): AuthorizedChallenge {
  const requested = assertHttpsUrl(requestUrl);
  const allowedOrigins = (config.allowedOrigins ?? []).map((origin) =>
    assertHttpsUrl(origin).origin.toLowerCase(),
  );
  if (
    allowedOrigins.length > 0 &&
    !allowedOrigins.includes(requested.origin.toLowerCase())
  ) {
    throw new PaymentBlocked(
      "Payment origin is not approved by runtime policy",
    );
  }

  const resourceUrl = challenge.resource.url;
  if (
    typeof resourceUrl !== "string" ||
    !sameResource(assertHttpsUrl(resourceUrl), requested)
  ) {
    throw new PaymentBlocked(
      "Payment challenge resource does not match the requested URL",
    );
  }

  const networks = config.networkPreferences?.length
    ? config.networkPreferences
    : DEFAULT_NETWORKS;
  const recipients = (config.allowedRecipients ?? []).map(normalize);
  const maxAmount = parseAmount(config.maxPaymentAmountAtomic);

  for (const accepted of challenge.accepts) {
    const scheme = String(accepted.scheme ?? "");
    const network = String(accepted.network ?? "");
    const asset = normalize(accepted.asset);
    const recipient = normalize(accepted.payTo);
    let amount: bigint;
    try {
      amount = parseAmount(accepted.amount ?? accepted.maxAmountRequired);
    } catch {
      continue;
    }
    if (
      scheme === "exact" &&
      networks.includes(network) &&
      configuredAssets(config, network).includes(asset) &&
      (config.allowAnyRecipient === true || recipients.includes(recipient)) &&
      amount <= maxAmount
    ) {
      return { ...challenge, accepted };
    }
  }

  throw new PaymentBlocked(
    "No payment option satisfies the configured scheme, network, asset, recipient, and amount policy",
  );
}

export function buildProcessPaymentPayload(
  accepted: Record<string, unknown>,
): Record<string, unknown> {
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

export function buildPaymentPayloadEnvelope(
  resource: Record<string, unknown>,
  accepted: Record<string, unknown>,
  signedPayload: Record<string, unknown>,
): string {
  const envelope = {
    x402Version: 2,
    resource,
    accepted,
    payload: signedPayload,
  };
  return Buffer.from(JSON.stringify(envelope)).toString("base64");
}

export function paymentSignatureHeader(value: string): Record<string, string> {
  return { "PAYMENT-SIGNATURE": value };
}

export async function sleepPastValidAfter(
  signedPayload: Record<string, unknown>,
): Promise<void> {
  const authorization = signedPayload.authorization;
  if (
    !authorization ||
    typeof authorization !== "object" ||
    Array.isArray(authorization)
  )
    return;
  const raw = (authorization as Record<string, unknown>).validAfter;
  if (raw === undefined || raw === null) return;
  const validAfter =
    typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
  if (!Number.isFinite(validAfter)) {
    throw new PaymentBlocked(
      "Signed payment contains an invalid validAfter value",
    );
  }
  const waitMs = validAfter * 1000 - Date.now() + 1000;
  if (waitMs <= 0) return;
  if (waitMs > MAX_VALID_AFTER_WAIT_MS) {
    throw new PaymentBlocked(
      "Signed payment is not valid within the bounded retry window",
    );
  }
  await new Promise((resolve) => setTimeout(resolve, waitMs));
}

export async function replayWithHeader(
  url: string,
  headerValue: string,
): Promise<{
  status: number;
  contentType: string;
  bodySha256: string;
  bodyBytes: number;
  url: string;
}> {
  const result = await hardenedGet(url, paymentSignatureHeader(headerValue));
  return {
    status: result.status,
    contentType: result.contentType,
    bodySha256: result.bodySha256,
    bodyBytes: result.bodyBytes,
    url: result.url,
  };
}
