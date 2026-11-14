# BYU Badminton Tournament System

A tested tournament engine, a local web admin for running the event, and a
public display that can be published to GitHub Pages.

- **Standard library only** — no pip installs, no build step. Python 3.11+.
- **Logic is separated from UI** and unit-tested (`python -m unittest`).
- **Branded** in BYU navy/white with the club logo throughout.

Two halves:

| | Runs where | What it does |
|---|---|---|
| **Admin** | your laptop (`python -m tournament.cli serve`) | import, pairs, divisions, formats, seeding, brackets, results, schedule, exports |
| **Public display** | your laptop *and* GitHub Pages | read-only brackets, pool standings, champions, schedule |

GitHub Pages can't run Python, so the admin is never published — only the
read-only view is. Everything below covers both.

---

## 1. Get it running (a minute)

```bash
cd NEW
python -m tournament.cli serve          # http://127.0.0.1:8765
```

Open:

- **Admin:** <http://127.0.0.1:8765/>
- **Public display:** <http://127.0.0.1:8765/public> — put this on the second
  monitor; it updates itself every 5 seconds as you work in the admin.

Other port (5000/5001 are deliberately avoided):

```bash
python -m tournament.cli serve --port 8800     # or set BADMINTON_PORT
```

State is one file, `data/tournament.json`. It is written atomically and a `.bak`
copy of the previous version is kept before every generate, so a bad click is
recoverable. Corrections are appended to `data/audit.log`.

---

## 2. Running an event, screen by screen

### Step 1 — Import & Validate

1. Paste the Google Form CSV URL (File → Share → Publish to web → CSV), or
   choose the CSV file, or paste the rows.
2. Check the preview: adapter, counts, and the validation dashboard. Errors must
   be fixed; warnings are usually name/gender/skill mismatches.
3. Fix gender, skill or "withdrawn" inline — each edit is logged with who/when.
4. **Commit** to save. Nothing downstream exists until you do.

### Step 2 — Pairs

The pairs panel is where you fix what the import guessed:

- Each pair shows both players; pick a different player to **swap**.
- **Shuffle** re-pairs everything, **Re-pair** fills only the open slots.
- Players left without a partner drop into the unpaired list with the reason
  (wrong gender for mixed, withdrawn, no partner available). Leaving them
  unpaired is supported — they simply aren't entered in that event.
- Mixed doubles pairs one man with one woman; doubles pairs respect the club's
  split rules and warn you when a pair breaks them.

Saving a pair change rebuilds the divisions for the affected events. Your format
and seeding choices are remembered and reapplied.

### Step 3 — Divisions & Brackets

Each division row has the format, the seeding method and an optional seed number:

| Format | Use it for |
|---|---|
| `single_elim` | the usual event |
| `double_elim` | when players want a second chance (loser bracket, grand-final reset) |
| `round_robin` | small pools where everyone plays everyone |
| `group_knockout` | pools first, then a knockout from the pool places |

Seeding: **ranking** (club skill), **random** (with a seed number so the draw is
reproducible), or manual.

1. Choose format + seeding, press **Generate**. The draw is stored with the RNG
   seed, so you can regenerate exactly the same bracket later.
2. Enter scores on the visual bracket; the winner advances automatically.
3. **Finalize** locks the bracket (regenerating then needs `force`).

Hand-made divisions, team events and custom brackets are kept when the table is
rebuilt; generated ones are replaced.

### Step 4 — Results, standings, schedule & exports

- Pool standings use configurable tie-breaks (head-to-head, game difference,
  points, seed) and flag unresolved three-way ties.
- **Schedule**: courts, day start, warm-up, buffer and rest minutes are
  configurable in `tournament/config.py`. The generator avoids double-booking a
  player across events.
- **Export**: roster, schedule by time, schedule by court, standings and results
  as CSV — also available from the CLI (`/api/export/csv`).

### Starting over, safely

| Want | Do |
|---|---|
| Re-import a corrected CSV | Import screen again, then Commit |
| Redo the draw only | Divisions → **Build** (clears brackets, keeps pairs) |
| Undo the last generate | restore `data/tournament.json.bak` over `data/tournament.json` |
| Start a fresh event | move `data/tournament.json` aside and import again |

---

## 3. Publishing the public display (GitHub Pages)

The published site is the same page as `/public`, in read-only mode. It lives in
`site/`, which is generated — never edit it by hand.

### One-time setup

1. Push the repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions** (this repo is already set up
   that way).
3. The site lands at `https://<user>.github.io/<repo>/`.

### Refreshing it (the part that keeps it current)

After you change anything in the admin — a result, a new division, a finalized
bracket — run:

```bash
python -m tournament.cli publish
```

That exports the snapshot from `data/tournament.json`, commits **only** `site/`
and pushes. The workflow redeploys Pages in about a minute. Anyone with the page
open picks the new version up within a minute without reloading (it re-checks
the snapshot every 60 seconds).

Useful variants:

```bash
python -m tournament.cli export --out site       # just rebuild the files
python -m tournament.cli publish --no-push       # commit locally, push later
python -m http.server 8000 --directory site      # preview the published page locally
```

If the push fails, the commit is still there — push it yourself and the site
updates. If `data/tournament.json` isn't in the checkout (it is gitignored),
the workflow simply republishes the committed `site/`, so nothing breaks.

### What gets published

Only the public view: divisions, draws, seeds, scores, standings, champions and
the schedule. The registration document stays out of Git and is never part of
the site — it holds emails and phone numbers, and only `data/tournament.json`
has those.

---

## 4. Command reference

```bash
python -m tournament.cli serve    [--port 8765] [--data data/tournament.json] [--actor admin]
python -m tournament.cli import   --file roster.csv [--schema auto|legacy|strict] [--commit]
python -m tournament.cli import   --url "<published sheet csv>" [--commit]
python -m tournament.cli validate [--data data/tournament.json]
python -m tournament.cli export   [--out site]
python -m tournament.cli publish  [--no-push] [--out site]
```

`import` without `--commit` is a preview: it prints the stats and validation
report and writes nothing.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `Address already in use` | another server is running; `--port 8800` or stop it |
| Admin shows stale data | refresh the tab; the page loads state on open |
| Public page says "reconnecting…" | the server stopped — restart `serve` |
| Published page is old | run `python -m tournament.cli publish`; check the Actions tab |
| A generate went wrong | copy `data/tournament.json.bak` back over `data/tournament.json` |
| Bracket finalized by mistake | Divisions → Unfinalize, then regenerate |

---

## 6. Architecture

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
  server/             http.server JSON API (thin) + application service + static export
  publish.py          refresh the snapshot, commit and push it
  cli.py              import / validate / serve / export / publish
web/                  admin.html, public.html, css/, js/ (vanilla), assets/logo.png
site/                 generated public display served by GitHub Pages
tests/                unittest suite + real messy-data fixture
docs/                 RESEARCH.md (cited rules), NEW_FORM_SPEC.md, GOOGLE_FORM_SETUP.md
```

Bracket generation is reproducible from its saved RNG seed, and a finalized
bracket cannot be overwritten without `force`.

## 7. Supported formats

Implemented: **single elimination, double elimination, round robin, group →
knockout**. Registered but not implemented (they fail with a clear message):
Swiss, consolation, compass — see `docs/RESEARCH.md`.

## 8. Tests

```bash
python -m unittest discover -s tests -t .
```

Covers import/cleanup, fuzzy resolution, validation rules, division grouping,
pair editing, seeding + bye placement, RNG reproducibility, single & double elim
progression (incl. the grand-final reset), round robin, group→knockout,
tie-breakers, multi-court scheduling, conflict avoidance, late arrivals, tiny
brackets, the service/API, the static export and the publish flow.

## 9. Configuration

Defaults live in `tournament/config.py` (`Settings`): court count, day start,
match format (best-of-3 to 21, cap 30), slot timing (warm-up/play/buffer), rest
minutes, and the tie-break order. Adjust them per tournament.
