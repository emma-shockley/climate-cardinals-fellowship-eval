""""
Records token usage (input, output, and cache read/write) for every call to
Claude, and turns it into a plain-language cost summary at the end of a run.

Privacy: applicant identities are hashed (SHA-256) before being written to
the log file - the log never contains a raw email or name.

Self-check: if prompt caching should be active but zero cache reads show up
across a multi-applicant run, this prints a warning rather than silently
paying full price for every applicant.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class UsageLog:
    """Accumulates per-request token usage and writes it to a JSONL file."""

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.truncations = 0

    @staticmethod
    def _anonymise(applicant_id: str) -> str:
        return hashlib.sha256(applicant_id.encode("utf-8")).hexdigest()[:16]

    def record(
        self,
        applicant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int,
        cache_read_input_tokens: int,
        stop_reason: str | None,
        truncated: bool,
        static_prompt_hash: str,
    ) -> None:
        self.requests += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_tokens += cache_creation_input_tokens
        self.cache_read_tokens += cache_read_input_tokens
        if truncated:
            self.truncations += 1

        if not self.path:
            return

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "applicant": self._anonymise(applicant_id),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "stop_reason": stop_reason,
            "truncated": truncated,
            "static_prompt_hash": static_prompt_hash,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    # ------------------------------------------------------------------ summary

    @property
    def billable_input_tokens(self) -> int:
        """Fresh input tokens billed at the full rate (cache reads excluded)."""
        return self.input_tokens + self.cache_creation_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Share of prefix tokens served from cache rather than billed fresh."""
        total = self.cache_read_tokens + self.cache_creation_tokens
        return (self.cache_read_tokens / total) if total else 0.0

    def summary_lines(self) -> list[str]:
        if not self.requests:
            return ["  (no API requests recorded)"]

        lines = [
            f"  Requests:                {self.requests:,}",
            f"  Fresh input tokens:      {self.input_tokens:,}",
            f"  Cache WRITE tokens:      {self.cache_creation_tokens:,}  (full price, first call only)",
            f"  Cache READ tokens:       {self.cache_read_tokens:,}  (heavily discounted)",
            f"  Output tokens:           {self.output_tokens:,}",
            f"  Cache hit rate:          {self.cache_hit_rate:.1%}",
            f"  Avg output/applicant:    {self.output_tokens / self.requests:,.0f}",
        ]
        if self.truncations:
            lines.append(f"  Truncated responses:     {self.truncations:,}")
        if self.cache_read_tokens == 0 and self.requests > 1:
            lines.append(
                "  ⚠ No cache reads recorded — prompt caching is NOT working. "
                "Check that the rubric has not changed mid-run."
            )
        return lines
