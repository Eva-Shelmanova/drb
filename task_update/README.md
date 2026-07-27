# Core task hardening

Adds exactly one new boundary distinction to each of the 161 Core tasks in
`benchmark_extraction/final.xlsx`, using `deepseek/deepseek-v4-flash` via
OpenRouter. Output goes to a new workbook; the source file is never modified.

## Why it works the way it does

Four facts about the existing sheet shaped the design.

**Every task already has a trap.** All 161 Core prompts contain exactly one
`Methodological trap:` sentence (and all 17 Set prompts a `Boundary trap:`
one). So "add a trap" cannot mean "append a second trap" without breaking the
one-trap-per-task rule. It means *extend the existing trap by one distinction*.
The pipeline passes the existing trap body and its distinction count to the
model and rejects any replacement that enumerates fewer distinctions, which is
the failure mode a naive prompt produces: asked to add one trap, the model
happily replaces a four-way distinction with a one-way distinction and reports
that the task got harder.

**The benchmark runs on Russian.** `src/config.py` sets
`DEFAULT_PROMPT_FIELD = "final_prompt_text_ru"`, and all five scored runs used
it. Editing only the English column would have no measurable effect, so every
edit gets a second pass that produces the `_ru` twin.

**Only the rubric is scored.** `score_and_report.py` hands the judge the prompt,
the response, and `fixed_criteria_0_2_each` — nothing else. A harder prompt
graded against an unchanged rubric measures nothing, so the editor also updates
the rubric bodies, and `fixed_criteria_0_2_each` is recomposed from them.

**Naming the trap is itself a hint.** The sheet shipped every prompt with a
labelled boundary sentence — `Methodological trap: distinguish ...` — which tells
the model under test that the question contains a deliberate confusion. That
gives away the very thing being measured. `neutralise_prompts.py` rewrites the
sentence to state the distinctions flatly (`Distinguish ...`), and the validator
now rejects any edit whose sentence contains "trap", "trick", "pitfall",
"beware", "careful" or "caution", or the Russian equivalents. Only the two prompt
columns are neutralised; the rubric keeps its wording because it goes to the
judge, not to the model.

**The model cannot be trusted to police itself.** In an early trial it listed
the gold answer (`1 January 2026`) as a distractor and set
`needs_human_review: false`. Distractors are therefore checked against the
bolded gold values in `accuracy` and `key_facts_from_source_bundle`, and the
model's own flag is advisory only.

## Design

The model never rewrites the prompt. It returns a replacement trap sentence and
new list items; `edit_tasks.py` splices them in. The research object, answer
unit, `source_scope` instruction and `Return:` clause are therefore preserved
structurally rather than by instruction.

Curated fields are appended to, never replaced: `common_failure_modes`,
`borderline_cases` and `internal_source_boundary` keep everything they had.
`optional_distractors` and `boundary_notes` are empty on Core today and get
populated. Rubric dimensions the model returns unchanged are dropped before the
translation pass so the Russian text is not reworded gratuitously.

## Files

| file | role |
|---|---|
| `edit_tasks.py` | CLI orchestrator; two passes per row, then write-back |
| `prompts.py` | editor and translator system prompts, context assembly |
| `validate.py` | reject / flag rules applied before anything is written |
| `sheet.py` | trap parsing, rubric parse+compose, workbook write-back |
| `verify_output.py` | diffs a produced workbook against the original |

## Usage

Requires `OPENROUTER_API_KEY`, plus `openpyxl` and `requests`.

```bash
# structural checks over every row, no API calls
python edit_tasks.py --dry-run

# pilot
python edit_tasks.py --limit 10

# full run
python edit_tasks.py --workers 8

# repair pass: reprocess the rows that were rejected or errored, on top of the
# workbook the previous pass produced, so accepted edits accumulate
python edit_tasks.py \
  --input out/final_hardened_<run>.xlsx \
  --retry-from out/edits_<run>.jsonl \
  --workers 8

# confirm only intended cells moved
python verify_output.py out/final_hardened_<run>.xlsx --show Core-batch1-task1-CORE-POL-01
```

Strip the trap label from the prompts that reach the model under test. This is
deterministic, with no model call, and applies to all 161 rows:

```bash
python neutralise_prompts.py in.xlsx out.xlsx --dry-run
python neutralise_prompts.py in.xlsx out.xlsx
```

Repair passes pay off for several rounds, but with sharply diminishing returns.
The first full run wrote 99 of 161 rows; retrying the 62 failures recovered 44,
a third pass over the remaining 18 recovered 8, and two further passes over the
last 10 recovered 8 more. Final state: **159 of 161 hardened, all 161
neutralised**, for about $0.31 total. The authoritative workbook is
`out/final_hardened_20260727T105202Z.xlsx`, published as
`../benchmark_extraction/final_v2_hardened.xlsx`. `final.xlsx` is never written
to; the scored runs in `benchmark_test/` still correspond to it.

Two things made the late passes work, and both are worth keeping. `--retry-from`
feeds each row its own prior rejection reasons back into the prompt, which stops
the model re-proposing a distinction it has already had rejected. And the model
may decline a row by returning `{"cannot_harden": true, "reason": ...}`, recorded
as status `declined`; a row whose distinctions the source has genuinely exhausted
is better left alone than padded with a recombination of words already in the
sentence.

The distractor rule that unblocked the last recoverable rows: an empty
`optional_distractors` list is always accepted. Where the gold answer is a
country list or a pair of rounded figures, every plausible wrong option restates
it, so the distinction is kept and the distractors are dropped.

The 2 rows that survive every pass are listed in
`out/NEEDS_MANUAL_AUTHORING.md` and should be authored by hand rather than
retried again.

Artifacts land in `out/`: `edits_<run>.jsonl` (every model response and every
validator issue), `report_<run>.md` (summary, trap types, all flags and
rejects), and `final_hardened_<run>.xlsx`.

Run `--dry-run` after any change to `sheet.py`. It asserts that
`compose_rubric(cell, {}) == cell` for all 322 rubric cells, which is what
stops a parser change from silently corrupting them.

## Validation rules

Rejected, and not written:

- trap sentence missing, malformed, multi-line, or not starting `Boundary trap: distinguish `
- more or fewer than one occurrence of the word "trap"
- fewer distinctions than the original sentence had
- `new_trap_dimension` adds nothing that was not already in the original trap
- a distractor contains a bolded gold value
- `boundary_notes` does not start with `Exclude answers that`
- a rubric body that does not have exactly three levels (`- 2:`, `- 1:`, `- 0:`)
- the accuracy rubric's bolded gold value changed
- Russian output missing, or its list lengths disagree with the English

Flagged, written but needing review:

- distinction count unchanged (a distinction may have been merged)
- distractor shares a significant number with the gold value
- no bolded gold value on the row, so distractors are not machine-verifiable
- numbers present in English but absent from Russian
- the model set `needs_human_review`

## Known limits

- 34 of 161 rows have no bolded gold value; their distractors are always flagged
  for human review.
- The Set sheet (17 rows) is out of scope. It has never been run or scored, has
  no `key_facts_from_source_bundle`, and uses a different field set.
- The sheet already ships with drift between the Russian per-dimension rubric
  columns and `fixed_criteria_0_2_each_ru`. This pipeline keeps the dimensions
  it edits consistent and leaves the rest alone.
- Scores from a hardened workbook are not comparable with the four existing
  scored runs; the prompts and rubrics both change.
