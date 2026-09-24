# Staged: what a full BrainBench-style port would need

The working baseline lives here (`run.py` + `adapters/grep_only.py`). The
pieces below are staged, not built — each needs the named prerequisite.

Ported from the design of garrytan/gbrain-evals (MIT). Their repo is the
reference implementation; do not re-implement from scratch what can be cited.

## 1. Vector + hybrid adapters
- **What:** a `vector` adapter (embeddings + cosine) and a hybrid RRF-fusion
  adapter combining keyword + vector, mirroring their four-adapter comparison.
- **Needs:** an embeddings call that never hits disk with a raw key — route via
  the agent-stack's SDK path (OpenAI embeddings) or Gemini embeddings. See
  `~/workspace/agent-stack/ORCHESTRATION.md` routing map.
- **Why:** their data shows vector search alone beats keyword on
  differently-worded concept questions (118/181 vs keyword baseline); hybrid
  wins overall. Our sample corpus is too small to prove it — build a real
  corpus first (see 4).

## 2. Relationship/graph adapter
- **What:** extraction of typed relationships (e.g. "invested in") and graph
  traversal answering relational templates, mirroring their `gbrain` adapter.
- **Needs:** an entity/relation extractor over our corpus (LLM or rule-based),
  plus a parser for the question templates we care about.
- **Why:** the baseline visibly fails q04/q05 (relational) — this is the
  capability our memory vault (MOCs, wiki-links) is *designed* for, so it
  should beat keyword here. Their controlled test: 9/39 → 21/39 first-place
  hits on investor questions with relationship retrieval on.

## 3. Write-path eval (transcript distillation)
- **What:** measure how much useful material survives when a session becomes a
  memory page (their cat35). Recorded retention 70.2% → 88.1% after a repair;
  7.0% claim hallucination on the write path.
- **Needs:** an LLM judge with human calibration; pairs of (session
  transcript → distilled page) from our daily note pipeline.
- **Why:** directly scores our MEMORY.md / daily-notes pipeline quality.

## 4. Real corpus + question families
- **What:** a held-out question set with gold keys against a real (or large
  fictional) corpus; source-swamp test (their cat13b) to catch popularity-bias.
- **Needs:** question authoring discipline from their `eval/CONTRIBUTING.md`:
  slug-keyed gold lists, verified answer pages, abstention questions,
  `as_of_date` for time-sensitive wording. Never use real personal data in a
  shared corpus.
- **Why:** 8 pages / 6 questions is a smoke test, not an eval.

## 5. Docs to port (read, don't rewrite)
- `docs/retrieval-lessons.md` — when words, vectors, or relationships win;
  what retrieval scores mean vs. answer accuracy.
- `docs/settings.md` — practical defaults: when to rerank, trim, expand,
  favor a source. (Their finding: score-based trimming *hurt* multi-evidence
  questions — 379/470 → 449/470 when disabled; extra query rewrites hurt at k=5.)
- `eval/RUNBOOK.md` — how to reproduce a run; receipts as the unit of record.

## Explicitly out of scope
- Copying their TypeScript runner (Bun stack, fictional corpus, gbrain
  internals) — the methodology ports, the code doesn't need to.
- Paid-provider matrix comparisons — revisit only when an embedding/reranker
  decision is actually on the table.
