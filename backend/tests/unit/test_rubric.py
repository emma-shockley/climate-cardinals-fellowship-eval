""" Rubric Tests — proves the scoring math matches the real spreadsheet.

Checks that the weighted-score formula produces the exact same numbers as
real historical applicants from the original spreadsheet (see the row
citations in each test), that invalid weight configurations are rejected,
and that a criterion score's evidence rules (must have a quote, or explicitly
flag insufficient evidence - never both, never neither) are enforced.
"""
import pytest
from pydantic import ValidationError

from fellowship_eval.domain.rubric import (
    CriterionName,
    CriterionScore,
    Evidence,
    RubricWeights,
    compute_weighted_score,
)


ALL_FIVE = { # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
    CriterionName.GROWTH_POTENTIAL: 3,
    CriterionName.SOCIAL_IMPACT: 3,
    CriterionName.COMMITMENT: 2,
    CriterionName.TEAM_ORIENTATION: 5,
    CriterionName.INITIATIVE: 5,
}


def test_weights_default_to_canonical_workbook_values():
    """REPLACE: these are Climate Cardinals' own policy weights, not technical
    defaults. Set this test's assertions to YOUR org's actual weighting
    decision, under your own category names.
    """
    weights = RubricWeights()
    assert weights.growth_potential == 0.25
    assert weights.social_impact == 0.25
    assert weights.commitment == 0.20
    assert weights.team_orientation == 0.15
    assert weights.initiative == 0.15


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        RubricWeights(growth_potential=0.30)  # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC

"""REPLACE ALL THREE CASES: these are real historical applicants scored
under Climate Cardinals' own rubric and weights. Swap in your own
sample data (your category names, your scores) and recalculate the
expected weighted score by hand using YOUR weights — don't just
rename these and keep 3.4/2.7/1.5, those numbers won't be correct
for a different rubric.
"""
@pytest.mark.parametrize(
    "criterion_scores, expected",
    [
        # Fellow_1 from the canonical workbook (Scores_Emma!row2): 3,3,2,5,5 -> 3.4
        ({
            CriterionName.GROWTH_POTENTIAL: 3,
            CriterionName.SOCIAL_IMPACT: 3,
            CriterionName.COMMITMENT: 2,
            CriterionName.TEAM_ORIENTATION: 5,
            CriterionName.INITIATIVE: 5,
        }, 3.4),
        # Fellow_2 (Scores_Emma!row3): 3,2,2,2,5 -> 2.7
        ({
            CriterionName.GROWTH_POTENTIAL: 3,
            CriterionName.SOCIAL_IMPACT: 2,
            CriterionName.COMMITMENT: 2,
            CriterionName.TEAM_ORIENTATION: 2,
            CriterionName.INITIATIVE: 5,
        }, 2.7),
        # Fellow_9 (Scores_Emma!row10): 1,3,1,1,1 -> 1.5
        ({
            CriterionName.GROWTH_POTENTIAL: 1,
            CriterionName.SOCIAL_IMPACT: 3,
            CriterionName.COMMITMENT: 1,
            CriterionName.TEAM_ORIENTATION: 1,
            CriterionName.INITIATIVE: 1,
        }, 1.5),
    ],
)
def test_compute_weighted_score_matches_canonical_workbook_samples(criterion_scores, expected):
    result = compute_weighted_score(criterion_scores, RubricWeights())
    assert result == pytest.approx(expected, abs=1e-9)


def test_compute_weighted_score_raises_on_missing_criterion():
    scores = dict(ALL_FIVE)
    del scores[CriterionName.INITIATIVE]
    with pytest.raises(ValueError, match="missing scores"):
        compute_weighted_score(scores, RubricWeights())


def test_compute_weighted_score_accepts_averaged_floats_not_just_single_evaluator_ints():
    """REPLACE: these five numbers simulate an averaged score across multiple
    human reviewers for one real applicant in Climate Cardinals' own data.
    Swap in your own sample numbers, then recalculate "result" by hand using
    YOUR rubric's weights -- 4.2 is only correct for OUR specific weights
    and these specific numbers, it will not be correct for yours.
    """
    # rankings.avg_criterion_scores (docs/03-data-model.md) can be a mean across an
    # AI evaluation plus escalation-driven human reviews -- must not require ints.
    averaged = {
        CriterionName.GROWTH_POTENTIAL: 3.6666666666666665,
        CriterionName.SOCIAL_IMPACT: 4.333333333333333,
        CriterionName.COMMITMENT: 4.0,
        CriterionName.TEAM_ORIENTATION: 4.333333333333333,
        CriterionName.INITIATIVE: 5.0,
    }
    # matches the canonical workbook's Leaderboard!row2 (Fellow_1) cached value: 4.2
    result = compute_weighted_score(averaged, RubricWeights())
    assert result == pytest.approx(4.2, abs=1e-9)


def test_criterion_score_rejects_evidence_with_insufficient_evidence_flag():
    with pytest.raises(ValidationError):
        CriterionScore(
            criterion=CriterionName.COMMITMENT, # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
            score=1,
            confidence=0.2,
            insufficient_evidence=True,
            evidence=[Evidence(quote="x", source_field="essay_1")],
        )


def test_criterion_score_requires_evidence_unless_flagged_insufficient():
    with pytest.raises(ValidationError):
        CriterionScore(
            criterion=CriterionName.COMMITMENT, # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
            score=3,
            confidence=0.5,
            insufficient_evidence=False,
            evidence=[],
        )


def test_criterion_score_allows_empty_evidence_when_flagged_insufficient():
    score = CriterionScore(
        criterion=CriterionName.TEAM_ORIENTATION, # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
        score=1,
        confidence=0.3,
        insufficient_evidence=True,
        evidence=[],
    )
    assert score.evidence == []
