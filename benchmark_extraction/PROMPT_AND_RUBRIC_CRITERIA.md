# Prompt And Rubric Criteria

This file summarizes the criteria used in the final benchmark construction workflow.

## Prompt Generation Criteria

Core prompts must:

- Use one research object and one methodology-sensitive answer target.
- Require multi-source comparison rather than single-fact lookup.
- Anchor the answer in the official primary source.
- Use corroborating sources only to check revisions, naming, boundary conflicts, later summaries, or source comparability.
- Include a clear methodological trap about definitions, dates, reporting scope, update status, source comparability, or measurement boundaries.
- Require the answer format: conclusion, source comparison, caveat, and confidence level.
- Avoid broad list retrieval or essays unrelated to the named research object.

Set prompts must:

- Use one explicit candidate item.
- Use one bounded answer target for that candidate.
- Include a real boundary condition, such as measure definition, table year, source version, row scope, or exclusion rule.
- Avoid asking for a whole-list retrieval task.
- Support precision, recall, and F1 scoring against a bounded gold set.

## Core Rubric Criteria

Each Core task uses five fixed criteria scored on a 0-2 scale, for 10 total points:

1. Coverage
2. Accuracy
3. Reasoning
4. Use of evidence
5. Clarity and structure

For each Core task, the rubric must include:

- `rubric_id`
- `task_type: Core`
- `research_object`
- `answer_unit`
- 5-10 key facts from the source bundle
- expected response sections
- positive and negative scoring examples for each fixed criterion
- common failure modes
- borderline cases

## Set Gold-Set Criteria

Each Set task uses a gold set rather than a narrative rubric.

Each gold set must include:

- `gold_set_id`
- `task_type: Set`
- `research_object`
- `candidate_item`
- `answer_unit`
- correct items
- acceptable variants
- optional distractors
- explicit exclusion rules
- boundary notes

Set evaluation uses precision, recall, and F1. The gold set must therefore be exhaustive or bounded clearly enough to support stable scoring.
