# 05 — Ethical Risk Assessment

## Method

For each non-goal in the project brief (Section 2), we state the concrete way it could
be violated in practice, the architectural control that prevents it, and the residual
risk that remains even with the control in place.

## Risk register

### R1 — The system quietly becomes a decision-maker

**How it could happen:** a "Decision Signal" tier or rank gets treated by a downstream
process (or a rushed reviewer) as sufficient justification to reject, without a human
actually reading the application.

**Control:** the LLM's output schema has no field representing accept/reject/interview
(see [02-ai-evaluation-pipeline.md](02-ai-evaluation-pipeline.md), closing paragraph) —
`decision_tier` is a deterministic label computed from the rubric score, always paired
with the full evidence trail wherever it's shown. Nothing in the pipeline outputs a
final admissions verdict.

**Residual risk:** a control on the software cannot fully prevent an organizational
process failure (a reviewer who stops reading applications and just filters by tier).
This is a training/process risk Climate Cardinals staff, and other users of this project,
need to own — recommend an explicit reviewer-facing statement of how AI scores should and
shouldn't be used.

### R1a — AI-first workflow: a qualified applicant is filtered out with no human ever reviewing them

**This is the single highest-consequence risk in the system**, introduced directly by
the confirmed Phase 0 decision that the AI performs the complete first-round evaluation
for every applicant, with humans reviewing only a sampled subset afterward - see
[03-spreadsheet-reverse-engineering.md].

Under a full triple-blind human model, a wrongly-scored applicant still gets several
independent human reads. Under AI-first-with-spot-check, an applicant the AI
mis-scores low is, by default, never seen by a human at all unless they land in the
sample. A silent false negative here is not a data-quality bug — it is a real person
who never got the fellowship they should have, with no one aware it happened.

**How it could happen:** the AI systematically undervalues a legitimate but unusual
way of demonstrating a criterion (e.g. informal community organizing that doesn't read
as "founding an initiative"), and every affected applicant lands in "Do not advance"
with no human ever reading their file.

**Control — the spot-check sampling design is not incidental, it is the primary
mitigation for this risk, and is specified deliberately:**

1. **Stratified, not purely random, sampling.** Every ranking recompute should produce a
   spot-check assignment batch drawn with guaranteed minimum coverage across two axes:
   - **Every decision tier**, weighted toward `do_not_advance` — because a false
     negative there (a good applicant silently dropped) is far more consequential than
     a false positive in `interview` (which gets a full human interview anyway,
     providing a natural second check). This is a policy tradeoff (reviewer time
     vs. false-negative risk) the program should own explicitly, not a number
     the CPO picks unilaterally.
   - **Every `cohort_team`** so no applicant subgroup is structurally under-checked,
      and so any bias monitoring retains enough statistical power to detect a subgroup-specific
      problem instead of just an aggregate one.
   - Applicants near a tier **boundary** are also over-sampled — boundary cases are
     exactly where a small scoring error changes the outcome, and exactly where AI
     miscalibration is hardest to see in aggregate metrics.
2. **Discrepancy escalation, not just logging.** If a spot-check human's independent
   score materially diverges from the AI's, that applicant should be flagged, and they should
   **automatically expand the spot-check sample** to pull additional applicants who scored similarly
   to the flagged one on the same criterion. One caught discrepancy is treated as evidence of a
   possible systematic pattern, not an isolated miss, until a wider check confirms otherwise.
3. **A standing appeal/reconsideration path** independent of sampling: any mechanism
   Climate Cardinals already has (or adopts) for an applicant or referrer to request a
   second look is a valid backstop this design should not assume away.
4. **Full-audit fallback.** Regardless of the steady-state spot-check rate, the first
   live cycle running this system should use a much higher spot-check rate — near-
   universal human review — specifically to build a real AI-vs-human agreement
   baseline before trusting a lower steady-state sampling rate.

**Residual risk:** stratified sampling reduces but cannot eliminate this risk — an
applicant with an unusual profile that doesn't fall into any over-sampled stratum, and
who the AI happens to mis-score, can still fall through. This is the clearest reason
agreement-with-reviewers and low-hallucination-rate must be tracked continuously and
taken seriously as gating criteria, not just launch-day validation.

### R2 — Inferring protected characteristics from application content

**How it could happen:** an applicant's name, school, city, or writing style correlates
with race, nationality, gender, or socioeconomic status, and the model's score is
influenced by that correlation even without being asked to score it directly — this is
the classic "proxy discrimination" failure mode of NLP-adjacent scoring systems, and
it's structural, not something a single prompt instruction eliminates outright.

**Control:** (a) explicit prompt-level prohibition (see
[02-ai-evaluation-pipeline.md](02-ai-evaluation-pipeline.md)); (b) no protected
characteristic is ever passed to the LLM call; (c) any bias monitoring that exists
should statistically check score distributions for correlation with available
legitimate metadata as an early-warning signal.

**Residual risk:** this is the hardest non-goal to fully guarantee, because the proxy
signal lives in free text the model must read to do its job at all — you cannot redact
"where I grew up" out of an essay about growth potential without destroying the
essay's substance. This is why ongoing measurement matters, not a one-time fix: its
findings should feed prompt revisions, with versioning/review.

### R3 — Fabricated or hallucinated evidence

**How it could happen:** the model states "the applicant describes founding a
nonprofit" when no such statement exists in the application.

**Control:** structural (schema-enforced) evidence citation (see
[02-ai-evaluation-pipeline.md](02-ai-evaluation-pipeline.md)) — a quote should be an
actual substring of the application text, never accepted as a loose paraphrase.

**Residual risk:** a grounding check verifies a quote *exists* in the text; it does
not verify the quote is being *characterized correctly* (a real quote used to support a
wrong conclusion isn't caught by substring matching). This is exactly what showing the
actual quoted text next to the score addresses at the human level — a reviewer can (and should!)
judge the characterization themselves in seconds.

### R4 — Insufficient evidence gets silently guessed instead of flagged

**How it could happen:** an application says nothing about team collaboration, and the
model produces a plausible-sounding but invented score rationale rather than admitting
the gap.

**Control:** `insufficient_evidence` is a required, validated boolean field with its own
consistency check (cannot be true alongside populated evidence, cannot be false with
zero evidence) — see the Pydantic validator in
[02-ai-evaluation-pipeline.md](02-ai-evaluation-pipeline.md).

**Residual risk:** a model can still under- or over-flag this in genuinely ambiguous
cases (partial-but-thin evidence).

### R6 — Reviewer over-trust / automation bias

**How it could happen:** under the confirmed AI-first workflow (R1a), the spot-check
reviewer's entire job is to check the AI's work — which is precisely the setup most
prone to automation bias in the human-factors literature (a person asked to verify a
system that's "usually right" tends to converge toward rubber-stamping it, especially
under time pressure with thousands of applicants to get through). This risk is sharper
here than in a general AI-assist tool, because spot-check reviewers are not forming
their own independent opinion first (as the old triple-blind model did) — they may
anchor on the AI's score before reading closely.

**Control:** every AI score is shown with its confidence (labeled uncalibrated until
proven otherwise) and its evidence, so a reviewer is prompted to actually read the
excerpt, not just the number. Recommend that whatever interface a human uses for
spot-checking require them to record their own score **before** revealing the AI's
score and evidence side-by-side (a blind-then-reveal pattern) — this preserves an
independent judgment to compare against, rather than inviting anchoring from the
outset.

**Residual risk:** a software design can make disengagement harder, not impossible —
periodic audits of agreement patterns (e.g. a spot-check reviewer whose scores are
suspiciously always identical to the AI's) are worth tracking if this workflow is
ever run at scale.

## Ethical principles checklist, mapped to concrete mechanisms that actually exist

| Principle | Mechanism | Where specified |
|---|---|---|
| Transparency | Every score ships with evidence + explanation, visible in the Sheet | [02](02-ai-evaluation-pipeline.md) |
| Explainability | Structured evidence citations | [02](03-ai-evaluation-pipeline.md) |
| Confidence estimation | Per-criterion confidence, labeled uncalibrated until proven | [02](03-ai-evaluation-pipeline.md) |
| Human accountability | AI as a labeled reviewer among humans; no decision output exists | [08](08-design-decisions-tradeoffs.md) D1, D3 |