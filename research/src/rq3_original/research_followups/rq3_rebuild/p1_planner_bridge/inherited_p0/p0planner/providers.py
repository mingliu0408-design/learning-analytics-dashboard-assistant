"""Deterministic supplied objects only. No SDK, transport or model imports."""
from copy import deepcopy
from typing import Any

from .contracts import CandidateRequest


class ProductionTransportDisabled(RuntimeError):
    pass


class ProductionProvider:
    def __init__(self, *args: Any, **kwargs: Any):
        # No client factory is accepted, instantiated or called before failure.
        raise ProductionTransportDisabled("P0 production transport is unimplemented and disabled before client construction.")


class MockProvider:
    def __init__(self, candidates: list[Any]):
        self._candidates = deepcopy(candidates)
        self.requests: list[CandidateRequest] = []

    def propose(self, request: CandidateRequest) -> Any:
        index = len(self.requests)
        self.requests.append(request)
        if index >= len(self._candidates):
            raise IndexError("No supplied synthetic candidate remains.")
        return deepcopy(self._candidates[index])
