"""Email Deduplication Tests — ensures user is not double-billed for the same applicant
by running tests concerning case sensitivity, whitespace, and other email normalization issues.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluate_and_upload import norm_email


def test_case_variants_are_the_same_person(): # confirms capitalization does not affect email normalization
    assert norm_email("Placeholderemail@gmail.com") == norm_email(
        "placeholderemail@gmail.com"
    )


def test_surrounding_whitespace_ignored(): # confirms leading/trailing whitespace does not affect email normalization
    assert norm_email("  foo@bar.com  ") == norm_email("foo@bar.com")


def test_all_caps_matches_lowercase(): # confirms that all caps email matches lowercase email
    assert norm_email("FOO@BAR.COM") == norm_email("foo@bar.com")


def test_different_people_stay_different(): # confirms that different people are not considered the same
    assert norm_email("alice@example.com") != norm_email("bob@example.com")


def test_none_and_empty_are_safe(): # confirms that None and empty strings do not cause the program to crash
    assert norm_email(None) == ""
    assert norm_email("") == ""


def test_checkpoint_skips_case_variant(): # confirms that a case variant of an already scored email is recognized as the same person
    already_scored = {norm_email("placeholderemail@gmail.com")}
    incoming = "Placeholderemail@gmail.com"
    assert norm_email(incoming) in already_scored


def test_repeat_submissions_collapse_within_one_run(): # confirms that repeat submissions of the same email in a single run are collapsed into one
    eligible = [
        "Placeholderemail@gmail.com",
        "someone@else.com",
        "Placeholderemail@gmail.com",
        "SOMEONE@ELSE.COM",
    ]
    seen, keep = set(), []
    for e in eligible:
        k = norm_email(e)
        if k in seen:
            continue
        seen.add(k)
        keep.append(e)

    assert keep == ["Placeholderemail@gmail.com", "someone@else.com"]
    assert len(keep) == 2


def test_flush_dedup_uses_normalised_form(): # confirms that the flush deduplication process uses the normalized form of emails to determine uniqueness
    existing = {norm_email("Foo@Example.com")}
    batch = [{"applicant_id": "foo@example.com"}, {"applicant_id": "new@example.com"}]
    fresh = [r for r in batch if norm_email(r["applicant_id"]) not in existing]
    assert [r["applicant_id"] for r in fresh] == ["new@example.com"]
