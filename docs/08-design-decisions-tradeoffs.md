# 08 — Design Decisions and Tradeoffs

Each entry: the decision, the alternatives considered, why we chose what we chose, and
what we gave up.

## D1. LLM never computes the weighted score, rank, or tier

**Decision:** The LLM's only output is per-criterion `{score, confidence, evidence}`
JSON. All arithmetic (weighting, ranking, tiering, reliability, strength/weakness) is
plain deterministic code.

**Alternatives considered:** (a) let the LLM output the weighted score directly and
sanity-check it; (b) let the LLM output a recommendation ("Interview"/"Reject").

**Why not (a):** LLM arithmetic is not guaranteed byte-identical across runs even at
temperature 0, which breaks the spreadsheet-parity requirement and reproducibility
requirement outright. A five-term weighted sum is also simply not something worth
spending model capability on.

**Why not (b):** This is the single clearest way an "AI-assisted scoring" project drifts
into "AI hiring bot." A recommendation label is one UI change away from being treated as
a decision, however many disclaimers surround it. Keeping the model's output strictly to
rubric-criterion evaluation makes the non-goal ("does not decide admissions") a property
of the type system, not a policy that can be silently violated.

**Cost:** Two-step pipeline (LLM call → deterministic engine) instead of one call. This
is a negligible latency cost (well under a second of added compute per applicant) for a
correctness and governance guarantee that is not negotiable.

## D2. Reproduce the spreadsheet's business rules, not just the written rubric

**Decision:** Decision Signal, Priority Status, Data Reliability, and Strength/Weakness
— all discovered in the live workbook, not the PDF — are first-class outputs of the
deterministic ranking engine.

**Why:** The project brief states the spreadsheet is canonical and takes precedence over
conflicting assumptions. Ignoring logic that already exists and is already relied on by
reviewers would make the new system a regression, not an upgrade, on day one.

**Cost:** Slightly larger ranking-engine surface area than the brief implied. The two
genuinely uncertain rules flagged here (reviewer quorum, AI's role relative to human
reviewers) were resolved in Phase 0 — see the resolved decisions in
[06](06-spreadsheet-reverse-engineering.md#resolved-decisions-fellowship-team-sign-off-phase-0)
and D11 below, which materially changed `Data Reliability`'s meaning rather than simply
confirming the workbook's literal behavior.

## D3. AI as a labeled reviewer, not a silent input

**Decision:** The AI's scores are stored and displayed as their own reviewer identity
(e.g. `Voter = "AI (gpt-x, prompt v3)"`), never blended into a human reviewer's row, and
never averaged into the weighted score without being visibly attributable.

**Alternatives considered:** Have the AI pre-fill a draft that a human overwrites in
place (no separate row).

**Why not the alternative:** it destroys the audit trail — you could no longer tell, a
year later, whether a given number was AI-originated or human-originated, which
undermines both auditability and the "reviewer corrections will be available after
deployment" assumption (Section 3 of the brief), which requires distinguishing AI output
from human correction to be usable as a feedback signal at all.

**Cost:** Requires the reviewer count/quorum question to be resolved explicitly with
Climate Cardinals rather than assumed — resolved in Phase 0 as AI-first with sampled
human spot-check, not a 4th-reviewer-alongside-3 model; see D11 below for the
consequences of that answer.

## D4. Structured output (JSON schema) over free-text + regex parsing

**Decision:** Use the model provider's native structured-output / tool-use mode to
constrain the LLM response to a validated JSON schema (see
[05-ai-evaluation-pipeline.md](05-ai-evaluation-pipeline.md)).

**Alternatives considered:** Prompt for free text, parse scores with regex; fine-tune a
model.

**Why not free text:** regex parsing of LLM prose is a recurring source of silent
failures (a reworded sentence breaks the parser, and the failure mode is a wrong score,
not a visible crash). Structured output makes malformed responses a loud, catchable
validation error instead.

**Why not fine-tuning:** explicitly excluded by the brief's non-goals ("must not train
foundation models"), and unnecessary — five well-specified rubric criteria with concrete
score-level descriptions is a strong prompting problem, not a fine-tuning problem. Revisit
only if post-launch calibration data shows systematic, prompt-engineering-resistant
miscalibration against reviewer scores (see [05](05-ai-evaluation-pipeline.md)).

**Cost:** None material; structured output is supported by all frontier model providers
we'd consider (see [15-technology-stack.md](15-technology-stack.md)).

## D5. RAG is not used for rubric evaluation

**Decision:** No retrieval-augmented generation. The full application text and the
versioned rubric are passed directly in context; there is no external knowledge base to
retrieve from.

**Why:** RAG solves the problem of grounding answers in a large, external, frequently
changing corpus. Here the only grounding source is the applicant's own submission
(already in hand, and typically well within context window limits) and the rubric
(a fixed, versioned, small document). Adding a retrieval layer would add latency, cost,
and failure modes (retrieval misses, chunk boundary artifacts splitting evidence) with
no corresponding benefit. Avoiding unnecessary complexity is an explicit brief
requirement (Section 10).

**Revisit condition:** if applications later include large supplementary artifacts
(portfolios, long-form essays across many documents) that don't fit in a single context
window, chunked retrieval becomes worth reconsidering — but not preemptively.

## D6. Google Sheets stays the reviewer system of record for the review workflow

**Decision:** The platform treats the Fellowship Google Sheet as a write target, not
something to replace with a new frontend for the reviewer's day-to-day scoring workflow.

**Why:** Reviewers already have a working, familiar tool with its own review habits
built around it (the triple-blind sheets, the Leaderboard view). Section 8's success
metric is reviewer efficiency, not adoption of new tooling. A parallel bespoke UI is a
change-management cost with no clear benefit at this scale (a few reviewers, 4,000
applications/cycle) versus writing into the tool they already trust.

**Cost:** The Sheets API has real constraints (rate limits, concurrent-edit conflicts,
schema drift if a reviewer manually edits a column) that a bespoke database-backed UI
would not have. These are handled explicitly — see
[07-google-sheets-integration.md](07-google-sheets-integration.md). The platform also
ships a minimal internal admin UI (see [01](01-system-architecture.md)) for ops
functions the Sheet can't do well (triggering runs, viewing audit logs, managing prompt
versions) — that UI is not a reviewer-facing scoring surface.

## D7. Confidence estimation is model self-reported, calibrated post-hoc

**Decision:** The LLM emits a 0–1 confidence per criterion as part of structured output.
This is treated as a raw signal, then calibrated against human-reviewer agreement data
once available (isotonic regression or Platt scaling over a held-out set), not trusted
at face value from day one.

**Why:** Raw LLM-reported confidence is known to be poorly calibrated out of the box. Not
calibrating it at all would be dishonest about what the number means; delaying launch
until a full calibration model exists would be over-engineering before any real
disagreement data exists. Ship with the raw signal clearly labeled "uncalibrated" in the
UI until enough reviewer-agreement data accumulates to calibrate it — an explicit,
visible caveat rather than a false precision.

## D8. Single relational store, not a vector database

**Decision:** Postgres for all structured data (applicants, scores, evidence, audit).
No vector database in the initial architecture.

**Why:** There is no semantic search or embedding-based retrieval requirement in this
system (see D5) — evidence is extracted spans from a specific application, looked up by
ID, not retrieved by similarity. Introducing a vector store without a concrete query
pattern that needs one is exactly the unnecessary complexity the brief warns against.

**Revisit condition:** if a future feature needs "find applications similar to this one"
or embedding-based duplicate detection, add a vector column/extension (e.g. `pgvector`)
at that point rather than provisioning for it now.

## D9. Ties broken deterministically by Applicant ID, not spreadsheet `RANK` semantics

**Decision:** The ranking engine breaks ties in weighted score by Applicant ID
(ascending), not by reproducing Excel/Sheets' `RANK()` shared-rank-with-gap behavior.

**Why:** `RANK()`'s tie behavior (e.g. two applicants tied for rank 3 both show "3", next
applicant shows "5") is an artifact of spreadsheet convention, not a considered policy
decision — reproducing it exactly adds complexity for a behavior nobody is likely to
actually want. Still unconfirmed by Climate Cardinals as of Phase 0 (unlike the other
three questions in [06](06-spreadsheet-reverse-engineering.md), which were resolved);
this remains our recommended default, reversible before Phase 1 sign-off if Climate
Cardinals staff prefer literal `RANK()` parity.

## D10. No autonomous retraining or online learning from reviewer corrections

**Decision:** Reviewer corrections are logged and made available for offline analysis
(calibration, prompt iteration, bias monitoring) but never automatically fed back into
prompt content or model weights without a human explicitly authoring the change.

**Why:** Automatic self-modification from feedback is an explicit non-goal
("continuous calibration" in Section 10 means measured and human-actioned, not a closed
automated loop) and a governance risk — an unsupervised feedback loop can silently drift
scoring behavior in ways nobody signed off on. Every prompt change goes through the same
versioning and review process as a code change (see
[05-ai-evaluation-pipeline.md](05-ai-evaluation-pipeline.md)).

## D11. AI-first evaluation with stratified human spot-check, not universal parallel human review

**Decision (Climate Cardinals, Phase 0):** the AI performs the complete first-round
rubric evaluation for every applicant, solo. Humans do not independently score every
applicant in parallel (as the canonical workbook's triple-blind model did); instead a
Spot-Check Sampling Service selects a stratified subset for human QA, with escalation
on any flagged discrepancy. Full design in
[08-ethical-risk-assessment.md](08-ethical-risk-assessment.md#r1a--ai-first-workflow-a-qualified-applicant-is-filtered-out-with-no-human-ever-reviewing-them).

**Alternatives considered:** (a) AI as a 4th reviewer alongside 3 full independent human
reviews (the original design's default assumption, preserving the workbook's model
unchanged); (b) AI replacing one of 3 human slots (2 humans + AI per applicant).

**Why this over (a)/(b):** neither alternative was actually proposed by Climate
Cardinals — both were engineering's attempt to extend the existing workbook model
conservatively. The organization's actual operational reality is that reviewer time
does not scale to independently re-scoring 4,000 applications per cycle three times
over; a solo-AI-first-pass model is what makes the platform actually usable at the
stated volume, which is the whole reason this project exists (see
[00-executive-summary.md](00-executive-summary.md)).

**Cost / residual risk — this is the largest tradeoff in the entire design, stated
plainly, not minimized:** under a full triple-blind model, a mis-scored applicant still
gets several independent human reads before any consequence follows. Under AI-first
with sampling, a mis-scored applicant who doesn't land in the sample gets **no** human
read. This is qualitatively different from every other risk in this document, because
the failure mode is a real person silently and permanently missing an opportunity they
should have gotten, with no record that anything went wrong. It is only acceptable
because of, and only to the extent that, the mitigations in
[08-ethical-risk-assessment.md](08-ethical-risk-assessment.md#r1a) are actually
implemented and taken seriously: stratified sampling weighted toward `do_not_advance`
and tier boundaries, mandatory sample expansion on any flagged discrepancy, a
near-universal spot-check rate during the Phase 6 pilot before any lower steady-state
rate is trusted, and a standing appeal path independent of sampling. Engineering's
responsibility here is to make sure the mitigation is real, not cosmetic — a sampling
service that exists on paper but samples too small a fraction, or isn't weighted toward
the highest-consequence tier, would make this decision materially less safe than it
looks in this document. This tradeoff should be revisited by Climate Cardinals
leadership after the Phase 6 pilot with real agreement data, not treated as settled
permanently by this design.

**What did not change despite this decision:** the core invariant of the whole system —
the LLM never computes a weighted score, rank, tier, or accept/reject decision (D1) —
holds exactly the same under AI-first-with-spot-check as it did under any other
reviewer-composition model. This decision changes *how much human attention* each
applicant gets before their AI-derived tier is acted on; it does not change *what the
AI is allowed to output* in the first place.
