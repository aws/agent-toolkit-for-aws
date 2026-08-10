import { Type } from "typebox";
import { getConfig, loadConfig, type X402Config } from "./config.js";
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

export const MAX_RETURNED_BODY_BYTES = 10240;

/**
 * Build the model-visible `get_paid_content` result from a successfully paid
 * replay. Pure and side-effect-free so the security contract around body
 * withholding can be tested directly, without mocking the network.
 *
 * Default/absent `config.returnBody` preserves the original behavior exactly:
 * metadata + hash only, never the paid body. Opt-in (`returnBody: true`)
 * additionally returns the body (capped, marked untrusted) — see
 * references/security-model.md ("Publisher content isolation"): unsanitized
 * paid content may carry prompt injection.
 */
export function buildPaidContentResult(
  result: {
    status: number;
    contentType: string;
    bodySha256: string;
    bodyBytes: number;
    url: string;
    body: string;
  },
  config: Pick<X402Config, "returnBody">,
): Record<string, unknown> {
  const response: Record<string, unknown> = {
    paid: result.status >= 200 && result.status < 300,
    refused: false,
    status_code: result.status,
    content_type: result.contentType,
    body_sha256: result.bodySha256,
    body_bytes: result.bodyBytes,
    url: result.url,
    content_returned: false,
  };

  if (config.returnBody === true) {
    const truncated = result.body.length > MAX_RETURNED_BODY_BYTES;
    response.content_returned = true;
    response.body = result.body.slice(0, MAX_RETURNED_BODY_BYTES);
    response.truncated = truncated;
    response.untrusted = true;
  }

  return response;
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

    const config = getConfig();
    const parsed = extractChallenge(probe);
    const authorized = validateChallengePolicy(parsed, url, config);
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

      return buildPaidContentResult(result, config);
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
