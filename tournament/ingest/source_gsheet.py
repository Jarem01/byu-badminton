"""Fetch a Google Sheet published as CSV (File -> Share -> Publish to web -> CSV).

Uses stdlib urllib with default TLS certificate validation (never disabled).
No credentials or third-party libraries required.
"""

from __future__ import annotations

import ssl
import urllib.request

from .source_csv import read_rows_from_text


def fetch_rows(url: str, timeout: float = 20.0):
    """Return (headers, rows) from a published-CSV URL."""
    context = ssl.create_default_context()  # validation ON by design
    req = urllib.request.Request(url, headers={"User-Agent": "badminton-tournament"})
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        text = resp.read().decode(charset, errors="replace")
    return read_rows_from_text(text)
