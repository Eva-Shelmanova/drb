"""Remove the `source_scope` instruction from the prompts sent to the model.

Every prompt in the sheet carries a sentence naming an internal spreadsheet
column:

    Use `source_scope` only to locate the relevant row, note, paragraph, or
    table; do not infer beyond it.

The model under test never receives that column, so the sentence points at
something it cannot see. Empirically it also suppresses answers: the same model
over the same 161 tasks produced refusal-shaped replies for 14% of prompts with
the sentence and 5% without it.

The four scored runs in `benchmark_test/` were produced from a copy of the sheet
with this sentence already removed, but that copy was never committed and no
longer exists on disk. Stripping is exactly reversible, so this script both
cleans a workbook and reconstructs the file those runs actually used. Run with
`--verify-against` to prove the reconstruction byte-for-byte against the prompts
stored in a run record.

Only `final_prompt_text` and `final_prompt_text_ru` are touched, because they are
the only fields the benchmarked model ever sees. The rubric is left alone: it
goes to the judge, and there `source_scope` is a legitimate reference.

Russian phrasing varies across rows (twelve wordings of the same instruction), so
the sentence is located by the `source_scope` token and bounded by sentence
edges rather than matched literally.

Deterministic, with no model call. Usage:

  python strip_source_scope.py in.xlsx out.xlsx [--dry-run]
  python strip_source_scope.py in.xlsx out.xlsx --verify-against run.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sheet import load_rows, write_updates

PROMPT_COLS = ("final_prompt_text", "final_prompt_text_ru")

# Bounded by the sentence's own first character and its terminator. The leading
# `[^.\s]` matters: it keeps the whitespace *before* the sentence out of the
# match, so a paragraph break preceding it survives, while the trailing `\s*`
# removes the separator that would otherwise be left dangling.
SCOPE_RE = re.compile(r"[^.\s][^.]*`?source_scope`?[^.]*\.\s*")


def strip_scope(text: str) -> str:
    """Drop the source_scope sentence, leaving surrounding text untouched."""
    m = SCOPE_RE.search(text)
    if not m:
        return text
    return (text[: m.start()] + text[m.end() :]).strip()


def _key(task_id: str) -> str:
    """Normalise the two id schemes the runner has emitted over time.

    Older runs write `Core-batch1-task1-CORE-POL-01`, newer ones
    `Core-1-task1-CORE-POL-01` for the same task.
    """
    return str(task_id).replace("batch", "")


def verify(rows, run_path: Path) -> tuple[int, int, list[str], list[str]]:
    """Compare stripped prompts against the prompts a run actually sent."""
    sent: dict[str, str] = {}
    field = ""
    with open(run_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            sent[_key(rec.get("task_id"))] = str(rec.get("prompt") or "")
            field = str(rec.get("prompt_field_used") or field)

    matched = 0
    mismatched: list[str] = []
    absent: list[str] = []
    for row in rows:
        want = sent.get(_key(row.row_id))
        if want is None:
            absent.append(row.row_id)
            continue
        got = strip_scope(str(row.get(field, "")))
        if got.strip() == want.strip():
            matched += 1
        else:
            mismatched.append(row.row_id)
    return matched, len(sent), mismatched, absent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path, nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--verify-against",
        type=Path,
        action="append",
        default=[],
        help="run JSONL whose stored prompts the result must reproduce exactly",
    )
    args = ap.parse_args()

    _, rows = load_rows(args.source)
    updates: dict[int, dict[str, str]] = {}
    untouched: list[str] = []
    residual: list[str] = []

    for row in rows:
        fields = {}
        for col in PROMPT_COLS:
            before = str(row.get(col, ""))
            after = strip_scope(before)
            if after != before:
                fields[col] = after
            if "source_scope" in after:
                residual.append(f"{row.row_id}:{col}")
        if fields:
            updates[row.row_index] = fields
        else:
            untouched.append(row.row_id)

    print(f"rows:                {len(rows)}")
    print(f"prompts cleaned:     {len(updates)}")
    print(f"already clean:       {len(untouched)}")

    if residual:
        print(f"\nFAIL: source_scope still present in {len(residual)} cell(s):")
        for r in residual[:10]:
            print(f"  {r}")
        return 1

    ok = True
    for run in args.verify_against:
        matched, total, bad, absent = verify(rows, run)
        state = "OK" if not bad and matched == total else "MISMATCH"
        print(f"\nverify {run.name}: {matched}/{total} prompts reproduced exactly [{state}]")
        for r in bad[:10]:
            print(f"  mismatch: {r}")
        for r in absent[:5]:
            print(f"  not in run: {r}")
        if bad or matched != total:
            ok = False
    if not ok:
        return 1

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0
    if not args.dest:
        print("\nno destination given, nothing written")
        return 1

    write_updates(args.source, args.dest, updates)
    print(f"\nwrote -> {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
