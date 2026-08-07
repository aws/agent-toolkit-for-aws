import { Type } from "typebox";
import { getConfig, loadConfig } from "./config.js";
import { getPaymentSessionStatus, processPayment } from "./payments.js";
import {
  PaymentBlocked,
  probeUrl,
  extractChallenge,
  buildProcessPaymentPayload,
  buildPaymentPayloadEnvelope,
  sleepPastValidAfter,
  replayWithHeader,
  validateChallengePolicy,
} from "./x402.js";

function json(payload: unknown) {
  return {
    content: [
      { type: "text" as const, text: JSON.stringify(payload, null, 2) },
    ],
    details: payload,
  };
}

function clearObject(value: Record<string, unknown>): void {
  for (const key of Object.keys(value)) {
    delete value[key];
  }
}

async function paidFetch(url: string): Promise<Record<string, unknown>> {
  try {
    const probe = await probeUrl(url);
    if (probe.status !== 402) {
      return {
        paid: false,
        refused: true,
        status_code: probe.status,
        reason: "URL did not return an x402 payment challenge",
      };
    }

    const parsed = extractChallenge(probe);
    const authorized = validateChallengePolicy(parsed, url, getConfig());
    const accepted = buildProcessPaymentPayload(authorized.accepted);
    const payment = await processPayment(authorized.version, accepted, url);

    let signature = "";
    try {
      await sleepPastValidAfter(payment.signedPayload);
      signature = buildPaymentPayloadEnvelope(
        authorized.resource,
        authorized.accepted,
        payment.signedPayload,
      );
      const result = await replayWithHeader(url, signature);
      if (result.status === 402) {
        return {
          paid: false,
          refused: false,
          status_code: 402,
          reason:
            "The merchant still returned 402 after the idempotent paid replay",
        };
      }

      return {
        paid: result.status >= 200 && result.status < 300,
        refused: false,
        status_code: result.status,
        content_type: result.contentType,
        body_sha256: result.bodySha256,
        body_bytes: result.bodyBytes,
        url: result.url,
        content_returned: false,
      };
    } finally {
      signature = "";
      clearObject(payment.signedPayload);
    }
  } catch (error) {
    return {
      paid: false,
      refused: true,
      reason:
        error instanceof PaymentBlocked
          ? error.message
          : "Payment flow failed safely without exposing provider or proof details",
    };
  }
}

export function definePluginEntry(api: any) {
  let configLoaded = false;
  async function ensureConfig() {
    if (!configLoaded) {
      await loadConfig(api.pluginConfig);
      configLoaded = true;
    }
  }

  api.registerTool({
    name: "get_payment_session_status",
    description:
      "Return whether the operator-provisioned payment session is usable. " +
      "The runtime cannot create or replace payment sessions.",
    parameters: Type.Object({}),
    async execute(_toolCallId: string) {
      await ensureConfig();
      return json(await getPaymentSessionStatus());
    },
  });

  api.registerTool({
    name: "get_paid_content",
    description:
      "Fetch and pay an approved x402 v2 URL, returning response metadata only. " +
      "Publisher content and signed proofs never enter model-visible output.",
    parameters: Type.Object({
      url: Type.String({ description: "HTTPS x402 v2 resource URL" }),
    }),
    async execute(_toolCallId: string, params: { url: string }) {
      await ensureConfig();
      return json(await paidFetch(params.url));
    },
  });
}

export default definePluginEntry;
