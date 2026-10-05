"""Google Sheets Adapter: writes evaluation results to the Scores_Agent tab.

Authenticates with a service account JSON key and appends rows to the
Scores_Agent sheet in the "Fellowship_Round 1 Scoring" workbook.

Column mapping:
  A: Applicant ID
  B: Growth Potential (1-5)
  C: Demonstrated Interest in Social Impact (1-5)
  D: Demonstrated Commitment (1-5)
  E: Team-Orientation (1-5)
  F: Demonstrated Initiative / Willingness to Learn (1-5)
  G: (auto-calculated weighted score — not written)
  H: Voter ("Hiring Support Agent")
  I: Team (first choice team from application)

CUSTOMIZE BEFORE REUSING: the sheet tab name ("Scores_Agent") and exact
column layout (A-N) are specific to Climate Cardinals' own results workbook.
"""
from __future__ import annotations

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


class GoogleSheetsWriter:
    """Writes applicant criterion scores to Google Sheets."""

    @staticmethod
    def _format_justification(evidence_list: list[str], explanation: str, insufficient: bool) -> str:
        """Formats evidence and explanation into a readable justification.

        Args:
            evidence_list: List of verbatim quotes from the application
            explanation: The model's reasoning for the score
            insufficient: Whether evidence was insufficient

        Returns:
            Formatted justification string
        """
        if insufficient or not evidence_list:
            return f"Insufficient evidence in application.\n\nReasoning: {explanation}"

        evidence_text = "\n".join([f"- {quote}" for quote in evidence_list])
        return f"Evidence found:\n{evidence_text}\n\nReasoning: {explanation}"

    def __init__(self, credentials_path: str, spreadsheet_id: str):
        """
        Args:
            credentials_path: Path to the service account JSON key
            spreadsheet_id: The Google Sheets ID (from the URL)
        """
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._service = None

    @property
    def service(self):
        """Lazy-load the Sheets API service."""
        if self._service is None:
            creds = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    async def append_batch(
        self,
        evaluations: list[dict],
    ) -> None:
        """Appends multiple evaluations at once.

        Args:
            evaluations: List of dicts with keys:
                - applicant_id, growth_potential, social_impact, commitment,
                  team_orientation, initiative, team (required)
                - *_evidence (lists), *_explanation (str), *_insufficient (bool) (optional)
        """
        # Step 1: Append columns A-F (criterion scores)
        values_a_to_f = [
            [
                eval_dict["applicant_id"],            # Column A
                eval_dict["growth_potential"],        # Column B
                eval_dict["social_impact"],           # Column C
                eval_dict["commitment"],              # Column D
                eval_dict["team_orientation"],        # Column E
                eval_dict["initiative"],              # Column F
            ]
            for eval_dict in evaluations
        ]
        body_a_f = {"values": values_a_to_f}

        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range="Scores_Agent!A:F",
            valueInputOption="USER_ENTERED",
            body=body_a_f,
        ).execute()

        # Step 2: Get the starting row number from the append result
        if "updates" not in result or "updatedRange" not in result["updates"]:
            return

        updated_range = result["updates"]["updatedRange"]
        # Parse range like "Scores_Agent!A3:F8" to get starting row
        start_row = int(updated_range.split("!")[1].split(":")[0][1:])
        num_rows = len(evaluations)
        end_row = start_row + num_rows - 1

        # Step 3: Write columns H-N (Voter, Team, and Justifications)
        values_h_n = []
        for eval_dict in evaluations:
            growth_justif = self._format_justification(
                eval_dict.get("growth_potential_evidence", []),
                eval_dict.get("growth_potential_explanation", ""),
                eval_dict.get("growth_potential_insufficient", False),
            )
            social_justif = self._format_justification(
                eval_dict.get("social_impact_evidence", []),
                eval_dict.get("social_impact_explanation", ""),
                eval_dict.get("social_impact_insufficient", False),
            )
            commitment_justif = self._format_justification(
                eval_dict.get("commitment_evidence", []),
                eval_dict.get("commitment_explanation", ""),
                eval_dict.get("commitment_insufficient", False),
            )
            team_justif = self._format_justification(
                eval_dict.get("team_orientation_evidence", []),
                eval_dict.get("team_orientation_explanation", ""),
                eval_dict.get("team_orientation_insufficient", False),
            )
            initiative_justif = self._format_justification(
                eval_dict.get("initiative_evidence", []),
                eval_dict.get("initiative_explanation", ""),
                eval_dict.get("initiative_insufficient", False),
            )

            values_h_n.append(
                [
                    "Hiring Support Agent",  # Column H: Voter
                    eval_dict["team"],       # Column I: Team
                    growth_justif,           # Column J: Growth Potential Justification
                    social_justif,           # Column K: Social Impact Justification
                    commitment_justif,       # Column L: Commitment Justification
                    team_justif,             # Column M: Team-Orientation Justification
                    initiative_justif,       # Column N: Initiative Justification
                ]
            )

        body_h_n = {"values": values_h_n}

        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"Scores_Agent!H{start_row}:N{end_row}",
            valueInputOption="USER_ENTERED",
            body=body_h_n,
        ).execute()
