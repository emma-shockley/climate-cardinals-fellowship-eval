"""AI Evaluator Tests — proves the cost-saving and safety mechanisms work as intended.

Includes prompt caching, quote verification, truncation handling and usage telemetry.
(1) the cached part of the prompt is byte-for-byte identical across applicants and
contains no applicant data, so Anthropic's prompt caching actually triggers and never
leaks one applicant's info into another's request; (2) a quote the AI claims as evidence
is thrown out unless it appears verbatim in the applicant's own text, so fabricated
evidence can never reach a human reviewer; (3) the evaluator recovers if the AI's response
gets cut off mid-answer by retrying with more room; (4) usage logs record token counts for
cost tracking without ever storing an applicant's email address.

These tests exist entirely in a sandbox -- they make no network calls, need no API key,
and never touch Google Sheets.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.fellowship_eval.adapters.llm.anthropic_evaluator import (
    AnthropicRubricEvaluator,
    build_static_prompt,
)
from src.fellowship_eval.adapters.llm.usage_telemetry import UsageLog
from src.fellowship_eval.domain.ports import ApplicationText
from src.fellowship_eval.domain.rubric import CriterionName

RUBRIC = "CRITERION: GROWTH POTENTIAL\nScore 5: Exceptional.\nScore 1: None."


class StubRubricLoader:
    def __init__(self, text=RUBRIC):
        self.text = text
        self.calls = 0

    def load_rubric_text(self, use_cache=True):
        self.calls += 1
        return self.text


def make_message(payload_text, stop_reason="end_turn", usage=None):
    """Builds a stand-in for an Anthropic Message object."""
    block = types.SimpleNamespace(text=payload_text)
    default_usage = types.SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    return types.SimpleNamespace(
        content=[block],
        stop_reason=stop_reason,
        usage=usage or default_usage,
    )


def make_evaluator(loader=None, **kwargs):
    ev = AnthropicRubricEvaluator(
        api_key="test-key-not-real",
        rubric_loader=loader or StubRubricLoader(),
        **kwargs,
    )
    ev.client = None  # guarantee no real client is ever used
    return ev


def valid_payload(quote="I led a climate club for two years"):
    q = f'"{quote}"' if quote else ""
    ev = f"[{q}]" if quote else "[]"
    return ( # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
        "{"
        f'"growth_potential": {{"score": 4, "confidence": 0.9, "evidence": {ev}, "explanation": "Solid."}},'
        f'"social_impact": {{"score": 3, "confidence": 0.8, "evidence": [], "explanation": "Some."}},'
        f'"commitment": {{"score": 5, "confidence": 0.9, "evidence": [], "explanation": "Long."}},'
        f'"team_orientation": {{"score": 2, "confidence": 0.7, "evidence": [], "explanation": "Little."}},'
        f'"initiative": {{"score": 4, "confidence": 0.85, "evidence": [], "explanation": "Good."}}'
        "}"
    )


# ---------------------------------------------------------------- cacheability


def test_static_prompt_identical_across_applicants():
    """The cached prefix must not vary between applicants, or caching breaks."""
    ev = make_evaluator()
    first = ev.static_prompt()
    ev2 = make_evaluator()
    assert first == ev2.static_prompt()
    assert ev.static_prompt_hash() == ev2.static_prompt_hash()


def test_static_prompt_contains_no_applicant_data():
    prompt = build_static_prompt(RUBRIC)
    assert "@" not in prompt
    assert "applicant@" not in prompt.lower()


def test_static_prompt_has_no_timestamp():
    """A timestamp in the prefix would invalidate the cache on every call."""
    import re

    prompt = build_static_prompt(RUBRIC)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", prompt)


def test_rubric_change_changes_hash():
    a = make_evaluator(StubRubricLoader("rubric A"))
    b = make_evaluator(StubRubricLoader("rubric B"))
    assert a.static_prompt_hash() != b.static_prompt_hash()


def test_rubric_precedes_nothing_dynamic():
    """Regression guard: the rubric lives in the static prefix, not after user text."""
    prompt = build_static_prompt(RUBRIC)
    assert RUBRIC in prompt
    assert "<application_text>" not in prompt


def test_cache_control_attached_when_enabled():
    ev = make_evaluator(use_prompt_caching=True)
    blocks = ev._system_blocks()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_cache_control_absent_when_disabled():
    ev = make_evaluator(use_prompt_caching=False)
    assert "cache_control" not in ev._system_blocks()[0]


def test_rubric_fetched_once_not_per_applicant():
    loader = StubRubricLoader()
    ev = make_evaluator(loader)
    for _ in range(5):
        ev.static_prompt()
    assert loader.calls == 1


# ------------------------------------------------------------ quote verification


@pytest.mark.asyncio
async def test_verbatim_quote_is_kept():
    ev = make_evaluator()
    text = "I led a climate club for two years and loved it."
    ev._create_message = lambda app, mt: make_message(valid_payload())

    result = await ev.evaluate(ApplicationText(applicant_id="a@b.c", raw_text=text), None)
    gp = result.scores[CriterionName.GROWTH_POTENTIAL] # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
    assert len(gp.evidence) == 1
    assert gp.insufficient_evidence is False


@pytest.mark.asyncio
async def test_fabricated_quote_is_dropped():
    """A quote absent from the application must not reach a human reviewer."""
    ev = make_evaluator()
    ev._create_message = lambda app, mt: make_message(
        valid_payload("I founded a global nonprofit")
    )

    result = await ev.evaluate(
        ApplicationText(applicant_id="a@b.c", raw_text="I attended one meeting."), None
    )
    gp = result.scores[CriterionName.GROWTH_POTENTIAL] # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
    assert gp.evidence == []
    assert gp.insufficient_evidence is True


@pytest.mark.asyncio
async def test_empty_evidence_marks_insufficient():
    ev = make_evaluator()
    ev._create_message = lambda app, mt: make_message(valid_payload(quote=""))

    result = await ev.evaluate(
        ApplicationText(applicant_id="a@b.c", raw_text="Nothing here."), None
    )
    assert result.scores[CriterionName.GROWTH_POTENTIAL].insufficient_evidence is True # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC


@pytest.mark.asyncio
async def test_all_five_criteria_present():
    ev = make_evaluator()
    ev._create_message = lambda app, mt: make_message(valid_payload(quote=""))

    result = await ev.evaluate(ApplicationText(applicant_id="a@b.c", raw_text="x"), None)
    assert set(result.scores) == {
        CriterionName.GROWTH_POTENTIAL, # CHANGE THESE CATEGORY NAMES TO MATCH YOUR RUBRIC
        CriterionName.SOCIAL_IMPACT,
        CriterionName.COMMITMENT,
        CriterionName.TEAM_ORIENTATION,
        CriterionName.INITIATIVE,
    }


# ------------------------------------------------------------------- robustness


@pytest.mark.asyncio
async def test_markdown_fences_are_stripped():
    ev = make_evaluator()
    ev._create_message = lambda app, mt: make_message(f"```json\n{valid_payload('')}\n```")

    result = await ev.evaluate(ApplicationText(applicant_id="a@b.c", raw_text="x"), None)
    assert result.scores[CriterionName.COMMITMENT].score == 5 # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC


@pytest.mark.asyncio
async def test_truncated_response_retries_with_larger_cap():
    """Truncation caused the earlier 'Unterminated string' failures."""
    ev = make_evaluator()
    caps = []

    def fake(app, max_tokens): 
        caps.append(max_tokens)
        if len(caps) == 1:
            return make_message('{"growth_potential": {"sco', stop_reason="max_tokens") # CHANGE THIS CATEGORY NAME TO MATCH YOUR RUBRIC
        return make_message(valid_payload(quote=""))

    ev._create_message = fake
    await ev.evaluate(ApplicationText(applicant_id="a@b.c", raw_text="x"), None)

    assert len(caps) == 2
    assert caps[1] > caps[0]


@pytest.mark.asyncio
async def test_malformed_json_raises_with_preview():
    ev = make_evaluator()
    ev._create_message = lambda app, mt: make_message("not json at all")

    with pytest.raises(ValueError, match="Invalid JSON"):
        await ev.evaluate(ApplicationText(applicant_id="a@b.c", raw_text="x"), None)


# -------------------------------------------------------------------- telemetry


def test_usage_log_aggregates_and_hides_emails(tmp_path):
    log_path = tmp_path / "usage.jsonl"
    log = UsageLog(str(log_path))

    log.record(
        applicant_id="secret@example.com",
        model="claude-opus-5",
        input_tokens=50,
        output_tokens=120,
        cache_creation_input_tokens=1500,
        cache_read_input_tokens=0,
        stop_reason="end_turn",
        truncated=False,
        static_prompt_hash="abc123",
    )
    log.record(
        applicant_id="other@example.com",
        model="claude-opus-5",
        input_tokens=60,
        output_tokens=110,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1500,
        stop_reason="end_turn",
        truncated=False,
        static_prompt_hash="abc123",
    )

    assert log.requests == 2
    assert log.cache_read_tokens == 1500
    assert log.cache_hit_rate == 0.5

    written = log_path.read_text()
    assert "secret@example.com" not in written
    assert "other@example.com" not in written


def test_usage_log_flags_broken_caching():
    log = UsageLog(None)
    for _ in range(3):
        log.record("a@b.c", "m", 1500, 100, 0, 0, "end_turn", False, "h")
    assert any("NOT working" in line for line in log.summary_lines())
