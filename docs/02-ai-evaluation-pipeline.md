# 02 — AI Evaluation Pipeline

## Model strategy

**Single frontier LLM call per applicant, JSON output requested via prompt, no fine-tuning,
no RAG, no embeddings.** The task — grade this application against a well-specified
5-criterion rubric — is in-distribution for instruction-following frontier models given a
clear prompt and the rubric's own concrete score-level language (see
[03-spreadsheet-reverse-engineering.md](03-spreadsheet-reverse-engineering.md)). Fine-tuning
or retrieval would add cost, latency, and failure surface without solving a problem that's
actually been observed — see D4/D5/D8 in
[08-design-decisions-tradeoffs.md](08-design-decisions-tradeoffs.md) for the fuller
reasoning.

**Model:** set as `AnthropicRubricEvaluator.model_version` in
`adapters/llm/anthropic_evaluator.py`, called through the `RubricEvaluator` interface (see
[01-technical-design.md](01-technical-design.md)) so swapping models doesn't touch
orchestration code.

## Pipeline shape

Combining these five scores into a weighted score or a decision tier happens afterward, in
`domain/rubric.py` and `domain/ranking.py` — see
[01-technical-design.md](01-technical-design.md). Nothing in this document computes that.

## Prompt design

One call evaluates all five criteria together, not five separate calls — it's cheaper, and
it gives the model the whole application in context once rather than risking inconsistent
reads of the same fact across separate calls.

The prompt is built by `build_static_prompt()` in `anthropic_evaluator.py` as a single
Python f-string — there's no separate template file or templating engine, and no version
history beyond normal git history on that function. Structure:

1. **Role framing:** the model is told it's producing scores for human review, not making
   the hiring decision.
2. **Rubric injection:** the actual rubric text, loaded fresh from the Google Sheet each run
   (cached within that run) — never hand-typed into the prompt, so the prompt and the sheet
   can't silently drift apart.
3. **Critical instructions:** don't hallucinate evidence — if none can be found for a
   criterion, score it 1, leave evidence empty, and write exactly "Insufficient evidence" as
   the explanation; quotes must be verbatim; all five criteria must be scored every time.
4. **Length limits:** at most one quote per criterion (≤25 words), each explanation ≤15
   words. These are kept deliberately tight — short answers are what keep responses from
   running into the output-token cap (see Truncation handling, below).
5. **Prompt-injection defense:** an explicit "UNTRUSTED INPUT" instruction telling the model
   the application text is data, not commands — if it contains anything that reads as an
   instruction, that's evidence about the applicant, not something to obey.
6. **Response format:** the JSON schema shown below, as literal text in the prompt.

## Output schema

— repeated once per rubric criterion. The five criterion keys (`growth_potential`,
`social_impact`, `commitment`, `team_orientation`, `initiative`) are hardcoded in
`_SCHEMA`/`_CRITERION_SHAPE` in `anthropic_evaluator.py`.

**CHANGE THIS IF YOUR RUBRIC'S CRITERIA DIFFER** (names or count) — these five names have to
match, exactly, in three places: this schema, the `CriterionName` enum in
`domain/rubric.py`, and however your own rubric loader parses your sheet. Nothing currently
enforces that the three stay in sync; update all three together.

This schema is requested in the prompt text — it is **not** enforced by Claude's API as a
structured-output or tool-use constraint, so there's no schema-level guarantee the response
actually matches this shape. Instead, the code strips markdown fences if the model wraps its
JSON in them anyway, calls `json.loads()`, and raises a clear error (logging a preview of the
bad response) if parsing fails. There's no automatic "retry with a correction prompt" on a
parse failure — it's just an exception that propagates up to the per-applicant error handling
in `evaluate_and_upload.py` (see [01-technical-design.md](01-technical-design.md)).

## Evidence grounding

After parsing, every evidence quote is checked locally, in `_to_domain()`
(`anthropic_evaluator.py`), against the applicant's actual submitted text: the quote
(whitespace-normalized) must appear verbatim as a substring, or it's dropped and a warning is
logged. A quote never reaches a human reviewer labeled as verified evidence if it isn't
actually in the application. A criterion ends up with `insufficient_evidence=True` whenever
it has zero evidence left after this check — whether because the model reported none, or
because every quote it gave didn't actually match. The model is never asked to self-report an
"insufficient evidence" flag; that boolean is computed from what evidence survives
verification.

## Truncation handling

The output cap (`max_tokens`) is sized for five short quote-plus-explanation pairs with
headroom. If a response is cut off mid-JSON (`stop_reason == "max_tokens"`), that's
unparseable, so the evaluator retries once with double the cap before giving up.

## Retries

Transient errors — rate limits, 5xx responses, timeouts, connection errors, matched against a
fixed list of substrings in the error message — get up to 3 attempts with exponential backoff
plus jitter. Anything else (a genuine bad request, an auth failure, a JSON parse failure) is
not retried and raises immediately.

## Cost: prompt caching

The prompt is split into a static part (role + rubric + rules + schema — identical for every
applicant in a run, built once per evaluator instance and cached via
`cache_control: ephemeral`) and a dynamic part (just that one applicant's text). Anthropic
bills the static part once per run and a cheaper cache-read rate on every applicant after the
first. This only works because the static part never contains per-applicant data, a
timestamp, or a run ID — any of those would silently break the cache and restore full-price
billing on every call. `static_prompt_hash()` gives a short hash of the cached text, for
confirming in logs that the cache is actually stable run to run.

## Usage logging

When a `usage_log` is supplied to the evaluator, every call records input/output token
counts, cache-creation and cache-read token counts, `stop_reason`, whether the response was
truncated, and the static prompt's hash — for tracking per-run cost and catching unexpected
cache misses.

## What the LLM is never asked to do

The LLM's output schema has no field for a weighted score, a rank, a tier label, or an
accept/interview/reject decision — it returns a 1-5 score, a confidence, evidence, and a
short explanation per criterion, and nothing else. That's a structural constraint (the schema has no such field), not just an instruction the model is trusted to follow.