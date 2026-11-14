"""Write the read-only public display as plain files (GitHub Pages).

The live display is served by the Python app; GitHub Pages only serves static
files. So this writes the exact snapshots ``/api/public`` and ``/api/schedule``
return, together with the public page's assets. ``public.js`` asks the API
first and falls back to ``static-data.json``, so one page works both live in
the arena and as a published snapshot.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

from ..store.repository import Repository
from .service import TournamentService

WEB_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "web"))

# admin.html/admin.js are deliberately absent: they need the local server.
_COPY = ("assets", "css", os.path.join("js", "api.js"),
         os.path.join("js", "bracket.js"), os.path.join("js", "public.js"))


def export_static(data_path: str, out_dir: str, *, web_dir: str = WEB_DIR,
                  generated: str | None = None) -> dict:
    """Write the public site into ``out_dir`` and report what went out."""
    svc = TournamentService(Repository(data_path))
    snapshot = svc.public_snapshot()
    schedule = svc.schedule_view()
    if generated is None:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(web_dir, "public.html"), encoding="utf-8") as fh:
        page = fh.read()
    # Tell the page there is no API behind it: read static-data.json instead.
    page = page.replace('name="data-source" content="live"',
                        'name="data-source" content="static"')
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    for rel in _COPY:
        src = os.path.join(web_dir, rel)
        dst = os.path.join(out_dir, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copyfile(src, dst)

    payload = {"generated": generated, "name": snapshot.get("name"),
               "public": snapshot, "schedule": schedule}
    with open(os.path.join(out_dir, "static-data.json"), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    # GitHub Pages runs Jekyll by default; the page has no templating to do.
    with open(os.path.join(out_dir, ".nojekyll"), "w", encoding="utf-8"):
        pass

    return {"out": out_dir, "generated": generated,
            "divisions": len(snapshot.get("divisions", [])),
            "matches": sum(len(d.get("rounds", [])) for d in
                           snapshot.get("divisions", []))}
