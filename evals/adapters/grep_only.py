"""BM25 keyword baseline — the honest 'what could any agent do with a
reasonable ranker in an afternoon' adapter.

Ported conceptually from garrytan/gbrain-evals eval/runner/adapters/grep-only.ts
(MIT). Formula: Robertson & Zaragoza (2009), Lucene defaults k1=1.5, b=0.75.
No embeddings, no LLM, deterministic.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .base import Page, Query, RankedDoc

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "can", "of", "to", "in",
    "on", "at", "for", "with", "by", "from", "as", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "we", "they",
    "them", "us", "him", "her", "his", "hers", "their", "theirs", "my",
    "mine", "your", "yours", "our", "ours", "who", "what", "where", "when",
    "which", "how", "did", "name",
}

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    # split on non-alnum first, so slug parts (e.g. people/alice-chen ->
    # alice, chen) tokenize naturally; drop 1-char tokens and stopwords
    return [
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) >= 2 and t not in STOPWORDS
    ]


class GrepOnlyAdapter:
    name = "grep-only"

    def init(self, pages: list[Page]) -> dict[str, Any]:
        doc_tokens: dict[str, Counter] = {}
        doc_freq: Counter = Counter()
        total_len = 0
        for p in pages:
            toks = tokenize(p.title + " " + p.content)
            counts = Counter(toks)
            doc_tokens[p.slug] = counts
            total_len += len(toks)
            for t in counts:
                doc_freq[t] += 1
        n_docs = len(pages)
        idf = {
            t: math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for t, df in doc_freq.items()
        }
        return {
            "slugs": [p.slug for p in pages],
            "doc_tokens": doc_tokens,
            "idf": idf,
            "avgdl": total_len / max(n_docs, 1),
        }

    def query(self, q: Query, state: dict[str, Any]) -> list[RankedDoc]:
        q_toks = tokenize(q.question)
        scored: list[RankedDoc] = []
        for slug in state["slugs"]:
            counts = state["doc_tokens"][slug]
            dl = sum(counts.values())
            score = 0.0
            for t in q_toks:
                if t not in state["idf"]:
                    continue
                tf = counts.get(t, 0)
                if tf == 0:
                    continue
                idf = state["idf"][t]
                denom = tf + K1 * (1 - B + B * dl / state["avgdl"])
                score += idf * (tf * (K1 + 1)) / denom
            if score > 0:
                scored.append(RankedDoc(slug=slug, score=score))
        scored.sort(key=lambda d: d.score, reverse=True)
        return scored
