#!/usr/bin/env python3
"""End-to-end Phase 3 pipeline: assess all applicants, evaluate with Claude,
write results to Google Sheets.

Usage:
  python3 evaluate_and_upload.py \
    --xlsx <path_to_xlsx> \
    --sheet-id <google_sheet_id> \
    --credentials <path_to_gcp_json>
"""
import asyncio
import os
import sys
from pathlib import Path

from src.fellowship_eval.adapters.data.application_loader import (
    load_applications_from_xlsx,
    sample_applications,
)
from src.fellowship_eval.adapters.llm.anthropic_evaluator import AnthropicRubricEvaluator
from src.fellowship_eval.adapters.llm.usage_telemetry import UsageLog
from src.fellowship_eval.adapters.sheets.google_sheets_writer import GoogleSheetsWriter
from src.fellowship_eval.adapters.sheets.rubric_loader import GoogleSheetsRubricLoader
from src.fellowship_eval.domain.ports import ApplicationText, RubricVersion
from src.fellowship_eval.domain.rubric import RubricWeights


def norm_email(value) -> str:
    """Canonical form used for every applicant-identity comparison.

    Email addresses are case-insensitive in practice, so "Foo@gmail.com" and
    "foo@gmail.com" are the same person. Comparing them literally caused one
    applicant to be evaluated and billed twice, and to appear twice in the
    results. Every identity check must go through this.
    """
    return str(value or "").strip().lower()


async def main():
    # Parse arguments
    xlsx_path = None
    sheet_id = None
    credentials_path = None
    limit = None

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--xlsx" and i + 1 < len(sys.argv) - 1:
            xlsx_path = sys.argv[i + 2]
        elif arg == "--sheet-id" and i + 1 < len(sys.argv) - 1:
            sheet_id = sys.argv[i + 2]
        elif arg == "--credentials" and i + 1 < len(sys.argv) - 1:
            credentials_path = sys.argv[i + 2]
        elif arg == "--limit" and i + 1 < len(sys.argv) - 1:
            limit = int(sys.argv[i + 2])

    # Safety flags (presence-only, order independent)
    no_upload = "--no-upload" in sys.argv
    dry_run = "--dry-run" in sys.argv

    
    # CHANGE THESE TO YOUR OWN, or pass --xlsx/--sheet-id/--credentials on the command line instead.
    xlsx_path = xlsx_path or "/path/to/your/applications.xlsx"
    sheet_id = sheet_id or "YOUR_GOOGLE_SHEET_ID"
    credentials_path = credentials_path or "/path/to/your/gcp_credentials.json"


    print("=" * 80)
    print("PHASE 3: FULL-SCALE EVALUATION WITH CLAUDE & UPLOAD TO SHEETS")
    print("=" * 80)

    # Step 1: Load and filter applications
    print(f"\n[1/5] Loading applications from {Path(xlsx_path).name}...")
    eligible, stats = load_applications_from_xlsx(xlsx_path)
    print(f"      ✓ Total rows: {stats['total_rows']}")
    print(f"      ✓ Eligible applicants: {stats['eligible_count']}")
    print(f"      ✓ Ineligible: {stats['ineligible_count']}")

    # Step 2: Check for already-evaluated applicants in Google Sheets
    print(f"\n[2/5] Checking for already-evaluated applicants in Google Sheets...")
    already_evaluated = set()
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        sheets_api = build("sheets", "v4", credentials=creds)

        result = sheets_api.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="Scores_Agent!A:A" #CHANGE THIS TO REFLECT YOUR SHEET NAME
        ).execute()

        rows = result.get("values", [])[1:]  # Skip header row
        already_evaluated = {norm_email(row[0]) for row in rows if row and row[0]}
        print(f"      ✓ Found {len(already_evaluated)} already-evaluated applicants")
    except Exception as e:
        print(f"      ⚠ Could not check Sheet (will re-evaluate all): {type(e).__name__}")

    # Filter to only unevaluated applicants
    # Skip anyone already scored, and collapse repeat submissions from the same
    # person within this run. Without the second step, two rows for one applicant
    # in the same 100-batch would both be evaluated (billed twice) and both
    # appended, since neither is in the Sheet yet when the batch is checked.
    applicants_to_evaluate = []
    seen_this_run = set()
    repeats = 0
    for app in eligible:
        key = norm_email(app.applicant_id)
        if key in already_evaluated:
            continue
        if key in seen_this_run:
            repeats += 1
            continue
        seen_this_run.add(key)
        applicants_to_evaluate.append(app)

    print(f"      ✓ Will evaluate {len(applicants_to_evaluate)} new applicants (skipping {len(already_evaluated)} already done)")
    if repeats:
        print(f"      ✓ Collapsed {repeats} repeat submission(s) from the same applicants")

    # Step 3: Initialize Claude evaluator and Sheets writer
    print(f"\n[3/5] Initializing Claude evaluator and Google Sheets writer...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if dry_run:
            # A dry run never calls the API, so a placeholder is fine here.
            api_key = "dry-run-placeholder-no-calls-made"
            print("      ℹ No ANTHROPIC_API_KEY (fine for --dry-run; no calls will be made)")
        else:
            print("      ✗ ERROR: ANTHROPIC_API_KEY not set")
            print("      Set it with: export ANTHROPIC_API_KEY=sk-...")
            sys.exit(1)

    # Initialize rubric loader (loads Rubric [AGENT] from Google Sheets)
    print(f"      ✓ Loading Rubric [AGENT] from Google Sheets...")
    rubric_loader = GoogleSheetsRubricLoader(credentials_path, sheet_id)

    # Anchor to this file's directory so the log lands in the same place
    # regardless of where the command is run from.
    usage_log = UsageLog(path=str(Path(__file__).resolve().parent / ".state" / "usage.jsonl"))
    evaluator = AnthropicRubricEvaluator(
        api_key=api_key, rubric_loader=rubric_loader, usage_log=usage_log
    )
    sheets_writer = GoogleSheetsWriter(credentials_path, sheet_id)
    print(f"      ✓ Claude (model: {evaluator.model_version}) ready")
    print(f"      ✓ Prompt caching ON (rubric fingerprint: {evaluator.static_prompt_hash()})")
    print(f"      ✓ Google Sheets ready (writing to Scores_Agent tab)") # CHANGE THIS TO REFLECT YOUR SHEET NAME

    # Dry run: verify wiring and prompt structure, then stop before spending anything.
    if dry_run:
        static = evaluator.static_prompt()
        print("\n" + "=" * 80)
        print("DRY RUN — no Anthropic calls, no Sheets writes")
        print("=" * 80)
        print(f"\n  Eligible applicants:        {len(eligible):,}")
        print(f"  Already scored (skipped):   {len(already_evaluated):,}")
        print(f"  Would evaluate:             {len(applicants_to_evaluate):,}")
        if limit:
            print(f"  Capped by --limit:          {limit}")
        print(f"\n  Cached prefix size:         {len(static):,} chars (~{len(static)//4:,} tokens)")
        print(f"  Cached prefix fingerprint:  {evaluator.static_prompt_hash()}")
        print(f"  Rubric inside cached block: {'YES' if 'SCORING RUBRIC' in static else 'NO'}")
        print(f"  Applicant text in prefix:   {'YES (BUG)' if '<application_text>' in static else 'NO (correct)'}")
        print(f"  cache_control attached:     {'YES' if 'cache_control' in str(evaluator._system_blocks()) else 'NO'}")
        print("\n  Nothing was sent and nothing was written.")
        print("=" * 80)
        return

    # Step 4: Evaluate each applicant
    print(f"\n[4/5] Evaluating {len(applicants_to_evaluate)} applicants with Claude...")
    print(f"      (Progress checkpoints every 100 applicants)")
    from src.fellowship_eval.domain.rubric import CriterionName

    results = []
    failed_applicants = []
    pending = []          # evaluated but not yet written to Sheets
    uploaded_count = 0
    consecutive_failures = 0
    SAVE_EVERY = 100      # flush to Sheets this often so a crash costs minutes, not hours

    def read_existing_ids() -> set:
        """Re-reads column A so we never append someone who is already there."""
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            api = build("sheets", "v4", credentials=creds)
            resp = api.spreadsheets().values().get(
                spreadsheetId=sheet_id, range="Scores_Agent!A:A" #CHANGE THIS TO REFLECT YOUR SHEET NAME
            ).execute()
            return {norm_email(row[0]) for row in resp.get("values", [])[1:] if row and row[0]}
        except Exception as e:
            print(f"          ⚠ Could not re-read Sheet: {type(e).__name__}")
            return set()

    async def flush(batch: list) -> int:
        """Writes a chunk to Sheets, skipping anyone already present. Returns rows written."""
        if not batch:
            return 0
        if no_upload:
            print(f"          ⏸ --no-upload: {len(batch)} result(s) held back, Sheet unchanged.")
            return 0

        existing = read_existing_ids()
        fresh = [r for r in batch if norm_email(r["applicant_id"]) not in existing]
        skipped = len(batch) - len(fresh)
        if skipped:
            print(f"          ⚠ {skipped} already in Sheet — skipped to avoid duplicates")
        if not fresh:
            return 0

        await sheets_writer.append_batch(fresh)
        print(f"          💾 Saved {len(fresh)} to Sheets (running total: {uploaded_count + len(fresh)})")
        return len(fresh)

    for i, app in enumerate(applicants_to_evaluate, 1):
        # Check limit
        if limit and i > limit:
            print(f"\n      [Test limit reached: stopping after {limit} applicants]")
            break

        # Progress checkpoints every 100
        if i % 100 == 1 and i > 1:
            print(f"      [{i-1}/{len(applicants_to_evaluate)}] Progress checkpoint - {len(results)} evaluated, {len(failed_applicants)} failed")

        application_text = ApplicationText(
            applicant_id=app.applicant_id,
            raw_text=app.impact_explanation or "",
        )

        try:
            # Manually call evaluator
            raw_result = await evaluator.evaluate(
                application_text,
                RubricVersion(
                    id="rubric-v1", version_label="round-1-v1", weights=RubricWeights()
                ),
            )

            """REPLACE IF YOUR RUBRIC'S CATEGORIES DIFFER (names or count) -- this block
            and the "results" dict below both assume exactly these five.
            """
            # Extract individual criterion scores and evidence
            gp_score = raw_result.scores[CriterionName.GROWTH_POTENTIAL]
            si_score = raw_result.scores[CriterionName.SOCIAL_IMPACT]
            c_score = raw_result.scores[CriterionName.COMMITMENT]
            to_score = raw_result.scores[CriterionName.TEAM_ORIENTATION]
            i_score = raw_result.scores[CriterionName.INITIATIVE]

            results.append(
                {
                    "applicant_id": app.applicant_id,
                    "growth_potential": gp_score.score,
                    "social_impact": si_score.score,
                    "commitment": c_score.score,
                    "team_orientation": to_score.score,
                    "initiative": i_score.score,
                    "team": app.first_choice_team,
                    # Evidence and explanations
                    "growth_potential_evidence": [e.quote for e in gp_score.evidence],
                    "social_impact_evidence": [e.quote for e in si_score.evidence],
                    "commitment_evidence": [e.quote for e in c_score.evidence],
                    "team_orientation_evidence": [e.quote for e in to_score.evidence],
                    "initiative_evidence": [e.quote for e in i_score.evidence],
                    "growth_potential_explanation": gp_score.explanation,
                    "social_impact_explanation": si_score.explanation,
                    "commitment_explanation": c_score.explanation,
                    "team_orientation_explanation": to_score.explanation,
                    "initiative_explanation": i_score.explanation,
                    "growth_potential_insufficient": gp_score.insufficient_evidence,
                    "social_impact_insufficient": si_score.insufficient_evidence,
                    "commitment_insufficient": c_score.insufficient_evidence,
                    "team_orientation_insufficient": to_score.insufficient_evidence,
                    "initiative_insufficient": i_score.insufficient_evidence,
                }
            )
            pending.append(results[-1])
            consecutive_failures = 0
            print(
                f"          ✓ Scores: GP={gp_score.score} SI={si_score.score} "
                f"C={c_score.score} TO={to_score.score} I={i_score.score}"
            )

            # Save periodically so an interruption costs minutes, not the whole run.
            if len(pending) >= SAVE_EVERY:
                uploaded_count += await flush(pending)
                pending = []

        except Exception as e:
            error_msg = str(e)[:200]  # Get more of the error message
            print(f"          ✗ FAILED - Email: {app.applicant_id}")
            print(f"             Error: {type(e).__name__}: {error_msg}")
            failed_applicants.append((app.applicant_id, f"{type(e).__name__}: {error_msg}"))

            # Stop immediately on billing failures. Without this the run grinds
            # through every remaining applicant failing instantly, producing
            # thousands of meaningless failures.
            low = error_msg.lower()
            if "credit balance" in low or "billing" in low or "quota" in low:
                print(f"\n      ⛔ OUT OF CREDITS — stopping now rather than failing "
                      f"{len(applicants_to_evaluate) - i:,} more applicants.")
                print(f"         Add credits, then re-run. Everything already saved is kept.")
                consecutive_failures = 999  # force the abort below
            else:
                consecutive_failures += 1

            if consecutive_failures >= 10:
                print(f"\n      ⛔ Stopping after repeated failures.")
                try:
                    uploaded_count += await flush(pending)
                    pending = []
                    print(f"         ✓ Saved the {len(results)} result(s) completed so far.")
                except Exception as flush_err:
                    print(f"         ⚠ Could not save final chunk: {type(flush_err).__name__}")
                break
            continue

    # Step 5: Write whatever is left over from the final partial chunk.
    # Everything before this was already saved during the loop.
    print(f"\n[5/5] Saving the final {len(pending)} result(s)...")
    try:
        uploaded_count += await flush(pending)
        pending = []
    except Exception as e:
        print(f"      ✗ Error writing final chunk: {type(e).__name__}: {e}")
        print(f"      ℹ {uploaded_count} result(s) from earlier chunks ARE safely saved.")
        print(f"        Re-run to retry the rest; already-saved applicants are skipped.")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("FULL-SCALE EVALUATION COMPLETE")
    print("=" * 80)
    print(f"\n✓ {len(results)}/{len(applicants_to_evaluate)} applicants successfully evaluated")
    if no_upload:
        print(f"⏸ --no-upload was set: nothing was written to the Sheet")
    else:
        print(f"✓ {uploaded_count} row(s) written to Google Sheet (Scores_Agent tab)") #CHANGE THIS TO REFLECT YOUR SHEET NAME
    if failed_applicants:
        print(f"\n✗ {len(failed_applicants)} applicants FAILED TO EVALUATE:")
        print(f"\nEMAILS TO MANUALLY REVIEW:")
        for email, error in failed_applicants:
            print(f"  {email}")

    print(f"\n\nEvaluation Metrics:")
    print(f"  - Dataset: {Path(xlsx_path).name}")
    print(f"  - Applicants evaluated this run: {len(results)}")
    print(f"  - Successfully evaluated: {len(results)}")
    print(f"  - Failed: {len(failed_applicants)}")

    print(f"\nToken Usage (see backend/.state/usage.jsonl):")
    for line in usage_log.summary_lines():
        print(line)
    print(f"\nResults Location: Scores_Agent tab in Google Sheet") #CHANGE THIS TO REFLECT YOUR SHEET NAME
    print(f"  - Sheet ID: {sheet_id}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
