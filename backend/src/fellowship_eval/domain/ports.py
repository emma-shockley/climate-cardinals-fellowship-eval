"""Interfaces the domain defines; adapters implement (dependency inversion).

Defines the plain data shapes used across the pipeline (an applicant's raw
text, a rubric version, a prompt version, a set of raw AI scores), plus one
contract - RubricEvaluator - that any AI evaluator must follow: something
with an `evaluate()` method that takes an application + rubric and returns
scores.

Why this file has no actual logic in it: keeping these definitions separate
from any specific AI provider's code means the rest of the pipeline (scoring,
ranking) never needs to know or care whether it's talking to Claude, a
different LLM, or anything else - it just needs something matching this
shape. Future employees can use any mechanism of thier choosing to implement.
"""
from __future__ import annotations

from typing import Dict, Protocol

from pydantic import BaseModel

from .rubric import CriterionName, CriterionScore, RubricWeights


class ApplicationText(BaseModel):
    applicant_id: str
    raw_text: str


class RubricVersion(BaseModel):
    """Corresponds to a `rubric_versions` row (docs/03-data-model.md)."""

    id: str
    version_label: str
    weights: RubricWeights


class PromptVersion(BaseModel):
    """Corresponds to a `prompt_versions` row (docs/03-data-model.md). Kept separate
    from `RubricVersion` because prompt wording can change without the rubric's
    substantive criteria changing, and vice versa — see that doc's rationale."""

    id: str
    version_label: str
    rubric_version_id: str


class RawCriterionScores(BaseModel):
    """The AI evaluator's validated output for one applicant, before the
    deterministic scoring engine computes anything from it."""

    scores: Dict[CriterionName, CriterionScore]


class RubricEvaluator(Protocol):
    """Implemented by `AnthropicRubricEvaluator` (adapters/llm/). Never computes a
    weighted score, rank, tier, or accept/reject signal — see
    docs/05-ai-evaluation-pipeline.md, closing section.
    """

    model_version: str

    async def evaluate(
        self, application: ApplicationText, rubric: RubricVersion
    ) -> RawCriterionScores: ...
