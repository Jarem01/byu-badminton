# Sample data (fictitious)

Fake registrations for testing and demos — **all names are invented**. Import any
file from the admin tool (Import panel → Local CSV → paste the path, e.g.
`sample_data/legacy_mixed.csv`), or from the CLI:

```bash
python -m tournament.cli import --file sample_data/legacy_mixed.csv
```

| File | What it exercises |
|------|-------------------|
| `legacy_mixed.csv` | Realistic mix across all 5 events, legacy form layout (one row per person, per-event partner hints). Includes a deliberate typo ("Jordn Kim") so fuzzy matching + validation warnings show up. Good all-round demo. |
| `legacy_messy.csv` | Deliberately broken data: missing partners, prose in the partner field, an invalid skill, a men's+women's gender conflict (an error), and a duplicate registration. Use it to see the validation dashboard catch problems. |
| `clean_singles_16.csv` | 16 men's + 16 women's singles — clean power-of-two fields, ideal for testing single/double elimination without byes. |
| `strict_pairs.csv` | The redesigned one-submission-per-pair schema (see `docs/GOOGLE_FORM_SETUP.md`). Imports via the strict adapter with **no fuzzy matching** and explicit gender/skill. |

Regenerate them any time (deterministic):

```bash
python sample_data/generate_samples.py
```
