"""Loads the Rubric [AGENT] from Google Sheets and formats it for evaluation prompts.
Caches the result so the rubric is only fetched once per run, not once per applicant.

FRAGILE MATCHING - READ BEFORE EDITING YOUR RUBRIC SHEET: this code
recognizes each criterion by matching the sheet's text EXACTLY against a
hardcoded list of 5 names. If you rename a criterion in the sheet without 
updating that list here, this will not error - it will silently drop that 
criterion from the rubric with no warning. Keep the names in _format_rubric() 
in sync with your sheet.

CUSTOMIZE BEFORE REUSING: the sheet tab name ("Rubric [AGENT]"), its column
layout (A-F), and the 5 hardcoded criterion names are specific to Climate
Cardinals' own rubric workbook.

"""
from __future__ import annotations

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


class GoogleSheetsRubricLoader:
    """Loads rubric criteria from the 'Rubric [AGENT]' sheet in Google Sheets."""

    def __init__(self, credentials_path: str, spreadsheet_id: str):
        """
        Args:
            credentials_path: Path to the service account JSON key
            spreadsheet_id: The Google Sheets ID
        """
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._service = None
        self._cached_rubric = None

    @property
    def service(self):
        """Lazy-load the Sheets API service."""
        if self._service is None:
            creds = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    def load_rubric_text(self, use_cache: bool = True) -> str:
        """Loads the Rubric [AGENT] from Google Sheets and formats it as prompt text.

        Args:
            use_cache: Whether to cache the rubric (default True for efficiency)

        Returns:
            Formatted rubric text suitable for embedding in evaluation prompts
        """
        if use_cache and self._cached_rubric:
            return self._cached_rubric

        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range="'Rubric [AGENT]'!A:F",
        ).execute()

        rows = result.get("values", [])
        rubric_text = self._format_rubric(rows)

        if use_cache:
            self._cached_rubric = rubric_text

        return rubric_text

    @staticmethod
    def _format_rubric(rows: list[list[str]]) -> str:
        """Formats raw sheet rows into rubric prompt text.

        Args:
            rows: All rows from the Rubric [AGENT] sheet

        Returns:
            Formatted rubric text
        """
        if not rows:
            raise ValueError("Rubric sheet is empty")

        rubric_parts = []
        current_criterion = None
        score_data = {}

        i = 0
        while i < len(rows):
            row = rows[i]
            if not row or not row[0]:
                i += 1
                continue

            # Check if this is a criterion header (e.g., "Growth Potential")
            if row[0] in [
                "Growth Potential",
                "Demonstrated Interest in Social Impact",
                "Demonstrated Commitment",
                "Team-Orientation",
                "Demonstrated Initiative / Willingness to Learn",
            ]:
                # If we have a previous criterion, format and add it
                if current_criterion:
                    rubric_parts.append(
                        GoogleSheetsRubricLoader._format_criterion(
                            current_criterion, score_data
                        )
                    )

                current_criterion = row[0]
                score_data = {}
                i += 1

                # Skip header row
                if i < len(rows) and rows[i] and rows[i][0] == "Score":
                    i += 1

                # Read score levels (5, 4, 3, 2, 1)
                while i < len(rows) and rows[i] and rows[i][0] in ["5", "4", "3", "2", "1"]:
                    score_row = rows[i]
                    score = score_row[0]
                    definition = score_row[1] if len(score_row) > 1 else ""
                    required_evidence = score_row[2] if len(score_row) > 2 else ""
                    positive_indicators = score_row[3] if len(score_row) > 3 else ""
                    negative_indicators = score_row[4] if len(score_row) > 4 else ""

                    score_data[score] = {
                        "definition": definition,
                        "required_evidence": required_evidence,
                        "positive_indicators": positive_indicators,
                        "negative_indicators": negative_indicators,
                    }
                    i += 1
            else:
                i += 1

        # Add the last criterion
        if current_criterion:
            rubric_parts.append(
                GoogleSheetsRubricLoader._format_criterion(
                    current_criterion, score_data
                )
            )

        return "\n\n".join(rubric_parts)

    @staticmethod
    def _format_criterion(criterion_name: str, score_data: dict[str, dict]) -> str:
        """Formats a single criterion for the prompt.

        Args:
            criterion_name: Name of the criterion
            score_data: Dict mapping score (5,4,3,2,1) to details

        Returns:
            Formatted criterion text
        """
        lines = [f"===== CRITERION: {criterion_name.upper()} ====="]

        for score in ["5", "4", "3", "2", "1"]:
            if score not in score_data:
                continue

            data = score_data[score]
            lines.append(f"\nScore {score}: {data['definition']}")

            if data["required_evidence"]:
                lines.append(f"  Required Evidence: {data['required_evidence']}")
            if data["positive_indicators"]:
                lines.append(f"  Positive Indicators: {data['positive_indicators']}")
            if data["negative_indicators"]:
                lines.append(f"  Negative Indicators: {data['negative_indicators']}")

        return "\n".join(lines)

    def clear_cache(self) -> None:
        """Clears the cached rubric, forcing a reload on next access. Optional."""
        self._cached_rubric = None
