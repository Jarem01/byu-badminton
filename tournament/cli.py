"""Command-line entry point.

    python -m tournament.cli serve   [--port 8765] [--data data/tournament.json]
    python -m tournament.cli import  --file roster.csv [--schema legacy] [--commit]
    python -m tournament.cli validate [--data data/tournament.json]
"""

from __future__ import annotations

import argparse
import os
import sys

from .config import resolve_port
from .ingest.importer import build_tournament
from .ingest.source_csv import read_rows
from .ingest.source_gsheet import fetch_rows
from .store.repository import Repository
from .validate.dashboard import validate

_DEFAULT_DATA = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "tournament.json"))


def _print_report(report) -> None:
    counts = report.counts()
    print(f"  errors={counts['error']}  warnings={counts['warning']}  "
          f"info={counts['info']}")
    for i in report.issues:
        print(f"  [{i.severity:7}] {i.code}: {i.message}")


def cmd_import(args) -> int:
    if args.url:
        headers, rows = fetch_rows(args.url)
    else:
        headers, rows = read_rows(args.file)
    result = build_tournament(headers, rows, schema=args.schema)
    report = validate(result.tournament, extra=result.issues)
    print(f"Adapter: {result.adapter}   Stats: {result.stats}")
    _print_report(report)
    if args.commit:
        repo = Repository(args.data)
        repo.save(result.tournament, backup=True)
        print(f"Committed to {args.data}")
    else:
        print("(preview only; pass --commit to save)")
    return 0 if report.ok else 1


def cmd_validate(args) -> int:
    repo = Repository(args.data)
    if not repo.exists():
        print(f"No tournament at {args.data}")
        return 1
    report = validate(repo.load())
    _print_report(report)
    return 0 if report.ok else 1


def cmd_serve(args) -> int:
    from .server.app import serve  # imported lazily so import/validate stay light
    serve(args.data, resolve_port(args.port), actor=args.actor)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tournament")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="import a roster CSV / published sheet")
    pi.add_argument("--file")
    pi.add_argument("--url")
    pi.add_argument("--schema", default="auto",
                    choices=["auto", "legacy", "strict"])
    pi.add_argument("--data", default=_DEFAULT_DATA)
    pi.add_argument("--commit", action="store_true")
    pi.set_defaults(func=cmd_import)

    pv = sub.add_parser("validate", help="validate the saved tournament")
    pv.add_argument("--data", default=_DEFAULT_DATA)
    pv.set_defaults(func=cmd_validate)

    ps = sub.add_parser("serve", help="run the local admin + public server")
    ps.add_argument("--port", type=int, default=None)
    ps.add_argument("--data", default=_DEFAULT_DATA)
    ps.add_argument("--actor", default="admin")
    ps.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
