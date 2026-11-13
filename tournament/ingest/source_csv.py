"""Read raw rows from a local CSV file (stdlib csv)."""

from __future__ import annotations

import csv


def read_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) where each row is a dict keyed by header."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return headers, rows


def read_rows_from_text(text: str) -> tuple[list[str], list[dict[str, str]]]:
    import io
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows
