""" Ranking Tests — proves the tiering and strength/weakness logic is correct.

Checks that `decision_tier` draws the Interview / Secondary Tier / Do Not Advance
boundaries at exactly the right points (including the edge cases right at 4.0
and 3.0), and that `strength_and_weakness` correctly picks an applicant's best-
and worst-scoring criteria - including when two scores are tied, and when scores
are averaged decimals rather than whole numbers.
"""

import pytest

from fellowship_eval.domain.ranking import (
    DecisionTier,
    TierThresholds,
    decision_tier,
    strength_and_weakness,
)
from fellowship_eval.domain.rubric import CriterionName


DEFAULT_THRESHOLDS = TierThresholds()  # interview=4.0, secondary_tier=3.0


@pytest.mark.parametrize(
    "weighted_score, expected_tier",
    [
        (4.0, DecisionTier.INTERVIEW),
        (4.2, DecisionTier.INTERVIEW),
        (3.99, DecisionTier.SECONDARY_TIER),
        (3.0, DecisionTier.SECONDARY_TIER),
        (2.99, DecisionTier.DO_NOT_ADVANCE),
        (0.0, DecisionTier.DO_NOT_ADVANCE),
    ],
)
def test_decision_tier_boundaries(weighted_score, expected_tier):
    assert decision_tier(weighted_score, DEFAULT_THRESHOLDS) == expected_tier


def test_strength_and_weakness_picks_max_and_min(): # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
    scores = {
        CriterionName.GROWTH_POTENTIAL: 3,
        CriterionName.SOCIAL_IMPACT: 4,
        CriterionName.COMMITMENT: 2,
        CriterionName.TEAM_ORIENTATION: 4,
        CriterionName.INITIATIVE: 5,
    }
    strongest, weakest = strength_and_weakness(scores)
    assert strongest == CriterionName.INITIATIVE
    assert weakest == CriterionName.COMMITMENT


def test_strength_and_weakness_ties_break_by_enum_order(): # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
    # growth_potential and social_impact tied at 5; growth_potential declared first.
    scores = {
        CriterionName.GROWTH_POTENTIAL: 5,
        CriterionName.SOCIAL_IMPACT: 5,
        CriterionName.COMMITMENT: 1,
        CriterionName.TEAM_ORIENTATION: 1,
        CriterionName.INITIATIVE: 3,
    }
    strongest, weakest = strength_and_weakness(scores)
    assert strongest == CriterionName.GROWTH_POTENTIAL
    assert weakest == CriterionName.COMMITMENT


def test_strength_and_weakness_accepts_averaged_floats(): # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
    scores = {
        CriterionName.GROWTH_POTENTIAL: 3.666666667,
        CriterionName.SOCIAL_IMPACT: 4.333333333,
        CriterionName.COMMITMENT: 4.0,
        CriterionName.TEAM_ORIENTATION: 4.333333333,
        CriterionName.INITIATIVE: 5.0,
    }
    strongest, weakest = strength_and_weakness(scores)
    assert strongest == CriterionName.INITIATIVE
    assert weakest == CriterionName.GROWTH_POTENTIAL