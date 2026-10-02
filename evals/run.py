"""Empiremind evals runner: loads corpus + questions, runs an adapter,
scores, and emits a scorecard + per-question receipts.

Metrics (mirroring gbrain-evals' separation of denominators):
- recall_all@k: all gold pages in top-k
- first_hit@k:  >=1 gold page in top-k
- mean_rank_first: average rank of first gold hit
- abstention_accuracy: correct empty rankings on abstention questions
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from adapters.base import Page, Query
from adapters.exact_match import ExactMatchAdapter
from adapters.grep_only import GrepOnlyAdapter

BLIND_FIELDS = {"gold": (), "expected_abstention": False}


def blind(query: Query) -> Query:
    """Return a copy of the query with answer keys stripped.

    The adapter contract (adapters/base.py) says the runner strips gold
    labels before calling query() — adapters must never read the answer
    keys. Enforce it structurally: an adapter handed a blinded Query
    cannot cheat, even by accident.
    """
    import dataclasses

    return dataclasses.replace(query, **BLIND_FIELDS)

HERE = Path(__file__).resolve().parent

ADAPTERS = {
    "exact-match": ExactMatchAdapter,
    "grep-only": GrepOnlyAdapter,
}


def load_json(path: Path):
    return json.loads(path.read_text())


def corpus_sha(pages: list[Page]) -> str:
    h = hashlib.sha256()
    for p in sorted(pages, key=lambda p: p.slug):
        h.update(f"{p.slug}\n{p.title}\n{p.content}\n".encode())
    return h.hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description="empiremind evals runner")
    ap.add_argument("--adapter", default="grep-only", choices=sorted(ADAPTERS))
    ap.add_argument("--queries", default="all",
                    help="'all' or a family: factoid, concept, relational, abstention")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    corpus = load_json(HERE / "data" / "sample_corpus.json")
    qdata = load_json(HERE / "data" / "sample_questions.json")
    pages = [Page(**p) for p in corpus["pages"]]
    queries = [Query(id=q["id"], family=q["family"], question=q["question"],
                     gold=tuple(q.get("gold", ())),
                     expected_abstention=q.get("family") == "abstention")
               for q in qdata["questions"]]
    if args.queries != "all":
        queries = [q for q in queries if q.family == args.queries]

    adapter = ADAPTERS[args.adapter]()
    state = adapter.init(pages)

    receipts = []
    for q in queries:
        ranked = adapter.query(blind(q), state)[: args.top_k]
        found = [d.slug for d in ranked]
        if q.expected_abstention:
            score = {
                "abstention_correct": len(found) == 0,
            }
            gold_hits = []
            first_rank = None
        else:
            gold = list(q.gold)
            gold_hits = [g for g in gold if g in found]
            ranks = [found.index(g) + 1 for g in gold_hits]
            first_rank = min(ranks) if ranks else None
            score = {
                "recall_all": len(gold_hits) == len(gold) and len(gold) > 0,
                "first_hit": len(gold_hits) > 0,
                "first_rank": first_rank,
                "gold_found": f"{len(gold_hits)}/{len(gold)}",
            }
        receipts.append({
            "query_id": q.id, "family": q.family, "question": q.question,
            "gold": list(q.gold), "expected_abstention": q.expected_abstention,
            "ranked": found, **score,
        })

    k = args.top_k
    scored = [r for r in receipts if not r["expected_abstention"]]
    abst = [r for r in receipts if r["expected_abstention"]]
    metrics = {
        "n_questions": len(receipts),
        "recall_all@%d" % k: (sum(r["recall_all"] for r in scored) / len(scored)) if scored else 0.0,
        "first_hit@%d" % k: (sum(r["first_hit"] for r in scored) / len(scored)) if scored else 0.0,
        "mean_rank_first": (sum(r["first_rank"] for r in scored if r["first_rank"]) /
                            max(1, sum(1 for r in scored if r["first_rank"]))),
        "abstention_accuracy": (sum(r["abstention_correct"] for r in abst) / len(abst)) if abst else None,
    }

    scorecard = {
        "schema_version": 1,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "config_card": {
            "evals_version": "0.1.0",
            "adapter": {"name": adapter.name, "stack_id": "empiremind/evals-0.1.0"},
            "corpus_sha": corpus_sha(pages),
            "top_k": k,
        },
        "metrics": metrics,
        "per_question": receipts,
    }

    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(scorecard, indent=2) + "\n")
    for r in receipts:
        (out / f"{r['query_id']}-receipt.json").write_text(json.dumps(r, indent=2) + "\n")

    print(f"adapter={adapter.name} top_k={k} n={len(receipts)}")
    for key, val in metrics.items():
        if val is not None:
            print(f"  {key}: {round(val, 3) if isinstance(val, float) else val}")
    print(f"\nreceipts -> {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
