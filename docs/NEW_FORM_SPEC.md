# Recommended Google Form (clean-data redesign)

Goal: collect registrations so clean the app needs **no fuzzy matching** — one
submission per entry (per pair for doubles), explicit gender and skill, and
event codes the importer reads directly. This matches `StrictPairFormAdapter`
(`ingest/adapters.py`); its exported CSV imports with zero guesswork.

## Key design rules
1. **One submission per entry.** For doubles, exactly one partner submits for the
   pair and enters *both* players. This removes the "who submitted / did the
   partner also submit / one-sided request" mess entirely.
2. **Explicit gender and skill per player** — never inferred, never fabricated.
3. **One event per submission.** A person playing 3 events submits 3 times. This
   keeps each row unambiguous and makes multi-event conflict handling exact.
4. Use **dropdowns**, not free text, wherever possible.

## Form questions

| # | Question | Type | Required | Options / validation |
|---|----------|------|----------|----------------------|
| 1 | Event | Dropdown | Yes | Men's Singles (MS), Women's Singles (WS), Men's Doubles (MD), Women's Doubles (WD), Mixed Doubles (XD) |
| 2 | Club / affiliation | Short answer | No | e.g. "BYU Badminton Club" |
| 3 | Player 1 — First name | Short answer | Yes | |
| 4 | Player 1 — Last name | Short answer | Yes | |
| 5 | Player 1 — Email | Short answer | Yes | response validation: email |
| 6 | Player 1 — Gender | Dropdown | Yes | Male, Female |
| 7 | Player 1 — Skill (1–9) | Dropdown | Yes | 1…9 (see scale below) |
| 8 | Player 2 — First name | Short answer | No* | *required for MD/WD/XD |
| 9 | Player 2 — Last name | Short answer | No* | |
| 10 | Player 2 — Email | Short answer | No* | email validation |
| 11 | Player 2 — Gender | Dropdown | No* | Male, Female (must be one M + one F for XD) |
| 12 | Player 2 — Skill (1–9) | Dropdown | No* | 1…9 |
| 13 | Availability — weekends | Checkboxes | No | list the candidate weekend dates |
| 14 | Availability — weekday evenings | Checkboxes | No | Monday…Thursday |
| 15 | Willing to play more than one match in a team tie? | Dropdown | No | Yes / No (**team events only**) |

Question 15 feeds the team engine: only players who answer **Yes** may be
doubled-up across rubbers in a single team tie (capped by the *multi-event cap*
setting, default 2). It maps to the `multi_event_ok` player flag; everyone else
plays at most one rubber per tie. Header keyword: "multiple" / "willing to play".

\* Player 2 fields: make a **section** that only appears for doubles events using
Google Forms "Go to section based on answer" on the Event question, so singles
registrants never see Player 2 fields.

### CSV headers the importer expects
`Event, Club, Player 1 First Name, Player 1 Last Name, Player 1 Email,
Player 1 Gender, Player 1 Skill, Player 2 First Name, Player 2 Last Name,
Player 2 Email, Player 2 Gender, Player 2 Skill` (availability columns optional).
Header matching is fuzzy on keywords ("Player 1 First", "Skill", "Event"), so
minor wording changes are fine.

## Skill scale (put this in the form's help text)
Use a consistent 1–9 self-rating so seeding is meaningful:
- **1–2** New / still learning basic strokes and serve.
- **3–4** Casual; rallies, but inconsistent clears/smashes.
- **5–6** Intermediate; consistent strokes, understands footwork and doubles rotation.
- **7–8** Advanced; strong smashes/defense, competitive at club level.
- **9** Elite / near-collegiate competitive.

## Publish-to-web (so the app can sync)
1. Form responses populate a Google Sheet (Responses → link to Sheets).
2. In the Sheet: **File → Share → Publish to web → (this sheet) → CSV → Publish**.
3. Copy the published CSV URL.
4. In the admin tool's Import panel, pick **Published sheet URL**, paste it, set
   schema to **strict pair form** (or auto), and click **Preview → Commit**.

## Why this removes the old pain
The 2026 legacy form produced messy partner strings ("Sunny uou", "Jarem",
"Yuen Yuen Chang(XD), Jarem Miller(MD)"), one-sided partner requests, and
inferred genders. The redesign makes every pair explicit and every field typed,
so `StrictPairFormAdapter` builds both players and the pair directly — no fuzzy
resolution, no placeholder stubs, far fewer validation warnings. The legacy
importer remains available for the old data.
