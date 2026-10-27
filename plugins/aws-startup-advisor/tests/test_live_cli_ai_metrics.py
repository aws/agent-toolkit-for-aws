"""Guard: live az/gcloud discovery keeps Azure OpenAI and Gemini usage.

Deployment lists name the model. They do not say how many tokens moved.
These contracts keep the read-only metric commands, the consent disclosure,
and the estimate rules that stop a 30-day sum from being treated as a peak.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text()


AZURE_LIVE = _read(
    "skills/azure-to-aws/references/phases/discover/discover-live.md"
)
GCP_LIVE = _read("skills/gcp-to-aws/references/phases/discover/discover-live.md")
AZURE_ESTIMATE = _read(
    "skills/azure-to-aws/references/phases/estimate/estimate-ai.md"
)
GCP_ESTIMATE = _read("skills/gcp-to-aws/references/phases/estimate/estimate-ai.md")


def test_azure_monitor_commands_and_consent():
    for needle in (
        "ProcessedPromptTokens",
        "GeneratedTokens",
        "AzureOpenAIRequests",
        "AzureOpenAIContextTokensCachedWrite",
        "AzureOpenAITimeToResponse",
        "--interval PT1H",
        "ModelDeploymentName eq '<deployment name>'",
        "ServiceTierRequest eq '*'",
        "ServiceTierResponse eq '*'",
        "service_tier_response",
        "IsSpillover eq '*'",
        "--top 50",
        "coverage_incomplete",
        "service_tier` to `\"unknown\"`",
        "azure-openai-metrics-profile.json",
        "cache_write_tokens",
        'peak_source` is `"hour"`',
        "maximum hour anywhere in the window",
        "Do NOT query the metric named `Latency`",
        "AzureOpenAIContextTokensCacheMatchRate",
        "prompts, or completions",
        "az cognitiveservices account keys list` is FORBIDDEN",
    ):
        assert needle in AZURE_LIVE, needle
    assert "ModelDeploymentName eq '*'" not in AZURE_LIVE
    assert "do not set inventory `metadata.confidence` to `measured`" in AZURE_LIVE


def test_gcloud_publisher_metrics_and_consent():
    for needle in (
        "https://monitoring.googleapis.com/v3/projects/$GCP_PROJECT/timeSeries",
        "nextPageToken",
        "aiplatform.googleapis.com/publisher/online_serving/token_count",
        "publisher/online_serving/model_invocation_count",
        "publisher/online_serving/first_token_latencies",
        "ALIGN_SUM",
        "ALIGN_PERCENTILE_95",
        "metric.label.type",
        "metric.label.source",
        "batch_",
        "gcp-publisher-metrics-profile.json",
        "gcloud ai models list",
        "serverless Gemini",
        "prompts, or completions",
        "worst hour's p95",
        "maximum hour anywhere in the window",
        "live_monitoring",
        "Do not read",
        "resource.data",
    ):
        assert needle in GCP_LIVE, needle
    assert "gcloud monitoring time-series list` is not a command" in GCP_LIVE
    assert "gcloud monitoring time-series list --project" not in GCP_LIVE


def test_estimate_reads_live_metric_profiles():
    assert "azure-openai-metrics-profile.json" in AZURE_ESTIMATE
    assert "not a customer-measured p95" in AZURE_ESTIMATE
    assert "Do not add it to `input_tokens`" in AZURE_ESTIMATE
    assert "maximum hour anywhere in the window" in AZURE_ESTIMATE
    assert "gcp-publisher-metrics-profile.json" in GCP_ESTIMATE
    assert "not a latency SLO" in GCP_ESTIMATE
    assert "serverless Gemini" in GCP_ESTIMATE
    assert "maximum hour anywhere in the window" in GCP_ESTIMATE


def test_decline_and_clarify_consume_live_profiles():
    azure_discover = _read(
        "skills/azure-to-aws/references/phases/discover/discover.md"
    )
    assert "azure-openai-metrics-profile.json" in azure_discover
    gcp_discover = _read("skills/gcp-to-aws/references/phases/discover/discover.md")
    assert "live_monitoring" in gcp_discover
    for relative in (
        "skills/azure-to-aws/references/phases/clarify/clarify-ai.md",
        "skills/azure-to-aws/references/phases/clarify/clarify-ai-only.md",
        "skills/gcp-to-aws/references/phases/clarify/clarify-ai.md",
        "skills/gcp-to-aws/references/phases/clarify/clarify-ai-only.md",
    ):
        text = _read(relative)
        assert "partial_window" in text
        assert "input_tokens + output_tokens" in text
    quotas = _read("skills/shared/ai/bedrock-quotas.md")
    assert "observed_on_demand_peak" in quotas
    assert "200,000" in quotas
    assert 'ai_source` to\n`"both"`' in GCP_LIVE or 'set `ai_source` to\n`"both"`' in GCP_LIVE
    assert "OpenAI code profile plus these Gemini models" in GCP_LIVE
