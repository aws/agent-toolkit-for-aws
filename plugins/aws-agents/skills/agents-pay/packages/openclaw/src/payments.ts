import {
  BedrockAgentCoreClient,
  GetPaymentSessionCommand,
  ProcessPaymentCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import type {
  PaymentSession,
} from "@aws-sdk/client-bedrock-agentcore";
import { createHash } from "node:crypto";
import { getConfig } from "./config.js";

let client: BedrockAgentCoreClient | null = null;

function getClient(): BedrockAgentCoreClient {
  if (!client) {
    const config = getConfig();
    client = new BedrockAgentCoreClient({ region: config.region });
  }
  return client;
}

export interface SessionStatus {
  usable: boolean;
  status: string;
  expired: boolean;
  minutes_left: number | null;
  remaining_usd: number | null;
  raw?: unknown;
}

/**
 * Get the current payment session status
 */
export async function getPaymentSessionStatus(): Promise<SessionStatus> {
  const config = getConfig();

  if (!config.payment_session_id) {
    return {
      usable: false,
      status: "no_session",
      expired: true,
      minutes_left: null,
      remaining_usd: null,
    };
  }

  const cmd = new GetPaymentSessionCommand({
    paymentManagerArn: config.paymentManagerArn,
    paymentSessionId: config.payment_session_id,
    userId: config.userId,
  } as any);

  try {
    const response = await getClient().send(cmd);
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

    // Compute expiry from createdAt + expiryTimeInMinutes
    let expired = false;
    let minutesLeft: number | null = null;

    if (session.createdAt && session.expiryTimeInMinutes) {
      const expiryDate = new Date(
        session.createdAt.getTime() + session.expiryTimeInMinutes * 60 * 1000
      );
      const now = new Date();
      expired = expiryDate <= now;
      if (!expired) {
        minutesLeft = Math.round((expiryDate.getTime() - now.getTime()) / 60000);
      }
    }

    // Get remaining balance from availableLimits
    let remainingUsd: number | null = null;
    if (session.availableLimits?.availableSpendAmount?.value) {
      remainingUsd = parseFloat(session.availableLimits.availableSpendAmount.value);
    }

    const usable = !expired && (remainingUsd === null || remainingUsd > 0);

    return {
      usable,
      status: expired ? "EXPIRED" : "ACTIVE",
      expired,
      minutes_left: minutesLeft,
      remaining_usd: remainingUsd,
      raw: session,
    };
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return {
      usable: false,
      status: `error: ${errMsg}`,
      expired: true,
      minutes_left: null,
      remaining_usd: null,
    };
  }
}

export interface PaymentResult {
  headerName: string;
  headerValue: string;
  signedPayload: Record<string, unknown>;
  paymentOutput: unknown;
}

/**
 * Process an x402 payment — send the challenge payload, get back the signed payment.
 *
 * @param version - x402 protocol version ("1" or "2")
 * @param challengePayload - The payment challenge object (accepts entry fields: scheme, network, amount, etc.)
 * @returns The signed payment payload (authorization + signature) and metadata
 */
export async function processPayment(
  version: string,
  challengePayload: Record<string, unknown>,
  resourceUrl: string
): Promise<PaymentResult> {
  const config = getConfig();

  if (!config.payment_session_id) {
    throw new Error("No active payment session. Create one first.");
  }

  // Derive a stable clientToken from the challenge to ensure idempotent retries.
  // Without this, the SDK auto-generates a fresh UUID per call, making retries
  // separate payments (double-spend).
  const clientToken = createHash("sha256")
    .update(JSON.stringify(challengePayload))
    .update(config.payment_session_id)
    .update(resourceUrl)
    .digest("hex")
    .slice(0, 64);

  const cmd = new ProcessPaymentCommand({
    paymentManagerArn: config.paymentManagerArn,
    paymentSessionId: config.payment_session_id,
    paymentInstrumentId: config.paymentInstrumentId,
    userId: config.userId,
    clientToken,
    paymentType: "CRYPTO_X402",
    paymentInput: {
      cryptoX402: {
        version,
        payload: challengePayload as any,
      },
    },
  });

  const response = await getClient().send(cmd);
  const paymentOutput = response.paymentOutput;

  if (!paymentOutput || !("cryptoX402" in paymentOutput) || !paymentOutput.cryptoX402) {
    throw new Error("ProcessPayment did not return cryptoX402 output");
  }

  const cryptoX402Output = paymentOutput.cryptoX402;
  const signedPayload = cryptoX402Output.payload;

  if (!signedPayload) {
    throw new Error("ProcessPayment cryptoX402 output missing payload (signed payment)");
  }

  // The payload is a DocumentType — normalize to object
  const signedPayloadObj: Record<string, unknown> =
    typeof signedPayload === "string" ? JSON.parse(signedPayload) : signedPayload;

  // Header is X-PAYMENT for both v1 and v2
  const headerName = "X-PAYMENT";

  return {
    headerName,
    headerValue: JSON.stringify(signedPayloadObj), // raw JSON; caller builds envelope
    signedPayload: signedPayloadObj,
    paymentOutput,
  };
}
