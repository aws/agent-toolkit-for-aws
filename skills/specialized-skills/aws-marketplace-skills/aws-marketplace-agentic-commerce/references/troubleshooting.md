# Troubleshooting

## Startup and configuration errors

| Symptom | Cause | Fix |
|---|---|---|
| `No scheme implementation registered for "exact" on network "aws:base"` | The route has an `aws:base` option but the server scheme was never registered | Call `register_exact_agentic_commerce_server` / `registerExactAgenticCommerceServer` on the resource server the middleware uses |
| `Facilitator does not support scheme "exact" on network "aws:base"` | No facilitator client advertises `aws:base` | Add the in-process Agentic Commerce facilitator to the resource server's facilitator client list (TypeScript: wrapped in `InProcessFacilitatorClient`) |
| `failed to initialize x402 server` with a connection error | The existing remote facilitator is unreachable at startup | Fix the existing facilitator URL or network access; the in-process facilitator does not need it |
| `ValidationError` for a price, or a `500` on the first `402` | The `aws:base` price has more than 8 decimal places, an exponent, or an asset other than `iso4217:` plus an upper-case three-letter code | Use `"$0.01"`, `"0.01 USD"`, a number, or `{amount: "0.01", asset: "iso4217:USD"}` |
| `SigningError` at startup or on the first `402` | The PEM cannot be loaded (wrong password, RSA-PSS key, RSA under 2048 bits), or KMS `Sign` failed | Check the key against [seller-keys.md](seller-keys.md); for KMS check `kms:Sign` on the alias's key and the region |
| `402` without an `aws:base` entry | The route's `accepts` was not extended, or a different route key matched | Append the `aws:base` option to the matching route |
| `500` with no logged exception on the first `402` | The IAM policy for `kms:Sign`/`kms:GetPublicKey` was granted on the KMS **alias ARN** instead of the key ARN; IAM accepts this silently but KMS never authorizes the call, and some frameworks swallow the resulting exception into a generic error response | Grant the policy on the key's `key/<id>` ARN, not its `alias/<name>` ARN — see [seller-keys.md](seller-keys.md) |

## Payment failure reasons

A refused payment gets another `402`; the reason is in the `error` field of the decoded `PAYMENT-REQUIRED` header and in the facilitator's verify result:

| Reason | Usual seller-side cause |
|---|---|
| `invalid_quote` | The verifier's seller key resolver points at a different key than the signer (or than the listing); a JWKS that does not contain the quote's `kid`; a rotated key published less than an hour before signing |
| `quote_expired` | The buyer paid after the quote's lifetime (300 seconds by default); a seller clock far off |
| `invalid_payment` | The payment token's audience does not match the quote's `iss` (the signer's service URL differs from the URL the buyer was quoted), the route's price or currency changed between the `402` and the retry, or the quote is for another product |
| `payment_replayed` | The seller's own after-verify hook refused a payment it already served; expected for a buyer that resends an old payment. If the first request never got its `200`, check the hook only records valid `aws:base` payments |
| `payment_expired` | The buyer retried after the payment token expired |
| `dpop_required` | The payment token is DPoP-bound and the request carries no `DPoP` header; a proxy that strips headers |
| `dpop_invalid` | The URL the framework reports differs from the public URL the buyer called (proxy without forwarded `Host` / scheme, missing `trust proxy`, a stage or base path stripped), or a replayed proof |

## Debugging steps

1. Run the 402 check in Step 7 of SKILL.md and fix any `FAIL` line, then run it again.
2. Decode the quote (`extra.quoteToken` of the `aws:base` entry) and confirm its header `kid` is a key the verifier resolves.
3. Log the URL the framework reports for a request and compare it with the public URL; they **MUST** match for DPoP.
4. Confirm the runtime role has `kms:Sign` and `kms:GetPublicKey` (KMS) or that the JWKS URL serves the current key over HTTPS (JWKS).
