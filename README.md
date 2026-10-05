# Climate Cardinals Fellowship AI Evaluation Platform

An AI-assisted tool for scoring fellowship applications. It reads applications from an
Excel export, sends each eligible applicant's response to Claude for scoring against a
5-criterion rubric, and writes the scores to a Google Sheet — where the sheet's own
formulas handle ranking and tiering. It does not make hiring decisions; it produces
per-criterion scores with supporting evidence for a human reviewer.

Built for Climate Cardinals' own Fellowship Program. Several values are specific to our
rubric, application form, and spreadsheet — see **Before you reuse this** below for what
to change.

## What it does

- Loads applications from an `.xlsx` export and applies three eligibility checks.
- Loads the current rubric live from a Google Sheet tab (so the rubric and the prompt
  can't silently drift apart).
- Sends each eligible applicant's response to Claude in a single call, scoring all five
  rubric criteria together, with the rubric text cached across the run to keep cost down.
- Verifies every piece of "evidence" Claude returns is an actual verbatim quote from the
  applicant's own text before accepting it.
- Writes the resulting scores to a Google Sheet tab, skipping anyone already scored
  (safe to re-run after an interruption).

## How it's built

```
backend/
├── evaluate_and_upload.py       # CLI entry point — wires everything together
└── src/fellowship_eval/
    ├── domain/                  # Pure logic, no I/O
    │   ├── rubric.py            # criteria, weights, weighted-score formula
    │   ├── ranking.py           # decision-tier logic (not called by the live
    │   │                        # pipeline today — the Sheet's own formulas do
    │   │                        # this; kept here tested, for anyone who wants it)
    │   └── ports.py             # the RubricEvaluator interface adapters implement
    └── adapters/
        ├── data/                # Loads & filters applications from the xlsx
        ├── llm/                 # Claude integration (prompting, caching, retries)
        └── sheets/              # Reads the rubric from, and writes scores to, Sheets
```

There's no database, API server, or admin UI — just the two layers above plus the CLI
script. See `docs/01-technical-design.md` and `docs/02-ai-evaluation-pipeline.md` for the
full detail on each part.

## Before you reuse this

This was built around Climate Cardinals' specific rubric, application form, and
spreadsheet. The following are hardcoded and marked `CHANGE`/`REPLACE` in the code —
all of them need your own values before this will work for a different rubric or sheet:

- **Rubric criteria and weights** — `domain/rubric.py` (`RubricWeights`). The same five
  criterion names also appear hardcoded in `adapters/llm/anthropic_evaluator.py`'s output
  schema and in `evaluate_and_upload.py`'s score-extraction step — all three have to be
  edited together if your criteria differ in name or count.
- **The xlsx column layout and eligibility answers** — `adapters/data/application_loader.py`
  assumes a specific exported form layout: fixed column letters (e.g. column G is email,
  column Y is a "3–5 hrs/week" commitment question) and exact expected answer strings
  (e.g. `"Yes."`, `"Yes; I am authorized..."`). This file will need rewriting against
  your own form's export format.
- **The Google Sheet tab scores get written to** — defaults to `Scores_Director` in
  `evaluate_and_upload.py`.
- **Default file paths** — the xlsx path, Google credentials path, and Sheet ID in
  `evaluate_and_upload.py` are placeholders; pass your own via command-line flags (below)
  or edit the defaults directly.

## Setup

1. Python 3.9+
2. From `backend/`: `pip install -e .` (add `[dev]` for the test dependencies — see
   `pyproject.toml`)
3. Set `ANTHROPIC_API_KEY` in your environment
4. Create a Google Cloud service-account, download its credentials JSON, and share your
   target Google Sheet with that service account's email (edit access)
5. Your Sheet needs a `Rubric [AGENT]` tab in the format the rubric loader expects — see
   `docs/03-spreadsheet-reverse-engineering.md`

## Running it

```bash
cd backend
python3 evaluate_and_upload.py \
  --xlsx <path_to_applications.xlsx> \
  --sheet-id <your_google_sheet_id> \
  --credentials <path_to_gcp_credentials.json>
```

Useful flags:

- `--dry-run` — verifies the setup (credentials, rubric loading, prompt structure) and
  makes no API calls and no Sheet writes.
- `--no-upload` — runs real evaluations against Claude but doesn't write results to the
  Sheet.
- `--limit N` — stops after N applicants, for a small real test run.

Results are saved to the Sheet every 100 applicants, so an interruption costs minutes of
work, not the whole run — re-running picks up where it left off and skips anyone already
scored.

## Tests

```bash
cd backend
python3 -m pytest tests/ -q
```

Includes unit tests for the scoring/ranking logic and a parity test suite that checks the
weighted-score math against the spreadsheet's own cached formula results.

## Documentation

The `docs/` folder has the fuller design writeup — start with
[docs/00-executive-summary.md](docs/00-executive-summary.md), which links to the rest.

## License

No license is included yet — add one here before treating this code as free for others
to reuse.