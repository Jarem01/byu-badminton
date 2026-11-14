"""Refresh the published public display and commit it.

The Pages site is static, but it has to be current: ``publish`` re-exports the
snapshot from the saved tournament, commits ``site/`` and (unless told not to)
pushes, which is what redeploys Pages through the workflow.
"""

from __future__ import annotations

import os
import subprocess


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True)
    except OSError as exc:              # git not installed
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def publish_snapshot(data_path: str, out_dir: str = "site", *,
                     push: bool = True, cwd: str | None = None) -> dict:
    """Export the snapshot, then commit (and push) just that folder."""
    from .server.static_export import export_static

    info = export_static(data_path, out_dir)
    report = {"out": info["out"], "generated": info["generated"],
              "committed": False, "pushed": False, "ok": True, "detail": ""}

    root = cwd or os.getcwd()
    # A linked worktree has a .git file, not a directory, so ask git itself.
    probe = _git(["rev-parse", "--is-inside-work-tree"], root)
    if probe.returncode or probe.stdout.strip() != "true":
        report["detail"] = ("not a git checkout — the files are written; commit "
                            "them yourself")
        return report

    rel = os.path.relpath(os.path.abspath(os.path.join(root, out_dir)), root)
    add = _git(["add", "--", rel], root)
    if add.returncode:
        report["ok"] = False
        report["detail"] = (add.stderr or add.stdout).strip()
        return report
    if _git(["diff", "--cached", "--quiet", "--", rel], root).returncode == 0:
        report["detail"] = "already up to date — nothing to publish"
        return report

    msg = f"Refresh the published snapshot ({info['generated']})"
    commit = _git(["commit", "-m", msg, "--", rel], root)
    if commit.returncode:
        report["ok"] = False
        report["detail"] = (commit.stderr or commit.stdout).strip()
        return report
    report["committed"] = True

    if not push:
        report["detail"] = "committed — push it when you are ready"
        return report
    res = _git(["push"], root)
    if res.returncode:
        report["ok"] = False
        report["detail"] = ("committed, but the push failed — push it yourself:\n"
                            + (res.stderr or res.stdout).strip())
        return report
    report["pushed"] = True
    report["detail"] = "pushed — GitHub Pages redeploys in about a minute"
    return report
