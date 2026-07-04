from __future__ import annotations

from src.config import MODEL_CONFIGS
from src.models import Task

REQUIRED_COLUMNS = [
    "batch",
    "task_number",
    "task name",
    "global domain",
    "task_type",
    "manual_status",
    "final_prompt_text",
    "final_prompt_text_ru",
    "fixed_criteria_0_2_each",
    "fixed_criteria_0_2_each_ru",
    "rubric_id",
    "gold_set_id",
    "correct_items",
    "acceptable_variants",
    "optional_distractors",
    "explicit_exclusion_rules",
    "boundary_notes",
]


def validate_required_columns(columns: list[str]) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    if missing:
        raise ValueError(f"Missing required spreadsheet columns: {', '.join(missing)}")


def validate_model_slug(model_slug: str) -> None:
    if model_slug not in MODEL_CONFIGS:
        available = ", ".join(sorted(MODEL_CONFIGS.keys()))
        raise ValueError(f"Unknown model slug '{model_slug}'. Available: {available}")


def validate_prompt(task: Task, prompt_field: str) -> str:
    prompt = task.prompt_for(prompt_field).strip()
    if not prompt:
        raise ValueError(f"Task '{task.task_id}' has an empty '{prompt_field}' prompt.")
    return prompt


def validate_response_text(response_text: str) -> None:
    if not response_text or not response_text.strip():
        raise ValueError("Model response is empty.")

    # Keep storage simple and deterministic for JSONL/CSV/XLSX outputs.
    if "\x00" in response_text:
        raise ValueError("Model response contains non-storable null byte.")

