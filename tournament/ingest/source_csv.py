"""Read raw rows from a local CSV file (stdlib csv).

Headers are normalised to be **unique**. Real Google-Form exports repeat whole
question blocks -- the fall-2026 form asks for the MD/WD partner's name and then
asks again for the XD partner's name under the exact same question text -- and
``csv.DictReader`` silently keeps only the last value of a duplicated column,
which loses every MD/WD partner. Repeated headers become ``"<name> (2)"``,
``"<name> (3)"``, ... so a lookup can address each one by position.
"""

from __future__ import annotations

import csv
import io


def _unique_headers(headers: list[str]) -> list[str]:
    """Make duplicate header names unique, preserving their order."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for header in headers:
        n = seen.get(header, 0) + 1
        seen[header] = n
        out.append(header if n == 1 else f"{header} ({n})")
    return out


def _parse(text: str) -> tuple[list[str], list[dict[str, str]]]:
    raw = list(csv.reader(io.StringIO(text)))
    if not raw:
        return [], []
    headers = _unique_headers(raw[0])
    rows: list[dict[str, str]] = []
    for r in raw[1:]:
        if not any((cell or "").strip() for cell in r):
            continue                      # skip blank lines entirely
        rows.append({h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)})
    return headers, rows


def read_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) where each row is a dict keyed by header."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return _parse(fh.read())


def read_rows_from_text(text: str) -> tuple[list[str], list[dict[str, str]]]:
    return _parse(text)
