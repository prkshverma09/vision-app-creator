"""Deterministic VisualReasoner fake; never performs network calls."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from vision_app.contracts.models import SemanticObservation


class ScriptedVisualReasoner:
    def __init__(
        self, *, classifications: Sequence[SemanticObservation] = (),
        reviews: Sequence[dict[str, Any]] = (), delay_ms: int = 0,
    ) -> None:
        self._classifications = list(classifications)
        self._reviews = list(reviews)
        self._delay_ms = delay_ms
        self.classify_calls = 0
        self.review_calls = 0

    async def _delay(self) -> None:
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000)

    async def classify(self, source_id: str, start_ms: int, end_ms: int, prompt: str) -> SemanticObservation:
        del source_id, start_ms, end_ms, prompt
        self.classify_calls += 1
        await self._delay()
        if not self._classifications:
            raise AssertionError("unexpected classify call: script exhausted")
        return self._classifications.pop(0)

    async def review_candidate(self, prompt: str, *, evidence_refs: list[str]) -> dict[str, Any]:
        del prompt, evidence_refs
        self.review_calls += 1
        await self._delay()
        if not self._reviews:
            raise AssertionError("unexpected review call: script exhausted")
        return self._reviews.pop(0)
