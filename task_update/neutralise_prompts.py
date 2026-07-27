"""Remove the trap label from the prompts sent to the model under test.

The sheet ships every Core prompt with a labelled boundary sentence:

    Methodological trap: distinguish legal establishment, ... begin operations.

Naming the trap is itself a hint. It tells the model that the question contains
a deliberate confusion, which is exactly what the task is supposed to test. This
script rewrites the sentence to state the distinctions flatly:

    Distinguish legal establishment, ... begin operations.

Only `final_prompt_text` and `final_prompt_text_ru` are touched, because they
are the only fields the benchmarked model ever sees. The rubric keeps its
wording: it goes to the judge, not to the model.

The transformation is deterministic, with no model call. Usage:

  python neutralise_prompts.py in.xlsx out.xlsx [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sheet import (
    load_rows,
    neutralise_en,
    neutralise_ru,
    parse_en_trap,
    parse_ru_trap,
    splice_trap,
    write_updates,
)

GIVEAWAY_EN = ("trap", "trick", "pitfall", "beware")
GIVEAWAY_RU = ("ловушк", "подвох")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path, nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _, rows = load_rows(args.source)
    updates: dict[int, dict[str, str]] = {}
    unparsed: list[str] = []
    already: list[str] = []
    residual: list[str] = []

    for row in rows:
        en = parse_en_trap(row["final_prompt_text"])
        ru = parse_ru_trap(row["final_prompt_text_ru"])
        if not en or not ru:
            unparsed.append(row.row_id)
            continue

        en_sentence, _ = en
        ru_sentence, _ = ru
        en_new = neutralise_en(en_sentence)
        ru_new = neutralise_ru(ru_sentence)

        if en_new == en_sentence and ru_new == ru_sentence:
            already.append(row.row_id)
            continue

        fields = {}
        if en_new != en_sentence:
            fields["final_prompt_text"] = splice_trap(
                row["final_prompt_text"], en_sentence, en_new
            )
        if ru_new != ru_sentence:
            fields["final_prompt_text_ru"] = splice_trap(
                row["final_prompt_text_ru"], ru_sentence, ru_new
            )

        # nothing that hints at a trick may survive in either prompt
        for col, text in fields.items():
            low = text.lower()
            words = GIVEAWAY_RU if col.endswith("_ru") else GIVEAWAY_EN
            if any(w in low for w in words):
                residual.append(f"{row.row_id}:{col}")
        updates[row.row_index] = fields

    print(f"rows:                    {len(rows)}")
    print(f"labels removed:          {len(updates)}")
    print(f"already neutral:         {len(already)}")
    print(f"boundary sentence n/a:   {len(unparsed)}")
    if unparsed:
        for r in unparsed[:10]:
            print(f"  unparsed: {r}")
    if residual:
        print(f"\nFAIL: giveaway wording still present in {len(residual)} cell(s):")
        for r in residual[:10]:
            print(f"  {r}")
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
