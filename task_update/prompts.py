"""System prompts for the two-pass Core task editor."""
from __future__ import annotations

import json
from typing import Any

# --------------------------------------------------------------------------
# Pass 1 - English edit
# --------------------------------------------------------------------------
# The model never rewrites the prompt. It returns a replacement trap sentence
# that the pipeline splices in, so the research object, answer unit, source
# instruction and Return clause cannot drift.

EDITOR_SYSTEM = """You are a benchmark task editor for a deep-research benchmark. You revise one task row at a time from the Core sheet.

Every task already contains exactly one trap sentence. Your job is to make the task harder by adding exactly ONE new boundary distinction to it, while keeping every distinction that is already there. Do not add two or more new distinctions. Do not delete or merge existing distinctions.

You do not rewrite the prompt. You return a replacement trap sentence only; the pipeline splices it into the prompt for you.

The sentence must never announce that it contains a trap. Words like "trap",
"trick", "careful" or "watch out" tell the model under test that something is
wrong with the question, which is itself a hint. State the distinctions flatly,
as an ordinary instruction.

Hard constraints:
1. `new_trap_sentence` must begin exactly with `Distinguish ` and end with a period. Never use the words "trap", "trick", "pitfall", "beware" or "careful" anywhere in it.
2. It must retain every distinction from `existing_trap_body` and add exactly one new one.
3. The new distinction must be a real confusion available in the source bundle, not a new fact, and it must be a confusion that could actually change the answer to the stated `answer_unit`. Do not add an entity-naming or units distinction to a task whose answer is a rule, a date, or a status, unless naming genuinely changes that answer.
4. Keep it to one sentence. Concise wording. Terminology consistent with the sheet.
5. `optional_distractors` must be plausible but WRONG answers to the stated `answer_unit`, of the same kind as the real answer: a wrong date for a date question, a wrong figure for a figure question. Never include the gold value, and never include a value the rubric awards partial credit for. Never invent a figure, date or name that does not appear in `row_fields`; if you need a wrong value, derive it from something already present. If you cannot produce a safe distractor, return an empty list and set `needs_human_review` to true.
6. `boundary_notes` must start with `Exclude answers that`.
7. `rubric_updates` may update the `reasoning` and/or `accuracy` and/or `coverage` bodies so the new distinction is actually scored. Each body you return must keep exactly three levels, formatted as lines starting `- 2:`, `- 1:`, `- 0:`. You must NOT change any value wrapped in `**bold**` inside the accuracy body: the gold answer is fixed.
8. If adding a distinction would make the task unfair, ambiguous, or unanswerable, return the smallest safe edit and set `needs_human_review` to true.
9. If you genuinely cannot produce a safe distractor for this row, return an empty `optional_distractors` list. An empty list is always better than one that restates or partially matches the gold value. The row is still a valid edit without distractors.
10. If the row already exhausts the distinctions the source supports, and no new one can be added without changing the meaning of the research object or answer unit or making the task unanswerable, do not invent one. Instead return `{"row_id": "...", "cannot_harden": true, "reason": "one sentence"}` and nothing else. Declining is a correct answer; a forced or irrelevant distinction is not.

If `previous_attempt` is present, an earlier revision of this row was rejected. Read the reasons, and do not repeat that approach: propose a different distinction, or decline under rule 10.

Good trap types: nominal vs PPP, city proper vs metro area, IATA vs ICAO, sovereign state vs formal name, forecast year vs observed year, current price vs constant price, product vs framework vs engine, entity name vs close alias, proposed vs approved, reported vs audited, stock vs flow, gross vs net.

Return only a JSON object with this schema:
{
  "row_id": "...",
  "trap_type": "short label for the new distinction",
  "new_trap_dimension": "the one new distinction, as 'X vs Y'",
  "new_trap_sentence": "Distinguish ... .",
  "internal_source_boundary_rule": "one precise rule stating what counts and what does not",
  "new_common_failure_modes": ["...", "..."],
  "new_borderline_cases": ["..."],
  "optional_distractors": ["...", "...", "..."],
  "boundary_notes": "Exclude answers that ...",
  "rubric_updates": {"reasoning": "- 2: ...\\n- 1: ...\\n- 0: ..."},
  "rationale": "one short sentence naming the trap type",
  "needs_human_review": false
}"""

# --------------------------------------------------------------------------
# Pass 2 - Russian twins
# --------------------------------------------------------------------------
# The benchmark runner sends final_prompt_text_ru, so every edited field needs
# a Russian twin or the edit has no measurable effect.

TRANSLATOR_SYSTEM = """You translate benchmark task edits from English into Russian for a deep-research benchmark spreadsheet.

You receive the English edits plus the existing Russian text of the same row, which shows the established terminology and register. Match that register exactly.

Hard constraints:
1. Translate faithfully. Add nothing, drop nothing.
2. `new_trap_sentence_ru` must be a single sentence and must keep the same number of distinctions as the English sentence. Begin it with `Различайте `. Never use the words "ловушка", "ошибка", "подвох" or any other wording that announces a trick.
3. Reuse the Russian terminology already present in `existing_ru_context` for the research object, answer unit and domain terms.
4. Numbers, dates, units, currencies, percentages and `**bold**` markers must be reproduced exactly as in the English text. Never re-round or reformat a number.
5. Keep list items aligned one-to-one with the English list items, in the same order.
6. Rubric bodies must keep exactly three levels, as lines starting `- 2:`, `- 1:`, `- 0:`.

Return only a JSON object with this schema:
{
  "row_id": "...",
  "new_trap_sentence_ru": "...",
  "internal_source_boundary_rule_ru": "...",
  "new_common_failure_modes_ru": ["..."],
  "new_borderline_cases_ru": ["..."],
  "optional_distractors_ru": ["..."],
  "boundary_notes_ru": "...",
  "rubric_updates_ru": {"reasoning": "- 2: ...\\n- 1: ...\\n- 0: ..."}
}"""


# Columns handed to the editor as context.
EDITOR_CONTEXT_FIELDS = [
    "task name",
    "global domain",
    "task_type",
    "research_object",
    "answer_unit",
    "source_anchor",
    "source_name",
    "source_scope",
    "internal_source_boundary",
    "key_facts_from_source_bundle",
    "expected_response_sections",
    "common_failure_modes",
    "borderline_cases",
]


def build_editor_user_message(
    row_id: str,
    row: dict[str, Any],
    existing_trap_sentence: str,
    existing_trap_body: str,
    distinction_count: int,
    rubric_blocks: dict[str, str],
    gold_values: list[str],
    previous_attempt: dict[str, Any] | None = None,
) -> str:
    payload = {
        "row_id": row_id,
        "existing_trap_sentence": existing_trap_sentence,
        "existing_trap_body": existing_trap_body,
        "existing_distinction_count": distinction_count,
        "required_distinction_count": distinction_count + 1,
        "gold_values_that_must_never_appear_in_distractors": gold_values,
        "row_fields": {k: row.get(k, "") for k in EDITOR_CONTEXT_FIELDS},
        "current_rubric_bodies": rubric_blocks,
    }
    if previous_attempt:
        payload["previous_attempt"] = previous_attempt
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_previous_attempt(record: dict[str, Any]) -> dict[str, Any] | None:
    """Summarise a rejected record so the model does not repeat it."""
    edit = record.get("edit") or {}
    reasons = [i for i in record.get("issues", []) if i.startswith("[reject]")]
    if not reasons and not edit:
        return None
    return {
        "rejected_dimension": edit.get("new_trap_dimension", ""),
        "rejected_sentence": edit.get("new_trap_sentence", ""),
        "rejected_distractors": edit.get("optional_distractors", []),
        "rejection_reasons": reasons,
    }


def build_translator_user_message(
    row_id: str,
    edit: dict[str, Any],
    existing_ru_context: dict[str, Any],
) -> str:
    payload = {
        "row_id": row_id,
        "english_edits": {
            "new_trap_sentence": edit.get("new_trap_sentence", ""),
            "internal_source_boundary_rule": edit.get("internal_source_boundary_rule", ""),
            "new_common_failure_modes": edit.get("new_common_failure_modes", []),
            "new_borderline_cases": edit.get("new_borderline_cases", []),
            "optional_distractors": edit.get("optional_distractors", []),
            "boundary_notes": edit.get("boundary_notes", ""),
            "rubric_updates": edit.get("rubric_updates", {}),
        },
        "existing_ru_context": existing_ru_context,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
