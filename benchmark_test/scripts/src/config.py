from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.models import ModelConfig

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MODEL_CONFIGS: dict[str, ModelConfig] = {
    # --- currently accessible (verified 2026-07-02) ---
    "perplexity/sonar-pro-search": ModelConfig(
        slug="perplexity/sonar-pro-search",
        provider="perplexity",
        max_tokens=8000,
    ),
    "perplexity/sonar-deep-research": ModelConfig(
        slug="perplexity/sonar-deep-research",
        provider="perplexity",
        max_tokens=16000,
    ),
    "deepseek/deepseek-v4-pro": ModelConfig(
        slug="deepseek/deepseek-v4-pro",
        provider="deepseek",
        max_tokens=16000,
    ),
    "openai/gpt-5.5": ModelConfig(
        slug="openai/gpt-5.5",
        provider="openai",
        max_tokens=16000,
        extra_body={"reasoning": {"enabled": True}},
    ),
    "anthropic/claude-opus-4.8": ModelConfig(
        slug="anthropic/claude-opus-4.8",
        provider="anthropic",
        max_tokens=16000,
    ),
    "anthropic/claude-opus-4.5": ModelConfig(
        slug="anthropic/claude-opus-4.5",
        provider="anthropic",
    ),
    "anthropic/claude-opus-4.1": ModelConfig(
        slug="anthropic/claude-opus-4.1",
        provider="anthropic",
    ),
    "anthropic/claude-opus-4": ModelConfig(
        slug="anthropic/claude-opus-4",
        provider="anthropic",
    ),
    # --- do NOT use: same model as claude-opus-4.8 but 3× price ---
    # "anthropic/claude-opus-4.8-fast": priority-queue variant, avoid
    # --- retired / removed from OpenRouter ---
    # "alibaba/tongyi-deepresearch-30b-a3b": 404 - no endpoints
}

DEFAULT_INPUT = Path("final.xlsx")
DEFAULT_INPUT_PATH = DEFAULT_INPUT  # alias used by retry_tasks.py
DEFAULT_OUTPUT_DIR = Path("outputs")
DEFAULT_SHEET = "Core"
DEFAULT_LIMIT: int | None = None
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 5.0
DEFAULT_PROMPT_FIELD = "final_prompt_text_ru"


def get_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")


def get_model_config(model_slug: str) -> ModelConfig:
    if model_slug not in MODEL_CONFIGS:
        available = ", ".join(sorted(MODEL_CONFIGS.keys()))
        raise ValueError(f"Unknown model slug '{model_slug}'. Available: {available}")
    return MODEL_CONFIGS[model_slug]
