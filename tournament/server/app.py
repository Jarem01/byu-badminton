"""Local JSON API + static file server (stdlib http.server).

Thin transport layer: parse the request, call one ``TournamentService`` method,
return JSON. All tournament logic lives in the engine; nothing here computes
results. Default port 8765 (configurable) since 5000/5001 are in use elsewhere.
"""

from __future__ import annotations

import json
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..config import resolve_port
from ..store.repository import Repository
from .service import Conflict, TournamentService

WEB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))
_MIME = {".html": "text/html; charset=utf-8", ".css": "text/css",
         ".js": "text/javascript", ".png": "image/png", ".ico": "image/x-icon",
         ".json": "application/json", ".svg": "image/svg+xml",
         ".woff2": "font/woff2", ".woff": "font/woff"}


class Handler(BaseHTTPRequestHandler):
    service: TournamentService  # injected on the server instance

    # --- plumbing -----------------------------------------------------------
    def log_message(self, *args):  # quieter console
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        """Parse the JSON request body.

        Handles both Content-Length and chunked bodies. A reverse proxy or an
        HTTP/2 -> HTTP/1.1 bridge can forward a POST without Content-Length, and
        treating that as an empty body made every action fail with a confusing
        "No such file or directory: ''".
        """
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raw = self._read_chunked()
        else:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _read_chunked(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            line = self.rfile.readline(65536).strip()
            if not line:
                break
            try:
                size = int(line.split(b";")[0], 16)
            except ValueError:
                break
            if size == 0:
                self.rfile.readline(65536)      # CRLF after the last chunk
                break
            chunks.append(self.rfile.read(size))
            self.rfile.read(2)                  # CRLF ending this chunk
        return b"".join(chunks)

    def _static(self, url_path: str):
        if url_path in ("/", ""):
            url_path = "/admin.html"
        elif url_path == "/public":
            url_path = "/public.html"
        rel = posixpath.normpath(url_path).lstrip("/")
        target = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not target.startswith(WEB_DIR) or not os.path.isfile(target):
            self._json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- routing ------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path, q = parsed.path, parse_qs(parsed.query)
        svc = self.service
        try:
            if not path.startswith("/api/"):
                return self._static(path)
            if path == "/api/health":
                return self._json({"ok": True})
            if path == "/api/mode":
                return self._json({"mode": svc.t.mode})
            if path == "/api/players":
                return self._json({"players": svc.players()})
            if path == "/api/pairs":
                return self._json(svc.pairs_view())
            if path == "/api/partnerships":
                return self._json(svc.partnerships_view())
            if path == "/api/divisions":
                return self._json({"divisions": svc.divisions()})
            if path == "/api/validation":
                return self._json(svc.validation())
            if path == "/api/bracket":
                return self._json(svc.bracket_view(q["division"][0]))
            if path == "/api/seed/preview":
                return self._json(svc.seed_preview(
                    q["division"][0], q.get("method", ["ranking"])[0],
                    int(q["rng_seed"][0]) if q.get("rng_seed") else None))
            if path == "/api/public":
                return self._json(svc.public_snapshot())
            if path == "/api/board":
                return self._json(svc.board_view())
            if path == "/api/schedule":
                return self._json(svc.schedule_view())
            if path == "/api/best-dates":
                return self._json(svc.best_dates())
            if path == "/api/settings":
                return self._json(svc.get_settings())
            if path == "/api/export/csv":
                fname, text = svc.export_csv(q.get("what", ["roster"])[0])
                body = ("﻿" + text).encode("utf-8")  # BOM for Excel
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._json({"error": "unknown endpoint"}, 404)
        except KeyError as e:
            return self._json({"error": f"missing parameter {e}"}, 400)
        except Exception as e:  # noqa: BLE001 - surface as JSON, never 500-crash
            return self._json({"error": str(e)}, 400)

    def do_POST(self):
        path = urlparse(self.path).path
        svc = self.service
        body = self._read_body()
        try:
            if path == "/api/import":
                return self._json(svc.import_preview(
                    body.get("source", "file"), body.get("ref", ""),
                    body.get("schema", "auto")))
            if path == "/api/import/commit":
                return self._json(svc.import_commit())
            if path == "/api/override":
                return self._json(svc.override(
                    body["target"], body["field"], str(body.get("value", "")),
                    body.get("reason", "")))
            if path == "/api/divisions/build":
                return self._json(svc.build_divisions(body.get("rng_seed")))
            if path == "/api/pairs/set":
                return self._json(svc.pairs_set(body["event"], body.get("groups", [])))
            if path == "/api/pairs/shuffle":
                return self._json(svc.pairs_shuffle(body["event"], body.get("rng_seed")))
            if path == "/api/pairs/auto":
                return self._json(svc.pairs_auto(body["event"], body.get("rng_seed")))
            if path == "/api/partnership/assign":
                return self._json(svc.partnership_assign(
                    body["event"], body["player"], body["partner"]))
            if path == "/api/partnership/clear":
                return self._json(svc.partnership_clear(
                    body["event"], body["player"]))
            if path == "/api/division/format":
                return self._json(svc.set_format(body["division"], body["format"]))
            if path == "/api/division/seed":
                return self._json(svc.set_seed_choice(
                    body["division"], body.get("method", "ranking"),
                    body.get("rng_seed")))
            if path == "/api/bracket/generate":
                return self._json(svc.generate_bracket(
                    body["division"], body.get("format"),
                    body.get("method", "ranking"), body.get("rng_seed"),
                    body.get("manual_order"), bool(body.get("force")),
                    body.get("num_groups"), body.get("main_draw")))
            if path == "/api/bracket/finalize":
                return self._json(svc.finalize(body["division"]))
            if path == "/api/bracket/unfinalize":
                return self._json(svc.unfinalize(body["division"]))
            if path == "/api/result":
                return self._json(svc.record_result(
                    body["division"], body["match"], body["games"]))
            if path == "/api/result/clear":
                return self._json(svc.clear_match(body["division"], body["match"]))
            if path == "/api/schedule/generate":
                return self._json(svc.generate_schedule(body.get("divisions")))
            if path == "/api/plan":
                return self._json(svc.plan_division(
                    body["division"], body.get("start"), body.get("end"),
                    body.get("courts"), body.get("method", "ranking"),
                    body.get("num_groups")))
            if path == "/api/settings":
                return self._json(svc.update_settings(body))
            if path == "/api/division/custom":
                return self._json(svc.create_custom_division(
                    body["label"], body.get("kind", "player"),
                    body.get("entries", []), body.get("event", "MS"),
                    body.get("format", "single_elim")))
            if path == "/api/clear":
                return self._json(svc.clear(body["stage"]))
            if path == "/api/mode":
                return self._json(svc.set_mode(body["mode"]))
            if path == "/api/teams/preview":
                return self._json(svc.team_preview(body))
            if path == "/api/teams/commit":
                return self._json(svc.commit_teams(body))
            if path == "/api/division/team-format":
                return self._json(svc.set_team_format(
                    body["division"], body.get("template")))
            if path == "/api/board/assign":
                return self._json(svc.board_assign(int(body["court"]), body["match"]))
            if path == "/api/board/clear":
                return self._json(svc.board_clear(int(body["court"])))
            if path == "/api/board/result":
                return self._json(svc.board_result(int(body["court"]), body["games"]))
            return self._json({"error": "unknown endpoint"}, 404)
        except Conflict as e:
            return self._json({"error": str(e), "conflict": True}, 409)
        except KeyError as e:
            return self._json({"error": f"missing field {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 400)


def make_server(data_path: str, port: int | None = None, actor: str = "admin"):
    repo = Repository(data_path)
    service = TournamentService(repo, actor=actor)
    port = resolve_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.RequestHandlerClass.service = service  # shared across requests
    return httpd, port


def serve(data_path: str, port: int | None = None, actor: str = "admin") -> None:
    httpd, port = make_server(data_path, port, actor)
    print(f"BYU Badminton Tournament server on http://127.0.0.1:{port}")
    print(f"  Admin:  http://127.0.0.1:{port}/")
    print(f"  Public: http://127.0.0.1:{port}/public")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        httpd.shutdown()
