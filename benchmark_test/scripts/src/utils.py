from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import openpyxl


def utc_timestamp_slug() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows_list = list(rows)
    if not rows_list:
        return
    fieldnames = list(rows_list[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_list)


def write_xlsx(path: Path, rows: Iterable[dict[str, Any]], sheet_name: str = "results") -> None:
    rows_list = list(rows)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name

    if rows_list:
        headers = list(rows_list[0].keys())
        worksheet.append(headers)
        for row in rows_list:
            worksheet.append([row.get(column, "") for column in headers])

    workbook.save(path)
    workbook.close()

