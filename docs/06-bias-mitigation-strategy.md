# 06 — Bias Mitigation

## What the system does and doesn't collect

The application data loaded by `adapters/data/application_loader.py` doesn't include any
protected characteristic (race, gender, nationality, religion, disability, ethnicity,
political affiliation). The one field that touches fairness directly is `is_multilingual`
(column L of the form export) — whether an applicant indicated they're multilingual. It's
loaded into `RawApplication` but isn't currently used by anything downstream; the only way
to act on it today is to filter or sort by it manually in the exported data.

## What actually constrains the model's scoring

The prompt sent to Claude (`build_static_prompt()` in `anthropic_evaluator.py`) does not
contain an explicit instruction against inferring or using protected characteristics. What
does constrain scoring: the rubric itself only defines five criteria (Growth Potential,
Social Impact, Commitment, Team-Orientation, Initiative), none of which reference any
protected characteristic, and the model is scored against that rubric text directly rather
than given open-ended discretion.

The one concrete anti-fabrication safeguard that does exist: every evidence quote the
model returns is checked against the applicant's actual submitted text (`_to_domain()`),
and a quote that doesn't appear verbatim is dropped rather than shown to a reviewer as
evidence. That reduces one failure mode — a reviewer trusting fabricated evidence — but it
doesn't verify that the *scoring itself* was unbiased, only that the cited evidence was
real.

## Language and translation fairness

With applicants writing in a non-native language, a real risk is that phrasing or prose
quality gets penalized rather than substance. There's no automated check for this today.
The `is_multilingual` flag is available as a way to manually spot-check whether
multilingual applicants' scores look systematically different from the rest, but that
comparison isn't built into any tooling — it would mean pulling the data and checking by
hand.

## Human reviewer tabs as a manual cross-check

The spreadsheet has separate tabs for human reviewers (`Scores_Emma`, `Scores_Lea`,
`Scores_Director`) alongside the AI's own `Scores_Agent` tab. Comparing the AI's scores
against a human reviewer's for the same applicant is possible by looking across these
tabs directly in the sheet — there's no automated agreement-tracking or dashboard that
does this comparison for you.