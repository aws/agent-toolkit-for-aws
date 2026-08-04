import {
  BedrockAgentCoreClient,
  GetPaymentSessionCommand,
  ProcessPaymentCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import type { PaymentSession } from "@aws-sdk/client-bedrock-agentcore";
import { createHash } from "node:crypto";
import { getConfig } from "./config.js";

let client: BedrockAgentCoreClient | null = null;

function getClient(): BedrockAgentCoreClient {
  if (!client) {
    client = new BedrockAgentCoreClient({ region: getConfig().region });
  }
  return client;
}

export interface SessionStatus {
  usable: boolean;
  status: string;
  expired: boolean;
  minutes_left: number | null;
  remaining_usd: number | null;
}

export async function getPaymentSessionStatus(): Promise<SessionStatus> {
  const config = getConfig();
  const command = new GetPaymentSessionCommand({
    paymentManagerArn: config.paymentManagerArn,
    paymentSessionId: config.payment_session_id,
    userId: config.userId,
  } as any);

  try {
    const response = await getClient().send(command);
    const session: PaymentSession | undefined = response.paymentSession;
    if (!session) {
      return {
        usable: false,
        status: "not_found",
        expired: true,
        minutes_left: null,
        remaining_usd: null,
      };
    }

    let expired = false;
    let minutesLeft: number | null = null;
    if (session.createdAt && session.expiryTimeInMinutes) {
      const expiresAt =
        session.createdAt.getTime() + session.expiryTimeInMinutes * 60_000;
      expired = expiresAt <= Date.now();
      if (!expired) {
        minutesLeft = Math.max(
          0,
          Math.floor((expiresAt - Date.now()) / 60_000),
        );
      }
    }

    const rawRemaining = session.availableLimits?.availableSpendAmount?.value;
    const remainingUsd =
      rawRemaining === undefined ? null : Number.parseFloat(rawRemaining);
    const hasBudget =
      remainingUsd === null ||
      (Number.isFinite(remainingUsd) && remainingUsd > 0);
    const usable = !expired && hasBudget;

    return {
      usable,
      status: usable ? "ACTIVE" : expired ? "EXPIRED" : "DRAINED",
      expired,
      minutes_left: minutesLeft,
      remaining_usd: remainingUsd,
    };
  } catch {
    return {
      usable: false,
      status: "error",
      expired: true,
      minutes_left: null,
      remaining_usd: null,
    };
  }
}

function stableResource(url: string): string {
  const parsed = new URL(url);
  return `${parsed.origin}${parsed.pathname || "/"}`;
}

/**
 * Build one stable token per logical purchase. Publisher-controlled fields such
 * as extra.nonce are deliberately excluded so a rotating challenge cannot turn
 * a retry into another payment.
 */
export function deriveClientToken(
  sessionId: string,
  resourceUrl: string,
  accepted: Record<string, unknown>,
): string {
  const material = [
    sessionId,
    stableResource(resourceUrl),
    String(accepted.scheme ?? ""),
    String(accepted.network ?? ""),
    String(accepted.asset ?? "").toLowerCase(),
    String(accepted.payTo ?? "").toLowerCase(),
    String(accepted.amount ?? accepted.maxAmountRequired ?? ""),
  ].join("\x1f");
  return createHash("sha256").update(material).digest("hex");
}

export interface PaymentResult {
  signedPayload: Record<string, unknown>;
}

export async function processPayment(
  version: string,
  accepted: Record<string, unknown>,
  resourceUrl: string,
): Promise<PaymentResult> {
  if (version !== "2") {
    throw new Error("Only x402 v2 payment challenges are supported");
  }

  const config = getConfig();
  const command = new ProcessPaymentCommand({
    paymentManagerArn: config.paymentManagerArn,
    paymentSessionId: config.payment_session_id,
    paymentInstrumentId: config.paymentInstrumentId,
    userId: config.userId,
    clientToken: deriveClientToken(
      config.payment_session_id,
      resourceUrl,
      accepted,
    ),
    paymentType: "CRYPTO_X402",
    paymentInput: {
      cryptoX402: {
        version,
        payload: accepted as any,
      },
    },
  });

  const response = await getClient().send(command);
  const paymentOutput = response.paymentOutput;
  if (
    !paymentOutput ||
    !("cryptoX402" in paymentOutput) ||
    !paymentOutput.cryptoX402?.payload
  ) {
    throw new Error(
      "ProcessPayment did not return a signed cryptoX402 payload",
    );
  }

  const payload = paymentOutput.cryptoX402.payload;
  const normalized: unknown =
    typeof payload === "string" ? JSON.parse(payload) : payload;
  if (
    !normalized ||
    typeof normalized !== "object" ||
    Array.isArray(normalized)
  ) {
    throw new Error("ProcessPayment returned an invalid signed payload");
  }
  return { signedPayload: normalized as Record<string, unknown> };
}
