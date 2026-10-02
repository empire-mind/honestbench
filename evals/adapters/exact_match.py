"""Exact-match baseline — the naive 'exact term frequency' adapter.

Ranks documents by the raw frequency of query tokens matching in the document
title and content. Unlike grep-only (BM25), it uses no inverse document frequency
(IDF) weighting, no term saturation parameter (k1), and no document length
normalization (b). Deterministic and offline.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .base import Page, Query, RankedDoc
from .grep_only import tokenize


class ExactMatchAdapter:
    name = "exact-match"

    def init(self, pages: list[Page]) -> dict[str, Any]:
        doc_tokens: dict[str, Counter] = {}
        for p in pages:
            toks = tokenize(p.title + " " + p.content)
            doc_tokens[p.slug] = Counter(toks)
        return {
            "slugs": [p.slug for p in pages],
            "doc_tokens": doc_tokens,
        }

    def query(self, q: Query, state: dict[str, Any]) -> list[RankedDoc]:
        q_toks = tokenize(q.question)
        scored: list[RankedDoc] = []
        for slug in state["slugs"]:
            counts = state["doc_tokens"][slug]
            score = float(sum(counts.get(t, 0) for t in q_toks))
            if score > 0:
                scored.append(RankedDoc(slug=slug, score=score))
        scored.sort(key=lambda d: (-d.score, d.slug))
        return scored
