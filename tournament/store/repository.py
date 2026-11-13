"""Load/save the tournament document.

- One JSON document per tournament, written atomically (temp file + os.replace)
  so a crash can never leave a half-written file.
- A ``.bak`` snapshot is taken before each save that follows a generate/mutate,
  giving cheap undo/rollback.
- Overrides are appended to a JSONL audit log and never rewritten.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict

from ..model.codec import from_jsonable, to_jsonable
from ..model.entities import Override, Tournament


class Repository:
    def __init__(self, path: str) -> None:
        self.path = path
        self.audit_path = os.path.join(os.path.dirname(path) or ".", "audit.log")

    # --- tournament document ------------------------------------------------
    def exists(self) -> bool:
        return os.path.exists(self.path)

    def load(self) -> Tournament:
        if not self.exists():
            return Tournament()
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return from_jsonable(Tournament, data)

    def save(self, tournament: Tournament, *, backup: bool = False) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if backup and os.path.exists(self.path):
            shutil.copy2(self.path, self.path + ".bak")
        payload = to_jsonable(tournament)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)  # atomic on Windows and POSIX

    def restore_backup(self) -> bool:
        bak = self.path + ".bak"
        if os.path.exists(bak):
            os.replace(bak, self.path)
            return True
        return False

    # --- append-only audit log ---------------------------------------------
    def append_audit(self, override: Override) -> None:
        os.makedirs(os.path.dirname(self.audit_path) or ".", exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(override), ensure_ascii=False) + "\n")

    def read_audit(self) -> list[dict]:
        if not os.path.exists(self.audit_path):
            return []
        out = []
        with open(self.audit_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
