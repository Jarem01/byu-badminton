# BYU Badminton Tournament System

A tested tournament engine, a local web admin for running the event, and a
public display that can be published to GitHub Pages.

- **Standard library only** — no pip installs, no build step. Python 3.11+.
- **Logic is separated from UI** and unit-tested (`python -m unittest`).
- **Branded** in BYU navy/white with the club logo throughout.

Two halves:

| | Runs where | What it does |
|---|---|---|
| **Admin** | your laptop (`python3 -m tournament.cli serve`) | import, pairs, divisions, formats, seeding, brackets, results, schedule, exports |
| **Public display** | your laptop *and* GitHub Pages | read-only brackets, pool standings, champions, schedule |

GitHub Pages can't run Python, so the admin is never published — only the
read-only view is. Everything below covers both.

---

## 1. Set it up (once, about five minutes)

Nothing to install beyond Python — the app is standard library only, so there is
no `pip install`, no virtualenv and no build step. It runs on your own computer
and prints a web address you open in a browser.

### What you need

1. **Python 3.11 or newer.**
2. **This repository on your computer** (a clone or a ZIP download).
3. **Git** — only if you want to publish the public display from your machine.

### Step 1 — Check your Python

Open a terminal and run:

| Your computer | Command |
|---|---|
| **Windows** | `py --version` (or `python --version`) |
| **macOS / Linux** | `python3 --version` |

You want **3.11** or higher. If you get a lower number, or "command not found":

- **Windows:** install from <https://www.python.org/downloads/> and tick
  *Add python.exe to PATH* in the installer.
- **macOS:** `brew install python@3.12`, or the installer from python.org.
- **Linux:** `sudo apt install python3` (Debian/Ubuntu) or your distro's package.

No Python at all is fine to fix later, but the rest of this walkthrough assumes
the command works.

### Step 2 — Get the code onto your computer

**Option A — with git (recommended**, because publishing updates later needs it):

```bash
git clone https://github.com/Jarem01/byu-badminton.git
cd byu-badminton
```

**Option B — no git:** open the repository page, click **Code → Download ZIP**,
unzip it, and open a terminal inside the unzipped `byu-badminton` folder.

Either way you should now be in the folder that contains `README.md`,
`tournament/` and `web/`. Every command below is run from there — there is no
`NEW` folder any more; that name was left over from the old layout.

### Step 3 — Start it

| Your computer | Command |
|---|---|
| **Windows** | `py -m tournament.cli serve` |
| **macOS / Linux** | `python3 -m tournament.cli serve` |

You'll see:

```
BYU Badminton Tournament server on http://127.0.0.1:8765
  Admin:  http://127.0.0.1:8765/
  Public: http://127.0.0.1:8765/public
Press Ctrl+C to stop.
```

Leave that terminal open — it *is* the app. `Ctrl+C` stops it.

### Step 4 — Open the two pages

- **Admin:** <http://127.0.0.1:8765/> — you run the tournament here.
- **Public display:** <http://127.0.0.1:8765/public> — read-only brackets and
  schedule for a second monitor; it refreshes itself every 5 seconds.

### Step 5 — Load the roster

On the admin page, **Import & Validate** → paste the published Google Form CSV
URL (Form → Responses → ⋮ → *Get response CSV*, or *File → Share → Publish to
web*), or pick the CSV file from your computer → check the validation list →
**Commit**. From there, follow §2.

A repo you just cloned starts empty: no players, no draws. That's expected.

### Where your data lives

Everything you enter is saved to **`data/tournament.json` inside the project
folder**, created the first time you Commit:

- Nothing is uploaded anywhere; the public page reads from the same process.
- It is gitignored on purpose — it holds emails and phone numbers.
- **Back it up** (copy the file) before the event, and to continue on another
  computer just copy it into that checkout's `data/` folder.
- `data/tournament.json.bak` is the previous version, kept before each generate.
- `data/audit.log` records every correction you make to a registration.

### Changing the port

5000 and 5001 are deliberately avoided (they clash with other tools):

```bash
python3 -m tournament.cli serve --port 8800    # or set BADMINTON_PORT
```

### Updating the code later

```bash
git pull                       # get the latest version
python3 -m tournament.cli publish   # republish the public display
```

Your `data/` folder is untouched by either command.

---

## 2. Running an event, screen by screen

### Step 1 — Import & Validate

1. Paste the Google Form CSV URL (File → Share → Publish to web → CSV), or
   choose the CSV file, or paste the rows.
2. Check the preview: adapter, counts, and the validation dashboard. Errors must
   be fixed; warnings are usually name/gender/skill mismatches.
3. Fix gender, skill or "withdrawn" inline — each edit is logged with who/when.
   The event codes on each row (MS WS MD WD XD) are buttons: click one to put a
   player into that event — how you fill a spot nobody signed up for — and click
   it again to take them out. Two guards apply, the same way pair changes are
   refused: an event they are already paired in can't be removed until you
   unpair them, and an event whose bracket is already drawn can't be changed at
   all (clear that division first) — otherwise the draw would be left stale and
   the new entry missing from it.
   **Merge a duplicate.** A `Possible duplicate registrations` or
   `Duplicate registration email` warning carries a **Merge into <name>**
   button for each entry. Near-miss names are caught as well, not just exact
   ones: "Amy Ngyun" next to "Amy Nguyen" (or "Sunny" next to "Sonny") raises
   the same warning, as does a placeholder partner typed with a typo. A
   different surname that merely looks similar ("Josh Lim" / "Josh Liu") is
   left alone. Entries spelt identically are always grouped together and the
   list is ordered by name then id, so the same roster always produces the same
   warning (`'Kei Wong' ×3 and 'Kei Wng'`) and the same buttons. Pressing it confirms, then folds that person into the
   chosen survivor: their registration and partner requests, the pairs they are
   in (that partner stays with the survivor) and the events they entered all
   move across, and the duplicate is deleted. The merge is written to the audit
   log both ways (`merged_from` on the survivor, `merged_into` on the one that
   goes). It refuses when the two entries are paired with different partners in
   the same event (unpair one first) and when a bracket is already drawn for an
   event the merge touches (clear that division first), so no draw is left
   pointing at a player who no longer exists. If the entry you keep is a
   placeholder, it takes the real player's name, email, gender and skill, and
   stops being a placeholder — each change is audited separately.
   **Undo merge** in the Players header takes the last merge back, putting both
   entries exactly as they were (name, email, gender, skill, events, partner
   requests and the pair the duplicate was in), newest merge first. Like the
   merge itself it is refused while a bracket is drawn for an event it touches,
   and it is refused if the survivor has been paired since — unpair them first.
4. Settle the **partnerships** (see below) while you are still on this screen.
5. **Commit** to save. Nothing downstream exists until you do.

#### Partnerships (the table under Players)

One table per doubles event, **one row per player**, with that player's gender
and skill and their partner's:

| Status | Meaning | What you can do |
|---|---|---|
| `paired` | they are a pair on the roster | **Unpair** frees both players |
| `agreed` | both named each other; they pair when divisions are built | **Confirm** / **Unpair** |
| `waiting on them` | this player named someone who hasn't named them back | **Confirm** accepts it, **Clear** drops the request |
| `they asked you` | someone named this player; no answer yet | **Confirm** accepts it |
| `not honoured` | the request can't be used (partner paired elsewhere or withdrawn) | pick someone else |
| `no partner` | nobody named anybody | choose a partner from the list |

"Set partner" lists everyone already in that event first, then anyone else
(choosing them adds the event to their form). Gender-rule mismatches are shown
before you save, not after. Every change is audited, and the choice survives a
rebuild — a hand-picked pair is never re-shuffled away.

### Step 2 — Pairs

There is exactly one pair editor: the **Partnerships** table on the Import tab.
The Draw tab has no separate pair list any more — it builds the divisions from
whatever that table says, so the two can't drift apart.

Bulk actions sit in each event's header in the same table:

- **Shuffle this event** re-pairs everyone at random (the seed number makes it
  repeatable; mixed doubles still pairs one man with one woman).
- **Re-pair from forms** throws away every hand-picked pair and pairs from what
  the registration form asked for, then fills the leftovers at random. This is
  the reset button: the form answers are never modified, so it always works.
- **Undo last change** steps back one decision at a time, back to the previous
  arrangement and finally back to the form answers. If the change you undo had
  added an event to a partner who hadn't entered it, that entry is taken back off
  too (unless they are still paired in it).
- Players left out simply aren't entered in that event — supported, not an error.

The form answers are kept exactly as submitted. Every pairing you make, shuffle,
re-pair or clear is stored beside them (never in place of them) with an audit
line in `data/audit.log` recording who changed what, before and after, so you can
play with pairings and always get back to where you were. Any pair change
rebuilds the divisions for the affected events; your format and seeding choices
are remembered and reapplied. Partnerships are editable until a bracket is drawn
— after that, un-finalize or clear divisions first. During an import preview
they stay editable whatever state the committed data is in, and every pair
change made there — undo included — affects the preview only until you commit it.

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
python3 -m tournament.cli publish
```

That exports the snapshot from `data/tournament.json`, commits **only** `site/`
and pushes. The workflow redeploys Pages in about a minute. Anyone with the page
open picks the new version up within a minute without reloading (it re-checks
the snapshot every 60 seconds). If nothing changed, it says *already up to
date — nothing to publish* and makes no commit.

Useful variants:

```bash
python3 -m tournament.cli export --out site       # just rebuild the files
python3 -m tournament.cli publish --no-push       # commit locally, push later
python3 -m http.server 8000 --directory site      # preview the published page locally
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

Run these from the project folder. **On Windows type `py` where these say
`python3`** (`py -m tournament.cli serve`).

```bash
python3 -m tournament.cli serve    [--port 8765] [--data data/tournament.json] [--actor admin]
python3 -m tournament.cli import   --file roster.csv [--schema auto|legacy|strict] [--commit]
python3 -m tournament.cli import   --url "<published sheet csv>" [--commit]
python3 -m tournament.cli validate [--data data/tournament.json]
python3 -m tournament.cli export   [--out site]
python3 -m tournament.cli publish  [--no-push] [--out site]
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
| Published page is old | run `python3 -m tournament.cli publish`; check the Actions tab |
| `SyntaxError` on startup | your `python3`/`py` is older than 3.11 — install a newer one |
| `python3: command not found` | Python isn't installed or not on PATH; see §1 Step 1 |
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
