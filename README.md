# DeepResearch Benchmark

This repository contains the Deep Research Benchmark (DRB) — a structured evaluation of LLM deep research capabilities across multiple domains.

## Repository Structure

```
├── benchmark_extraction/      Original benchmark construction files
│   ├── README_benchmark_extruction.md
│   ├── final.xlsx             161-task benchmark task set
│   ├── PROMPT_AND_RUBRIC_CRITERIA.md
│   ├── Benchmark Plan.pdf
│   └── *.py                   Source extraction / normalization scripts
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
