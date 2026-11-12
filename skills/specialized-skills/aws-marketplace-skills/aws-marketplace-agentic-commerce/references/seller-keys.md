# Seller quote-signing keys

The seller brings the quote-signing key already registered on the listing; this skill configures it and does not create keys. The seller signs every quote with its own key, and the facilitator verifies quotes with that same key. The key registered on the Marketplace listing, the signer and the verifier's seller key resolver **MUST** all be the same key, because a quote signed by any other key is refused as `invalid_quote`.

## Choosing

| | AWS KMS key | Your own key + JWKS URL |
|---|---|---|
| Listing key source | KMS alias ARN (and the access role the listing asks for) | JWKS URL, `https://<seller>/.well-known/jwks.json` |
| Private key | Never leaves KMS | Held by the seller (file, secrets manager, HSM export) |
| Signer | `KmsQuoteSigner` | `LocalQuoteSigner.from_pem` / `LocalQuoteSigner.fromPem` |
| Verifier resolver | KMS: `KmsSellerKeyResolver(arn, region)` / `{ type: 'kms', kmsKeyArn, region }` | JWKS: `JwksSellerKeyResolver(base_url)` / `{ type: 'jwks', jwksUrl: baseUrl }` |
| Extra route | none | `GET /.well-known/jwks.json` serving `jwks_document(...)` / `jwksDocument(...)` |

You **SHOULD** recommend KMS for sellers running on AWS, since the private key never leaves KMS and rotation needs no JWKS publishing.

A key held in another system (for example an HSM that signs remotely) can implement the `QuoteSigner` interface instead: `sign_quote(payload) -> str` and `get_service_url() -> str` in Python, `signQuote(payload): Promise<string>` and `getServiceUrl(): string` in TypeScript.

## AWS KMS key

- Use the **alias ARN** registered on the listing (`arn:aws:kms:<region>:<account>:alias/<name>`) in the signer and the resolver.
- `ECC_NIST_P384` signs with `ECDSA_SHA_384` by default. `ECC_NIST_P256` and `ECC_NIST_P521` need the signer's algorithm set to `ECDSA_SHA_256` or `ECDSA_SHA_512`.
- IAM: the seller's runtime role needs `kms:Sign`; the role running the verifier (the same process, with an in-process facilitator) needs `kms:GetPublicKey`. **`kms:Sign` and `kms:GetPublicKey` only authorize against the key's own ARN (`key/<id>`), never its alias ARN** — granting on the alias ARN is accepted by IAM without error but never matches at call time, so the signer fails silently. Resolve the key ID once (`aws kms describe-key --key-id alias/<name>`) and grant on `arn:aws:kms:<region>:<account>:key/<id>`.
- The quote's JWS `kid` is the alias name (or `key/<id>` for a key ARN) unless the signer sets `kid`.

## Your own key with a JWKS URL

- Supported keys: EC on P-256, P-384 or P-521, or plain RSA of at least 2048 bits. RSA keys restricted to RSA-PSS (`openssl genpkey -algorithm RSA-PSS`) are rejected, because quotes are signed with RS256.
- Every key needs a unique `kid`; the verifier picks the key named in the quote's header.
- Serve `jwks_document(signer.public_jwk)` / `jwksDocument(signer.publicJwk)` at `/.well-known/jwks.json` and keep that route out of the paid routes. The helper rejects private key members, so the PEM is never published.
- The PEM **MUST** be loaded from a mounted file or a secrets manager at startup, never committed or baked into an image, since anyone holding it can sign quotes for the product.

## Rotation (JWKS)

1. Publish both keys: `jwks_document(new.public_jwk, old.public_jwk)` / `jwksDocument(next.publicJwk, current.publicJwk)`.
2. Wait at least one hour, because verifiers cache the JWKS for up to an hour.
3. Switch the signer to the new key.
4. Remove the old key once its quotes have expired (the quote lifetime, 300 seconds by default).
