#!/usr/bin/env python3
"""Extract raw text from Set source files under set/, one .txt per downloaded file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from extract_raw_sources import (
    EXTRACTORS,
    extract_text,
    setup_logging,
    sha256_bytes,
    sha256_text,
)

SET_ID_PATTERN = re.compile(r"^(SET\d{3})_", re.I)
SUPPORTED_EXTENSIONS = {".pdf", ".html", ".htm"}
SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass
class FileRecord:
    source_id: str
    output_stem: str
    path: Path
    rel_path: str
    extension: str
    file_size: int
    file_sha256: str
    status: str
    error: str = ""
    text: str = ""
    text_length: int = 0
    text_sha256: str = ""
    duplicate_file_group: str = ""
    source_has_multiple_files: bool = False


def parse_set_id(filename: str) -> str | None:
    match = SET_ID_PATTERN.match(filename)
    return match.group(1).upper() if match else None


def output_stem_from_filename(filename: str) -> str:
    """SET009_foo bar.htm -> SET009_foo_bar"""
    stem = Path(filename).stem
    sid = parse_set_id(filename)
    if not sid:
        return SLUG_RE.sub("_", stem).strip("_")
    rest = stem[len(sid) + 1 :] if stem.upper().startswith(sid + "_") else stem
    slug = SLUG_RE.sub("_", rest).strip("_")
    return f"{sid}_{slug}" if slug else sid


def discover_files(set_dir: Path, logger: logging.Logger) -> list[Path]:
    found: list[Path] = []
    skipped = 0
    for path in sorted(set_dir.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        if parse_set_id(path.name) is None:
            skipped += 1
            logger.debug("skip (name does not match SET###_): %s", path)
            continue
        found.append(path)
    logger.info(
        "discovered %d Set source files (skipped %d bad names)",
        len(found),
        skipped,
    )
    return found


def process_file(path: Path, set_dir: Path, logger: logging.Logger) -> FileRecord:
    source_id = parse_set_id(path.name) or "UNKNOWN"
    output_stem = output_stem_from_filename(path.name)
    rel_path = str(path.relative_to(set_dir.parent))
    ext = path.suffix.lower()

    try:
        raw_bytes = path.read_bytes()
        file_sha = sha256_bytes(raw_bytes)
        file_size = len(raw_bytes)
    except Exception as exc:
        logger.error("failed to read file %s: %s", path, exc)
        return FileRecord(
            source_id=source_id,
            output_stem=output_stem,
            path=path,
            rel_path=rel_path,
            extension=ext.lstrip("."),
            file_size=0,
            file_sha256="",
            status="failed",
            error=f"read error: {exc}",
        )

    try:
        text = extract_text(path, ext).strip()
        text_len = len(text)
        text_sha = sha256_text(text) if text_len else ""
        if text_len == 0:
            logger.warning("empty text extracted from %s", path)
        return FileRecord(
            source_id=source_id,
            output_stem=output_stem,
            path=path,
            rel_path=rel_path,
            extension=ext.lstrip("."),
            file_size=file_size,
            file_sha256=file_sha,
            status="ok",
            text=text,
            text_length=text_len,
            text_sha256=text_sha,
        )
    except Exception as exc:
        logger.error("extraction failed for %s: %s", path, exc, exc_info=True)
        return FileRecord(
            source_id=source_id,
            output_stem=output_stem,
            path=path,
            rel_path=rel_path,
            extension=ext.lstrip("."),
            file_size=file_size,
            file_sha256=file_sha,
            status="failed",
            error=str(exc),
        )


def mark_duplicates(records: list[FileRecord], logger: logging.Logger) -> None:
    by_file_hash: dict[str, list[FileRecord]] = defaultdict(list)
    by_source: dict[str, list[FileRecord]] = defaultdict(list)

    for rec in records:
        if rec.file_sha256:
            by_file_hash[rec.file_sha256].append(rec)
        by_source[rec.source_id].append(rec)

    for sha, group in by_file_hash.items():
        if len(group) < 2:
            continue
        group_id = f"file_sha256:{sha[:16]}"
        paths = [r.rel_path for r in group]
        logger.warning("duplicate file bytes (%d files): %s", len(group), paths)
        for rec in group:
            rec.duplicate_file_group = group_id

    for sid, group in sorted(by_source.items()):
        if len(group) > 1:
            for rec in group:
                rec.source_has_multiple_files = True
            logger.info("source_id %s has %d files", sid, len(group))


def write_raw_text_files(
    records: list[FileRecord],
    raw_text_dir: Path,
    logger: logging.Logger,
) -> int:
    written = 0
    for rec in sorted(records, key=lambda r: r.output_stem):
        if rec.status != "ok":
            continue
        header = f"===== FILE: {rec.rel_path} =====\n"
        out_path = raw_text_dir / f"{rec.output_stem}.txt"
        out_path.write_text(header + rec.text + "\n", encoding="utf-8")
        written += 1
        logger.debug("wrote %s (%d chars)", out_path.name, len(rec.text))
    logger.info("wrote %d raw_text_set files to %s", written, raw_text_dir)
    return written


def write_index_csv(records: list[FileRecord], index_path: Path) -> None:
    fieldnames = [
        "source_id",
        "output_stem",
        "file_path",
        "file_name",
        "format",
        "status",
        "error_message",
        "file_size_bytes",
        "file_sha256",
        "text_length",
        "text_sha256",
        "duplicate_file_group",
        "source_has_multiple_files",
        "raw_text_output",
        "processed_at_utc",
    ]
    timestamp = datetime.now(timezone.utc).isoformat()

    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in sorted(records, key=lambda r: (r.source_id, r.output_stem)):
            raw_out = (
                f"raw_text_set/{rec.output_stem}.txt" if rec.status == "ok" else ""
            )
            writer.writerow(
                {
                    "source_id": rec.source_id,
                    "output_stem": rec.output_stem,
                    "file_path": rec.rel_path,
                    "file_name": rec.path.name,
                    "format": rec.extension,
                    "status": rec.status,
                    "error_message": rec.error,
                    "file_size_bytes": rec.file_size,
                    "file_sha256": rec.file_sha256,
                    "text_length": rec.text_length,
                    "text_sha256": rec.text_sha256,
                    "duplicate_file_group": rec.duplicate_file_group,
                    "source_has_multiple_files": rec.source_has_multiple_files,
                    "raw_text_output": raw_out,
                    "processed_at_utc": timestamp,
                }
            )


def run(set_dir: Path, output_dir: Path) -> int:
    set_dir = set_dir.resolve()
    output_dir = output_dir.resolve()
    raw_text_dir = output_dir / "raw_text_set"
    raw_text_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "set_extraction.log"
    index_path = output_dir / "raw_set_sources_index.csv"
    logger = setup_logging(log_path)

    logger.info("set_dir=%s output_dir=%s", set_dir, output_dir)

    if not set_dir.is_dir():
        logger.error("set directory does not exist: %s", set_dir)
        return 1

    paths = discover_files(set_dir, logger)
    if not paths:
        logger.error("no matching Set source files found under %s", set_dir)
        write_index_csv([], index_path)
        return 1

    records = [process_file(path, set_dir, logger) for path in paths]
    mark_duplicates(records, logger)
    write_raw_text_files(records, raw_text_dir, logger)
    write_index_csv(records, index_path)

    ok = sum(1 for r in records if r.status == "ok")
    failed = sum(1 for r in records if r.status == "failed")
    set_ids = len({r.source_id for r in records})

    logger.info(
        "done: %d files, %d ok, %d failed, %d SET IDs",
        len(records),
        ok,
        failed,
        set_ids,
    )
    logger.info("index: %s", index_path)
    return 0 if failed == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--set-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "set",
        help="Folder containing SET###_* source files (default: ./set)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory for raw_text_set/, index CSV, and log (default: project root)",
    )
    args = parser.parse_args()
    sys.exit(run(args.set_dir, args.output_dir))


if __name__ == "__main__":
    main()
