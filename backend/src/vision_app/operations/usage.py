"""Attempt usage aggregation with estimates and provider measurements kept distinct."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UsageSnapshot:
    estimated_microusd: int
    measured_microusd: int
    model_calls: int
    failed_calls: int
    retried_calls: int
    input_tokens: int
    output_tokens: int


class UsageAggregator:
    def __init__(self) -> None:
        self._estimated = 0
        self._measured = 0
        self._calls = 0
        self._failed = 0
        self._retried = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def record_call(
        self,
        *,
        estimated_microusd: int,
        measured_microusd: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        failed: bool = False,
        retry: bool = False,
    ) -> None:
        values = (estimated_microusd, measured_microusd, input_tokens, output_tokens)
        if any(value < 0 for value in values):
            raise ValueError("usage cannot be negative")
        self._estimated += estimated_microusd
        self._measured += measured_microusd
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._calls += 1
        self._failed += int(failed)
        self._retried += int(retry)

    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            estimated_microusd=self._estimated,
            measured_microusd=self._measured,
            model_calls=self._calls,
            failed_calls=self._failed,
            retried_calls=self._retried,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
