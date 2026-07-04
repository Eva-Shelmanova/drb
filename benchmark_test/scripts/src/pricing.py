from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenPricing:
    input_per_million: float | None
    output_per_million: float | None


# Prices are intentionally explicit and model-specific.
# Update these values if your billing terms change.
MODEL_PRICING: dict[str, TokenPricing] = {
    "alibaba/tongyi-deepresearch-30b-a3b": TokenPricing(None, None),
    "perplexity/sonar-deep-research": TokenPricing(None, None),
    "openai/gpt-5.5": TokenPricing(None, None),
    "anthropic/claude-opus-4.8-fast": TokenPricing(None, None),
    "deepseek/deepseek-v4-pro": TokenPricing(None, None),
}


def estimate_cost(
    model_slug: str,
    token_usage: dict[str, Any] | None,
) -> tuple[float | None, str]:
    pricing = MODEL_PRICING.get(model_slug)
    if pricing is None:
        return None, "unknown_model"

    if token_usage is None:
        return None, "unknown_no_usage"

    prompt_tokens = _extract_int(token_usage, "prompt_tokens")
    completion_tokens = _extract_int(token_usage, "completion_tokens")
    if prompt_tokens is None or completion_tokens is None:
        return None, "unknown_missing_token_fields"

    if pricing.input_per_million is None or pricing.output_per_million is None:
        return None, "estimated_missing_price_table"

    input_cost = (prompt_tokens / 1_000_000) * pricing.input_per_million
    output_cost = (completion_tokens / 1_000_000) * pricing.output_per_million
    return input_cost + output_cost, "estimated_from_usage"


def _extract_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

