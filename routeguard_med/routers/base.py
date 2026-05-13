"""Router base classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from routeguard_med.schemas import EvidenceSnippet, RouterDecision


class BaseRouter(ABC):
    name: str = "base"

    @abstractmethod
    def route(self, query: str, evidence: List[EvidenceSnippet] | None = None) -> RouterDecision:
        raise NotImplementedError
