"""Deterministic, zero-network provider used only by Stage 1D unit tests."""

from __future__ import annotations

from collections.abc import Sequence


class MockResponseExhausted(RuntimeError):
    """Raised when no configured mock response remains."""


class DeterministicMockProvider:
    """Return configured strings in order without importing or calling a network API."""

    offline_only = True
    provider_name = "DETERMINISTIC_MOCK"

    def __init__(self, responses: str | Sequence[str]) -> None:
        configured = (responses,) if isinstance(responses, str) else tuple(responses)
        if not configured or any(not isinstance(item, str) for item in configured):
            raise ValueError("responses must contain one or more strings")
        self._responses = configured
        self._call_count = 0
        self._received_prompts: list[str] = []

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def network_call_count(self) -> int:
        return 0

    @property
    def real_provider_call_count(self) -> int:
        return 0

    @property
    def received_prompts(self) -> tuple[str, ...]:
        return tuple(self._received_prompts)

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("prompt must be non-empty text")
        response_index = self._call_count
        self._call_count += 1
        self._received_prompts.append(prompt)
        if response_index >= len(self._responses):
            raise MockResponseExhausted(
                f"no configured response for mock call {response_index + 1}"
            )
        return self._responses[response_index]
