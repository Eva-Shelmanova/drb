# DeepResearch Benchmark

This repository contains the Deep Research Benchmark (DRB) — a structured evaluation of LLM deep research capabilities across multiple domains.

## Repository Structure

```
├── benchmark_extraction/      Original benchmark construction files
│   ├── README_benchmark_extruction.md
│   ├── final.xlsx             161-task benchmark task set (v1, scored below)
│   ├── final_v2_hardened.xlsx 161-task set with sharpened boundary distinctions
│   ├── PROMPT_AND_RUBRIC_CRITERIA.md
│   ├── Benchmark Plan.pdf
│   └── *.py                   Source extraction / normalization scripts
│
├── task_update/               Pipeline that produced final_v2_hardened.xlsx
│   ├── edit_tasks.py          LLM-as-editor orchestrator
│   ├── sheet.py               Prompt / rubric parsing and splicing
│   ├── validate.py            Validation gates (gold leaks, difficulty, giveaways)
│   ├── neutralise_prompts.py  Strips the "trap" label from prompts
│   ├── verify_output.py       Diffs a produced workbook against the original
│   └── out/                   Run logs, reports, manual-authoring notes
│
└── benchmark_test/            Model benchmark results
    ├── cross_model_analysis/  Refusal analysis & response-type breakdown plots
    ├── perplexity_sonar-deep-research/  Partial runs (API issues)
    ├── perplexity_sonar-pro-search/     Full scored run
    ├── deepseek_deepseek-v4-pro/        Full scored run
    ├── claude_opus-4.8/                 Full scored run
    └── openai_gpt-5.5/                  Full scored run
        ├── plots/    Score-by-domain & distribution plots
        ├── runs/     Raw JSONL / CSV model outputs
        ├── reports/  Markdown summary reports
        └── scores/   Per-task scored JSONL / CSV
```

## Models Evaluated

| Section | Model slug | Tasks |
|---------|-----------|-------|
| perplexity_sonar-deep-research | perplexity/sonar-deep-research | partial (API timeouts) |
| perplexity_sonar-pro-search | perplexity/sonar-pro-search | 161 |
| deepseek_deepseek-v4-pro | deepseek/deepseek-v4-pro | 161 |
| claude_opus-4.8 | anthropic/claude-opus-4.8 | 161 |
| openai_gpt-5.5 | openai/gpt-5.5 | 161 |

All scores above were produced against `final.xlsx` (v1). That file is left
unchanged so those runs stay reproducible.

## Task set versions

`final_v2_hardened.xlsx` is the same 161 tasks with a harder boundary condition.
Two changes distinguish it from v1:

- **One extra distinction per task.** 159 of 161 tasks gained a source-supported
  confusion the answer must resolve, such as nominal vs PPP or city proper vs
  metro area. The rubric dimension that scores it was updated in step, in both
  English and Russian. The 2 tasks whose sources exhaust their distinctions are
  documented in `task_update/out/NEEDS_MANUAL_AUTHORING.md`.
- **No label on the boundary sentence.** v1 prompts introduced the confusion with
  `Methodological trap:`, which tells the model under test that the question
  contains a trick. All 161 v2 prompts state the distinctions flatly instead
  (`Distinguish X from Y.`), in both languages.

`task_update/README.md` covers how the edits were made and validated.
