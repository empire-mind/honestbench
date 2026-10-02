# honestbench — evals that measure verification, not just passing

English | [简体中文](README.zh-CN.md)

Every benchmark tells you pass/fail. HonestBench asks the harder question:
**did the agent *verify* before claiming it was done?** It audits the
trajectory, not just the patch — because ~10% of benchmark "passes" are
luck (blind retries, missing verification, disordered exploration).

## Status: working foundation, research roadmap

What exists today — two shipped systems, composed:

1. **`evals/`** — an offline-first retrieval/memory eval harness. Adapter
   contract (`init` → `query` → ranked docs), question families with gold
   answer keys, structural anti-cheat (adapters receive blinded queries —
   they *cannot* read the answer keys, even by accident), machine-readable
   scorecards + per-question receipts. Runs with zero API calls.
2. **`code-factory/`** — the hardened execution plane evals run on:
   timeouts, whole-process-group SIGKILL, env scrubbing, cwd jail, network
   isolation, 64 KiB output caps, `runs/<run-id>/` evidence persistence.
   10/10 tests pass (see `code-factory/tests/TEST-LOG.md`).

What's next — the actual lucky-pass detector (trajectory auditing:
blind-retry, missing-verification, regression-cycle, disordered-exploration
detectors with published precision/recall). That's the research roadmap in
the `help wanted` issues. The harness + execution plane are the substrate
it needs; they work now.

## 60-second demo (no API calls, no install)

```bash
git clone https://github.com/empire-mind/honestbench.git
cd honestbench/evals
python3 run.py --adapter grep-only --queries all
```

You get a scorecard and per-question receipts under `evals/reports/`:

```
adapter=grep-only top_k=5 n=6
  recall_all@5: 0.6
  first_hit@5: 0.6
  mean_rank_first: 1.0
  abstention_accuracy: 0.0
```

Try the execution plane too:

```bash
cd ../code-factory
./factory run --language python --timeout 10 - <<'EOF'
print("hello from the factory")
EOF
```

## Design principles

- **Separate denominators.** Retrieval is measured independently of answer
  correctness; a good score on one family is a reason to investigate, not
  a promise about every workload.
- **Adapters can't cheat.** The runner strips gold labels structurally
  before the adapter ever sees a query.
- **Receipts, not vibes.** Every run emits machine-readable scorecards
  with a schema version, config card, and corpus hash. If you can't
  re-run it, it didn't happen.
- **Honest limits, in writing.** `code-factory/CODE-FACTORY.md` documents
  what the execution plane does *not* do (no filesystem sandboxing, silent
  backend degradation). We keep that culture here.

## Layout

```
honestbench/
  evals/            the harness: run.py, adapters/, data/, STAGE-NEXT.md
  code-factory/     the execution plane: factory CLI + factory.py
  examples/         hello-eval walkthrough
```

## Development

```bash
cd evals && python3 run.py --adapter grep-only   # harness smoke
cd ../code-factory && ./factory backends          # execution plane probes
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

**Every issue and external PR gets a first response within 7 calendar
days.** `good first issue` items are scoped for one evening; the
lucky-pass detector work is under `help wanted` and genuinely needs
research help. Full funnel in [CONTRIBUTING.md](CONTRIBUTING.md).
Security issues: see the org
[SECURITY.md](https://github.com/empire-mind/.github/blob/main/SECURITY.md).

## Attribution

Eval methodology adapted from
[garrytan/gbrain-evals](https://github.com/garrytan/gbrain-evals)
(BrainBench), MIT © 2026 Garry Tan — architecture adopted, code original.
See `evals/README.md` and `evals/STAGE-NEXT.md`.

## License

MIT — see [LICENSE](LICENSE).
