"""Generate fictitious registration CSVs for testing the whole pipeline.

All names are invented (any resemblance to real players is coincidental). Run:

    cd NEW && python sample_data/generate_samples.py

Produces several scenarios in this folder:
  - legacy_mixed.csv    : realistic mix across all 5 events, legacy form columns,
                          with partner requests + a couple of deliberate typos
                          so the fuzzy matcher / validation dashboard get exercised.
  - legacy_messy.csv    : lots of data problems (missing partners, prose, unknown
                          gender, duplicate) to stress the validation dashboard.
  - clean_singles_16.csv: 16 men's singles + 16 women's singles (a clean
                          power-of-two field for single/double elimination).
  - strict_pairs.csv    : the redesigned one-submission-per-pair schema
                          (imports via StrictPairFormAdapter, no fuzzy matching).

Deterministic (fixed timestamps/skills) so tests and demos are reproducible.
"""

from __future__ import annotations

import csv
import os

HERE = os.path.dirname(__file__)

LEGACY_HEADERS = [
    "Timestamp", "First Name", "Last Name", "Email",
    "Select which weekends work best for you to participate in a tournament:",
    "Depending on availability in the RB, the tournament may have to be done on "
    "weekdays. If so, which evenings are best for you?",
    "Approximate Skill Level:", "How long have you been playing badminton? ",
    "How often do you play?", "What event(s) will you be participating?",
    "If you will be playing doubles, do you already have a partner? ",
    "If yes, what is your partner’s full name?",
    "If no, are you willing to be assigned a random partner? ",
]

EVENT_TEXT = {
    "MS": "Men’s Singles (MS)", "WS": "Women’s Singles (WS)",
    "MD": "Men’s Doubles (MD)", "WD": "Women’s Doubles (WD)",
    "XD": "Mixed Doubles (XD)",
}
WKND = "March 20-21, March 27-28, April 10-11"
WKDY = "Tuesday, Thursday"


def ev(*codes):
    return ", ".join(EVENT_TEXT[c] for c in codes)


def legacy_row(i, first, last, skill, events, partner="", willing="Yes"):
    has = "Yes" if partner else ("No" if any(c in events for c in "MD WD XD".split()) else "")
    return [f"01/03/2026 1{i%10}:0{i%6}:00", first, last,
            f"{first.lower()}.{last.lower()}@example.com", WKND, WKDY,
            str(skill), "3+ years", "Once a week", ", ".join(EVENT_TEXT[c] for c in events),
            has, partner, willing]


def write_csv(name, headers, rows):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    print(f"wrote {name} ({len(rows)} rows)")


def build_legacy_mixed():
    # One row per person (like the real form): all their events on one row, with
    # per-event partner hints. One deliberate typo ("Jordn Kim") exercises fuzzy.
    # (person) -> (skill, {event: partner_full_name or None})
    people = {
        ("Alex", "Rivera"):  (8, {"MS": None, "MD": "Jordan Kim", "XD": "Mia Chen"}),
        ("Jordan", "Kim"):   (7, {"MS": None, "MD": "Alex Rivera", "XD": "Zoe Park"}),
        ("Sam", "Okafor"):   (6, {"MS": None, "MD": "Diego Santos", "XD": "Ava Lopez"}),
        ("Diego", "Santos"): (7, {"MS": None, "MD": "Sam Okafor", "XD": "Lena Costa"}),
        ("Tom", "Becker"):   (6, {"MS": None, "MD": "Luis Moreno", "XD": "Ivy Tran"}),
        ("Luis", "Moreno"):  (5, {"MD": "Tom Becker"}),
        ("Chris", "Nguyen"): (5, {"MS": None}),
        ("Mia", "Chen"):     (8, {"WS": None, "WD": "Zoe Park", "XD": "Alex Rivera"}),
        ("Zoe", "Park"):     (7, {"WS": None, "WD": "Mia Chen", "XD": "Jordn Kim"}),  # typo
        ("Ava", "Lopez"):    (6, {"WS": None, "WD": "Ivy Tran", "XD": "Sam Okafor"}),
        ("Ivy", "Tran"):     (5, {"WD": "Ava Lopez", "XD": "Tom Becker"}),
        ("Lena", "Costa"):   (6, {"WS": None, "XD": "Diego Santos"}),
        ("Nina", "Wells"):   (4, {"WS": None}),
    }
    rows = []
    for i, ((f, l), (skill, evmap)) in enumerate(people.items()):
        events = list(evmap)
        doubles = [e for e in events if e in ("MD", "WD", "XD")]
        partner = ", ".join(f"{evmap[e]}({e})" for e in doubles if evmap[e])
        rows.append(legacy_row(i, f, l, skill, events, partner=partner,
                               willing="No" if partner else ""))
    write_csv("legacy_mixed.csv", LEGACY_HEADERS, rows)


def build_legacy_messy():
    rows = []
    i = 0
    rows.append(legacy_row(i, "Pat", "Doyle", 5, ["MD"], partner="anyone is fine")); i += 1
    rows.append(legacy_row(i, "Casey", "Vue", 0, ["XD"], partner="")); i += 1  # bad skill
    rows.append(legacy_row(i, "Robin", "Fox", 6, ["MS", "WS"])); i += 1  # gender conflict
    rows.append(legacy_row(i, "Jamie", "Ako", 7, ["XD"], partner="I don't have one :(")); i += 1
    rows.append(legacy_row(i, "Taylor", "Reed", 6, ["MD"], partner="Taylro Reed")); i += 1  # self/typo
    rows.append(legacy_row(i, "Morgan", "Bui", 5, ["WD"], partner="Morgan Bui", willing="No")); i += 1
    rows.append(legacy_row(i, "Morgan", "Bui", 5, ["WD"])); i += 1  # duplicate registration
    write_csv("legacy_messy.csv", LEGACY_HEADERS, rows)


def build_clean_singles_16():
    rows = []
    for i in range(16):
        rows.append(legacy_row(i, "Mplayer", f"M{i:02d}", (i % 9) + 1, ["MS"], willing=""))
    for i in range(16):
        rows.append(legacy_row(i + 16, "Wplayer", f"W{i:02d}", (i % 9) + 1, ["WS"], willing=""))
    write_csv("clean_singles_16.csv", LEGACY_HEADERS, rows)


def build_strict_pairs():
    headers = ["Timestamp", "Event", "Club",
               "Player 1 First Name", "Player 1 Last Name", "Player 1 Email",
               "Player 1 Gender", "Player 1 Skill",
               "Player 2 First Name", "Player 2 Last Name", "Player 2 Email",
               "Player 2 Gender", "Player 2 Skill"]
    rows = []
    # Doubles pairs (both players explicit).
    pairs = [("XD", "Mia", "Chen", "F", 8, "Alex", "Rivera", "M", 8),
             ("XD", "Zoe", "Park", "F", 7, "Jordan", "Kim", "M", 7),
             ("MD", "Sam", "Okafor", "M", 6, "Diego", "Santos", "M", 7),
             ("MD", "Tom", "Becker", "M", 6, "Luis", "Moreno", "M", 5),
             ("WD", "Ava", "Lopez", "F", 6, "Ivy", "Tran", "F", 5)]
    for ev_, f1, l1, g1, s1, f2, l2, g2, s2 in pairs:
        rows.append(["01/03/2026 12:00:00", EVENT_TEXT[ev_], "BYU Badminton Club",
                     f1, l1, f"{f1.lower()}@example.com", "Male" if g1 == "M" else "Female", s1,
                     f2, l2, f"{f2.lower()}@example.com", "Male" if g2 == "M" else "Female", s2])
    # Singles (Player 2 blank).
    for f, l, g, s in [("Alex", "Rivera", "M", 8), ("Jordan", "Kim", "M", 7),
                       ("Mia", "Chen", "F", 8), ("Zoe", "Park", "F", 7)]:
        ev_ = "MS" if g == "M" else "WS"
        rows.append(["01/03/2026 12:00:00", EVENT_TEXT[ev_], "BYU Badminton Club",
                     f, l, f"{f.lower()}@example.com", "Male" if g == "M" else "Female", s,
                     "", "", "", "", ""])
    write_csv("strict_pairs.csv", headers, rows)


if __name__ == "__main__":
    build_legacy_mixed()
    build_legacy_messy()
    build_clean_singles_16()
    build_strict_pairs()
    print("Done. Import any of these from the admin tool (Import panel).")
