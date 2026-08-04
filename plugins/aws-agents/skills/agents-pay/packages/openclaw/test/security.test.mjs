import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { deriveClientToken } from "../dist/payments.js";
import {
  PaymentBlocked,
  assertHttpsUrl,
  assertPublicAddress,
  buildPaymentPayloadEnvelope,
  extractChallenge,
  paymentSignatureHeader,
  validateChallengePolicy,
} from "../dist/x402.js";

const fixture = JSON.parse(
  await readFile(
    new URL("./fixtures/v2-security-contract.json", import.meta.url),
    "utf8",
  ),
);

function probeFor(challenge) {
  return {
    status: 402,
    headers: {
      "payment-required": Buffer.from(JSON.stringify(challenge)).toString(
        "base64",
      ),
    },
    body: "",
    contentType: "application/json",
    bodySha256: "",
    bodyBytes: 0,
  };
}

test("v2 policy skips a hostile first offer and selects the approved offer", () => {
  const parsed = extractChallenge(probeFor(fixture.challenge));
  const authorized = validateChallengePolicy(
    parsed,
    fixture.requestUrl,
    fixture.config,
  );
  assert.equal(authorized.accepted.payTo.toLowerCase(), fixture.merchant);
  assert.equal(authorized.accepted.amount, "1000");
});

test("v1 challenges fail closed", () => {
  const challenge = structuredClone(fixture.challenge);
  challenge.x402Version = 1;
  assert.throws(() => extractChallenge(probeFor(challenge)), PaymentBlocked);
});

test("recipient, amount, asset, scheme, network, origin, and resource are policy-bound", () => {
  const mutations = [
    (challenge) => {
      challenge.accepts[0].payTo = "0x2222222222222222222222222222222222222222";
    },
    (challenge) => {
      challenge.accepts[0].amount = "100001";
    },
    (challenge) => {
      challenge.accepts[0].asset = "0x2222222222222222222222222222222222222222";
    },
    (challenge) => {
      challenge.accepts[0].scheme = "upto";
    },
    (challenge) => {
      challenge.accepts[0].network = "eip155:1";
    },
    (challenge) => {
      challenge.resource.url = "https://evil.example/pay/weather";
    },
  ];
  for (const mutate of mutations) {
    const challenge = structuredClone(fixture.challenge);
    challenge.accepts = [challenge.accepts[1]];
    mutate(challenge);
    const parsed = extractChallenge(probeFor(challenge));
    assert.throws(
      () => validateChallengePolicy(parsed, fixture.requestUrl, fixture.config),
      PaymentBlocked,
    );
  }

  const config = structuredClone(fixture.config);
  config.allowedOrigins = ["https://other.example"];
  const parsed = extractChallenge(probeFor(fixture.challenge));
  assert.throws(
    () => validateChallengePolicy(parsed, fixture.requestUrl, config),
    PaymentBlocked,
  );
});

test("amounts must be canonical positive integer atomic units", () => {
  for (const amount of ["0", "-1", "1.0", "1e3", " 1000 "]) {
    const challenge = structuredClone(fixture.challenge);
    challenge.accepts = [challenge.accepts[1]];
    challenge.accepts[0].amount = amount;
    const parsed = extractChallenge(probeFor(challenge));
    assert.throws(
      () => validateChallengePolicy(parsed, fixture.requestUrl, fixture.config),
      PaymentBlocked,
    );
  }
});

test("SSRF guard refuses non-HTTPS and non-public destinations", () => {
  assert.throws(
    () => assertHttpsUrl("http://merchant.example/pay"),
    PaymentBlocked,
  );
  for (const address of [
    "127.0.0.1",
    "10.0.0.1",
    "100.64.0.1",
    "169.254.169.254",
    "192.168.1.1",
    "::1",
    "fc00::1",
    "fe80::1",
    "::ffff:127.0.0.1",
  ]) {
    assert.throws(() => assertPublicAddress(address), PaymentBlocked);
  }
  assert.doesNotThrow(() => assertPublicAddress("8.8.8.8"));
  assert.doesNotThrow(() => assertPublicAddress("2606:4700:4700::1111"));
});

test("stable idempotency excludes rotating publisher nonce", () => {
  const accepted1 = structuredClone(fixture.challenge.accepts[1]);
  const accepted2 = structuredClone(accepted1);
  accepted2.extra.nonce = "publisher-nonce-2";
  const token1 = deriveClientToken(
    "session-example",
    fixture.requestUrl,
    accepted1,
  );
  const token2 = deriveClientToken(
    "session-example",
    fixture.requestUrl,
    accepted2,
  );
  assert.equal(token1, token2);
  assert.notEqual(
    token1,
    deriveClientToken("session-example", fixture.requestUrl, {
      ...accepted1,
      amount: "1001",
    }),
  );
  assert.notEqual(
    token1,
    deriveClientToken("another-session", fixture.requestUrl, accepted1),
  );
});

test("v2 replay uses PAYMENT-SIGNATURE and a complete base64 envelope", () => {
  const signedPayload = {
    authorization: { validAfter: "0", nonce: "proof-nonce" },
    signature: "0xsigned-proof",
  };
  const value = buildPaymentPayloadEnvelope(
    fixture.challenge.resource,
    fixture.challenge.accepts[1],
    signedPayload,
  );
  assert.deepEqual(paymentSignatureHeader(value), {
    "PAYMENT-SIGNATURE": value,
  });
  const envelope = JSON.parse(Buffer.from(value, "base64").toString("utf8"));
  assert.equal(envelope.x402Version, 2);
  assert.deepEqual(envelope.payload, signedPayload);
});

test("model-facing tool inventory excludes setup, session creation, and proof tools", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
  );
  assert.deepEqual(manifest.contracts.tools, [
    "get_payment_session_status",
    "get_paid_content",
  ]);
  const forbidden = [
    "create_payment_session",
    "setup_x402_payments",
    "pay_and_get_header",
  ];
  for (const name of forbidden) {
    assert.ok(!manifest.contracts.tools.includes(name));
  }
});

test("manifest permits installation before trusted runtime config is supplied", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
  );
  assert.deepEqual(manifest.configSchema.required, []);
});
