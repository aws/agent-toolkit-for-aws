# bedrock_pricing.py
"""Look up Amazon Bedrock on-demand token prices.

Primary source is the curated STATIC_FALLBACK table below (checked against the
public pricing page). The live AWS Pricing API is tried as a secondary source
for models not in the table — note its 'model' attribute holds display names
("Claude 3 Haiku"), NOT model IDs, so we query with a display name derived
from the model id; this is best-effort and may miss.

Usage: python bedrock_pricing.py --region <r> --models <id,id,...>
Prints JSON {model_id: {input_per_1k_usd, output_per_1k_usd, available, note}}.
Never raises on lookup failure — emits an 'available: false' banner instead.
"""
import argparse, json, re, sys


def parse_price_dimensions(price_item: dict) -> dict:
    """Pure: pull input/output per-1K-token USD rates from one PriceList item.
    Only matches base input/output token dimensions — excludes cache read/write
    and other extended dimensions that share the 'input'/'output' substring."""
    inp = out = None
    terms = price_item.get("terms", {}).get("OnDemand", {})
    for term in terms.values():
        for dim in term.get("priceDimensions", {}).values():
            usd = float(dim.get("pricePerUnit", {}).get("USD", "0") or 0)
            desc = dim.get("description", "").lower()
            if any(skip in desc for skip in ("cache", "read", "write", "batch")):
                continue
            if "input" in desc and "token" in desc:
                inp = usd
            elif "output" in desc and "token" in desc:
                out = usd
    return {"input_per_1k_usd": inp, "output_per_1k_usd": out}


# Static fallback table: per-1K-token USD rates from public pricing pages.
# Used when the PriceList API doesn't return data (e.g. new cross-region inference profile IDs).
# Source: https://aws.amazon.com/bedrock/pricing/, cross-checked row-by-row against
# skills/gcp-to-aws/references/shared/pricing-cache.md (its per-1M rates / 1000).
# Every row below was re-verified against that cache on 2026-08-04; the Opus 4.8 row
# had been copied from Opus 4.1's legacy $15/$75 and was corrected to $5/$25.
# Re-check this table against that cache (and the public pricing page) whenever either moves.
STATIC_FALLBACK = {
    "anthropic.claude-haiku-4-5-20251001-v1:0":     {"input_per_1k_usd": 0.001, "output_per_1k_usd": 0.005},
    "us.anthropic.claude-haiku-4-5-20251001-v1:0":  {"input_per_1k_usd": 0.001, "output_per_1k_usd": 0.005},
    # Recommend default
    "anthropic.claude-sonnet-5":                    {"input_per_1k_usd": 0.002, "output_per_1k_usd": 0.010},
    "us.anthropic.claude-sonnet-5":                 {"input_per_1k_usd": 0.002, "output_per_1k_usd": 0.010},
    # Still Active — existing workloads / fallbacks
    "anthropic.claude-sonnet-4-6":                  {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},
    "us.anthropic.claude-sonnet-4-6":               {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},

    # Opus 4.8 has no dated foundation-model ID on the model card — suffix-less only.
    "anthropic.claude-opus-4-8":                    {"input_per_1k_usd": 0.005, "output_per_1k_usd": 0.025},
    "us.anthropic.claude-opus-4-8":                 {"input_per_1k_usd": 0.005, "output_per_1k_usd": 0.025},
    "amazon.nova-micro-v1:0":                       {"input_per_1k_usd": 0.000035, "output_per_1k_usd": 0.00014},
    "amazon.nova-lite-v1:0":                        {"input_per_1k_usd": 0.00006, "output_per_1k_usd": 0.00024},
    "amazon.nova-pro-v1:0":                         {"input_per_1k_usd": 0.0008, "output_per_1k_usd": 0.0032},
    # OpenAI proprietary GPT models, SHORT-CONTEXT (272K) tier. Read off the model
    # cards 2026-08-21. The PriceList API carries no GPT-5.x rows, so this table is
    # the ONLY source. Pricing has an inference-option dimension:
    #   - bare mantle ids and Geo CRIS (us./in. prefixed): 1.10x OpenAI's standard
    #     list price (parity with OpenAI's *data residency* tier)
    #   - Global CRIS (global. prefixed, GPT-5.6 only): OpenAI's standard list
    #     price — cost PARITY, for workloads with no residency constraint
    # The GPT-5.6 family also has a LONG-CONTEXT (1M) tier at 2.0x input / 1.5x
    # output per option, NOT represented here — a >272K workload priced from this
    # table is understated. GPT-5.5 and GPT-5.4: mantle-only, no CRIS, no 1M tier.
    "openai.gpt-5.6-sol":                           {"input_per_1k_usd": 0.0044, "output_per_1k_usd": 0.022},
    "openai.gpt-5.6-terra":                         {"input_per_1k_usd": 0.0022, "output_per_1k_usd": 0.0132},
    "openai.gpt-5.6-luna":                          {"input_per_1k_usd": 0.00022, "output_per_1k_usd": 0.00132},
    "openai.gpt-5.5":                               {"input_per_1k_usd": 0.0055, "output_per_1k_usd": 0.033},
    "openai.gpt-5.4":                               {"input_per_1k_usd": 0.00275, "output_per_1k_usd": 0.0165},
    # GPT-5.6 CRIS profile ids (bedrock-runtime). Geo = data-residency tier
    # (same as in-region); Global = standard-price parity.
    "us.openai.gpt-5.6-sol":                        {"input_per_1k_usd": 0.0044, "output_per_1k_usd": 0.022},
    "us.openai.gpt-5.6-terra":                      {"input_per_1k_usd": 0.0022, "output_per_1k_usd": 0.0132},
    "us.openai.gpt-5.6-luna":                       {"input_per_1k_usd": 0.00022, "output_per_1k_usd": 0.00132},
    "in.openai.gpt-5.6-terra":                      {"input_per_1k_usd": 0.0022, "output_per_1k_usd": 0.0132},
    "in.openai.gpt-5.6-luna":                       {"input_per_1k_usd": 0.00022, "output_per_1k_usd": 0.00132},
    "global.openai.gpt-5.6-sol":                    {"input_per_1k_usd": 0.004, "output_per_1k_usd": 0.020},
    "global.openai.gpt-5.6-terra":                  {"input_per_1k_usd": 0.002, "output_per_1k_usd": 0.012},
    "global.openai.gpt-5.6-luna":                   {"input_per_1k_usd": 0.0002, "output_per_1k_usd": 0.0012},
}


def is_mantle_gpt(model_id: str) -> bool:
    """Pure: OpenAI's proprietary GPT models, which the AWS PriceList API does not
    carry. The open-weight gpt-oss models ARE in the PriceList API and must not match."""
    mid = model_id.lower()
    return mid.startswith("openai.gpt-5") and "oss" not in mid


def unavailable(note: str) -> dict:
    return {"available": False, "input_per_1k_usd": None,
            "output_per_1k_usd": None, "note": f"Pricing unavailable: {note}"}


def _static_fallback(model_id: str) -> dict | None:
    """Try the static fallback table. Returns a result dict or None."""
    entry = STATIC_FALLBACK.get(model_id)
    if entry:
        return {**entry, "available": True, "note": "static fallback (PriceList API had no entry)"}
    # Proprietary GPT ids require an EXACT match, in every form (bare mantle id or
    # us./in./global. CRIS profile). Tier names differ only by suffix at very
    # different price points, and the inference options differ by prefix at a 10%
    # spread — a partial match on e.g. `openai.gpt-5.6` or `us.openai.gpt-5.6`
    # would silently bill one tier or option at another's rate.
    if is_mantle_gpt(model_id) or re.match(r"^(us|in|global)\.openai\.gpt-5", model_id):
        return None
    # Try stripping the version suffix for a partial match (e.g. us.anthropic.claude-sonnet-5)
    base = model_id.rsplit("-v", 1)[0] if "-v" in model_id else model_id
    for key, val in STATIC_FALLBACK.items():
        # Bidirectional: a dateless query must match a dated table key
        # (key startswith base) AND a date-pinned query must match a dateless
        # family key (base startswith key + "-"; the separator guard keeps
        # ...opus-4-85 from matching the ...opus-4-8 family).
        if key.startswith(base) or base == key or base.startswith(key + "-"):
            return {**val, "available": True, "note": f"static fallback (matched {key})"}
    # Also strip a trailing date stamp (e.g. ...-sonnet-4-6-20250514 -> ...-sonnet-4-6) so a
    # dated ID form still matches the undated table keys.
    dateless = re.sub(r"-\d{8}$", "", base)
    if dateless != base:
        for key, val in STATIC_FALLBACK.items():
            if key.startswith(dateless):
                return {**val, "available": True, "note": f"static fallback (matched {key})"}
    return None


def display_name_guess(model_id: str) -> str:
    """Pure: derive a Pricing-API display-name guess from a Bedrock model id.
    'us.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'Claude Haiku 4.5'.
    The Pricing API's 'model' attribute holds display names, not model ids."""
    base = model_id.split(":", 1)[0]
    base = re.sub(r"^(us|eu|apac|global)\.", "", base)
    base = base.split(".", 1)[-1]                      # drop vendor prefix
    base = re.sub(r"-v\d+$", "", base)                 # drop -v1
    base = re.sub(r"-\d{8}$", "", base)                # drop date stamp
    words = []
    for tok in base.split("-"):
        if tok.isdigit():
            # version digits join with '.' (4-5 -> 4.5)
            if words and re.match(r"^\d[\d.]*$", words[-1]):
                words[-1] = f"{words[-1]}.{tok}"
            else:
                words.append(tok)
        else:
            words.append(tok.capitalize())
    return " ".join(words)


def lookup(region: str, model_id: str) -> dict:
    # Curated static table is the primary source — the Pricing API keys models
    # by display name and frequently lacks entries for new inference profiles.
    fb = _static_fallback(model_id)
    if fb:
        fb["note"] = ("static pricing table (verified 2026-08-04 against "
                      "aws.amazon.com/bedrock/pricing and the vendored pricing cache)")
        return fb
    if is_mantle_gpt(model_id):
        # Short-circuit: the PriceList API carries no rows for the proprietary GPT
        # models, so a live lookup would burn a round trip and still return nothing —
        # and a generic "unavailable" would read as "this model doesn't exist".
        return unavailable(
            f"the AWS PriceList API does not carry OpenAI's proprietary GPT models, and "
            f"{model_id} is not in the static table. This does NOT mean the model is "
            f"unavailable. Read the rate from the OpenAI tab of "
            f"aws.amazon.com/bedrock/pricing and add it to STATIC_FALLBACK. Do not derive "
            f"it from a percentage change to an older rate.")
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        # Best-effort live lookup for models not in the static table.
        # Pricing API is only served from us-east-1 / ap-south-1.
        client = boto3.client("pricing", region_name="us-east-1")
        resp = client.get_products(
            ServiceCode="AmazonBedrock",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "model", "Value": display_name_guess(model_id)},
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            ],
            MaxResults=1,
        )
        items = resp.get("PriceList", [])
        if not items:
            return unavailable(
                f"not in static table and no PriceList entry for display name "
                f"'{display_name_guess(model_id)}' in {region}")
        parsed = parse_price_dimensions(json.loads(items[0]))
        parsed["available"] = parsed["input_per_1k_usd"] is not None
        parsed["note"] = (f"live Pricing API (matched display name '{display_name_guess(model_id)}')"
                          if parsed["available"] else "rates not found in price item")
        return parsed
    except (BotoCoreError, ClientError, ValueError, TypeError, AttributeError) as e:
        return unavailable(str(e))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--models", required=True)
    args = ap.parse_args(argv)
    out = {m.strip(): lookup(args.region, m.strip())
           for m in args.models.split(",") if m.strip()}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
