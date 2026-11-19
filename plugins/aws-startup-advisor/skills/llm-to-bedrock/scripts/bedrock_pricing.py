# bedrock_pricing.py
"""Look up Amazon Bedrock on-demand token prices.

Primary sources are the shared token-rate table (skills/shared/ai/bedrock-pricing.json,
vendored at references/vendored/ai/bedrock-pricing.json and exposed here as STATIC_FALLBACK)
and the region/profile-aware Opus 5.5 rates (checked against AWS pricing). The live AWS Pricing API is a secondary source
for models not in the table — note its 'model' attribute holds display names
("Claude 3 Haiku"), NOT model IDs, so we query with a display name derived
from the model id; this is best-effort and may miss.

Usage: python bedrock_pricing.py --region <r> --models <id,id,...>
Prints JSON {model_id: {input_per_1k_usd, output_per_1k_usd, available, note}}.
Never raises on lookup failure — emits an 'available: false' banner instead.
"""
import argparse, json, re, sys
from pathlib import Path


def _load_model_catalog():
    """Import the sibling model_catalog.py, also when this file is loaded by path from
    another skill's tests (its directory is then not on sys.path)."""
    import importlib.util
    import sys as _sys
    from pathlib import Path as _Path
    if "model_catalog" in _sys.modules:
        return _sys.modules["model_catalog"]
    path = _Path(__file__).resolve().with_name("model_catalog.py")
    spec = importlib.util.spec_from_file_location("model_catalog", path)
    module = importlib.util.module_from_spec(spec)
    _sys.modules["model_catalog"] = module
    spec.loader.exec_module(module)
    return module


model_catalog = _load_model_catalog()


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


# Token rates come from the shared pricing table, skills/shared/ai/bedrock-pricing.json,
# vendored into this skill at references/vendored/ai/bedrock-pricing.json. Edit the shared
# file and run tools/sync-vendored.py; never add rates here. The JSON is per 1M tokens, per
# model and inference-profile prefix. STATIC_FALLBACK is the per-1K view this module has
# always exposed, keyed by the exact invocable id (`<prefix>.<bare id>`, or the bare id for
# the Global/base rate). A Geo prefix carries its own verified rate (about 10% above
# Global); a prefix the JSON does not price is unverified, and lookup() returns unavailable
# for it instead of borrowing another prefix's or another model's rate.
PRICING_PATH = (Path(__file__).resolve().parent.parent
                / "references" / "vendored" / "ai" / "bedrock-pricing.json")
_PROFILE_PREFIXES = model_catalog.profile_prefixes()


def _per_1k(rate_per_1m: float) -> float:
    return round(rate_per_1m / 1000, 12)


def _load_pricing(path=PRICING_PATH):
    """Read the shared pricing JSON. Returns (static_table, region_table, model_of, models):
    static_table maps an invocable id to its per-1K entry; region_table maps
    (region, invocable id) to a Region-specific entry; model_of maps an invocable id back to
    its bare model id; models is the JSON `models` object."""
    doc = json.loads(Path(path).read_text())
    table, regional, model_of = {}, {}, {}

    def entry(rate, lc_rate=None, threshold=None):
        out = {"input_per_1k_usd": _per_1k(rate["input"]),
               "output_per_1k_usd": _per_1k(rate["output"])}
        if lc_rate is not None:
            out["long_context_input_per_1k_usd"] = _per_1k(lc_rate["input"])
            out["long_context_output_per_1k_usd"] = _per_1k(lc_rate["output"])
            out["long_context_threshold_tokens"] = threshold
        return out

    # `cache_read` rates in the JSON are reference data for the estimate docs; this module
    # prices input and output tokens only, as it always has.
    for bare, model in doc["models"].items():
        lc = model.get("long_context")
        for prefix, rate in model["rates"].items():
            mid = bare if prefix == "bare" else f"{prefix}.{bare}"
            lc_rate = lc["rates"].get(prefix) if lc else None
            table[mid] = entry(rate, lc_rate, lc["threshold_tokens"] if lc_rate else None)
            model_of[mid] = bare
        for region, rates in model.get("region_rates", {}).items():
            for prefix, rate in rates.items():
                mid = bare if prefix == "bare" else f"{prefix}.{bare}"
                regional[(region, mid)] = entry(rate)
    return table, regional, model_of, doc["models"]


STATIC_FALLBACK, REGION_RATES, _MODEL_OF, PRICED_MODELS = _load_pricing()


def is_mantle_gpt(model_id: str) -> bool:
    """Pure: BARE ids of OpenAI's proprietary GPT models (GPT-5.5/5.4/5.6 and GPT-6
    Astra/Sol/Luna/6.1 Sol) — the bedrock-mantle id form — which the AWS PriceList
    API does not carry. The `us.`/`in.`/`global.` CRIS forms (bedrock-runtime; GPT-5.5
    and 5.4 have `us.`/`global.` ids too) do not match here; callers pair this with
    an explicit prefixed-id regex. The open-weight gpt-oss models ARE in the
    PriceList API and must not match."""
    mid = model_id.lower()
    return (mid.startswith("openai.gpt-5") or mid.startswith("openai.gpt-6")) and "oss" not in mid


def unavailable(note: str) -> dict:
    return {"available": False, "input_per_1k_usd": None,
            "output_per_1k_usd": None, "note": f"Pricing unavailable: {note}"}


# AWS Price List API, AmazonBedrockFoundationModels, verified 2026-09-24.
# servicename: Claude Opus 5.5 (Amazon Bedrock Edition). Prices are per 1K.
# Runtime uses Geo/Global profiles, or the bare ID in eu-west-2 (verified 2026-10-03).
_OPUS55_ID = model_catalog.OPUS_55_ID
# Opus 5.5's inference-profile, Mantle and runtime in-region Regions come from the shared model
# catalog (references/vendored/ai/models/); only its rates are restated in _opus55_pricing.
_OPUS55_PROFILE_REGIONS = model_catalog.opus_55_profile_regions()
_OPUS55_MANTLE_REGIONS = model_catalog.opus_55_mantle_regions()
_OPUS55_RUNTIME_IN_REGION_REGIONS = model_catalog.opus_55_runtime_in_region_regions()


def _opus55_pricing(region: str, model_id: str) -> dict:
    if model_id == _OPUS55_ID:
        valid = region in _OPUS55_MANTLE_REGIONS | _OPUS55_RUNTIME_IN_REGION_REGIONS
        prefix = "runtime-in-region" if region in _OPUS55_RUNTIME_IN_REGION_REGIONS else "mantle"
    else:
        prefix, _, base = model_id.partition(".")
        valid = base == _OPUS55_ID and region in _OPUS55_PROFILE_REGIONS.get(prefix, [])
    if not valid:
        return unavailable(f"no verified Opus 5.5 rate for {model_id} in {region}; "
                           "confirm the exact model ID, endpoint and inference profile")
    if region.startswith("us-gov-"):
        inp, output = 0.0048, 0.024
    elif prefix == "global":
        inp, output = 0.004, 0.020
    else:
        inp, output = 0.0044, 0.022
    verified = "2026-10-03" if prefix == "runtime-in-region" else "2026-09-24"
    return {"available": True, "input_per_1k_usd": inp, "output_per_1k_usd": output,
            "note": f"AWS Price List API AmazonBedrockFoundationModels; verified {verified}; "
                    f"Standard tier, {region}, {prefix} inference; no Batch"}


# A snapshot suffix is the part of a model id that does not change the priced model: a
# date stamp and/or an API version suffix (`-20251001`, `-v1:0`). A further VERSION
# component is not one: `anthropic.claude-sonnet-5-5` and `anthropic.claude-sonnet-5` are
# different models with independently published rates.
_SNAPSHOT_SUFFIX = re.compile(r"(-\d{8})?(-v\d+(:\d+)?)?")

# The literal the Estimate phases already consume for an unresolved context tier
# (gcp-to-aws and azure-to-aws references/phases/estimate/estimate-ai.md).
_APPROXIMATE_TIER = "approximate — request-size distribution unknown"


def _is_snapshot_of(model_id: str, key: str) -> bool:
    """Pure: True when `model_id` is `key` plus only a snapshot suffix."""
    if not model_id.startswith(key):
        return False
    rest = model_id[len(key):]
    return bool(rest) and _SNAPSHOT_SUFFIX.fullmatch(rest) is not None


def _priced(entry: dict, note: str) -> dict:
    """An available result. An entry with a long-context tier also carries
    `pricing_tier`, so a caller cannot quote the lower tier as the only rate when the
    per-request prompt size is unknown (bedrock-pricing-cache.md requires both rows)."""
    out = {**entry, "available": True, "note": note}
    if "long_context_threshold_tokens" in entry:
        out["pricing_tier"] = _APPROXIMATE_TIER
    return out


def _match_key(model_id: str) -> str | None:
    """The STATIC_FALLBACK key that prices `model_id`, or None."""
    if "claude-opus-5" in model_id:
        return None  # Opus 5.5 requires exact, region-aware pricing.
    if model_id in STATIC_FALLBACK:
        return model_id
    # Proprietary GPT ids require an EXACT match, in every form (bare mantle id or
    # us./in./global. CRIS profile). Tier names differ only by suffix at very
    # different price points, and the inference options differ by prefix at a 10%
    # spread; a partial match on e.g. `openai.gpt-5.6` or `us.openai.gpt-5.6`
    # would silently bill one tier or option at another's rate.
    if is_mantle_gpt(model_id) or re.match(r"^(us|in|global)\.openai\.gpt-[56]", model_id):
        return None
    # Strip the version suffix for a partial match (e.g. us.anthropic.claude-sonnet-5).
    base = model_id.rsplit("-v", 1)[0] if "-v" in model_id else model_id
    for key in STATIC_FALLBACK:
        # Bidirectional: a dateless query matches a dated table key (key startswith
        # base), and a date-pinned query matches its dateless family key only when the
        # remainder is a snapshot suffix, so `...sonnet-5-5` never matches `...sonnet-5`.
        if key.startswith(base) or base == key or _is_snapshot_of(base, key):
            return key
    # Also strip a trailing date stamp (e.g. ...-sonnet-4-6-20250514 -> ...-sonnet-4-6) so a
    # dated ID form still matches the undated table keys.
    dateless = re.sub(r"-\d{8}$", "", base)
    if dateless != base:
        for key in STATIC_FALLBACK:
            if key.startswith(dateless):
                return key
    return None


def _static_fallback(model_id: str) -> dict | None:
    """Try the static table. Returns a result dict or None."""
    key = _match_key(model_id)
    if key is None:
        return None
    note = ("static fallback (PriceList API had no entry)" if key == model_id
            else f"static fallback (matched {key})")
    return _priced(STATIC_FALLBACK[key], note)


def _unverified_profile(model_id: str) -> str | None:
    """The bare model id when `model_id` is an inference-profile form of a priced model whose
    prefix has no verified rate (for example `eu.anthropic.claude-sonnet-5-5`), else None.
    Only models that publish at least one prefixed rate count: a model priced by its bare id
    alone (the Nova models) keeps its profile forms on the live PriceList lookup."""
    prefix, _, rest = model_id.partition(".")
    if prefix not in _PROFILE_PREFIXES or not rest:
        return None
    key = _match_key(rest)
    bare = _MODEL_OF.get(key) if key else None
    if bare is None or set(PRICED_MODELS[bare]["rates"]) == {"bare"}:
        return None
    return bare


def display_name_guess(model_id: str) -> str:
    """Pure: derive a Pricing-API display-name guess from a Bedrock model id.
    'us.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'Claude Haiku 4.5'.
    The Pricing API's 'model' attribute holds display names, not model ids."""
    base = model_id.split(":", 1)[0]
    base = model_catalog.profile_prefix_regex().sub("", base)
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
    profile_arn = re.fullmatch(
        r"arn:aws:bedrock:[^:]+:[0-9]{12}:inference-profile/([^/]+)", model_id
    )
    if profile_arn:
        model_id = profile_arn.group(1)
    if "claude-opus-5" in model_id:
        return _opus55_pricing(region, model_id)
    # Curated static table is the primary source: the Pricing API keys models
    # by display name and frequently lacks entries for new inference profiles.
    fb = _static_fallback(model_id)
    if fb:
        key = _match_key(model_id)
        model = PRICED_MODELS[_MODEL_OF[key]]
        fb["note"] = (f"static pricing table (bedrock-pricing.json; {model['source']}, "
                      f"verified {model['verified_at']})")
        regional = REGION_RATES.get((region, key))
        if regional:
            # A Region-specific rate replaces the commercial one. Its long-context tier is
            # unpublished, so drop the commercial long-context rates rather than quote them
            # for this Region; `pricing_tier` stays, because the tier still exists.
            for field in ("long_context_input_per_1k_usd", "long_context_output_per_1k_usd",
                          "long_context_threshold_tokens"):
                fb.pop(field, None)
            fb.update(regional)
            fb["note"] += f"; {region} rate"
            if "long_context" in model:
                fb["pricing_tier"] = _APPROXIMATE_TIER
                fb["note"] += "; no published long-context rate for this Region"
        elif region.startswith("us-gov-"):
            fb["note"] += (f"; commercial rate: bedrock-pricing.json has no {region} rate for "
                           f"this model, so verify the GovCloud price before quoting it")
        if model_id.endswith("openai.gpt-6-astra"):
            fb["note"] += ("; Standard tier, <=272K input tokens. For >272K, "
                           "use 2x input / 1.5x output rates.")
        if model_id.endswith("openai.gpt-6.1-terra"):
            fb["note"] = (
                "static pricing table; GPT-6.1 Terra AWS model card verified 2026-11-03; "
                "Standard tier, <=272K input tokens. For >272K, reprice the full request "
                "at 2x input / 1.5x output rates. Maximum context window: 1,050,000 tokens. "
                "Source-provider prices require separate verification."
            )
        return fb
    if is_mantle_gpt(model_id) or re.match(r"^[^.]+\.openai\.gpt-[56]", model_id):
        # Short-circuit: the PriceList API carries no rows for the proprietary GPT
        # models, so a live lookup would burn a round trip and still return nothing —
        # and a generic "unavailable" would read as "this model doesn't exist".
        return unavailable(
            f"the AWS PriceList API does not carry OpenAI's proprietary GPT models, and "
            f"{model_id} is not in the static table. This does NOT mean the model is "
            f"unavailable. Read the rate from the OpenAI tab of "
            f"aws.amazon.com/bedrock/pricing and add it to skills/shared/ai/bedrock-pricing.json. Do not derive "
            f"it from a percentage change to an older rate.")
    bare = _unverified_profile(model_id)
    if bare:
        forms = ", ".join(sorted(k for k, v in _MODEL_OF.items() if v == bare))
        return unavailable(
            f"no verified rate for {model_id}. bedrock-pricing.json prices {bare} only as: "
            f"{forms}. Do not substitute another inference profile's rate; verify this "
            f"profile on aws.amazon.com/bedrock/pricing and add it to the shared table.")
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
