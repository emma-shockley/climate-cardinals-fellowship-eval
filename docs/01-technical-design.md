# 01 — Technical Design

## Layering

Two layers, plus a couple of standalone scripts that wire them together:

Entry-point scripts at the top of `backend/` (like `evaluate_and_upload.py`) import
from both layers and run the actual evaluation. There's no API server, database, or
background worker — these are scripts run directly from the command line.

`domain/` has no import of `anthropic`, `google-api-python-client`, or any networking
library — it's scoring/ranking rules expressed as plain Python + Pydantic models,
which is what makes them unit-testable without mocking anything (see the parity
tests in [07-testing-strategy.md](07-testing-strategy.md)).

## The shared contract (domain/ports.py)

```python
class ApplicationText(BaseModel):
    applicant_id: str
    raw_text: str

class RubricVersion(BaseModel):
    id: str
    version_label: str
    weights: RubricWeights

class RawCriterionScores(BaseModel):
    scores: Dict[CriterionName, CriterionScore]

class RubricEvaluator(Protocol):
    """Implemented by AnthropicRubricEvaluator. Never computes a weighted score,
    rank, tier, or accept/reject signal."""
    model_version: str
    async def evaluate(self, application: ApplicationText, rubric: RubricVersion) -> RawCriterionScores: ...
```

This is what keeps `adapters/llm/anthropic_evaluator.py` swappable in principle — anything
matching this shape could stand in for it — though today Claude is the only
implementation that exists.

## Core domain types (domain/rubric.py)

```python
class CriterionName(str, Enum):
    GROWTH_POTENTIAL = "growth_potential"
    SOCIAL_IMPACT = "social_impact"
    COMMITMENT = "commitment"
    TEAM_ORIENTATION = "team_orientation"
    INITIATIVE = "initiative"

class Evidence(BaseModel):
    quote: str
    source_field: str

class CriterionScore(BaseModel):
    criterion: CriterionName
    score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence]
    insufficient_evidence: bool = False
    # a score must carry evidence unless insufficient_evidence is set — never both, never neither

class RubricWeights(BaseModel):
    growth_potential: float = 0.25
    social_impact: float = 0.25
    commitment: float = 0.20
    team_orientation: float = 0.15
    initiative: float = 0.15

def compute_weighted_score(scores: dict[CriterionName, float], weights: RubricWeights) -> float:
    """The only place the weighted-score formula is implemented."""
    return sum(scores[c] * weights.for_criterion(c) for c in CriterionName)
```

## Ranking (domain/ranking.py)

```python
class DecisionTier(str, Enum):
    INTERVIEW = "interview"            # weighted_score >= 4.0
    SECONDARY_TIER = "secondary_tier"  # 3.0 <= weighted_score < 4.0
    DO_NOT_ADVANCE = "do_not_advance"  # weighted_score < 3.0

def decision_tier(weighted_score, thresholds) -> DecisionTier: ...
def strength_and_weakness(scores) -> tuple[CriterionName, CriterionName]: ...
```

Both functions are fully unit-tested against real historical data from the spreadsheet
(see [07-testing-strategy.md](07-testing-strategy.md)), but neither is currently called
by `evaluate_and_upload.py` — that script writes only the raw 1-5 score per criterion to
the Sheet, and the Sheet's own formulas compute the weighted score, tier, and
strength/weakness from there. These functions are a verified, reusable implementation of
that same math in code, available for anything that needs it outside the Sheet.

## The AI evaluation adapter (adapters/llm/)

`AnthropicRubricEvaluator` is the one piece that calls Claude. It builds a prompt from
the rubric (loaded live from the Google Sheet via `GoogleSheetsRubricLoader`), sends the
applicant's text, and gets back a `RawCriterionScores` object — one `CriterionScore` per
rubric criterion, each with its score, confidence, evidence, and an
insufficient-evidence flag. It never computes a weighted score, rank, or tier itself —
see [02-ai-evaluation-pipeline.md](02-ai-evaluation-pipeline.md).

`usage_telemetry.py`'s `UsageLog` records token usage and cost per call, appended to
`backend/.state/usage.jsonl`.

## Reading applications and talking to Sheets

`adapters/data/application_loader.py` reads the applicant `.xlsx`, applies three
eligibility checks, and returns the eligible applicants plus pass/fail stats.

`adapters/sheets/rubric_loader.py` reads the live `Rubric [AGENT]` tab so the prompt's
rubric text always matches whatever's actually in the Sheet.

`adapters/sheets/google_sheets_writer.py` appends each evaluated applicant's scores and
evidence as a new row.

## How it's actually run

`evaluate_and_upload.py`, at the top of `backend/`, is the real entry point: it loads
applications, filters out anyone already scored (checked by email against the Sheet),
evaluates each remaining applicant with Claude, and writes results back in batches of
100 so a crash partway through only costs a few minutes of re-work, not the whole run.
It's a straightforward loop with retry/stop logic for failures — not a queue, not a web
service, just a script run from the command line.

**Idempotency:** keyed by lowercased, trimmed email, checked against who's already in
the Sheet. Re-running the script skips anyone already present and also collapses
repeat submissions from the same person within one run.

**Error handling:** an LLM failure for one applicant is caught, logged, and added to a
failed-applicants list; the run stops after 10 consecutive failures, or immediately if
a billing/credit/quota error shows up. There's no dead-letter queue or database —
failures are printed to the console and summarized at the end of the run.

**Configuration:** rubric weights and tier thresholds are Pydantic model defaults in
`rubric.py`/`ranking.py` — changing them means editing those defaults in code, not a
live config panel.