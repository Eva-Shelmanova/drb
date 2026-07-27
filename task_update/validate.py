"""Programmatic validation of editor output.

Nothing is written to the workbook unless it passes here. The model's own
`needs_human_review` flag is treated as advisory only, because it has been
observed to report false while leaking the gold answer into a distractor.
"""
from __future__ import annotations

import re
from typing import Any

from sheet import BOLD_RE, count_distinctions

REJECT = "reject"
FLAG = "flag"
OK = "ok"

REQUIRED_KEYS = [
    "new_trap_sentence",
    "new_trap_dimension",
    "internal_source_boundary_rule",
    "boundary_notes",
]
TRAP_PREFIX = "Distinguish "
# Wording that would tell the model under test that the question contains a trick.
GIVEAWAY_EN = re.compile(r"(?i)\b(trap|trick|pitfall|beware|careful|caution|gotcha)\b")
GIVEAWAY_RU = re.compile(r"(?i)ловушк|подвох|ошибочн|осторожн")
# Newline-agnostic: English rubric cells are multi-line, Russian ones are flat.
RUBRIC_LEVEL_RE = re.compile(r"(?:^|\s)-\s*(?P<level>[012])\s*:")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
WORD_RE = re.compile(r"[a-z]{4,}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _is_specific(gold: str) -> bool:
    """Is this gold value distinctive enough for a containment test?

    Some rows have categorical gold values like 'direct' / 'indirect' /
    'unsupported'. A substring test on those fires constantly: 'direct' is
    inside 'indirect' and inside any sentence that uses the word. Only values
    carrying a number, or phrases of three or more words, are matched by
    containment; short categorical ones are matched exactly.
    """
    g = _norm(gold)
    return bool(re.search(r"\d", g)) or len(g.split()) >= 3


def _contains_word(haystack: str, needle: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack))


def _numbers(text: str) -> set[str]:
    """Significant numeric tokens, with the Russian decimal comma normalised.

    Single digits are dropped: they collide constantly (the '1' in '1 January
    2026' matches almost anything) without indicating a real near-miss.
    """
    out = set()
    for tok in NUM_RE.findall(str(text or "")):
        tok = tok.replace(",", ".")
        if len(tok.replace(".", "")) >= 2:
            out.add(tok)
    return out


def _levels(body: str) -> list[str]:
    return [m.group("level") for m in RUBRIC_LEVEL_RE.finditer(body or "")]


def validate_edit(
    edit: dict[str, Any],
    existing_trap_body: str,
    existing_distinctions: int,
    gold_values: list[str],
    rubric_blocks: dict[str, str],
) -> tuple[str, list[str]]:
    """Return (severity, issues). severity is one of ok / flag / reject."""
    issues: list[str] = []
    severity = OK

    def reject(msg: str) -> None:
        nonlocal severity
        severity = REJECT
        issues.append(f"[reject] {msg}")

    def flag(msg: str) -> None:
        nonlocal severity
        if severity != REJECT:
            severity = FLAG
        issues.append(f"[flag] {msg}")

    # --- schema ---
    for key in REQUIRED_KEYS:
        if not str(edit.get(key, "")).strip():
            reject(f"missing required field: {key}")
    if severity == REJECT:
        return severity, issues

    sentence = str(edit["new_trap_sentence"]).strip()

    # --- boundary sentence shape ---
    if not sentence.startswith(TRAP_PREFIX):
        reject(f"boundary sentence must start with {TRAP_PREFIX!r}")
    if not sentence.endswith("."):
        flag("boundary sentence does not end with a period")
    giveaway = GIVEAWAY_EN.findall(sentence)
    if giveaway:
        reject(f"boundary sentence announces the trick to the model: {sorted(set(giveaway))}")
    if "\n" in sentence:
        reject("boundary sentence spans multiple lines")

    # --- no difficulty regression ---
    body = sentence[len(TRAP_PREFIX):] if sentence.startswith(TRAP_PREFIX) else sentence
    new_count = count_distinctions(body)
    if new_count < existing_distinctions:
        reject(
            f"difficulty regression: {new_count} distinctions vs {existing_distinctions} before"
        )
    elif new_count == existing_distinctions:
        flag(
            f"distinction count unchanged ({new_count}); existing distinction may have been merged"
        )

    # --- every original distinction survives ---
    old_terms = {w for w in WORD_RE.findall(_norm(existing_trap_body))}
    new_terms = {w for w in WORD_RE.findall(_norm(sentence))}
    dropped = old_terms - new_terms
    # Ignore filler that carries no distinction meaning.
    dropped -= {"distinguish", "between", "from", "versus", "that", "with", "this", "than", "when",
                "which", "were", "have", "been", "into", "each", "only", "such", "also", "other"}
    if len(dropped) > max(3, len(old_terms) // 3):
        flag(f"{len(dropped)} terms from the original trap are absent: {sorted(dropped)[:8]}")

    # --- the new distinction is actually new ---
    dim = _norm(edit.get("new_trap_dimension", ""))
    dim_words = set(WORD_RE.findall(dim))
    if dim_words and dim_words <= old_terms:
        reject(f"new_trap_dimension {dim!r} adds nothing not already in the original trap")

    # --- gold answer must not leak into distractors ---
    distractors = edit.get("optional_distractors") or []
    if not isinstance(distractors, list):
        reject("optional_distractors must be a list")
        distractors = []
    if not gold_values:
        flag("no bolded gold value on this row; distractors are not machine-verifiable")
    for d in distractors:
        dn = _norm(d)
        leaked = False
        for gold in gold_values:
            gn = _norm(gold)
            if not gn:
                continue
            if _is_specific(gold):
                if _contains_word(dn, gn):
                    reject(f"distractor leaks the gold value {gold!r}: {str(d)[:90]!r}")
                    leaked = True
                    break
            elif dn == gn:
                reject(f"distractor is the gold value {gold!r}")
                leaked = True
                break
            elif _contains_word(dn, gn):
                flag(f"distractor mentions the categorical gold {gold!r}: {str(d)[:90]!r}")
        if not leaked:
            for gold in gold_values:
                shared = _numbers(gold) & _numbers(dn)
                if shared:
                    flag(
                        f"distractor shares numeric parts {sorted(shared)} with gold "
                        f"{gold!r}; may earn partial credit"
                    )
                    break
    if distractors and len(distractors) < 2:
        flag(f"only {len(distractors)} distractor(s); rule asks for 2-3")
    if len(distractors) > 4:
        flag(f"{len(distractors)} distractors; rule asks for 2-3")

    # --- boundary notes wording ---
    if not _norm(edit["boundary_notes"]).startswith("exclude answers that"):
        reject("boundary_notes must start with 'Exclude answers that'")

    # --- rubric edits ---
    rubric_updates = edit.get("rubric_updates") or {}
    if not isinstance(rubric_updates, dict):
        reject("rubric_updates must be an object")
        rubric_updates = {}
    if not rubric_updates:
        flag("no rubric update; the new distinction will not be scored")
    for dim_key, new_body in rubric_updates.items():
        if dim_key not in rubric_blocks:
            reject(f"rubric_updates references unknown dimension {dim_key!r}")
            continue
        levels = _levels(new_body)
        if levels != ["2", "1", "0"]:
            reject(f"rubric '{dim_key}' levels are {levels}, expected ['2','1','0']")
        if dim_key == "accuracy":
            before = sorted(_norm(s) for s in BOLD_RE.findall(rubric_blocks["accuracy"]))
            after = sorted(_norm(s) for s in BOLD_RE.findall(str(new_body)))
            if before != after:
                reject(
                    f"accuracy rubric changed the bolded gold value: {before} -> {after}"
                )

    if edit.get("needs_human_review") is True and severity == OK:
        severity = FLAG
        issues.append("[flag] model self-reported needs_human_review")

    return severity, issues


def validate_translation(
    edit: dict[str, Any],
    translation: dict[str, Any],
) -> tuple[str, list[str]]:
    """Check the Russian twins line up with the English edits."""
    issues: list[str] = []
    severity = OK

    def reject(msg: str) -> None:
        nonlocal severity
        severity = REJECT
        issues.append(f"[reject] {msg}")

    def flag(msg: str) -> None:
        nonlocal severity
        if severity != REJECT:
            severity = FLAG
        issues.append(f"[flag] {msg}")

    ru_sentence = str(translation.get("new_trap_sentence_ru", "")).strip()
    if not ru_sentence:
        reject("missing new_trap_sentence_ru")
        return severity, issues
    if not ru_sentence.lower().startswith("различа"):
        reject("Russian boundary sentence must start with 'Различайте'")
    giveaway = GIVEAWAY_RU.findall(ru_sentence)
    if giveaway:
        reject(f"Russian boundary sentence announces the trick: {sorted(set(giveaway))}")
    if not str(translation.get("boundary_notes_ru", "")).strip():
        reject("missing boundary_notes_ru")

    # Only an undercount matters. Russian enumerations split on the very common
    # conjunction "и", so the Russian count runs high on correct translations.
    en_count = count_distinctions(str(edit.get("new_trap_sentence", "")))
    ru_count = count_distinctions(ru_sentence)
    if ru_count < en_count:
        flag(f"Russian trap has fewer distinctions: EN {en_count} vs RU {ru_count}")

    # list lengths must match one-to-one
    pairs = [
        ("new_common_failure_modes", "new_common_failure_modes_ru"),
        ("new_borderline_cases", "new_borderline_cases_ru"),
        ("optional_distractors", "optional_distractors_ru"),
    ]
    for en_key, ru_key in pairs:
        en_list = edit.get(en_key) or []
        ru_list = translation.get(ru_key) or []
        if len(en_list) != len(ru_list):
            reject(f"{ru_key} has {len(ru_list)} items, EN has {len(en_list)}")

    # numbers must survive translation
    en_nums = _numbers(
        " ".join(
            [str(edit.get("new_trap_sentence", "")), str(edit.get("boundary_notes", ""))]
            + [str(x) for x in (edit.get("optional_distractors") or [])]
        )
    )
    ru_nums = _numbers(
        " ".join(
            [ru_sentence, str(translation.get("boundary_notes_ru", ""))]
            + [str(x) for x in (translation.get("optional_distractors_ru") or [])]
        )
    )
    missing = en_nums - ru_nums
    if missing:
        flag(f"numbers present in EN but not RU: {sorted(missing)[:6]}")

    # Russian must not invent dimensions English did not touch. A Russian
    # subset is tolerated: build_updates writes only the intersection, so both
    # languages stay consistent, just with fewer dimensions updated.
    en_dims = set((edit.get("rubric_updates") or {}).keys())
    ru_dims = set((translation.get("rubric_updates_ru") or {}).keys())
    if ru_dims - en_dims:
        reject(f"rubric_updates_ru has dimensions absent from EN: {sorted(ru_dims - en_dims)}")
    elif en_dims - ru_dims:
        flag(
            f"no Russian rubric for {sorted(en_dims - ru_dims)}; "
            f"those dimensions will be left unchanged in both languages"
        )
    for dim_key, body in (translation.get("rubric_updates_ru") or {}).items():
        levels = _levels(str(body))
        if levels != ["2", "1", "0"]:
            reject(f"RU rubric '{dim_key}' levels are {levels}, expected ['2','1','0']")

    return severity, issues
