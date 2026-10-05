# 07 — Testing Strategy

## Running the tests

```bash
cd backend
python3 -m pytest tests/ -q
```

Configured in `pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = ["src"]`,
`asyncio_mode = "auto"` (needed for the evaluator's async tests). No network calls, no
API key, and nothing touches Google Sheets — everything runs against stubs and a frozen
local fixture.

## Domain unit tests (`tests/unit/test_rubric.py`, `test_ranking.py`)

Direct tests of `domain/rubric.py` and `domain/ranking.py`, with no mocks needed since
the domain layer has no I/O:

- `compute_weighted_score` checked against real historical applicants from the canonical
  workbook (cited by sheet and row in the test file), plus the weight-sum-to-1.0
  invariant on `RubricWeights`.
- `CriterionScore`'s evidence-consistency rule (must carry evidence, or explicitly flag
  `insufficient_evidence` — never both, never neither) tested directly against Pydantic's
  validation.
- `decision_tier` boundary tests at the exact tier cutoffs (4.0, 3.99, 3.0, 2.99).
- `strength_and_weakness`, including tie-breaking behavior and averaged (non-integer)
  scores.

## Evaluator tests (`tests/unit/test_prompt_caching.py`)

Tests `AnthropicRubricEvaluator` against stubbed Claude responses — no real API calls:

- The cached prefix is byte-for-byte identical across applicants and contains no
  applicant data or timestamp, so prompt caching actually triggers.
- A fabricated quote (one not present in the applicant's text) is dropped rather than
  kept; an empty or missing evidence list results in `insufficient_evidence=True`.
- A response truncated at the token cap (`stop_reason == "max_tokens"`) triggers exactly
  one retry at double the cap.
- Markdown code fences around the JSON response are stripped before parsing; malformed
  JSON raises a clear error rather than failing silently.
- `UsageLog` aggregates token counts correctly and never writes a raw applicant email to
  its log file (only a SHA-256 hash).

## Email deduplication tests (`tests/unit/test_email_dedup.py`)

Tests `norm_email()` directly from `evaluate_and_upload.py`: case variants, surrounding
whitespace, and all-caps all normalize to the same identity; `None`/empty don't crash;
repeat submissions within a single run collapse to one.

## Spreadsheet parity tests (`tests/parity/test_weighted_score_parity.py`)

The release-gate suite for "the backend's math matches the spreadsheet's own math." Uses
a frozen copy of the real rubric workbook (`fixtures/Fellowship_Scoring_Rubric_FINAL.xlsx`,
read with `data_only=True` so cached formula results are compared, not formula text):

- `compute_weighted_score` checked against each of `Scores_Emma`/`Scores_Lea`/
  `Scores_Director`'s own weighted-score column, and against the `Leaderboard` tab's
  averaged-score column.
- `decision_tier` checked against the `Leaderboard` tab's own "Decision Signal" column.
- `strength_and_weakness` checked against the `Leaderboard` tab's own Strength/Weakness
  columns.

If the canonical workbook's rubric or weights ever change, this fixture needs to be
refreshed deliberately as part of that change — it's a frozen snapshot, not something
that re-syncs automatically from a live sheet.