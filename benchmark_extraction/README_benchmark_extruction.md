# DeepResearch Benchmark Final Package

This repository contains the final benchmark package built from Core and Set source text extraction, source normalization, and manual prompt/rubric construction.

## Final Artifact

- `final.xlsx` - final two-sheet benchmark table:
  - `Core`: Core tasks with English and Russian prompt/rubric columns.
  - `Set`: Set tasks with English and Russian prompt/gold-set columns.

## Criteria And Plan

- `Benchmark Plan.pdf` - full benchmark design document.
- `PROMPT_AND_RUBRIC_CRITERIA.md` - concise Markdown criteria for generating prompts, Core rubrics, and Set gold sets.

## Included Scripts

- `extract_raw_sources.py` - extract text from Core source documents.
- `extract_raw_set_sources.py` - extract raw Set source material.
- `extract_set_sources.py` - build Set source extraction artifacts.
- `normalize_sources.py` - normalize extracted Core/Set source text.
- `build_clean_source_corpus.py` - build the clean source corpus used downstream.

## Not Included

Raw source folders, extracted text folders, batch draft files, intermediate workbooks, logs, and local archives are excluded from the repository.
