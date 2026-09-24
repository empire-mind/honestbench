# empiremind evals — agent-stack evaluation harness

A minimal, offline-first evaluation harness for the empiremind agent stack's
retrieval and agent memory behavior.

**Attribution.** Methodology adapted from [garrytan/gbrain-evals](https://github.com/garrytan/gbrain-evals)
(BrainBench), MIT © 2026 Garry Tan. We adopt their *architecture*, not their
code: the adapter contract (`init` → `query` → ranked docs), question families
with gold answer keys, and machine-readable receipts/scorecards. See
`STAGE-NEXT.md` for what a fuller port would add.

## Why this exists

Scoring a memory/retrieval setup is cheaper than arguing about it. This harness
answers narrow questions:

| Question | Entry point |
|---|---|
| Does keyword search find the right memory pages? | `--adapter grep-only` |
| Does *our* retrieval (once we add it) beat the baseline? | `--adapter <ours>` (see STAGE-NEXT.md) |
| Do conversations become useful memory pages? (write path) | staged — `STAGE-NEXT.md` |
| Does the right memory surface at the right time? | staged — `STAGE-NEXT.md` |

Scores are **separate measurements with separate denominators**: retrieval
(reported pages vs. gold pages) is measured independently of answer correctness.
A good score on one question family is a reason to investigate that capability,
not a promise about every workload.

## Quick start (no API calls)

```bash
cd evals
python3 run.py --adapter grep-only --queries all
```

Writes `reports/scorecard.json` and per-question receipts under `reports/`.

## Layout

```
evals/
  README.md            this file
  STAGE-NEXT.md        what a full BrainBench-style port would need
  run.py               CLI entry: --adapter, --queries, --top-k
                       (runner + metrics + receipt/scorecard emission)
  adapters/
    base.py            Adapter protocol (init/query), RankedDoc
    grep_only.py       BM25 keyword baseline (offline, deterministic)
  data/
    sample_corpus.json     fictional mini-world (8 pages; never use real data)
    sample_questions.json  6 questions: factoid, concept, relational, abstention
  reports/             generated scorecards/receipts (gitignored)
```

## Metrics

- `recall_all@k` — fraction of questions where *all* gold pages appear in top-k.
  A question needing two pages does not count if only one is found.
- `first_hit@k` — fraction with ≥1 gold page in top-k.
- `mean_rank_first` — average rank of the first gold hit (lower is better).
- `abstention_accuracy` — for questions with no answer in the corpus, fraction
  where the adapter correctly reported nothing (empty ranking).
