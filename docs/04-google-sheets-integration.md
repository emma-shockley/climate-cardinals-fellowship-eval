# 04 — Google Sheets Integration

## What gets written, and where

Results are written to the `Scores_Agent` tab, matching the schema of the human-reviewer
tabs (`Scores_Emma`/`Scores_Lea`/`Scores_Director`):

| Col | Header | Value |
|---|---|---|
| A | Applicant ID | the applicant's email |
| B | Growth Potential (1–5) | |
| C | Demonstrated Interest in Social Impact (1–5) | |
| D | Demonstrated Commitment (1–5) | |
| E | Team-Orientation (1–5) | |
| F | Demonstrated Initiative / Willingness to Learn (1–5) | |
| G | Weighted Score | auto-calculated by the sheet's own formula — never written by the backend |
| H | Voter | always `"Hiring Support Agent"` |
| I | Team | the applicant's first-choice team |
| J–N | Justification, one column per criterion | verbatim evidence quotes plus the model's explanation, or "Insufficient evidence in application" if none survived verification |

This is written in two API calls, not one: `GoogleSheetsWriter.append_batch()` first appends
columns A–F for the whole batch via `values().append()`, reads back the row range that
call reports, then writes columns H–N into that same row range via `values().update()`.
Both calls target the same tab name, which is hardcoded as `"Scores_Agent"` in
`adapters/sheets/google_sheets_writer.py` — **CUSTOMIZE BEFORE REUSING**, per that file's
own docstring.

## Reading the rubric

`GoogleSheetsRubricLoader` (`adapters/sheets/rubric_loader.py`) reads the `Rubric [AGENT]`
tab, columns A–F, and parses it by matching column A's text against a hardcoded list of
five exact criterion-name strings (e.g. `"Demonstrated Interest in Social Impact"`). That
file's own docstring is blunt about the risk here, worth repeating: if a criterion is
renamed in the sheet without updating that hardcoded list, parsing does not error — it
silently drops that criterion from the rubric with no warning. The rubric is fetched once
per evaluator instance (cached), not once per applicant.

## Checking for already-evaluated applicants

Rather than going through `GoogleSheetsWriter`, `evaluate_and_upload.py` makes its own
direct, read-only Sheets API calls (a separate authentication path from the writer and
rubric loader) to read `Scores_Agent!A:A` — once before a run starts, to build the set of
already-scored applicants, and again right before each 100-applicant flush, so an
applicant added to the sheet by another source mid-run is still picked up. Comparison is
by normalized email (`norm_email()` — case- and whitespace-insensitive) rather than exact
string match.

If that read fails for any reason, the error is caught and logged as "Could not check
Sheet (will re-evaluate all)," and the run proceeds without a dedup check rather than
stopping — worth knowing, since it means a transient Sheets error at the start of a run
could lead to re-scoring (and re-billing) applicants already in the sheet.

## Auth

A single Google service-account JSON key is used throughout, with the scope requested
matching what each call needs: `spreadsheets.readonly` for the rubric loader and the
dedup-check reads, `spreadsheets` (read/write) for `GoogleSheetsWriter`.