"""
Retry specific failed benchmark tasks and merge results back into an existing run.

Usage:
    python retry_tasks.py --run-id 20260702T100736Z \
        --task-id Core-batch2-task3-CORE-POL-09 \
        --max-tokens 32000
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src import loader
from src.config import DEFAULT_INPUT_PATH, DEFAULT_PROMPT_FIELD, get_api_key
from src.openrouter_client import OpenRouterClient
from src.utils import write_csv, write_xlsx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", action="append", default=None)
    parser.add_argument("--model", default=None, help="Override model (default: use model from run file)")
    parser.add_argument("--prompt-field", default=DEFAULT_PROMPT_FIELD)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--max-tokens", type=int, default=32000)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10+ is required.", file=sys.stderr)
        return 2

    load_dotenv()
    args = parse_args()

    base_dir   = Path(__file__).resolve().parent
    jsonl_path = base_dir / "outputs" / "raw" / f"run_{args.run_id}.jsonl"
    csv_path   = base_dir / "outputs" / "raw" / f"run_{args.run_id}.csv"
    xlsx_path  = base_dir / "outputs" / "raw" / f"run_{args.run_id}.xlsx"

    for p in (jsonl_path, csv_path):
        if not p.exists():
            print(f"Missing run artifact: {p}", file=sys.stderr)
            return 2

    # Determine model from existing run if not specified
    with open(jsonl_path) as f:
        first = json.loads(f.readline())
    model_slug = args.model or first.get("model", "deepseek/deepseek-v4-pro")
    print(f"Model: {model_slug}")

    task_ids = set(args.task_id or [])
    if not task_ids:
        # Auto-detect error tasks from run file
        with open(jsonl_path) as f:
            for line in f:
                r = json.loads(line)
                if r.get("status") == "error":
                    task_ids.add(r["task_id"])
        print(f"Auto-detected {len(task_ids)} error tasks")

    api_key = get_api_key()
    if not api_key:
        print("OPENROUTER_API_KEY is required.", file=sys.stderr)
        return 2

    all_tasks = loader.load_tasks(input_path=args.input, sheet="Core")
    task_map  = {t.task_id: t for t in all_tasks}
    missing   = sorted(task_ids - set(task_map))
    if missing:
        print(f"Task IDs not found in workbook: {missing}", file=sys.stderr)
        return 2

    tasks  = [task_map[tid] for tid in sorted(task_ids)]
    client = OpenRouterClient(api_key=api_key, timeout_seconds=args.timeout)

    # Import here to avoid circular issues with sys.version_info patching
    from src.runner import _execute_single, _result_to_summary_row
    from src.config import get_model_config

    try:
        model_cfg = get_model_config(model_slug)
        extra_body = model_cfg.extra_body
    except ValueError:
        extra_body = None

    jsonl_replacements: dict[str, dict] = {}
    csv_replacements:   dict[str, dict] = {}

    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] Retrying {task.task_id} (max_tokens={args.max_tokens}) ...", flush=True)
        result = _execute_single(
            task=task,
            model_slug=model_slug,
            prompt_field=args.prompt_field,
            dry_run=False,
            client=client,
            retries=args.retries,
            backoff_seconds=2.0,
            temperature=0.2,
            max_tokens=args.max_tokens,
            extra_body=extra_body,
        )
        print(f"  -> status={result.status}", flush=True)
        if result.error_message:
            print(f"  -> error={result.error_message[:200]}", flush=True)
        if result.response_text:
            print(f"  -> response_len={len(result.response_text)}", flush=True)

        jsonl_replacements[task.task_id] = result.to_dict()
        csv_replacements[task.task_id]   = _result_to_summary_row(result)

    # Merge into existing files
    print("Merging into existing run files...")
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                rows.append(jsonl_replacements.get(r["task_id"], r))
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(csv_path, newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    merged_csv = [csv_replacements.get(r["task_id"], r) for r in csv_rows]
    write_csv(csv_path, merged_csv)
    write_xlsx(xlsx_path, merged_csv)

    ok  = sum(1 for tid in task_ids if jsonl_replacements[tid]["status"] == "ok")
    err = len(task_ids) - ok
    print(f"Done. ok={ok} error={err}")
    print(f"Updated: {jsonl_path}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
