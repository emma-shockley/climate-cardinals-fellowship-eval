# 03 — Spreadsheet Reverse Engineering Report

## Purpose

This document is the authoritative mapping between the canonical Google Sheet
(`Fellowship_Scoring Rubric [FINAL].xlsx`, exported from Google Sheets — confirmed by
the `__xludf.DUMMYFUNCTION` wrapper Google's xlsx exporter uses to preserve
Sheets-only functions like `FILTER`, `SORT`, `UNIQUE`, `XLOOKUP`) and the system we are
building. Every field, formula, and business rule below was extracted directly from the
workbook, not inferred. Per the project spec, **this workbook is canonical** — if
anything in this report conflicts with an earlier assumption elsewhere, this report wins.

The workbook contains eight sheets. One of them (`Leas Version`) is a vestigial template
from an unrelated program and is explicitly out of scope. The other seven form a single
pipeline: three independent reviewer-entry sheets feed a union sheet, which feeds an
aggregation sheet, which feeds a sorted, decision-annotated leaderboard. The system we
build must reproduce this exact pipeline in code, because the Google Sheet is not being
retired — it is the reviewer-facing surface the backend writes into (see
[07-google-sheets-integration.md](07-google-sheets-integration.md)).

## Sheet inventory

| Sheet | Role | Populated rows (sample) | Notes |
|---|---|---|---|
| `Rubric` | Static reference copy of the PDF rubric | 8 rows | Read-only reference; not computed |
| `Scores_Emma` | Reviewer A's raw score entry | 9 data rows (grid provisioned to 43,670) | One reviewer, one row per applicant |
| `Scores_Lea` | Reviewer B's raw score entry | 4 data rows (grid provisioned to 998) | Same shape as `Scores_Emma` |
| `Scores_Director` | Reviewer C's raw score entry | 4 data rows (grid provisioned to 998) | Same shape as `Scores_Emma` |
| `Scores_Master` | Union of all three reviewer sheets | Derived (28 rows in sample) | Single `FILTER({...})` array formula |
| `Results` | Per-applicant aggregation across reviewers | Derived | `AVERAGEIF`/`COUNTIF`/`RANK` per applicant |
| `Leaderboard` | Sorted, decision-annotated view of `Results` | Derived | Adds priority, decision-signal, reliability, strength/weakness columns |
| `Leas Version` | Unrelated grant-regranting rubric template (0–40/0–30/0–20/0–10 scale, different program) | N/A | **Out of scope.** Not part of the Fellowship scoring model; do not port into the new system. Flagged for cleanup in the source sheet. |

## 1. `Rubric` sheet — static reference

Row 1: title. Row 2: decision-tier legend (`≥4.0 → Interview`, `3.0–3.99 → Secondary
Tier`, `<3.0 → Do not advance`). Rows 3–8: a 5-row × 5-column grid — one row per score
level (5=Excellent … 1=Very Poor), one column per criterion — reproducing the PDF rubric
verbatim. This sheet has no formulas; it exists so reviewers can see the rubric text
next to their scoring sheet. In our system this content becomes the versioned rubric
definition consumed by the prompt template (see
[05-ai-evaluation-pipeline.md](05-ai-evaluation-pipeline.md)) and displayed in the
reviewer UI — never re-typed, always sourced from one place.

## 2. `Scores_Emma` / `Scores_Lea` / `Scores_Director` — reviewer entry sheets

Identical schema across all three:

| Col | Header | Type | Source |
|---|---|---|---|
| A | Applicant ID | string, manual | Reviewer types e.g. `Fellow_1` |
| B | Growth Potential | integer 1–5, manual | Reviewer judgment against rubric |
| C | Demonstrated Interest in Social Impact | integer 1–5, manual | " |
| D | Demonstrated Commitment | integer 1–5, manual | " |
| E | Team-Orientation | integer 1–5, manual | " |
| F | Demonstrated Initiative / Willingness to Learn | integer 1–5, manual | " |
| G | Weighted Score | float, **array formula** | `=IF(A#="","", B#*0.25 + C#*0.25 + D#*0.2 + E#*0.15 + F#*0.15)` spilled down the whole column |
| H | Voter | string, **array formula, hardcoded per sheet** | `=IF(A#="","","Emma")` (or `"Lea"`/the director's name) — auto-stamps the reviewer identity on any row that has an Applicant ID |
| I | Team | string, manual | e.g. `TeamHere` — identifies the reviewer pod/cohort an applicant batch belongs to |

**This is the exact weighted-score formula the project spec describes in Section 6**,
confirmed independently in the live workbook: weights of 0.25 / 0.25 / 0.20 / 0.15 / 0.15
across Growth Potential, Social Impact, Commitment, Team-Orientation, and Initiative,
summing to 1.00. Our deterministic scoring engine must reproduce this formula exactly,
including using the criterion order above (it also matches the display order in
`Rubric`, `Results`, and `Leaderboard`).

Three independent reviewer sheets is a deliberate design, not an accident: it is a
**triple-blind review** model — each reviewer scores independently without seeing the
others' scores, and reconciliation happens downstream in `Scores_Master`/`Results`. This
directly shapes the data model (scores must be stored per-reviewer, never overwritten by
a later reviewer) and the workflow (the platform must support N reviewers per applicant,
not just one AI pass).

## 3. `Scores_Master` — union of all reviewer sheets

One array formula in `A2` spills the entire sheet:

```
=FILTER(Scores_Emma!A2:I3495, Scores_Emma!A2:A3495<>"");
 FILTER(Scores_Lea!A2:I3495, Scores_Lea!A2:A3495<>"");
 FILTER(Scores_Director!A2:I3495, Scores_Director!A2:A3495<>"")
```

(Google Sheets `{a;b;c}` vertical-stack syntax — stack the three reviewers' non-blank
rows into one long table.) Same 9-column schema as the reviewer sheets. This is a pure
row-level union — **no deduplication and no aggregation happens here**. One applicant
scored by three reviewers produces three rows in `Scores_Master`, keyed by
`(Applicant ID, Voter)`. This is the natural primary key for the `rubric_scores` table
in our data model (see [03-data-model.md](03-data-model.md)) — one row per
(applicant, reviewer, evaluation run).

## 4. `Results` — per-applicant aggregation

Row 2 unique-applicant discovery: `=SORT(UNIQUE(FILTER(Scores_Master!A2:A1000,
Scores_Master!A2:A1000<>"")))` — dedupes `Scores_Master` down to one row per applicant.

Per-criterion aggregation (repeated for columns B–F, one per rubric criterion):
`=IF(A#="","",AVERAGEIF(Scores_Master!A:A, A#, Scores_Master!B:B))` — the **simple
arithmetic mean across all reviewers who scored that criterion for that applicant**.
Column G (Avg Weighted Score) is the same `AVERAGEIF` pattern applied to
`Scores_Master!G:G`, i.e. **the average of each reviewer's already-weighted score**,
which is mathematically identical to weighting the averaged criteria (both reduce to the
same linear combination since averaging and the weighted sum are both linear operators).
Column H is `=COUNTIF(Scores_Master!A:A, A#)` — the number of reviewer scores found for
that applicant. Column I is `=RANK(G#, $G$2:$G1000, FALSE)` — descending rank by average
weighted score, ties broken by Excel/Sheets' standard `RANK` behavior (shared rank,
gap in sequence).

Three columns are **not derived from reviewer scoring at all** — they are manually
entered per applicant, presumably from the original application form/intake data:

- **J — Multilingual? (Y/N)**
- **K — Climate Cardinals Membership? (Y/N)**
- **L — Regular Internet Connection / Ability To Join Meetings Online? (Y / N / S)** —
  a three-state field (`S` = "sometimes"/spotty, seen in sample data), not boolean.

Column M (Team) is looked up via an array `XLOOKUP` against `Scores_Master!I:I` keyed on
Applicant ID (assumes a given Applicant ID maps to exactly one Team across all its
reviewer rows).

**Design implication:** applicant metadata (language, org membership, connectivity) is a
separate data source from rubric scoring and must be modeled as its own field group on
the `applicants` table, ingested from the application intake form — never inferred or
scored by the LLM. This is consistent with the non-goal of not inferring protected or
adjacent characteristics; these three fields are self-reported operational logistics
fields, not judgment scores, and must stay clearly separated from the rubric dimensions
in both the schema and the UI.

## 5. `Leaderboard` — sorted, decision-annotated view

Row 1 is `Results` row 1 verbatim; row 2 onward is
`SORT(FILTER(Results!A2:L1000, Results!A2:A1000<>""), 9, TRUE)` — i.e. `Results` sorted
ascending by column 9 (Rank). This is the sheet reviewers actually work from. Beyond
the columns already in `Results`, `Leaderboard` adds seven **derived decision-support
columns that are the real specification for the human-facing output** the project spec
in Section 7 only partially anticipates. These must be reproduced by our scoring/ranking
engine, not left as a spreadsheet-only afterthought:

| Col | Header | Formula (paraphrased) | Business rule |
|---|---|---|---|
| M | Priority Status | `IF(J="Y" AND K="Y", "High Priority", IF(J="Y" OR K="Y", "Priority", ""))` | Multilingual **and** CC-member ⇒ High Priority; either one alone ⇒ Priority; neither ⇒ blank |
| N | Internet Connectivity Status | `IF(L="N","No Internet", IF(L="S","Connection Issues",""))` | Flags applicants who may need scheduling accommodation |
| O | Decision Signal | `IF(G>=4,"Interview", IF(G>=3,"Secondary Tier","Do not advance"))` | **This is the exact tier logic from the PDF rubric's decision legend**, applied automatically off the average weighted score |
| P | Data Reliability | `IF(H=3,"✓ Reliable","⚠ Missing Scores")` | Flags any applicant who does **not** have exactly 3 reviewer scores — i.e. the reconciliation step requires a fixed quorum of reviewers (3) before a Decision Signal should be trusted |
| Q | Team | `XLOOKUP` against `Scores_Master!I:I` | Same lookup as `Results!M` |
| R | Strength | `INDEX(criteria_labels, MATCH(MAX(B:F), B:F, 0))` | The single highest-scoring rubric criterion, by label |
| S | Weakness | `INDEX(criteria_labels, MATCH(MIN(B:F), B:F, 0))` | The single lowest-scoring rubric criterion, by label |

Two of these rules materially extend what the project spec described and **must be
carried into the backend scoring engine** as first-class, deterministic, non-LLM
computations:

1. **The reviewer quorum of exactly 3.** `Data Reliability` is binary on `H=3`, not
   `H>=3` — a 4th or 5th score (e.g. a tie-breaker review) would currently flip an
   applicant to "⚠ Missing Scores" under the literal spreadsheet formula, which is very
   likely a workbook limitation (it was built assuming exactly 3 fixed reviewers) rather
   than an intentional rule. This is a discrepancy to confirm with the Fellowship team
   before encoding it verbatim — see the open question below — but until confirmed we
   should implement the config as "reliable if scored by all required reviewers for the
   applicant's assigned review pool" with the required count as a config value
   (`config.required_reviewer_count`, default 3), not a hardcoded literal.
2. **Strength/Weakness by min/max criterion.** This is a purely arithmetic derivation
   over the five rubric scores and belongs in the deterministic scoring engine
   alongside the weighted-score computation — never delegated to the LLM, since it is
   just an argmax/argmin over numbers already produced.

`Priority Status` and `Internet Connectivity Status` are pure business rules over
applicant intake metadata (not scores) and belong in the ranking/reporting layer, not
the AI evaluation layer.

## Consolidated column-to-system mapping

| Spreadsheet column (final, `Leaderboard`) | System field | Computed by |
|---|---|---|
| Applicant ID | `applicants.applicant_id` | Intake |
| Growth Potential … Initiative (×5) | `rubric_scores.criterion_score` — **AI score by default**, human spot-check score recorded separately, never silently blended (see below) | AI Evaluation Service (deterministic aggregation only if a spot-check occurred) |
| Avg Weighted Score | `weighted_scores.weighted_score` | Scoring engine (deterministic, §6 formula), computed from the AI score unless a spot-check has superseded/flagged it |
| # of Votes | Replaced — see "Reviewer model" below | — |
| Rank | `rankings.rank` | Ranking engine |
| Multilingual / CC Membership / Internet | `applicants.multilingual`, `.cc_member`, `.connectivity_status` | Intake, not scoring |
| Priority Status / Internet Connectivity Status | Ranking engine output (business rule, not stored score) | Ranking engine |
| Decision Signal | Ranking engine output from rubric tier thresholds | Ranking engine (config-driven thresholds, not hardcoded) |
| Data Reliability | **Redefined** — see "Reviewer model" below | Ranking engine |
| Strength / Weakness | Ranking engine output (argmax/argmin over 5 scores) | Ranking engine |
| Team | `applicants.cohort_team` — confirmed to mean **applicant program track/cohort**, not reviewer pod | Intake |

## Resolved decisions (Fellowship team sign-off, Phase 0)

The canonical workbook's `Scores_Emma`/`Scores_Lea`/`Scores_Director` model assumed
**every** applicant gets 3 independent full human reviews. Climate Cardinals has
decided to run a different workflow going forward: **the AI performs the complete
first-round evaluation solo, for every applicant; humans spot-check a sample
afterward for QA rather than fully re-reviewing everyone.** This is a real workflow
change, not just an implementation detail, and it changes what several of the
workbook's columns mean in the new system. Resolved:

1. **Reviewer quorum.** Decided: reliability is "all reviewers assigned to this
   applicant have submitted a score," not a hardcoded count of 3. In the new
   AI-first workflow this generalizes further — see `evaluation_source` /
   `spot_check_status` below, which replace the old exact-3 `Data Reliability` concept
   entirely for the default flow.
2. **AI's role relative to human reviewers.** Decided: **AI-first, human spot-check**
   — the AI is not a 4th reviewer alongside 3 full human reviews, and it does not
   occupy one of 3 human slots either. It is the sole first-pass evaluator for 100% of
   applicants. Humans review a sampled subset afterward as quality assurance, not as
   independent parallel scoring of everyone. This is a materially different — and
   materially higher-risk — model than either option originally proposed (see
   [08-ethical-risk-assessment.md](08-ethical-risk-assessment.md) R1/R6 for why, and
   the new spot-check design below for the mitigation). It supersedes the triple-blind
   model from the canonical workbook for the default flow; the workbook's 3-reviewer
   mechanism is preserved only as the *shape* of the spot-check process (a human score
   recorded independently, reconciled against the AI's, never overwriting it).
3. **`Team` field.** Confirmed: applicant cohort/track (which Fellowship program track
   the applicant applied to), not a reviewer pod. `applicants.cohort_team` is the
   field name across the data model; no longer an open question.
4. **Tie-break.** Not yet confirmed by the Fellowship team — proceeding with the
   recommended default (stable tie-break by Applicant ID, not spreadsheet `RANK`
   shared-rank semantics) per D9 in
   [16-design-decisions-tradeoffs.md](16-design-decisions-tradeoffs.md). Still open;
   revisit if this surfaces as a real concern during the Phase 6 pilot.

## Reviewer model, superseding the workbook's quorum-of-3

Because the default flow is now AI-first with sampled human spot-checks rather than
universal triple review, `# of Votes` and `Data Reliability` as the workbook defines
them no longer describe the default case (they described "how many of the 3 expected
human reviewers scored this applicant," which stops being meaningful when most
applicants get exactly one scorer — the AI). The new system replaces them with two
orthogonal fields on `rankings`, detailed in
[03-data-model.md](03-data-model.md) and
[08-ethical-risk-assessment.md](08-ethical-risk-assessment.md):

- **`evaluation_source`**: `ai_only` (the default — no human has looked at this
  applicant yet) or `ai_plus_spot_check` (a human has independently scored it too).
- **`spot_check_status`**: `not_sampled`, `agreement` (human score within tolerance of
  the AI's), or `discrepancy_flagged` (human score materially diverged — triggers
  escalation, see [08-ethical-risk-assessment.md](08-ethical-risk-assessment.md)).

This is a deliberate, visible admission that "Data Reliability: ✓ Reliable" would be a
misleading label to keep showing on every AI-only row — the new fields tell a reviewer
plainly whether a human has ever actually looked at a given applicant, which is exactly
the information the old column existed to convey, adapted to a workflow where "3 human
scores" is no longer the expected baseline.

**Note for whoever owns the live Google Sheet:** the `Scores_Master`/`Results`/
`Leaderboard` formulas as they exist today will need deliberate updates (not something
this system does silently on your sheet — see
[07-google-sheets-integration.md](07-google-sheets-integration.md)) to accommodate a
world where most applicants have exactly one (AI) score and only a sampled subset has
a second (human) score. Flagged as a Phase 4 coordination item.
