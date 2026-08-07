import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { deriveClientToken } from "../dist/payments.js";
import { parseBridgeResponse } from "../dist/bridge.js";
import { normalizeConfig } from "../dist/config.js";
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

async function relativeFiles(root) {
  const files = [];

  async function walk(directory, relativeDirectory = "") {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const relativePath = path.join(relativeDirectory, entry.name);
      const fullPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath, relativePath);
      } else {
        files.push(relativePath);
      }
    }
  }

  await walk(root);
  return files.sort();
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

test("allowAnyRecipient accepts an unlisted payee while retaining other controls", () => {
  const config = structuredClone(fixture.config);
  delete config.allowedRecipients;
  config.allowAnyRecipient = true;

  const challenge = structuredClone(fixture.challenge);
  challenge.accepts = [challenge.accepts[0]];
  const parsed = extractChallenge(probeFor(challenge));
  const authorized = validateChallengePolicy(
    parsed,
    fixture.requestUrl,
    config,
  );
  assert.equal(
    authorized.accepted.payTo,
    "0x9999999999999999999999999999999999999999",
  );

  const mutations = [
    (candidate) => {
      candidate.accepts[0].amount = "100001";
    },
    (candidate) => {
      candidate.accepts[0].asset =
        "0x2222222222222222222222222222222222222222";
    },
    (candidate) => {
      candidate.accepts[0].scheme = "upto";
    },
    (candidate) => {
      candidate.accepts[0].network = "eip155:1";
    },
    (candidate) => {
      candidate.resource.url = "https://evil.example/pay/weather";
    },
  ];
  for (const mutate of mutations) {
    const candidate = structuredClone(challenge);
    mutate(candidate);
    assert.throws(
      () =>
        validateChallengePolicy(
          extractChallenge(probeFor(candidate)),
          fixture.requestUrl,
          config,
        ),
      PaymentBlocked,
    );
  }

  const wrongOrigin = structuredClone(config);
  wrongOrigin.allowedOrigins = ["https://other.example"];
  assert.throws(
    () =>
      validateChallengePolicy(
        extractChallenge(probeFor(challenge)),
        fixture.requestUrl,
        wrongOrigin,
      ),
    PaymentBlocked,
  );
});

test("recipient configuration modes are explicit and mutually exclusive", () => {
  for (const allowAnyRecipient of [true, false]) {
    assert.throws(
      () =>
        normalizeConfig({
          ...structuredClone(fixture.config),
          allowAnyRecipient,
        }),
      /mutually exclusive/,
    );
  }

  const neither = structuredClone(fixture.config);
  delete neither.allowedRecipients;
  assert.throws(() => normalizeConfig(neither), /at least one allowed recipient/);

  const malformed = structuredClone(fixture.config);
  delete malformed.allowedRecipients;
  malformed.allowAnyRecipient = "true";
  assert.throws(() => normalizeConfig(malformed), /must be a boolean/);

  const allowAny = structuredClone(fixture.config);
  delete allowAny.allowedRecipients;
  allowAny.allowAnyRecipient = true;
  assert.equal(normalizeConfig(allowAny).allowAnyRecipient, true);
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

test("AgentCore bridge accepts only a successful object response", () => {
  assert.deepEqual(
    parseBridgeResponse('{"ok":true,"result":{"paymentSession":{"status":"ACTIVE"}}}'),
    { paymentSession: { status: "ACTIVE" } },
  );
  for (const response of [
    '{"ok":false,"error":"failed"}',
    '{"ok":true,"result":null}',
    '{"ok":true,"result":[]}',
    '{"result":{}}',
    "not-json",
  ]) {
    assert.throws(() => parseBridgeResponse(response));
  }
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

test("manifest declares all required fields for safe startup", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
  );
  const required = manifest.configSchema.required;
  // Every field the plugin refuses to start without must be declared here.
  assert.ok(required.includes("paymentManagerArn"));
  assert.ok(required.includes("paymentInstrumentId"));
  assert.ok(required.includes("userId"));
  assert.ok(required.includes("payment_session_id"));
  assert.ok(!required.includes("allowedRecipients"));
  assert.ok(required.includes("maxPaymentAmountAtomic"));
  assert.deepEqual(
    manifest.configSchema.oneOf.map((branch) => branch.required),
    [["allowedRecipients"], ["allowAnyRecipient"]],
  );
  const amount = manifest.configSchema.properties.maxPaymentAmountAtomic;
  assert.equal(amount.default, undefined);
  assert.equal(amount.pattern, "^[1-9][0-9]*$");
});

test("public package and runtime identities stay aligned", async () => {
  const [manifest, packageJson, readme] = await Promise.all([
    readFile(new URL("../openclaw.plugin.json", import.meta.url), "utf8").then(
      JSON.parse,
    ),
    readFile(new URL("../package.json", import.meta.url), "utf8").then(
      JSON.parse,
    ),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);
  assert.equal(packageJson.name, "@aws/aws-agents-pay");
  assert.equal(packageJson.version, "1.0.3");
  assert.equal(manifest.id, "aws-agents-pay");
  assert.equal(manifest.name, "AWS Agents Pay");
  assert.ok(packageJson.files.includes("skills"));
  assert.ok(packageJson.files.includes("runtime/agentcore_bridge.py"));
  assert.equal(packageJson.dependencies["@aws-sdk/client-bedrock-agentcore"], undefined);
  assert.match(readme, /clawhub:\@aws\/aws-agents-pay/);
  assert.doesNotMatch(readme, /clawhub:\@aws%2Faws-agents-pay/);
  assert.doesNotMatch(readme, /accepts an empty install-time config/);
});

test("bundled skill is exact and excludes nested packages", async () => {
  const packageRoot = fileURLToPath(new URL("../", import.meta.url));
  const canonicalRoot = path.resolve(packageRoot, "../..");
  const bundledRoot = path.join(packageRoot, "skills", "agents-pay");
  const includedEntries = [
    "SKILL.md",
    "requirements.txt",
    "references",
    "scripts",
  ];

  const expectedFiles = [];
  for (const entry of includedEntries) {
    const source = path.join(canonicalRoot, entry);
    try {
      const children = await relativeFiles(source);
      expectedFiles.push(...children.map((child) => path.join(entry, child)));
    } catch (error) {
      if (error.code !== "ENOTDIR") {
        throw error;
      }
      expectedFiles.push(entry);
    }
  }
  const expectedSourceFiles = expectedFiles
    .filter((relativePath) => {
      const parts = relativePath.split(path.sep);
      return !parts.includes("__pycache__") && !relativePath.endsWith(".pyc");
    })
    .sort();

  assert.deepEqual(await relativeFiles(bundledRoot), expectedSourceFiles);
  for (const relativePath of expectedSourceFiles) {
    assert.deepEqual(
      await readFile(path.join(bundledRoot, relativePath)),
      await readFile(path.join(canonicalRoot, relativePath)),
    );
  }
  await assert.rejects(access(path.join(bundledRoot, "packages")));
});

test("runtime dependency graph excludes Bowser", async () => {
  const packageLock = await readFile(
    new URL("../package-lock.json", import.meta.url),
    "utf8",
  ).then(JSON.parse);
  assert.equal(packageLock.packages["node_modules/bowser"], undefined);
  assert.equal(
    packageLock.packages["node_modules/@aws-sdk/client-bedrock-agentcore"],
    undefined,
  );
});
