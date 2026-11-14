# BYU Badminton Tournament System

A clean, tested tournament engine + local web admin tool + synced public display
for the BYU Badminton Club. Rebuilt from scratch (the old files in the parent
folder are reference only).

- **Standard library only** — no pip installs. Python 3.11+.
- **Logic is separated from UI** and fully unit-tested (`python -m unittest`).
- **Branded** in BYU navy/white with the club logo throughout.

## Quick start

```bash
cd NEW
python -m tournament.cli serve          # starts on http://127.0.0.1:8765
```
Then open:
- **Admin:**  http://127.0.0.1:8765/
- **Public display (2nd monitor):** http://127.0.0.1:8765/public

Port is configurable (5000/5001 are intentionally avoided):
```bash
python -m tournament.cli serve --port 8765        # or set BADMINTON_PORT
```

### Import from the command line (preview or commit)
```bash
python -m tournament.cli import --file "../Badminton Tournament 2026 (Responses) - Form responses 1.csv"
python -m tournament.cli import --file roster.csv --commit
python -m tournament.cli validate
```

## Publish the public display on GitHub Pages

GitHub Pages only serves static files, so it hosts the **read-only public
display** — brackets, pool standings, champions and the schedule — not the admin
app, which needs the local Python server. One page works both ways: live in the
arena it polls the API, and as a published snapshot it reads the exported JSON.

```bash
python -m tournament.cli export --out site      # snapshot of data/tournament.json
python -m http.server 8000 --directory site     # check it before pushing
```

The export writes `site/index.html`, the page's assets and `static-data.json`
(the same payloads `/api/public` and `/api/schedule` return), and marks the page
as a snapshot so it loads that file instead of polling. Re-run it after the
tournament changes and commit `site/`.

`.github/workflows/pages.yml` runs the tests, refreshes `site/` when
`data/tournament.json` is in the checkout, and deploys `site/`. To switch it on:
**Settings → Pages → Source: GitHub Actions** (the workflow also tries to enable
Pages itself). The site lands at `https://<user>.github.io/<repo>/`.

Only the public view is published — names, draws and results. The registration
document stays out of Git (`data/tournament.json` is ignored: it holds emails
and phone numbers).

## Admin workflow
1. **Import & Validate** — load the CSV (local file, pasted text, or a published
   Google Sheet CSV URL). Preview shows stats + a validation dashboard. Fix
   gender/skill/withdrawn inline (each edit is saved with an audit record), then
   **Commit**.
2. **Divisions & Brackets** — Build divisions & pairs (auto-pairs willing players,
   mixed doubles pairs one man + one woman). Pick a format per division
   (single/double elim, round robin, group→knockout), choose seeding
   (ranking/random), **Generate**, enter results on the visual bracket, and
   **Finalize** to lock it.
3. **Schedule & Export** — best-date suggestion from availability, generate the
   court schedule (warm-up/buffer/rest built in, no player double-booked),
   see conflicts, and export CSVs (roster, schedule, standings, results).

The public page mirrors the admin state live (polling), showing brackets, pool
standings, and champions on a second monitor.

## Architecture
```
tournament/           pure logic — no UI, no globals
  model/              dataclasses + JSON codec + IDs
  ingest/             CSV/sheet sources, schema adapters, normalization, partner parsing
  validate/           fuzzy name resolution, rules, dashboard, override audit
  engine/             seeding, single/double elim, round robin, group→knockout,
                      advancement, standings, configurable tie-breaks
  schedule/           slot math, court assignment, conflicts, lateness, best-date
  export/             CSV outputs
  store/              atomic JSON persistence + append-only audit log
  server/             http.server JSON API (thin) + application service
  cli.py              import / validate / serve / export
web/                  admin.html, public.html, css/, js/ (vanilla), assets/logo.png
site/                 generated static public display (GitHub Pages)
tests/                unittest suite + real messy-data fixture
docs/                 RESEARCH.md (cited rules), NEW_FORM_SPEC.md
```
State is one JSON document (`data/tournament.json`), written atomically with a
`.bak` snapshot before each generate. Corrections are logged to `data/audit.log`
(append-only). Bracket generation is reproducible from a saved RNG seed and a
finalized bracket cannot be overwritten without `force`.

## Supported formats
Implemented: **single elimination, double elimination, round robin, group →
knockout**. Registered but not yet implemented (fail with a clear message):
Swiss, consolation, compass — see `docs/RESEARCH.md`.

## Testing
```bash
cd NEW
python -m unittest discover -s tests -t .
```
Covers: import/cleanup, fuzzy resolution, validation rules, division grouping,
seeding + bye placement, RNG reproducibility, single & double elim progression
(incl. grand-final reset), round-robin generation, group→knockout advancement,
tie-breakers (2-way/3-way/seed fallback), multi-court scheduling with
warm-up/buffer, multi-event conflict avoidance, late-arrival non-cascade, tiny
brackets, and the service/API end-to-end.

## Configuration
Defaults live in `tournament/config.py` (`Settings`): court count, day start,
match format (best-of-3 to 21, cap 30), slot timing (warm-up/play/buffer), rest
minutes, and the tie-break order. All are meant to be adjusted per tournament.
