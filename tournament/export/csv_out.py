"""CSV rendering helpers (stdlib csv). Pure functions over plain rows so they
are trivial to unit-test and reuse."""

from __future__ import annotations

import csv
import io


def rows_to_csv(headers: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
