"""Rubric scoring domain model.

Pure logic, zero I/O, zero SDK imports (no LLM client, no DB, no HTTP). See
docs/06-spreadsheet-reverse-engineering.md for where these values come from.

Defines the 5 things every applicant is scored on (Growth Potential,
Social Impact, Commitment, Team Orientation, Initiative), how much each
one counts toward the final score, and the one function that combines
five individual scores into a single overall score.

This file has no side effects — it doesn't read a file, call an AI
model, or touch a database. It's just the "rules of the game," kept
separate so the scoring math can be tested and trusted on its own.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, model_validator

_WEIGHT_SUM_TOLERANCE = 1e-9


class CriterionName(str, Enum):
    """The five official rubric criteria, in the canonical workbook's column order."""

    GROWTH_POTENTIAL = "growth_potential"
    SOCIAL_IMPACT = "social_impact"
    COMMITMENT = "commitment"
    TEAM_ORIENTATION = "team_orientation"
    INITIATIVE = "initiative"


class Evidence(BaseModel):
    """A verbatim citation from the application text supporting a criterion score."""

    quote: str
    source_field: str


class CriterionScore(BaseModel):
    """One criterion's evaluation: a 1-5 score, confidence, and its evidence trail.

    `insufficient_evidence` and `evidence` are mutually exclusive by construction: a
    score with no evidence must say so explicitly rather than silently having none
    (see docs/05-ai-evaluation-pipeline.md, "Handling insufficient evidence").
    """

    criterion: CriterionName
    score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    insufficient_evidence: bool = False
    explanation: str = ""

    @model_validator(mode="after")
    def _evidence_consistency(self) -> "CriterionScore":
        if self.insufficient_evidence and self.evidence:
            raise ValueError("insufficient_evidence=True must not carry evidence")
        if not self.insufficient_evidence and not self.evidence:
            raise ValueError(
                "a score requires at least one evidence item unless "
                "insufficient_evidence is set"
            )
        return self


class RubricWeights(BaseModel):
    """The canonical workbook's weighting formula (docs/06, Scores_Emma!G2 etc.).

    Sourced from a rubric_versions row in production, never hardcoded at call sites
    (docs/02-technical-design.md, "Configuration over hardcoding").

    CUSTOMIZE BEFORE REUSING: this logic is specific to Climate Cardinals' Fellowship Program.
    """

    growth_potential: float = 0.25
    social_impact: float = 0.25
    commitment: float = 0.20
    team_orientation: float = 0.15
    initiative: float = 0.15

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "RubricWeights":
        total = (
            self.growth_potential
            + self.social_impact
            + self.commitment
            + self.team_orientation
            + self.initiative
        )
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"RubricWeights must sum to 1.0, got {total}")
        return self

    def for_criterion(self, criterion: CriterionName) -> float:
        return getattr(self, criterion.value)


def compute_weighted_score(
    scores: Dict[CriterionName, float], weights: RubricWeights
) -> float:
    """The ONLY place the weighted-score formula is implemented.

    Reproduces, exactly, the formula found duplicated across Scores_Emma / Scores_Lea
    / Scores_Director in the canonical workbook (docs/06-spreadsheet-reverse-engineering.md):
    growth*0.25 + social_impact*0.25 + commitment*0.20 + team_orientation*0.15 +
    initiative*0.15. Every caller (API, batch job, parity test) must go through this
    function rather than reimplementing the arithmetic.

    Takes plain numeric scores, not `CriterionScore` objects: under the AI-first
    workflow (docs/16-design-decisions-tradeoffs.md D11) this is most often a single
    AI evaluation's integer scores, but if an applicant is escalated to broader human
    review (docs/03-data-model.md, `rankings.avg_criterion_scores`) it is the *mean*
    across scorers, which is a float. The formula is identical either way; callers
    pass `{c: s.score for c, s in criterion_scores.items()}` for the single-evaluator
    case.
    """
    missing = [c for c in CriterionName if c not in scores]
    if missing:
        raise ValueError(f"missing scores for criteria: {[c.value for c in missing]}")
    return sum(scores[c] * weights.for_criterion(c) for c in CriterionName)
