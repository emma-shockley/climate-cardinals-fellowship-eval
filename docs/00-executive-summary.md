# 00 — Executive Summary

## What this system is

The Climate Cardinals Fellowship AI Evaluation Platform performs the complete
first-round rubric evaluation of every Fellowship application, at scale, replacing the
fully-manual triple-reviewer process Climate Cardinals has run to date. It does not
decide who is admitted. It reads each application, scores it against the five official
rubric criteria — Growth Potential, Demonstrated Interest in Social Impact, Demonstrated
Commitment, Team Orientation, and Demonstrated Initiative / Willingness to Learn —
attaches evidence and a confidence estimate to every score, computes the same weighted
formula the current spreadsheet uses (25/25/20/15/15), and writes the result into the
same Google Sheet reviewers already use.

## Why now

At ~6,500 applications per cycle across 100+ countries, the current fully-manual
process does not scale linearly with reviewer time. The instinct to "speed this up with
AI" is reasonable; the risk is doing it in a way that quietly becomes an admissions
decision engine. This spec exists to prevent that outcome by design, not by policy
alone: the LLM is architecturally barred from computing scores, ranking applicants, or
outputting accept/reject decisions. Those are deterministic backend computations and
human judgment calls, respectively — never a model's output.

## What we found reverse-engineering the canonical workbook

The Excel/Google Sheet Climate Cardinals already uses (03-spreadsheet-reverse-engineering.md)
turned out to specify more than the written rubric: a triple-blind review model (up to
3 independent reviewers per applicant, reconciled by averaging, never overwritten), and
business rules beyond the rubric itself — Decision Signal (tier bucket from the weighted
score) and Strength/Weakness (min/max scoring criterion) both made it into the actual
ranking code. A third rule found in the workbook, Priority Status (multilingual /
Climate-Cardinals-member flagging), was implemented manually. The triple-blind reviewer
model itself is **superseded** by Climate Cardinals' decision to run AI-first instead
(see [03](03-spreadsheet-reverse-engineering.md#resolved-decisions-fellowship-team-sign-off-phase-0)).

## System shape, in one paragraph

An application arrives → a structured-output LLM call scores each of the 5 rubric
criteria independently, with evidence quotes and a confidence score, refusing to guess
when evidence is absent → a deterministic scoring engine computes the weighted score, tier,
and strength/weakness → results are written into the Fellowship Google Sheet. 

## What "done" looks like

- Every AI-produced score has an evidence trail a reviewer can check in under 30 seconds.
- The backend's weighted-score output is byte-for-byte identical to the spreadsheet's
  formula, verified by an automated parity test suite (see
  [07-testing-strategy.md](07-testing-strategy.md)).
- No score, rank, or "interview/reject" label is ever computed inside a prompt.
- Every prediction is reproducible from (application text, prompt version, model
  version) alone.

## What this is not

Not a hiring bot. Not a replacement for reviewers. Not a system that infers protected
characteristics, fabricates evidence, or gets to skip explaining itself. See
[05-ethical-risk-assessment.md](05-ethical-risk-assessment.md) for the full non-goal
enforcement mechanisms.

## Document map

| # | Document | Answers |
|---|---|---|
| 01 | [Technical Design](01-technical-design.md) | Component-level design
| 02 | [AI Evaluation Pipeline](02-ai-evaluation-pipeline.md) | Prompting, structured output, model strategy |
| 03 | [Spreadsheet Reverse Engineering](03-spreadsheet-reverse-engineering.md) | What the canonical workbook actually specifies |
| 04 | [Google Sheets Integration](04-google-sheets-integration.md) | How writes land in the reviewer-facing sheet |
| 05 | [Ethical Risk Assessment](05-ethical-risk-assessment.md) | What could go wrong, and the control that prevents it |
| 06 | [Bias Mitigation Strategy](06-bias-mitigation-strategy.md) | How fairness would be measured and monitored |
| 07 | [Testing Strategy](07-testing-strategy.md) | Parity tests, bias tests, load tests |
| 08 | [Design Decisions & Tradeoffs](08-design-decisions-tradeoffs.md) | Why, with alternatives considered |
