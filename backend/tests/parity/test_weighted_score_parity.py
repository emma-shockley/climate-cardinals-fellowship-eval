"""Spreadsheet parity tests.

Verifies the domain layer's `compute_weighted_score` and `strength_and_weakness`
produce results identical to the canonical Google Sheet workbook
(docs/06-spreadsheet-reverse-engineering.md), using a frozen copy of the actual
workbook as ground truth rather than hand-picked examples. This is the release
gate for the "identical results to the spreadsheet" requirement in
docs/12-testing-strategy.md.
"""
from pathlib import Path

import openpyxl
import pytest

from fellowship_eval.domain.ranking import DecisionTier, TierThresholds, decision_tier, strength_and_weakness
from fellowship_eval.domain.rubric import CriterionName, RubricWeights, compute_weighted_score

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "Fellowship_Scoring_Rubric_FINAL.xlsx"

# CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC, in the same order as they appear in your rubric.
CRITERIA_COLUMN_ORDER = [
    CriterionName.GROWTH_POTENTIAL,
    CriterionName.SOCIAL_IMPACT,
    CriterionName.COMMITMENT,
    CriterionName.TEAM_ORIENTATION,
    CriterionName.INITIATIVE,
]


def _load_reviewer_sheet_rows(sheet_name: str):
    """Reads (applicant_id, {criterion: score}, cached_weighted_score) tuples from
    one of the Scores_Emma/Scores_Lea/Scores_Director sheets, using cached formula
    values (data_only=True) as ground truth.
    
    CHANGE THESE IF APPLICABLE: assumes column A = Applicant ID, columns B-F = your five
    criteria in CRITERIA_COLUMN_ORDER's order, column G = weighted score. Update
    the column numbers below if your sheet's layout differs.
    """
    wb = openpyxl.load_workbook(FIXTURE_PATH, data_only=True)
    ws = wb[sheet_name]
    rows = []
    for row in range(2, ws.max_row + 1):
        applicant_id = ws.cell(row=row, column=1).value
        if not applicant_id:
            continue
        scores = {
            criterion: ws.cell(row=row, column=2 + i).value
            for i, criterion in enumerate(CRITERIA_COLUMN_ORDER)
        }
        cached_weighted_score = ws.cell(row=row, column=7).value
        if any(v is None for v in scores.values()) or cached_weighted_score is None:
            continue  # spilled-formula rows below the real data, not actual applicants
        rows.append((applicant_id, scores, cached_weighted_score))
    return rows


def _load_leaderboard_rows():
    """Reads (applicant_id, {criterion: avg_score}, cached_weighted_score,
    cached_strength, cached_weakness) tuples from the Leaderboard sheet.
    
    CHANGE THESE IF APPLICABLE: assumes column A = Applicant ID, columns B-F = your five
    criteria in CRITERIA_COLUMN_ORDER's order, column G = weighted score. Update
    the column numbers below if your sheet's layout differs. Leaderboard is also a hardcoded
    tab name that may differ in your org's rubric workbook.
    """
    wb = openpyxl.load_workbook(FIXTURE_PATH, data_only=True)
    ws = wb["Leaderboard"]
    rows = []
    for row in range(2, ws.max_row + 1):
        applicant_id = ws.cell(row=row, column=1).value
        if not applicant_id:
            continue
        scores = {
            criterion: ws.cell(row=row, column=2 + i).value
            for i, criterion in enumerate(CRITERIA_COLUMN_ORDER)
        }
        cached_weighted_score = ws.cell(row=row, column=7).value  # G: Avg Weighted Score
        cached_decision_signal = ws.cell(row=row, column=15).value  # O: Decision Signal
        cached_strength = ws.cell(row=row, column=18).value  # R: Strength
        cached_weakness = ws.cell(row=row, column=19).value  # S: Weakness
        if any(v is None for v in scores.values()) or cached_weighted_score is None:
            continue
        rows.append(
            (applicant_id, scores, cached_weighted_score, cached_decision_signal, cached_strength, cached_weakness)
        )
    return rows


# Maps the workbook's Decision Signal text to our DecisionTier enum.
# CHANGE THESE STRINGS TO MATCH YOUR ORG'S ACTUAL DECISION SIGNALS, if they differ from the canonical workbook.
DECISION_SIGNAL_TO_TIER = {
    "Interview": DecisionTier.INTERVIEW,
    "Secondary Tier": DecisionTier.SECONDARY_TIER,
    "Do not advance": DecisionTier.DO_NOT_ADVANCE,
}


# Maps the workbook's human-readable criterion labels (used in Leaderboard!R,S) back
# to our CriterionName enum, so we can compare our enum output to the sheet's text.
# CHANGE THESE STRINGS TO MATCH YOUR ORG'S ACTUAL CRITERION LABELS, if they differ from the canonical workbook.
LABEL_TO_CRITERION = {
    "Growth Potential": CriterionName.GROWTH_POTENTIAL,
    "Demonstrated Interest in Social Impact": CriterionName.SOCIAL_IMPACT,
    "Demonstrated Commitment": CriterionName.COMMITMENT,
    "Team-Orientation": CriterionName.TEAM_ORIENTATION,
    "Demonstrated Initiative / Willingness to Learn": CriterionName.INITIATIVE,
}


@pytest.fixture(scope="module")
def weights():
    return RubricWeights()


# CHANGE THESE SHEET NAMES TO MATCH YOUR WORKBOOK'S REVIEWER TABS (and add/remove
# entries if you have a different number of reviewers than three)
@pytest.mark.parametrize("sheet_name", ["Scores_Emma", "Scores_Lea", "Scores_Director"])
def test_compute_weighted_score_matches_reviewer_sheet(sheet_name, weights):
    rows = _load_reviewer_sheet_rows(sheet_name)
    assert rows, f"expected at least one populated row in {sheet_name}"
    for applicant_id, scores, cached_weighted_score in rows:
        result = compute_weighted_score(scores, weights)
        assert result == pytest.approx(cached_weighted_score, abs=1e-6), (
            f"{sheet_name}/{applicant_id}: expected {cached_weighted_score}, got {result}"
        )


def test_compute_weighted_score_matches_leaderboard_aggregate(weights):
    rows = _load_leaderboard_rows()
    assert rows, "expected at least one populated row in Leaderboard"
    for applicant_id, scores, cached_weighted_score, _signal, _strength, _weakness in rows:
        result = compute_weighted_score(scores, weights)
        assert result == pytest.approx(cached_weighted_score, abs=1e-6), (
            f"Leaderboard/{applicant_id}: expected {cached_weighted_score}, got {result}"
        )


def test_decision_tier_matches_leaderboard_decision_signal():
    rows = _load_leaderboard_rows()
    assert rows, "expected at least one populated row in Leaderboard"
    thresholds = TierThresholds()
    for applicant_id, _scores, cached_weighted_score, cached_signal, _strength, _weakness in rows:
        result = decision_tier(cached_weighted_score, thresholds)
        expected = DECISION_SIGNAL_TO_TIER[cached_signal]
        assert result == expected, (
            f"Leaderboard/{applicant_id}: expected {expected}, got {result} "
            f"(weighted_score={cached_weighted_score})"
        )


def test_strength_and_weakness_matches_leaderboard():
    rows = _load_leaderboard_rows()
    assert rows, "expected at least one populated row in Leaderboard"
    for applicant_id, scores, _weighted_score, _signal, cached_strength, cached_weakness in rows:
        strongest, weakest = strength_and_weakness(scores)
        expected_strongest = LABEL_TO_CRITERION[cached_strength]
        expected_weakest = LABEL_TO_CRITERION[cached_weakness]
        assert strongest == expected_strongest, (
            f"Leaderboard/{applicant_id}: strength expected {expected_strongest}, got {strongest}"
        )
        assert weakest == expected_weakest, (
            f"Leaderboard/{applicant_id}: weakness expected {expected_weakest}, got {weakest}"
        )
