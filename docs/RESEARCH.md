# Tournament Design Reference (cited)

This document records the researched, source-verified rules that drive the
engine, and how each maps to code. Findings were gathered via a multi-source,
adversarially-verified web research pass. Where a claim could not be verified
against an authoritative source it is flagged as a **design choice**, not a
standard.

> Provenance note: bracket/seeding/tie-break rules below are verified against
> BWF primary regulations and standard references. Match-duration and rest-time
> numbers were **not** authoritatively verified; they are practical defaults
> grounded in the club's own March 2026 event (20-minute slots proved too short)
> and are fully configurable in `config.py`.

## 1. Single-elimination seeding & bracket construction
- **Standard seeding pairs highest vs lowest** (1v8, 2v7, 3v6, 4v5 for 8 seeds),
  built so the top two seeds cannot meet before the final and the top four not
  before the semifinals. *(Wikipedia, Single-elimination tournament; universally
  corroborated.)*
- **BWF seed placement** (BWF Statutes §5.1 "General Competition Regulations"):
  seed 1 at the top of the draw, seed 2 at the bottom; seeds 3–4 drawn by lot
  into the remaining quarters; 5–8 into the remaining eighths; 9–16 into the
  remaining sixteenths. Seeds beyond #2 are placed within their section by lot.
- **Code:** `engine/seeding.py::standard_bracket_order` builds the recursive
  slot order (`[1]` → each round maps `s` to `size+1-s`), giving exactly this
  separation. `place_seeds_in_slots` maps seeds to slots.

## 2. Byes (non-power-of-two fields)
- **Byes = (next power of two − number of entries)**; e.g. 17 entries → 32−17 =
  15 byes. Byes are awarded to the top seeds. *(BWF Statutes §5.1, worked
  example.)*
- **Code:** `seeding.num_byes` and `place_seeds_in_slots` leave the high seed
  numbers empty, so byes fall to the top seeds automatically; first-round byes
  auto-advance in `bracket_single.generate` via `advancement.resolve_byes`.

## 3. Number of seeds by draw size (BWF)
- 2 seeds for <16 entries, 4 for 16–31, 8 for 32–63, 16 for 64–128, 32 for 129+.
  *(BWF Statutes §5.1, reg 11.7.1.)* Our club events are small, so effectively
  2–8 seeds; the engine seeds every entry but only the separation of the top
  seeds matters for fairness.

## 4. Same-club / same-member separation
- Top two entries from one member/club are drawn into opposite halves; wherever
  possible, entries from one member do not meet in round one. *(BWF Statutes
  §5.1, reg 11.11 "Separation of Entries".)*
- **Code:** `Player.club` and `Pair.club` carry the data; separation is a
  documented **design choice** for a future refinement pass on the by-lot
  placement (top seeds are already separated by the standard order).

## 5. Double elimination
- Two brackets: winners (run like single elim) and losers. Each round's WB
  losers **drop into** the LB; a second loss eliminates. The LB alternates minor
  rounds (LB survivors play each other) and major rounds (LB survivors meet the
  new WB droppers). The LB winner meets the WB winner in the **grand final**, and
  if the LB finalist wins the first grand final there is a **bracket reset**
  (decider). *(Wikipedia, Double-elimination tournament; Scoreholio docs.)*
- **Code:** `engine/bracket_double.py` builds WB, the alternating LB with a cross
  pairing to avoid immediate rematches, and grand final + reset
  (`after_result`/`champion`). Targets clean power-of-two draws.

## 6. Round robin (circle method)
- One entrant is fixed and the rest rotate each round; a dummy is added for odd
  counts (its opponent gets a bye). A pure round robin has **n·(n−1)/2** games.
  *(Wikipedia, Round-robin tournament, Circle method; verified 3-0.)*
- **Code:** `engine/bracket_rr.py::circle_rounds` and `build_pool_matches`.

## 7. Group-stage tie-breakers
- **Configurable, not a single universal hierarchy** — the research explicitly
  refuted the idea of one fixed order (tournament platforms let organizers order
  their own criteria). *(Toornament tie-breaker docs.)* This validates our
  configurable `Settings.tiebreak_order`.
- **BWF default order** (General Competition Regulations, Art. 16.2): most
  matches won → for a 2-way tie, head-to-head → for 3+-way ties, games
  difference then points difference **computed among the tied players only**,
  then lot.
- **Code:** `engine/tiebreak.py` implements a configurable chain; tie-break
  criteria recompute stats among the tied subset (so head-to-head and ratios
  behave correctly for 2-way and 3+-way ties); the final fallback is seeded
  position so results are always deterministic and reproducible (never a live
  coin flip).

## 8. Group → knockout advancement
- Top *k* of each pool qualify; standard crossover seeds pool winners as top
  seeds so they are separated (e.g. winner A vs runner-up B). Balanced pools are
  built by serpentine/snake distribution of seeds into pots. *(General
  tournament practice; the specific "snake pot" phrasing was not verified from a
  single authoritative source, so serpentine distribution is a **design
  choice**.)*
- **Code:** `engine/bracket_groups.py` uses serpentine distribution and seeds
  pool winners as the top knockout seeds. Any qualifier count is supported —
  when it isn't a power of two, first-round knockout byes go to the top
  qualifiers (resolved after the real qualifiers are filled in). Exact
  winner-vs-runner-up cross pairing is a documented refinement.

## 9. Swiss / compass / consolation
- **Swiss:** pair similar-scoring players, avoid rematches, eliminate no one;
  pairings depend on prior-round results (dynamic). *(Standard references.)*
- **Compass draw:** consolation-style; works cleanly with power-of-two fields
  (8/16/32/64); popular in tennis/pickleball. *(printyourbrackets; corroborated.)*
- **Code:** registered as clear "not yet implemented" stubs
  (`engine/bracket_stubs.py`) with guidance; Swiss needs a round-by-round
  pairing loop, planned.

## 10. Scheduling (design choices, not standards)
- Best-of-3 to 21 (rally scoring, cap 30) realistically needs ~30 minutes of
  play; the March 2026 event's 20-minute slots with no gap were too short.
- Default slot = **warm-up 5 + play 30 + buffer 5 = 40 min**, 4 courts, 10-minute
  minimum rest between a player's matches — all configurable in `config.py`.
- Late arrivals consume their own warm-up; the day does not cascade unless a
  match genuinely cannot proceed (`schedule/lateness.py`).
- Players entered in multiple events are never double-booked; a match starts
  only after its feeder matches finish (`schedule/scheduler.py`).
