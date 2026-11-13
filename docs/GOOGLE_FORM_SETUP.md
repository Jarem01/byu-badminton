# How to build the next registration form (step by step)

A click-by-click guide to building a Google Form that produces **clean data** and
avoids the problems we hit last time. The field reference table lives in
`NEW_FORM_SPEC.md`; this file is the *how-to*.

## The five rules that prevent last year's bugs

Last year's mess came from a few specific things. Each rule below kills one:

1. **One submission per entry (per pair for doubles).** *One* partner submits for
   the pair and enters *both* players. → Kills "who submitted / did my partner
   also submit / one-sided partner request / partner named wrong" entirely.
2. **One event per submission.** Someone in 3 events submits 3 times. → Every row
   is unambiguous; no parsing "MD with X, XD with Y" out of one cell.
3. **Dropdowns, not free text**, for event, gender, and skill. → No misspelled
   skill levels, no "8/10", no guessing gender.
4. **Require both players' first name, last name, gender, and skill.** → No blank
   partner, no unknown skill, no "Jarem" with no last name.
5. **Validate email format.** → Clean contact + a reliable way to de-duplicate.

## Step-by-step

### 1. Create the form
Google Forms → Blank form. Title it e.g. "BYU Badminton Tournament — Registration".
In **Settings → Responses**, turn on **Collect email addresses** and **Limit to 1
response** (optional; requires sign-in).

### 2. Event (dropdown, required) — and branch on it
Add a **Dropdown** question "Which event are you registering for?" with exactly:
`Men's Singles (MS)`, `Women's Singles (WS)`, `Men's Doubles (MD)`,
`Women's Doubles (WD)`, `Mixed Doubles (XD)`. Mark **Required**.

Then use branching so doubles registrants get Player 2 fields and singles don't:
- Put Player 2's questions in their own **Section** (Add section).
- On the Event question's ⋮ menu → **Go to section based on answer**: send MS and
  WS to the "Submit" section; send MD, WD, XD to the "Player 2" section.

### 3. Club (short answer, optional)
"Club / affiliation" — default help text "e.g. BYU Badminton Club".

### 4. Player 1 (all required)
Add these, each **Required**:
- Short answer: "Player 1 — First name"
- Short answer: "Player 1 — Last name"
- Short answer: "Player 1 — Email" → ⋮ → **Response validation → Text → Email**.
- Dropdown: "Player 1 — Gender" → `Male`, `Female`.
- Dropdown: "Player 1 — Skill (1–9)" → options `1`…`9`. Paste the skill scale
  (below) into the question's description.

### 5. Player 2 (in the doubles-only section, all required there)
Repeat the five Player 1 questions as "Player 2 — …", all **Required**. Add a note
at the top of the section: *"Only one partner fills this out for the pair. Mixed
doubles must be one man + one woman."*

### 6. Availability (checkboxes, optional)
- Checkboxes: "Which weekends can you play?" → list your candidate dates.
- Checkboxes: "Which weekday evenings work?" → Monday…Thursday.

### 7. Skill scale (paste into the skill question descriptions)
```
1–2  New / learning basic strokes and serve
3–4  Casual; rallies but inconsistent clears/smashes
5–6  Intermediate; consistent strokes, good footwork & doubles rotation
7–8  Advanced; strong smash/defense, competitive at club level
9    Elite / near-collegiate competitive
```

## Connect it to the app (two ways)

**Live sync (recommended):**
1. Form → **Responses → Link to Sheets** (creates the response spreadsheet).
2. In that Sheet: **File → Share → Publish to web → (the responses sheet) → CSV →
   Publish**. Copy the URL.
3. In the admin tool's **Import** panel choose **Published sheet URL**, paste it,
   set schema to **auto** (or **strict pair form**), click **Preview → Commit**.

**Manual (always works offline):**
1. Sheet → **File → Download → CSV**.
2. Admin tool → Import → **Local CSV** → point to the downloaded file.

## Verifying it worked
After import, the **Validation** panel should be almost empty — no "unresolved
partner", no "unknown gender", no "missing skill". If you still see partner
warnings, a doubles submitter probably left Player 2 fields blank; make those
fields Required (Step 5). There is a ready-made example of this clean format in
`sample_data/strict_pairs.csv` you can import right now to see it in action.

## Why this maps cleanly to the importer
The app's **strict adapter** reads columns by keyword (`Event`, `Player 1 First`,
`Player 1 Skill`, `Player 2 …`), builds both players and the pair directly from
one row, and needs **no fuzzy name matching**. Minor wording changes to questions
are fine as long as they still contain those keywords.
