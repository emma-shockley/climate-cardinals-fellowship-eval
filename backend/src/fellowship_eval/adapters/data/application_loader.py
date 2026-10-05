"""Loads fellowship applications from XLSX, applies eligibility filters,
and samples random applicants for evaluation. Eligibility criteria are
applied in a single pass with clear logging for auditability.

File structure:
  Row 1: "Recruitment Form 2026"
  Row 2: "Incoming responses"
  Row 3: Headers
  Row 4+: Data (each row is "Incoming form answer", then values)

CUSTOMIZE BEFORE REUSING: every column number below, and the exact expected
answer strings in the three check_criterion_* methods, match Climate
Cardinals' own monday.com form export. A different form will have different
columns and different literal answers -- update RawApplication's column
comments, the column numbers in load_applications_from_xlsx, and the three
eligibility checks below to match your own form.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional

import openpyxl

"""CHANGE THESE: the column letters in the comments below match Climate Cardinals'
own form export -- update them to match your own.
"""
@dataclass
class RawApplication:
    """One applicant's raw data extracted from the XLSX."""

    applicant_id: str  # Column G (email)
    is_student: str  # Column C (must be "Yes.")
    us_authorization: str  # Column D (must contain "authorized")
    commitment_availability: str  # Column Y (must be "Yes")
    is_multilingual: bool  # Column L (inferred from text)
    prior_climate_cardinals_experience: bool  # Column N (inferred from text)
    prior_leadership_experience: str  # Column R
    leadership_organizations: str  # Column T
    linkedin_url: str  # Column U
    areas_of_expertise: str  # Column V
    people_reached: str  # Column W
    impact_explanation: str  # Column X
    cv_url: str  # Column Q
    first_choice_team: str  # Column Z (team interest)


class EligibilityResult:
    """Tracks why an applicant passes or fails eligibility."""

    def __init__(self, applicant_id: str):
        self.applicant_id = applicant_id
        self.passes = True
        self.reasons = []

    def check_criterion_c(self, value: str) -> bool:
        """Column C (Q1): "1. Are you currently a student?" - Must be "Yes." """
        result = value and str(value).strip() in ("Yes.", "Yes", "yes.", "yes")
        if not result:
            self.passes = False
            self.reasons.append(
                f"Column C (Q1: Are you currently a student?) was '{value}', expected 'Yes.'"
            )
        return result

    def check_criterion_d(self, value: str) -> bool:
        """Column D (Q4): Must start with "Yes; I am authorized..." """
        expected_start = "Yes; I am authorized"
        result = value and str(value).strip().startswith(expected_start)
        if not result:
            self.passes = False
            self.reasons.append(
                f"Column D (Q4: funds authorization) was '{value}', "
                f"expected 'Yes; I am authorized to receive funds from the United States.'"
            )
        return result

    def check_criterion_y(self, value: str) -> bool:
        """Column Y (Q3): "Are you able to commit 3-5 hours/week Sept 2026-May 2027?" - Must be "Yes." """
        result = value and str(value).strip() in ("Yes.", "Yes", "yes.", "yes")
        if not result:
            self.passes = False
            self.reasons.append(
                f"Column Y (Q3: 3-5 hrs/week commitment) was '{value}', expected 'Yes.'"
            )
        return result


def load_applications_from_xlsx(
    xlsx_path: str, sheet_name: str = 0
) -> tuple[List[RawApplication], dict]:
    """Loads applications from XLSX, applies three eligibility filters,
    and returns all raw applications plus summary stats.

    File structure:
      Row 1: Title
      Row 2: "Incoming responses"
      Row 3: Headers
      Row 4+: Data

    Eligibility criteria (all three must pass):
    - Criterion C (column C / #3): Q1 "Are you currently a student?" - Must be "Yes"
    - Criterion D (column D / #4): Q4 "Funds authorization" - Must contain "authorized"
    - Criterion Y (column Y / #25): Q3 "3-5 hours/week commitment" - Must be "Yes"

    Returns:
        (list of RawApplication, stats dict with pass/fail counts and reasons)
    """
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.worksheets[sheet_name] if isinstance(sheet_name, int) else wb[sheet_name]

    all_applications = []
    eligible_applications = []
    ineligible_reasons = []

    # Data starts at row 4 (because row 3 is headers due to monday.com export format)
    for row_num in range(4, ws.max_row + 1):
        try:
            # Extract key fields (column numbers are 1-indexed in openpyxl)
            applicant_id = ws.cell(row=row_num, column=7).value  # Column G: Email

            # Mark rows with no email as ineligible
            if not applicant_id:
                ineligible_reasons.append(
                    {
                        "applicant_id": f"Row {row_num}",
                        "reasons": ["No email address provided (applicant_id required)"],
                    }
                )
                continue  # Skip empty rows

            # Extract all raw fields
            criterion_c = ws.cell(row=row_num, column=3).value  # Column C: Q1 Student?
            criterion_d = ws.cell(row=row_num, column=4).value  # Column D: Q4 Funds auth
            criterion_y = ws.cell(row=row_num, column=25).value  # Column Y: Q3 3-5hrs commitment
            is_multilingual = ws.cell(row=row_num, column=12).value  # Column L: Languages
            prior_cc_exp = ws.cell(row=row_num, column=14).value  # Column N: Prior CC exp
            cv_url = ws.cell(row=row_num, column=17).value  # Column Q: CV
            prior_leadership = ws.cell(row=row_num, column=18).value  # Column R: Leadership exp?
            leadership_orgs = ws.cell(row=row_num, column=20).value  # Column T: Organizations
            linkedin_url = ws.cell(row=row_num, column=21).value  # Column U: LinkedIn
            expertise = ws.cell(row=row_num, column=22).value  # Column V: Expertise
            people_reached = ws.cell(row=row_num, column=23).value  # Column W: People reached
            impact_explain = ws.cell(row=row_num, column=24).value  # Column X: Explanation
            first_choice_team = ws.cell(row=row_num, column=26).value  # Column Z: First choice team

            app = RawApplication(
                applicant_id=str(applicant_id).strip(),
                is_student=str(criterion_c) if criterion_c else "",
                us_authorization=str(criterion_d) if criterion_d else "",
                commitment_availability=str(criterion_y) if criterion_y else "",
                is_multilingual=bool(is_multilingual and str(is_multilingual).lower() != "no"),
                prior_climate_cardinals_experience=bool(
                    prior_cc_exp and str(prior_cc_exp).lower() != "no"
                ),
                prior_leadership_experience=str(prior_leadership) if prior_leadership else "",
                leadership_organizations=str(leadership_orgs) if leadership_orgs else "",
                linkedin_url=str(linkedin_url) if linkedin_url else "",
                areas_of_expertise=str(expertise) if expertise else "",
                people_reached=str(people_reached) if people_reached else "",
                impact_explanation=str(impact_explain) if impact_explain else "",
                cv_url=str(cv_url) if cv_url else "",
                first_choice_team=str(first_choice_team).strip() if first_choice_team else "",
            )
            all_applications.append(app)

            # Apply eligibility filters
            eligibility = EligibilityResult(app.applicant_id)
            eligibility.check_criterion_c(criterion_c)
            eligibility.check_criterion_d(criterion_d)
            eligibility.check_criterion_y(criterion_y)

            # If applicant is eligible, add to eligible list; otherwise, log reasons
            if eligibility.passes:
                eligible_applications.append(app)
            else:
                ineligible_reasons.append(
                    {
                        "applicant_id": app.applicant_id,
                        "reasons": eligibility.reasons,
                    }
                )

        except Exception as e:
            print(f"Error processing row {row_num}: {e}")
            continue

    # Compile summary statistics re: ineligible versus eligible candidates
    stats = {
        "total_rows": len(all_applications),
        "eligible_count": len(eligible_applications),
        "ineligible_count": len(ineligible_reasons),
        "ineligible_details": ineligible_reasons,
    }

    return eligible_applications, stats


def sample_applications(
    applications: List[RawApplication], sample_size: int = 10, seed: Optional[int] = None
) -> List[RawApplication]:
    """Randomly samples `sample_size` applications from the eligible pool.

    Args:
        applications: List of RawApplication objects (should be pre-filtered)
        sample_size: Number to sample (default 10)
        seed: Random seed for reproducibility (optional)

    Returns:
        List of sampled applications
    """
    if seed is not None:
        random.seed(seed)

    if len(applications) <= sample_size:
        return applications

    return random.sample(applications, sample_size)
