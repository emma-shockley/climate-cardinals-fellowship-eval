""" Decision Tiering — turns a score into Interview / Secondary / Do Not Advance

Two small functions: `decision_tier` converts a weighted score into one of three
outcomes using two thresholds, and `strength_and_weakness` finds an applicant's
best- and worst-scoring criteria. Both reproduce columns the Google Sheet's own
Leaderboard tab already calculates via formula (see docs/06) - kept here as a
tested, verified version of that same logic, not something the live pipeline
currently calls directly.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple

from pydantic import BaseModel

from .rubric import CriterionName


class DecisionTier(str, Enum):
    """Reproduces the PDF rubric's decision legend and Leaderboard!O exactly."""

    INTERVIEW = "interview"
    SECONDARY_TIER = "secondary_tier"
    DO_NOT_ADVANCE = "do_not_advance"

# CHANGE THESE DEFAULTS TO YOUR OWN ORG'S DECISION-TIER CUTOFFS
class TierThresholds(BaseModel):
    """Config, not a literal — see docs/02-technical-design.md."""

    interview: float = 4.0
    secondary_tier: float = 3.0


def decision_tier(weighted_score: float, thresholds: TierThresholds) -> DecisionTier:
    """>= interview -> Interview; >= secondary_tier -> Secondary Tier; else Do not advance.

    Boundaries are inclusive on the lower edge, matching the PDF rubric's legend
    (>=4.0, 3.0-3.99, <3.0) and the workbook's `IF(G>=4, ..., IF(G>=3, ..., ...))`
    formula exactly (docs/06-spreadsheet-reverse-engineering.md).
    """
    if weighted_score >= thresholds.interview:
        return DecisionTier.INTERVIEW
    if weighted_score >= thresholds.secondary_tier:
        return DecisionTier.SECONDARY_TIER
    return DecisionTier.DO_NOT_ADVANCE


def strength_and_weakness(
    scores: Dict[CriterionName, float],
) -> Tuple[CriterionName, CriterionName]:
    """argmax/argmin over the 5 criterion scores. Reproduces Leaderboard!R,S.

    Takes plain numeric scores (see `compute_weighted_score` in rubric.py for why:
    the canonical workbook's own formula runs this over averaged floats, not just a
    single evaluator's integers). Ties are broken by `CriterionName` enum
    declaration order (first-encountered wins) — a documented, deterministic rule
    rather than dict/argmax's incidental default.
    """
    missing = [c for c in CriterionName if c not in scores]
    if missing:
        raise ValueError(f"missing scores for criteria: {[c.value for c in missing]}")
    ordered = list(CriterionName)
    strongest = max(ordered, key=lambda c: scores[c])
    weakest = min(ordered, key=lambda c: scores[c])
    return strongest, weakest
