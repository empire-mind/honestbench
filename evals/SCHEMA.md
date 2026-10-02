# Evaluation Schema Reference (`evals/SCHEMA.md`)

This document specifies the exact JSON schemas for evaluation artifacts emitted by `evals/run.py`:
1. **`reports/scorecard.json`** — Aggregate run evaluation summary.
2. **`reports/{query_id}-receipt.json`** — Per-question evaluation receipts.

---

## 1. Scorecard Schema (`scorecard.json`)

The top-level summary emitted after every evaluation run.

### Field Definitions

| Field | Type | Classification | Description |
|---|---|---|---|
| `schema_version` | `integer` | **Stable API** | Version of the scorecard schema (currently `1`). Consumers should reject unsupported versions. |
| `ran_at` | `string` (ISO 8601 UTC) | **Stable API** | Timestamp when the evaluation completed in UTC (e.g. `2026-10-02T08:45:16.151262+00:00`). |
| `config_card` | `object` | **Stable API** | Parameters that define the exact evaluation run configuration. |
| `config_card.evals_version` | `string` | **Stable API** | SemVer of the evaluation engine (`"0.1.0"`). |
| `config_card.adapter` | `object` | **Stable API** | Adapter metadata. |
| `config_card.adapter.name` | `string` | **Stable API** | Name of the evaluated adapter (e.g. `"grep-only"`, `"exact-match"`). |
| `config_card.adapter.stack_id` | `string` | **Informational** | Stack identifier (e.g. `"empiremind/evals-0.1.0"`). |
| `config_card.corpus_sha` | `string` | **Stable API** | 16-character SHA-256 fingerprint of the corpus pages sorted by slug. |
| `config_card.top_k` | `integer` | **Stable API** | Maximum number of ranked documents considered for metrics (default: `5`). |
| `metrics` | `object` | **Stable API** | Summary metrics computed across all queries. |
| `metrics.n_questions` | `integer` | **Stable API** | Total number of queries executed. |
| `metrics.recall_all@k` | `number` (0.0–1.0) | **Stable API** | Fraction of non-abstention queries where **all** gold pages appear in top-k. |
| `metrics.first_hit@k` | `number` (0.0–1.0) | **Stable API** | Fraction of non-abstention queries where at least one gold page appears in top-k. |
| `metrics.mean_rank_first` | `number` (float) | **Stable API** | Mean 1-indexed rank of the first gold hit across queries with ≥1 hit. |
| `metrics.abstention_accuracy`| `number` or `null` | **Stable API** | Fraction of abstention queries where the ranking was correctly empty. |
| `per_question` | `array[object]` | **Stable API** | Array of individual per-question receipt objects (see Section 2). |

### Example Scorecard

```json
{
  "schema_version": 1,
  "ran_at": "2026-10-02T08:45:16.151262+00:00",
  "config_card": {
    "evals_version": "0.1.0",
    "adapter": {
      "name": "grep-only",
      "stack_id": "empiremind/evals-0.1.0"
    },
    "corpus_sha": "2a98f8eed5429da4",
    "top_k": 5
  },
  "metrics": {
    "n_questions": 6,
    "recall_all@5": 0.6,
    "first_hit@5": 0.6,
    "mean_rank_first": 1.0,
    "abstention_accuracy": 0.0
  },
  "per_question": [...]
}
```

---

## 2. Per-Question Receipt Schema (`{query_id}-receipt.json`)

Emitted for each question evaluated during the run.

### Common Fields (All Questions)

| Field | Type | Classification | Description |
|---|---|---|---|
| `query_id` | `string` | **Stable API** | Unique identifier of the question (e.g. `"q01"`, `"q06"`). |
| `family` | `string` | **Stable API** | Question family category: `"factoid"`, `"concept"`, `"relational"`, or `"abstention"`. |
| `question` | `string` | **Informational** | Full natural language text of the query. |
| `gold` | `array[string]` | **Stable API** | Slugs of gold ground-truth pages. Empty for abstention questions. |
| `expected_abstention` | `boolean` | **Stable API** | `true` if the question has no answer in the corpus and expects an empty ranking. |
| `ranked` | `array[string]` | **Stable API** | Slugs of retrieved documents ranked in descending score order (up to `top_k`). |

### Standard Query Specific Fields (`expected_abstention == false`)

| Field | Type | Classification | Description |
|---|---|---|---|
| `recall_all` | `boolean` | **Stable API** | `true` if all gold document slugs are present in `ranked`. |
| `first_hit` | `boolean` | **Stable API** | `true` if at least one gold document slug is present in `ranked`. |
| `first_rank` | `integer` or `null` | **Stable API** | 1-indexed rank of the highest-ranking gold document, or `null` if none retrieved. |
| `gold_found` | `string` | **Informational** | Human-readable string indicating proportion found (e.g. `"1/1"`, `"2/2"`). |

#### Example Standard Receipt (`q01-receipt.json`)

```json
{
  "query_id": "q01",
  "family": "factoid",
  "question": "Who owns the motion-planning stack at Nova Robotics?",
  "gold": [
    "people/alice-chen"
  ],
  "expected_abstention": false,
  "ranked": [
    "people/alice-chen",
    "companies/nova-robotics",
    "notes/sprint-42",
    "docs/wiki-motion-planning",
    "people/bob-okafor"
  ],
  "recall_all": true,
  "first_hit": true,
  "first_rank": 1,
  "gold_found": "1/1"
}
```

### Abstention Specific Fields (`expected_abstention == true`)

| Field | Type | Classification | Description |
|---|---|---|---|
| `abstention_correct` | `boolean` | **Stable API** | `true` if `ranked` is empty (`len(ranked) == 0`). `false` if the adapter retrieved documents. |

#### Example Abstention Receipt (`q06-receipt.json`)

```json
{
  "query_id": "q06",
  "family": "abstention",
  "question": "What is the Series C valuation of Nova Robotics?",
  "gold": [],
  "expected_abstention": true,
  "ranked": [
    "companies/nova-robotics",
    "people/bob-okafor",
    "companies/meridian-ventures",
    "people/alice-chen",
    "notes/board-minutes-q1"
  ],
  "abstention_correct": false
}
```

---

## 3. Stability Guarantees

- **Stable API fields**: Keys and value formats will not change without incrementing `schema_version`. Automation and scoring pipelines can safely build assertions on these fields.
- **Informational fields**: Human-oriented context (such as question wording or formatted strings like `gold_found`). Consumers should not rely on them for algorithmic decisions.
