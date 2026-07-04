from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    slug: str
    provider: str
    temperature: float = 0.2
    max_tokens: int = 1800
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class Task:
    sheet_name: str
    batch: str
    task_number: str
    task_name: str
    global_domain: str
    task_type: str
    manual_status: str
    final_prompt_text: str
    final_prompt_text_ru: str
    fixed_criteria_0_2_each: str
    fixed_criteria_0_2_each_ru: str
    rubric_id: str
    gold_set_id: str
    correct_items: str
    acceptable_variants: str
    optional_distractors: str
    explicit_exclusion_rules: str
    boundary_notes: str
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def task_id(self) -> str:
        return f"{self.sheet_name}-{self.batch}-task{self.task_number}-{self.task_name}"

    def prompt_for(self, prompt_field: str) -> str:
        if prompt_field == "final_prompt_text":
            return self.final_prompt_text
        if prompt_field == "final_prompt_text_ru":
            return self.final_prompt_text_ru
        raise ValueError(f"Unsupported prompt field: {prompt_field!r}")

    @property
    def task_family(self) -> str:
        parts = self.task_name.split("-")
        if len(parts) >= 2:
            return "-".join(parts[:2])
        return self.task_name or "Unknown"


@dataclass
class Result:
    task_id: str
    domain: str
    task_type: str
    prompt_field_used: str
    prompt: str
    response_text: str
    raw_response_json: dict[str, Any]
    token_usage: dict[str, Any] | None
    estimated_cost: float | None
    cost_status: str
    status: str
    error_message: str | None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "task_id": self.task_id,
            "domain": self.domain,
            "task_type": self.task_type,
            "prompt_field_used": self.prompt_field_used,
            "status": self.status,
            "error_message": self.error_message,
            "prompt": self.prompt,
            "response_text": self.response_text,
            "token_usage": self.token_usage,
            "estimated_cost": self.estimated_cost,
            "cost_status": self.cost_status,
            "raw_response_json": self.raw_response_json,
        }
