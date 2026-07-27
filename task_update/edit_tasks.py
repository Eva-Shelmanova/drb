"""Harden Core benchmark tasks by adding one boundary distinction per task.

Two passes per row against OpenRouter: an English edit, then a Russian
translation of that edit. The model returns only a replacement trap sentence
and new field items; this script splices them into the workbook, so the
research object, answer unit, source instruction and Return clause cannot
drift. Every edit must clear validate.py before it is written.

Nothing is written in place: the result goes to a new workbook.

Usage
-----
  # parse-only sanity check over every row, no API calls
  python edit_tasks.py --dry-run

  # 10-row pilot
  python edit_tasks.py --limit 10

  # full run
  python edit_tasks.py --workers 6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from prompts import (
    EDITOR_SYSTEM,
    TRANSLATOR_SYSTEM,
    build_editor_user_message,
    build_previous_attempt,
    build_translator_user_message,
)
from sheet import (
    DIMENSIONS,
    Row,
    append_bullets,
    bullets,
    compose_rubric,
    count_distinctions,
    flatten_ws,
    gold_spans,
    load_rows,
    parse_en_trap,
    parse_ru_trap,
    rubric_bodies,
    splice_trap,
    write_updates,
)
from validate import REJECT, validate_edit, validate_translation

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE.parent / "benchmark_extraction" / "final.xlsx"
DEFAULT_OUT_DIR = HERE / "out"
URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------
# model call
# --------------------------------------------------------------------------

def _unwrap(obj: Any) -> Any:
    """Undo JSON-mode wrappers.

    The model intermittently returns the whole payload as a string under a
    single key, e.g. {".json": "{\\"row_id\\": ...}"}. Unwrap up to a couple of
    levels so those responses are usable instead of failing on missing fields.
    """
    for _ in range(3):
        if isinstance(obj, dict) and len(obj) == 1:
            (value,) = obj.values()
            if isinstance(value, str):
                try:
                    obj = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    return obj
            if isinstance(value, dict):
                obj = value
                continue
        return obj
    return obj


def call_model(
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: int,
    retries: int,
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
                timeout=(15, timeout),
            )
            body = resp.json()
            if not resp.ok or "error" in body:
                raise RuntimeError(f"HTTP {resp.status_code}: {json.dumps(body)[:400]}")
            content = (body.get("choices") or [{}])[0].get("message", {}).get("content")
            if not content:
                finish = (body.get("choices") or [{}])[0].get("finish_reason")
                raise RuntimeError(f"empty content (finish_reason={finish})")
            return _unwrap(json.loads(content)), body.get("usage") or {}
        except Exception as exc:  # noqa: BLE001 - retried and reported per row
            last_error = exc
            if attempt < retries:
                time.sleep(3.0 * attempt)
    raise RuntimeError(f"model call failed after {retries} attempts: {last_error}")


# --------------------------------------------------------------------------
# per-row work
# --------------------------------------------------------------------------

def build_updates(
    row: Row,
    edit: dict[str, Any],
    translation: dict[str, Any],
    en_trap_sentence: str,
    ru_trap_sentence: str,
) -> dict[str, str]:
    """Compose the exact cell values to write for this row."""
    updates: dict[str, str] = {}

    # 1. prompts: trap sentence spliced in, everything else untouched
    updates["final_prompt_text"] = splice_trap(
        row["final_prompt_text"], en_trap_sentence, edit["new_trap_sentence"].strip()
    )
    updates["final_prompt_text_ru"] = splice_trap(
        row["final_prompt_text_ru"],
        ru_trap_sentence,
        flatten_ws(translation["new_trap_sentence_ru"]),
    )

    # 2. boundary rule appended to the existing grounding block
    rule_en = f"- boundary rule: {edit['internal_source_boundary_rule'].strip()}"
    rule_ru = f"- boundary rule: {flatten_ws(translation['internal_source_boundary_rule_ru'])}"
    updates["internal_source_boundary"] = append_bullets(
        row["internal_source_boundary"], [rule_en]
    )
    updates["internal_source_boundary_ru"] = append_bullets(
        row["internal_source_boundary_ru"], [rule_ru]
    )

    # 3. curated lists: append, never replace
    updates["common_failure_modes"] = append_bullets(
        row["common_failure_modes"], edit.get("new_common_failure_modes") or []
    )
    updates["common_failure_modes_ru"] = append_bullets(
        row["common_failure_modes_ru"], translation.get("new_common_failure_modes_ru") or []
    )
    updates["borderline_cases"] = append_bullets(
        row["borderline_cases"], edit.get("new_borderline_cases") or []
    )
    updates["borderline_cases_ru"] = append_bullets(
        row["borderline_cases_ru"], translation.get("new_borderline_cases_ru") or []
    )

    # 4. fields the Core sheet leaves empty today
    if edit.get("optional_distractors"):
        updates["optional_distractors"] = bullets(edit["optional_distractors"])
        updates["optional_distractors_ru"] = bullets(
            translation.get("optional_distractors_ru") or []
        )
    updates["boundary_notes"] = edit["boundary_notes"].strip()
    updates["boundary_notes_ru"] = flatten_ws(translation.get("boundary_notes_ru", ""))

    # 5. rubric: per-dimension columns plus the recomposed fixed_criteria cells.
    # Only dimensions present in both languages are written, so the English and
    # Russian rubrics never drift apart.
    ru_raw = translation.get("rubric_updates_ru") or {}
    shared_dims = set((edit.get("rubric_updates") or {}).keys()) & set(ru_raw.keys())
    en_bodies = {
        k: str(v).strip()
        for k, v in (edit.get("rubric_updates") or {}).items()
        if k in shared_dims
    }
    ru_bodies = {k: flatten_ws(v) for k, v in ru_raw.items() if k in shared_dims}
    for dim, body in en_bodies.items():
        updates[dim] = body
    for dim, body in ru_bodies.items():
        updates[f"{dim}_ru"] = body
    if en_bodies:
        updates["fixed_criteria_0_2_each"] = compose_rubric(
            row["fixed_criteria_0_2_each"], en_bodies
        )
    if ru_bodies:
        updates["fixed_criteria_0_2_each_ru"] = compose_rubric(
            row["fixed_criteria_0_2_each_ru"], ru_bodies
        )

    return updates


def process_row(
    row: Row,
    args: argparse.Namespace,
    api_key: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Edit, translate, validate. Returns a record; never raises."""
    rec: dict[str, Any] = {
        "row_id": row.row_id,
        "row_index": row.row_index,
        "task_name": row.get("task name", ""),
        "domain": row.get("global domain", ""),
        "status": "pending",
        "issues": [],
        "cost": 0.0,
    }

    en = parse_en_trap(row["final_prompt_text"])
    ru = parse_ru_trap(row["final_prompt_text_ru"])
    if not en:
        rec.update(status=REJECT, issues=["[reject] could not parse EN trap sentence"])
        return rec
    if not ru:
        rec.update(status=REJECT, issues=["[reject] could not parse RU trap sentence"])
        return rec

    en_sentence, en_body = en
    ru_sentence, _ = ru
    distinctions = count_distinctions(en_body)
    rec["existing_distinctions"] = distinctions

    try:
        blocks = rubric_bodies(row["fixed_criteria_0_2_each"])
        rubric_bodies(row["fixed_criteria_0_2_each_ru"])
    except ValueError as exc:
        rec.update(status=REJECT, issues=[f"[reject] rubric not parseable: {exc}"])
        return rec

    gold = gold_spans(row)
    rec["gold_values"] = gold

    # --- pass 1: English edit ---
    try:
        edit, usage = call_model(
            api_key,
            args.model,
            EDITOR_SYSTEM,
            build_editor_user_message(
                row.row_id, row, en_sentence, en_body, distinctions, blocks, gold,
                previous_attempt=previous,
            ),
            args.timeout,
            args.retries,
            args.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        rec.update(status="error", issues=[f"[error] editor pass: {exc}"])
        return rec
    rec["edit"] = edit
    rec["cost"] += float(usage.get("cost") or 0.0)

    # The model may decline a row whose distinctions the source already exhausts.
    # That is a valid outcome, not a failure: the row is left untouched.
    if edit.get("cannot_harden") is True:
        rec.update(
            status="declined",
            issues=[f"[declined] {edit.get('reason', 'no reason given')}"],
        )
        return rec

    severity, issues = validate_edit(edit, en_body, distinctions, gold, blocks)
    rec["issues"].extend(issues)
    if severity == REJECT:
        rec["status"] = REJECT
        return rec

    # Drop rubric dimensions the model returned unchanged. Translating those
    # would reword the Russian cell for no reason.
    edit["rubric_updates"] = {
        dim: body
        for dim, body in (edit.get("rubric_updates") or {}).items()
        if flatten_ws(body) != flatten_ws(blocks.get(dim, ""))
    }

    # --- pass 2: Russian twins ---
    ru_context = {
        "final_prompt_text_ru": row["final_prompt_text_ru"],
        "existing_trap_sentence_ru": ru_sentence,
        "research_object_ru": row.get("research_object_ru", ""),
        "answer_unit_ru": row.get("answer_unit_ru", ""),
        "internal_source_boundary_ru": row.get("internal_source_boundary_ru", ""),
        "current_rubric_bodies_ru": {
            k: v for k, v in rubric_bodies(row["fixed_criteria_0_2_each_ru"]).items()
            if k in (edit.get("rubric_updates") or {})
        },
    }
    if args.no_translate:
        rec.update(status="edit_only")
        return rec

    try:
        translation, usage = call_model(
            api_key,
            args.model,
            TRANSLATOR_SYSTEM,
            build_translator_user_message(row.row_id, edit, ru_context),
            args.timeout,
            args.retries,
            args.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        rec.update(status="error", issues=rec["issues"] + [f"[error] translator pass: {exc}"])
        return rec
    rec["translation"] = translation
    rec["cost"] += float(usage.get("cost") or 0.0)

    tr_sev, tr_issues = validate_translation(edit, translation)
    rec["issues"].extend(tr_issues)
    if tr_sev == REJECT:
        rec["status"] = REJECT
        return rec

    # --- compose cell values ---
    try:
        rec["updates"] = build_updates(row, edit, translation, en_sentence, ru_sentence)
    except Exception as exc:  # noqa: BLE001
        rec.update(status=REJECT, issues=rec["issues"] + [f"[reject] splice failed: {exc}"])
        return rec

    rec["status"] = "flag" if (severity == "flag" or tr_sev == "flag") else "ok"
    rec["new_distinctions"] = count_distinctions(edit["new_trap_sentence"])
    return rec


# --------------------------------------------------------------------------
# dry run: structural checks only, no API calls
# --------------------------------------------------------------------------

def dry_run(rows: list[Row]) -> int:
    en_fail, ru_fail, rubric_fail, roundtrip_fail = [], [], [], []
    dist: dict[int, int] = {}
    no_gold = []

    for row in rows:
        if not parse_en_trap(row["final_prompt_text"]):
            en_fail.append(row.row_id)
        else:
            c = count_distinctions(parse_en_trap(row["final_prompt_text"])[1])
            dist[c] = dist.get(c, 0) + 1
        if not parse_ru_trap(row["final_prompt_text_ru"]):
            ru_fail.append(row.row_id)
        for col in ("fixed_criteria_0_2_each", "fixed_criteria_0_2_each_ru"):
            try:
                rubric_bodies(row[col])
            except ValueError:
                rubric_fail.append(f"{row.row_id}:{col}")
                continue
            # round trip must be byte-identical or a write could corrupt the cell
            if compose_rubric(row[col], {}) != row[col]:
                roundtrip_fail.append(f"{row.row_id}:{col}")
        if not gold_spans(row):
            no_gold.append(row.row_id)

    n = len(rows)
    print(f"rows inspected: {n}")
    print(f"  EN trap parsed:            {n - len(en_fail)}/{n}")
    print(f"  RU trap parsed:            {n - len(ru_fail)}/{n}")
    print(f"  rubric parsed (EN+RU):     {2 * n - len(rubric_fail)}/{2 * n}")
    print(f"  rubric round-trip exact:   {2 * n - len(roundtrip_fail)}/{2 * n}")
    print(f"  rows with bolded gold:     {n - len(no_gold)}/{n}")
    print(f"  distinction counts:        {dict(sorted(dist.items()))}")

    problems = 0
    for label, items in (
        ("EN trap unparseable", en_fail),
        ("RU trap unparseable", ru_fail),
        ("rubric unparseable", rubric_fail),
        ("rubric round-trip mismatch", roundtrip_fail),
    ):
        if items:
            problems += len(items)
            print(f"\n  {label} ({len(items)}):")
            for i in items[:10]:
                print(f"    {i}")
    if no_gold:
        print(
            f"\n  {len(no_gold)} rows have no bolded gold value; their distractors "
            f"cannot be machine-verified and will be flagged for review."
        )
    print("\nDRY RUN CLEAN" if problems == 0 else f"\nDRY RUN FOUND {problems} PROBLEM(S)")
    return 0 if problems == 0 else 1


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def write_report(path: Path, records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    by_status: dict[str, list[dict]] = {}
    for r in records:
        by_status.setdefault(r["status"], []).append(r)
    total_cost = sum(r.get("cost", 0.0) for r in records)

    lines = [
        "# Core task hardening report",
        "",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        f"- model: `{args.model}`",
        f"- rows processed: {len(records)}",
        f"- estimated cost: ${total_cost:.4f}",
        "",
        "## Outcome",
        "",
        "| status | rows | meaning |",
        "|---|---|---|",
        f"| ok | {len(by_status.get('ok', []))} | written, no issues |",
        f"| flag | {len(by_status.get('flag', []))} | written, needs human review |",
        f"| declined | {len(by_status.get('declined', []))} | model judged the row already exhaustive |",
        f"| reject | {len(by_status.get('reject', []))} | not written |",
        f"| error | {len(by_status.get('error', []))} | API failure, not written |",
        "",
    ]

    trap_types: dict[str, int] = {}
    for r in records:
        t = (r.get("edit") or {}).get("trap_type")
        if t:
            trap_types[str(t)] = trap_types.get(str(t), 0) + 1
    if trap_types:
        lines += ["## Trap types added", ""]
        for t, c in sorted(trap_types.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {c} x {t}")
        lines.append("")

    for status in ("declined", "reject", "error", "flag"):
        items = by_status.get(status, [])
        if not items:
            continue
        lines += [f"## {status} ({len(items)})", ""]
        for r in items:
            lines.append(f"### {r['row_id']}")
            new_sentence = (r.get("edit") or {}).get("new_trap_sentence", "")
            if new_sentence:
                lines.append(f"- proposed trap: {new_sentence}")
            if "existing_distinctions" in r:
                lines.append(
                    f"- distinctions: {r.get('existing_distinctions')} -> "
                    f"{r.get('new_distinctions', '?')}"
                )
            for issue in r["issues"]:
                lines.append(f"- {issue}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--output-xlsx", type=Path, default=None)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--limit", type=int, default=None, help="process only the first N rows")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8000)
    p.add_argument(
        "--retry-from",
        type=Path,
        default=None,
        help="an edits_<run>.jsonl; reprocess only the rows that were rejected or errored",
    )
    p.add_argument("--dry-run", action="store_true", help="structural checks only, no API calls")
    p.add_argument("--no-translate", action="store_true", help="skip the Russian pass")
    p.add_argument("--no-write", action="store_true", help="produce artifacts but no workbook")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"input workbook not found: {args.input}", file=sys.stderr)
        return 1

    _, rows = load_rows(args.input)

    previous: dict[str, dict[str, Any]] = {}
    if args.retry_from:
        wanted = set()
        with open(args.retry_from, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("status") in (REJECT, "error"):
                    wanted.add(rec["row_id"])
                    prior = build_previous_attempt(rec)
                    if prior:
                        previous[rec["row_id"]] = prior
        rows = [r for r in rows if r.row_id in wanted]
        print(f"retrying {len(rows)} of {len(wanted)} previously failed rows")

    if args.limit:
        rows = rows[: args.limit]

    if args.dry_run:
        return dry_run(rows)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY is required", file=sys.stderr)
        return 1

    run_id = utc_slug()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    edits_path = args.out_dir / f"edits_{run_id}.jsonl"
    report_path = args.out_dir / f"report_{run_id}.md"
    out_xlsx = args.output_xlsx or (args.out_dir / f"final_hardened_{run_id}.xlsx")

    log(f"model={args.model} rows={len(rows)} workers={args.workers}")
    log(f"artifacts -> {args.out_dir}")

    records: list[dict[str, Any]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(process_row, row, args, api_key, previous.get(row.row_id))
            for row in rows
        ]
        with open(edits_path, "w", encoding="utf-8") as fh:
            for fut in as_completed(futures):
                rec = fut.result()
                records.append(rec)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                done += 1
                log(f"  [{done}/{len(rows)}] {rec['row_id']}: {rec['status']}")

    updates = {
        r["row_index"]: r["updates"]
        for r in records
        if r["status"] in ("ok", "flag") and r.get("updates")
    }

    write_report(report_path, records, args)

    if updates and not args.no_write:
        written = write_updates(args.input, out_xlsx, updates)
        log(f"wrote {written} updated rows -> {out_xlsx}")
    elif not updates:
        log("no rows passed validation; workbook not written")

    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    log(f"summary: {counts}")
    log(f"cost: ${sum(r.get('cost', 0.0) for r in records):.4f}")
    log(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
