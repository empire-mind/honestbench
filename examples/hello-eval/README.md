# hello-eval — your first HonestBench run

No API keys. No install. Offline.

```bash
cd ../../evals
python3 run.py --adapter grep-only --queries all
```

What just happened:

1. The runner loaded `data/sample_corpus.json` (8 fictional pages —
   never use real data in eval fixtures) and `data/sample_questions.json`
   (6 questions across 4 families: factoid, concept, relational,
   abstention).
2. It **blinded** every query (stripped the gold answer keys) before
   handing it to the adapter — the adapter cannot cheat, even by accident.
3. The `grep-only` baseline adapter ranked pages per query; the runner
   scored recall, first-hit, mean rank, and abstention accuracy.
4. It wrote `reports/scorecard.json` (metrics + config card + corpus hash)
   and one receipt per question (`reports/<query-id>-receipt.json`).

Now try:

```bash
python3 run.py --adapter grep-only --queries abstention --top-k 3
```

Then read `evals/STAGE-NEXT.md` — it lists exactly what a fuller port
needs, and several `good first issue` items map 1:1 onto it.
