import { Type } from "typebox";
import { getConfig, loadConfig } from "./config.js";
import {
  getPaymentSessionStatus,
  processPayment,
} from "./payments.js";
import {
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
    content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

/**
 * OpenClaw plugin entry point
 */
export function definePluginEntry(api: any) {
  let configLoaded = false;
  async function ensureConfig() {
    if (!configLoaded) {
      await loadConfig(api.pluginConfig);
      configLoaded = true;
    }
  }

  // Tool 1: get_payment_session_status
  api.registerTool({
    name: "get_payment_session_status",
    description:
      "Return current payment session status + a quick usability summary. " +
      "The summary tells the agent whether the pre-approved session is usable. " +
      "Session creation is intentionally not available to the runtime.",
    parameters: Type.Object({}),
    async execute(_toolCallId: string) {
      await ensureConfig();
      return json(await getPaymentSessionStatus());
    },
  });

  // Tool 2: get_paid_content
  api.registerTool({
    name: "get_paid_content",
    description:
      "Fetch an x402-paywalled URL, paying for it transparently. " +
      "Probes the URL, and if it returns 402, mints the payment header, " +
      "attaches it, replays the request, and returns bounded metadata only. " +
      "Paid publisher content is never returned into the payment-capable model context.",
    parameters: Type.Object({
      url: Type.String({ description: "The x402-paywalled URL to fetch and pay for" }),
    }),
    async execute(_toolCallId: string, params: { url: string }) {
      await ensureConfig();
      const config = getConfig();
      const url = params.url;

      // Step 1: Probe the URL
      const probe = await probeUrl(url);

      if (probe.status !== 402) {
        return json({
          error:
            `URL did not return 402. Got status ${probe.status}. ` +
            `This tool only handles x402-paywalled URLs.`,
          status_code: probe.status,
        });
      }

      // Step 2: Extract x402 challenge
      const challenge = extractChallenge(probe);

      // Step 3: Enforce trusted recipient, network, asset, amount, and origin policy
      validateChallengePolicy(challenge, url, config);

      // Step 4: Build the ProcessPayment payload from the accepted entry
      const processPayload = buildProcessPaymentPayload(challenge.accepted);

      // Step 5: Process payment via AgentCore
      const paymentResult = await processPayment(challenge.version, processPayload, url);

      // Step 6: Sleep past validAfter if needed
      await sleepPastValidAfter(paymentResult.signedPayload);

      // Step 7: Build the full PaymentPayload envelope and replay
      let headerValue: string;
      let headerName: string;

      if (challenge.version === "2") {
        headerValue = buildPaymentPayloadEnvelope(
          challenge.resource,
          challenge.accepted,
          paymentResult.signedPayload
        );
        headerName = "X-PAYMENT";
      } else {
        headerValue = paymentResult.headerValue;
        headerName = "X-PAYMENT";
      }

      const result = await replayWithHeader(url, headerName, headerValue);

      if (result.status === 402) {
        return json({
          error:
            "Payment was processed but the URL still returned 402. " +
            "The payment session may have drained. Check session status and retry.",
          status_code: 402,
        });
      }

      return json({
        status_code: result.status,
        content_type: result.contentType,
        body_sha256: result.bodySha256,
        body_bytes: result.bodyBytes,
        url: result.url,
        content_returned: false,
        note:
          "Paid content was fetched and withheld from the payment-capable model context. " +
          "Use a separate no-payment/no-network analysis path if content summarisation is required.",
        });
    },
  });
}

export default definePluginEntry;
