"""Contract: usage-API discovery keeps peaks, cache/tier splits, and OpenRouter latency.

The discover sub-files are the implementation. These checks pin the fields an
agent must write into the usage profiles, in both the gcp-to-aws and
azure-to-aws copies, and the estimate / llm-to-bedrock consumers that read them.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _pair(skill: str, name: str) -> list[Path]:
    return [
        PLUGIN_ROOT / "skills" / provider / "references" / "phases" / skill / name
        for provider in ("gcp-to-aws", "azure-to-aws")
    ]


OPENAI = _pair("discover", "discover-openai-api.md")
ANTHROPIC = _pair("discover", "discover-anthropic-api.md")
OPENROUTER = _pair("discover", "discover-openrouter-api.md")
ESTIMATE = _pair("estimate", "estimate-ai.md")
SKILL = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "SKILL.md"


def test_openai_profiles_keep_cache_tier_and_peak() -> None:
    for path in OPENAI:
        text = path.read_text(encoding="utf-8")
        for needle in (
            "group_by=model&group_by=batch&group_by=service_tier",
            "bucket_width=1h",
            "limit=168",
            "bucket_width=1m",
            "limit=1440",
            "input_cached_tokens",
            "input_cache_write_tokens",
            "peak_input_tokens_per_minute",
            "already includes cached and cache-write tokens",
        ):
            assert needle in text, f"{path.name} missing {needle}"


def test_anthropic_profiles_keep_tier_context_cache_split_and_peak() -> None:
    for path in ANTHROPIC:
        text = path.read_text(encoding="utf-8")
        for needle in (
            "group_by[]=model&group_by[]=service_tier&group_by[]=context_window&group_by[]=inference_geo",
            "cache_creation_5m_tokens",
            "cache_creation_1h_tokens",
            "web_search_requests",
            "Do not collapse rows",
            "peak_input_tokens_per_minute",
            "bucket_width=1h",
            "limit=168",
        ):
            assert needle in text, f"{path.name} missing {needle}"
        assert "group_by[]=model&group_by[]=service_tier" in text


def test_openrouter_analytics_adds_volume_latency_and_hourly_peak() -> None:
    for path in OPENROUTER:
        text = path.read_text(encoding="utf-8")
        for needle in (
            "tokens_prompt",
            "cached_tokens",
            "byok_fees",
            "byok_request_count",
            "p95_latency",
            "p95_throughput",
            "usage_web",
            "guardrail_invoked_count",
            '"granularity": "hour"',
            "metadata.truncated",
            "byok_usage",
            "openrouter_usage",
            "plus one read-only POST",
            "Do not split a mixed model's tokens",
        ):
            assert needle in text, f"{path.name} missing {needle}"


def test_estimate_uses_peaks_without_double_counting_cache() -> None:
    for path in ESTIMATE:
        text = path.read_text(encoding="utf-8")
        assert "peak_input_tokens_per_minute" in text
        assert "already inside `input_tokens`" in text
        assert "not a latency SLO" in text


def test_minute_sample_cannot_lower_a_different_days_hourly_peak() -> None:
    for path in OPENAI + ANTHROPIC:
        text = path.read_text(encoding="utf-8")
        assert "maximum hour anywhere in the window" in text or "full-window hourly rate" in text
        assert "Never replace a known hourly peak with a lower minute sample" in text
    openai = OPENAI[0].read_text(encoding="utf-8")
    assert "stays at 100 tokens/minute" in openai


def test_peak_warnings_do_not_blank_daily_volume() -> None:
    for path in ESTIMATE:
        text = path.read_text(encoding="utf-8")
        assert "means the peak is uncertain" in text
        assert "does not make the daily volume" in text or "Do not treat that warning as a failed daily usage endpoint" in text


def test_anthropic_quota_peak_includes_cache_writes_not_reads() -> None:
    for path in ANTHROPIC:
        text = path.read_text(encoding="utf-8")
        assert "Do not add" in text and "`cache_read_input_tokens` into that peak" in text
        assert "250,000 cache-write tokens" in text
        assert "`input_tokens` stays uncached input" in text


def test_optional_analytics_failure_is_a_terminal_omission() -> None:
    for path in OPENROUTER:
        text = path.read_text(encoding="utf-8")
        assert "terminal omission for this run" in text
        assert "Do not retry it" in text


def test_openrouter_analytics_rows_are_addressed_by_file() -> None:
    for path in OPENROUTER:
        text = path.read_text(encoding="utf-8")
        assert "file` is `analytics.json`" in text or "whose `file` is `analytics.json`" in text
        assert "analytics-volume.json" in text
        assert "do not block Step 3" in text or "Do not block Step 3" in text


def test_skill_adds_byok_fee_when_the_field_is_present() -> None:
    text = SKILL.read_text(encoding="utf-8")
    step = text[text.index("## Step 1.5") : text.index("## Phase A")]
    assert "byok_fees_usd" in step
    assert "byok_request_count" in step
