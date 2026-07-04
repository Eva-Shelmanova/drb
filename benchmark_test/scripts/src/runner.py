"""Benchmark runner – runs tasks from final.xlsx against OpenRouter models."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.config import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_INPUT,
    DEFAULT_LIMIT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROMPT_FIELD,
    DEFAULT_RETRIES,
    DEFAULT_SHEET,
    get_api_key,
    get_model_config,
)
from src.loader import load_tasks
from src.models import Result, Task
from src.openrouter_client import OpenRouterClient
from src.pricing import estimate_cost
from src.utils import append_jsonl, ensure_dir, utc_timestamp_slug, write_csv, write_xlsx
from src.validators import validate_model_slug, validate_prompt, validate_response_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run benchmark tasks against OpenRouter models.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sheet", type=str, default=DEFAULT_SHEET)
    parser.add_argument("--domain", type=str, default=None, help="Optional domain filter.")
    parser.add_argument(
        "--model",
        dest="models",
        nargs="+",
        required=True,
        help="One or more OpenRouter model slugs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Max number of tasks to run (use 5-10 for pilots).",
    )
    parser.add_argument(
        "--prompt-field",
        type=str,
        default=DEFAULT_PROMPT_FIELD,
        choices=["final_prompt_text", "final_prompt_text_ru"],
        help="Prompt column sent to the model (default: final_prompt_text_ru).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--backoff-seconds", type=float, default=DEFAULT_BACKOFF_SECONDS)
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="HTTP timeout in seconds per API call (default: 600; use 600+ for deep-research models).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Override max_tokens for all models (default: use per-model config value).",
    )
    return parser.parse_args()


def _is_retryable_http(status_code: int | None) -> bool:
    if status_code is None:
        return True
    return status_code in (429, 500, 502, 503, 504)


def _failed_result(task: Task, error_message: str, status: str = "error") -> Result:
    return Result(
        task_id=task.task_id,
        domain=task.global_domain,
        task_type=task.task_type,
        prompt_field_used="",
        prompt="",
        response_text="",
        raw_response_json={},
        token_usage=None,
        estimated_cost=None,
        cost_status="unknown_no_usage",
        status=status,
        error_message=error_message,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )


def _execute_single(
    task: Task,
    model_slug: str,
    prompt_field: str,
    dry_run: bool,
    client: OpenRouterClient | None,
    retries: int,
    backoff_seconds: float,
    temperature: float,
    max_tokens: int,
    extra_body: dict | None = None,
) -> Result:
    try:
        prompt = validate_prompt(task, prompt_field)
    except ValueError as exc:
        return _failed_result(task, str(exc), status="error_prompt")

    if dry_run:
        return Result(
            task_id=task.task_id,
            domain=task.global_domain,
            task_type=task.task_type,
            prompt_field_used=prompt_field,
            prompt=prompt,
            response_text="[DRY RUN] OpenRouter call skipped.",
            raw_response_json={},
            token_usage=None,
            estimated_cost=None,
            cost_status="dry_run",
            status="dry_run",
            error_message=None,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )

    if client is None:
        return _failed_result(task, "Internal error: missing API client.")

    last_error: str = ""
    for attempt in range(retries + 1):
        try:
            response_text, raw_json, usage = client.chat_completion(
                model_slug=model_slug,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
            validate_response_text(response_text)
            estimated_cost, cost_status = estimate_cost(model_slug, usage)
            return Result(
                task_id=task.task_id,
                domain=task.global_domain,
                task_type=task.task_type,
                prompt_field_used=prompt_field,
                prompt=prompt,
                response_text=response_text,
                raw_response_json=raw_json,
                token_usage=usage,
                estimated_cost=estimated_cost,
                cost_status=cost_status,
                status="ok",
                error_message=None,
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
            )
        except requests.HTTPError as exc:
            status_code: int | None = None
            if exc.response is not None:
                status_code = exc.response.status_code
            last_error = f"HTTPError(status={status_code}): {exc}"
            if not _is_retryable_http(status_code) or attempt == retries:
                return _failed_result(task, last_error)
        except requests.RequestException as exc:
            last_error = f"RequestException: {exc}"
            if attempt == retries:
                return _failed_result(task, last_error)
        except ValueError as exc:
            last_error = str(exc)
            return _failed_result(task, last_error, status="error_truncated")

        time.sleep(backoff_seconds * (2 ** attempt))

    return _failed_result(task, last_error)


def _result_to_summary_row(result: Result) -> dict:
    d = result.to_dict()
    d.pop("raw_response_json", None)
    d.pop("prompt", None)
    d.pop("response_text", None)
    return d


def main() -> None:
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    args = parse_args()

    input_path: Path = args.input
    if not input_path.exists():
        print(f"Input workbook not found: {input_path}")
        sys.exit(1)

    api_key = get_api_key()
    if not api_key and not args.dry_run:
        print("OPENROUTER_API_KEY is required for non-dry-run execution.")
        sys.exit(1)

    tasks = load_tasks(input_path, sheet=args.sheet, domain=args.domain, limit=args.limit)
    if not tasks:
        print("No tasks matched the given filters.")
        sys.exit(1)

    run_id = utc_timestamp_slug()
    raw_dir = args.output_dir / "raw"
    ensure_dir(raw_dir)

    client: OpenRouterClient | None = None
    if not args.dry_run:
        client = OpenRouterClient(api_key=api_key, timeout_seconds=args.timeout)

    for model_slug in args.models:
        validate_model_slug(model_slug)
        model_cfg = get_model_config(model_slug)
        max_tokens = args.max_tokens if args.max_tokens is not None else model_cfg.max_tokens

        jsonl_path = raw_dir / f"run_{run_id}.jsonl"
        csv_path = raw_dir / f"run_{run_id}.csv"
        xlsx_path = raw_dir / f"run_{run_id}.xlsx"

        all_rows: list[dict] = []

        for i, task in enumerate(tasks, start=1):
            print(f"  [{i}/{len(tasks)}] {model_slug} | {task.task_id} ...", flush=True)
            result = _execute_single(
                task=task,
                model_slug=model_slug,
                prompt_field=args.prompt_field,
                dry_run=args.dry_run,
                client=client,
                retries=args.retries,
                backoff_seconds=args.backoff_seconds,
                temperature=model_cfg.temperature,
                max_tokens=max_tokens,
                extra_body=model_cfg.extra_body,
            )
            row = result.to_dict()
            row["model"] = model_slug
            row["run_id"] = run_id
            row["sheet_name"] = task.sheet_name
            row["task_number"] = task.task_number
            row["task_name"] = task.task_name
            row["global_domain"] = task.global_domain
            row["task_family"] = task.task_family
            row["task_type"] = task.task_type
            append_jsonl(jsonl_path, row)
            all_rows.append(row)

        write_csv(csv_path, all_rows)
        write_xlsx(xlsx_path, all_rows, sheet_name="results")

        print(f"Run finished. JSONL: {jsonl_path}")
        print(f"Run finished. CSV:   {csv_path}")
        print(f"Run finished. XLSX:  {xlsx_path}")


if __name__ == "__main__":
    main()
