# test_bedrock_pricing.py
import bedrock_pricing as bp

def test_parse_price_dimensions_extracts_per_1k_token_rates():
    # Pure parser over a Pricing API PriceList JSON fragment.
    fragment = {
        "terms": {"OnDemand": {"x": {"priceDimensions": {
            "d1": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.003"},
                   "description": "Input tokens for Claude"},
            "d2": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.015"},
                   "description": "Output tokens for Claude"},
        }}}}}
    out = bp.parse_price_dimensions(fragment)
    assert out["input_per_1k_usd"] == 0.003
    assert out["output_per_1k_usd"] == 0.015

def test_unavailable_returns_banner_not_exception():
    out = bp.unavailable("network error")
    assert out["available"] is False
    assert "network error" in out["note"]

def test_static_fallback_returns_known_model():
    out = bp._static_fallback("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert out is not None
    assert out["available"] is True
    assert out["input_per_1k_usd"] == 0.001
    assert out["output_per_1k_usd"] == 0.005

def test_static_fallback_opus_4_8_rate_is_5_and_25_per_1m():
    """Opus 4.8 is $5/$25 per 1M tokens (0.005/0.025 per 1K), NOT Opus 4.1's legacy
    $15/$75 — see skills/gcp-to-aws/references/shared/pricing-cache.md for the
    source rates. The table
    now keys by dateless family id, so the raw entries are asserted on those keys and
    ALL four id shapes (bare/us., dateless/date-pinned) must resolve behaviorally —
    a date-pinned id failing to match the family key was a live regression."""
    for key in ("anthropic.claude-opus-4-8", "us.anthropic.claude-opus-4-8"):
        entry = bp.STATIC_FALLBACK[key]
        assert entry["input_per_1k_usd"] == 0.005, key
        assert entry["output_per_1k_usd"] == 0.025, key
    # Dated forms are built by concatenation: Opus 4.8 Bedrock IDs are undated
    # (tools/model-id-lint.py), but a stale plan can still carry a fabricated
    # dated form and the lookup must repair it rather than lose the price.
    for model_id in ("anthropic.claude-opus-4-8",
                     "us.anthropic.claude-opus-4-8",
                     "anthropic.claude-opus-4-8" + "-20250610-v1:0",
                     "us.anthropic.claude-opus-4-8" + "-20250610-v1:0"):
        out = bp.lookup("us-east-1", model_id)
        assert out["available"] is True
        assert out["input_per_1k_usd"] == 0.005, model_id
        assert out["output_per_1k_usd"] == 0.025, model_id


def test_static_fallback_partial_match():
    # us.anthropic.claude-sonnet-5 (no version suffix) should match the $2/$10 rate (launch rate, made standard Sep 1, 2026)
    out = bp._static_fallback("us.anthropic.claude-sonnet-5")
    assert out is not None
    assert out["available"] is True
    assert out["input_per_1k_usd"] == 0.002
    assert out["output_per_1k_usd"] == 0.010

def test_static_fallback_keeps_sonnet_4_6():
    out = bp._static_fallback("us.anthropic.claude-sonnet-4-6")
    assert out is not None
    assert out["input_per_1k_usd"] == 0.003

def test_static_fallback_dated_id_matches_undated_key():
    # A dated ID form (even a fabricated one from a stale plan) should still
    # resolve to the undated table key after the date stamp is stripped.
    # Built by concatenation so tools/model-id-lint.py doesn't flag a literal
    # fabricated ID — this test exists precisely to handle such broken inputs.
    dated_id = "us.anthropic.claude-sonnet-4-6" + "-20250514-v1:0"
    out = bp._static_fallback(dated_id)
    assert out is not None
    assert out["input_per_1k_usd"] == 0.003


def test_static_fallback_opus_48_rate_matches_cache():
    # Guards the $5/$25 per-1M rate (pricing-cache.md § Anthropic) — this entry
    # previously carried Opus-4-class $15/$75, a 3x overstatement.
    out = bp._static_fallback("us.anthropic.claude-opus-4-8")
    assert out is not None
    assert out["input_per_1k_usd"] == 0.005
    assert out["output_per_1k_usd"] == 0.025


def test_static_fallback_unknown_returns_none():
    out = bp._static_fallback("totally.fake.model-id")
    assert out is None


def test_display_name_guess_derives_pricing_api_display_names():
    # The Pricing API's 'model' attribute holds display names, not model ids.
    assert bp.display_name_guess("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "Claude Haiku 4.5"
    assert bp.display_name_guess("amazon.nova-lite-v1:0") == "Nova Lite"
    assert bp.display_name_guess("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "Claude Haiku 4.5"
    assert bp.display_name_guess("anthropic.claude-sonnet-5") == "Claude Sonnet 5"


def test_parse_price_dimensions_ignores_cache_dimensions():
    """Cache read/write dimensions must not override base input/output rates."""
    fragment = {
        "terms": {"OnDemand": {"x": {"priceDimensions": {
            "d1": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.003"},
                   "description": "Input tokens for Claude"},
            "d2": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.015"},
                   "description": "Output tokens for Claude"},
            "d3": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.00030"},
                   "description": "Cache read input tokens for Claude"},
            "d4": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.00375"},
                   "description": "Cache write input tokens for Claude"},
        }}}}}
    out = bp.parse_price_dimensions(fragment)
    assert out["input_per_1k_usd"] == 0.003
    assert out["output_per_1k_usd"] == 0.015


def test_parse_price_dimensions_ignores_batch_dimensions():
    """Batch dimensions should be skipped."""
    fragment = {
        "terms": {"OnDemand": {"x": {"priceDimensions": {
            "d1": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.001"},
                   "description": "Input token price for batch inference"},
            "d2": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.003"},
                   "description": "Input tokens for Claude"},
            "d3": {"unit": "1K tokens", "pricePerUnit": {"USD": "0.015"},
                   "description": "Output tokens for Claude"},
        }}}}}
    out = bp.parse_price_dimensions(fragment)
    assert out["input_per_1k_usd"] == 0.003
    assert out["output_per_1k_usd"] == 0.015


def test_lookup_serves_static_table_first_without_calling_the_api(monkeypatch):
    # Models in the curated table must not depend on boto3 at all.
    import builtins
    real_import = builtins.__import__
    def deny_boto3(name, *a, **k):
        if name == "boto3":
            raise AssertionError("lookup() must not import boto3 for static-table models")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", deny_boto3)
    out = bp.lookup("us-east-1", "amazon.nova-pro-v1:0")
    assert out["available"] is True
    assert out["input_per_1k_usd"] == 0.0008


def test_mantle_gpt_detection_excludes_gpt_oss():
    assert bp.is_mantle_gpt("openai.gpt-5.6-luna") is True
    assert bp.is_mantle_gpt("openai.gpt-5.5") is True
    assert bp.is_mantle_gpt("openai.gpt-oss-120b-1:0") is False
    assert bp.is_mantle_gpt("anthropic.claude-sonnet-4-6") is False


def test_mantle_gpt_verified_rates_come_from_static_table():
    # Short-context (272K) in-region rates off the Bedrock pricing page OpenAI tab.
    # NOT OpenAI's standard list price: Bedrock in-region is at parity with OpenAI's
    # data-residency tier, exactly 1.10x standard. An earlier revision used the
    # standard figures (0.0002/0.0012) and understated every estimate by 10%.
    v = bp.lookup("us-east-1", "openai.gpt-5.6-luna")
    assert v["available"] is True
    # $0.22 / $1.32 per 1M == $0.00022 / $0.00132 per 1K
    assert v["input_per_1k_usd"] == 0.00022
    assert v["output_per_1k_usd"] == 0.00132


def test_gpt_rates_by_inference_option():
    # Pricing has an inference-option dimension (verified 2026-08-21):
    # bare mantle ids and Geo CRIS (us./in.) are 1.10x OpenAI standard (the
    # data-residency tier); Global CRIS (global., GPT-5.6 only) is exactly the
    # standard price — cost parity. A future edit that flattens either direction
    # (all-standard, as shipped once, or all-premium) fails here.
    standard = {"gpt-5.6-sol": (0.004, 0.020),  # Aug 21, 2026 cut; promo >= Nov 21, 2026
                "gpt-5.6-terra": (0.002, 0.012),
                "gpt-5.6-luna": (0.0002, 0.0012),
                "gpt-5.5": (0.005, 0.030),
                "gpt-5.4": (0.0025, 0.015)}
    for mid, entry in bp.STATIC_FALLBACK.items():
        if "openai.gpt-5" not in mid or "oss" in mid:
            continue
        base = mid.split("openai.")[1]
        si, so = standard[base]
        factor = 1.0 if mid.startswith("global.") else 1.10
        assert abs(entry["input_per_1k_usd"] / si - factor) < 1e-6, mid
        assert abs(entry["output_per_1k_usd"] / so - factor) < 1e-6, mid


def test_cris_forms_never_partial_match():
    # A CRIS-form id absent from the table must resolve to the unavailable path,
    # not prefix-match another tier or option at a different rate.
    for probe in ("us.openai.gpt-5.6", "global.openai.gpt-5.6", "in.openai.gpt-5.6-sol"):
        assert bp._static_fallback(probe) is None, probe


def test_global_cris_is_priced_at_parity():
    v = bp.lookup("us-east-1", "global.openai.gpt-5.6-luna")
    assert v["available"] is True
    assert v["input_per_1k_usd"] == 0.0002 and v["output_per_1k_usd"] == 0.0012


def test_all_five_proprietary_gpt_models_are_priced():
    # Terra and Sol were previously absent and resolved to "unavailable"; the pricing
    # page now supplies them, so an estimate must not fall back to that path.
    for mid in ("openai.gpt-5.6-sol", "openai.gpt-5.6-terra", "openai.gpt-5.6-luna",
                "openai.gpt-5.5", "openai.gpt-5.4"):
        v = bp.lookup("us-east-1", mid)
        assert v["available"] is True, mid
        assert v["input_per_1k_usd"] > 0 and v["output_per_1k_usd"] > 0, mid


def test_mantle_gpt_never_prefix_matches_a_different_tier():
    # Regression: Sol, Terra and Luna differ only by suffix at very different price
    # points, so a prefix match would bill one tier at another tier's rate.
    v = bp.lookup("us-east-1", "openai.gpt-5.6")
    assert v["available"] is False
    assert v["input_per_1k_usd"] is None


def test_unpriced_mantle_gpt_says_unavailable_not_nonexistent(monkeypatch):
    # Regression: falling through to the PriceList API returned a bare
    # "Pricing unavailable", which reads as "no such model" for a GA model.
    import boto3

    def boom(*a, **k):
        raise AssertionError("must not call the PriceList API for a mantle GPT model")

    monkeypatch.setattr(boto3, "client", boom)
    # A plausible-but-unlisted tier. Terra/Sol used to serve here; the pricing page now
    # supplies them, so this needs an id genuinely absent from the table to still test
    # the short-circuit rather than silently passing on a priced model.
    v = bp.lookup("us-east-1", "openai.gpt-5.6-nova-pro-preview")
    assert v["available"] is False
    assert "does NOT mean the model is unavailable" in v["note"]
    assert "aws.amazon.com/bedrock/pricing" in v["note"]
