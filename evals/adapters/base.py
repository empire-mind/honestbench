"""Adapter protocol for empiremind evals.

Mirrors the garrytan/gbrain-evals (BrainBench) adapter contract, in Python:

    init(corpus) -> state          # ingest pages once
    query(q, state) -> RankedDoc[] # ranked results for one question

`BrainState` is opaque to the runner: adapters choose their representation.
The runner strips gold labels before calling query() — adapters must never
read the answer keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    content: str


@dataclass(frozen=True)
class RankedDoc:
    slug: str
    score: float


@dataclass(frozen=True)
class Query:
    id: str
    family: str  # factoid | concept | relational | abstention
    question: str
    gold: tuple[str, ...] = field(default_factory=tuple)
    expected_abstention: bool = False


class Adapter(Protocol):
    name: str

    def init(self, pages: list[Page]) -> Any:
        """Ingest the corpus once; return opaque state."""
        ...

    def query(self, q: Query, state: Any) -> list[RankedDoc]:
        """Return ranked docs for the question (empty list = abstain)."""
        ...
