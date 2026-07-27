"""Diff a hardened workbook against the original.

Confirms that only the intended columns changed, that no other row was
touched, and that the rubric cells stayed internally consistent (the
per-dimension columns must still match the recomposed fixed_criteria cell).

Usage:
  python verify_output.py out/final_hardened_<run>.xlsx [--show ROW_ID]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sheet import DIMENSIONS, load_rows, parse_en_trap, parse_ru_trap, rubric_bodies

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE.parent / "benchmark_extraction" / "final.xlsx"

ALLOWED = set()
for base in [
    "final_prompt_text",
    "internal_source_boundary",
    "common_failure_modes",
    "borderline_cases",
    "optional_distractors",
    "boundary_notes",
    "fixed_criteria_0_2_each",
] + DIMENSIONS:
    ALLOWED.add(base)
    ALLOWED.add(f"{base}_ru")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hardened", type=Path)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--show", default=None, help="print full before/after for this row_id")
    args = ap.parse_args()

    _, before = load_rows(args.input)
    _, after = load_rows(args.hardened)
    if len(before) != len(after):
        print(f"FAIL: row count changed {len(before)} -> {len(after)}")
        return 1

    col_changes: dict[str, int] = {}
    changed_rows = 0
    illegal: list[str] = []
    rubric_bad: list[str] = []

    for b, a in zip(before, after):
        if b.row_id != a.row_id:
            print(f"FAIL: row identity changed {b.row_id} -> {a.row_id}")
            return 1

        diffs = [c for c in b if b.get(c, "") != a.get(c, "")]
        if diffs:
            changed_rows += 1
        for c in diffs:
            col_changes[c] = col_changes.get(c, 0) + 1
            if c not in ALLOWED:
                illegal.append(f"{a.row_id}: {c}")

        if not diffs:
            continue

        # trap sentence must still parse, in both languages
        if not parse_en_trap(a["final_prompt_text"]):
            rubric_bad.append(f"{a.row_id}: EN trap no longer parses")
        if not parse_ru_trap(a["final_prompt_text_ru"]):
            rubric_bad.append(f"{a.row_id}: RU trap no longer parses")

        # The rubric must still split into five dimensions, and every dimension
        # we actually edited must agree with the recomposed fixed_criteria cell.
        # Dimensions we did not touch are skipped: the sheet already ships with
        # drift between the Russian per-dimension columns and the Russian
        # fixed_criteria cell, which is not this pipeline's doing.
        for suffix in ("", "_ru"):
            cell = a[f"fixed_criteria_0_2_each{suffix}"]
            try:
                bodies = rubric_bodies(cell)
            except ValueError as exc:
                rubric_bad.append(f"{a.row_id}: rubric{suffix} unparseable ({exc})")
                continue
            for dim in DIMENSIONS:
                col_name = f"{dim}{suffix}"
                if b.get(col_name, "") == a.get(col_name, ""):
                    continue
                col = a.get(col_name, "").strip()
                if col and " ".join(col.split()) != " ".join(bodies[dim].split()):
                    rubric_bad.append(f"{a.row_id}: {col_name} disagrees with fixed_criteria")

    print(f"rows in workbook:        {len(after)}")
    print(f"rows changed:            {changed_rows}")
    print(f"rows untouched:          {len(after) - changed_rows}")
    print("\ncolumns changed:")
    for c, n in sorted(col_changes.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = " " if c in ALLOWED else "  <-- UNEXPECTED"
        print(f"  {n:>4}  {c}{mark}")

    ok = True
    if illegal:
        ok = False
        print(f"\nFAIL: {len(illegal)} change(s) to columns outside the allowed set:")
        for i in illegal[:15]:
            print(f"  {i}")
    if rubric_bad:
        ok = False
        print(f"\nFAIL: {len(rubric_bad)} structural problem(s):")
        for i in rubric_bad[:15]:
            print(f"  {i}")

    if args.show:
        b = next((r for r in before if r.row_id == args.show), None)
        a = next((r for r in after if r.row_id == args.show), None)
        if not b or not a:
            print(f"\nrow_id {args.show!r} not found")
        else:
            print(f"\n{'=' * 76}\nBEFORE / AFTER for {args.show}\n{'=' * 76}")
            for c in b:
                if b.get(c, "") != a.get(c, ""):
                    print(f"\n--- {c} ---")
                    print(f"  BEFORE: {b.get(c, '')}")
                    print(f"  AFTER : {a.get(c, '')}")

    print("\nVERIFY OK" if ok else "\nVERIFY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
