"""Lucky-pass detector v0 — trajectory auditing for agent verification.

Flagship thesis: audit trajectories for verification, not just pass/fail.
Detects:
1. missing_verification: code/files were modified but no passing verification
   command was executed after the final modification before claiming completion.
2. blind_retry: a step failed and was immediately retried identically without
   diagnostic investigation, or code was blindly churned without reading errors.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

VERIFICATION_KEYWORDS = (
    "pytest",
    "test",
    "unittest",
    "mypy",
    "ruff",
    "flake8",
    "check",
    "verify",
    "build",
    "cargo test",
    "npm test",
    "go test",
)

MUTATION_ACTIONS = (
    "edit_file",
    "write_file",
    "replace_file_content",
    "patch",
)

DIAGNOSTIC_ACTIONS = (
    "read_file",
    "view_file",
    "inspect",
    "search_code",
    "git diff",
    "git status",
    "cat",
    "grep",
)


@dataclass(frozen=True)
class DetectionResult:
    detected: bool
    reason: str


@dataclass(frozen=True)
class TrajectoryAudit:
    trajectory_id: str
    is_lucky_pass: bool
    blind_retry: DetectionResult
    missing_verification: DetectionResult


def _is_verification_step(step: dict[str, Any]) -> bool:
    action = step.get("action", "")
    inp = str(step.get("input", "")).lower()
    if action == "run_command":
        return any(kw in inp for kw in VERIFICATION_KEYWORDS)
    return False


def _is_diagnostic_step(step: dict[str, Any]) -> bool:
    action = step.get("action", "")
    inp = str(step.get("input", "")).lower()
    if action in DIAGNOSTIC_ACTIONS:
        return True
    if action == "run_command":
        return any(kw in inp for kw in ("git diff", "git status", "cat ", "grep ", "head ", "tail "))
    return False


def detect_missing_verification(steps: list[dict[str, Any]]) -> DetectionResult:
    """Detect if file mutations were made without subsequent verification."""
    last_mutation_idx = -1
    for i, s in enumerate(steps):
        if s.get("action") in MUTATION_ACTIONS:
            last_mutation_idx = i

    if last_mutation_idx == -1:
        return DetectionResult(detected=False, reason="No code mutations performed.")

    # Look for a successful verification step after the last mutation
    has_verification = False
    for s in steps[last_mutation_idx + 1 :]:
        if _is_verification_step(s) and s.get("exit_code") == 0:
            has_verification = True
            break

    if not has_verification:
        return DetectionResult(
            detected=True,
            reason=f"Code modified at step {last_mutation_idx + 1} with no passing verification before completion.",
        )
    return DetectionResult(detected=False, reason="Verified with passing test/build after last mutation.")


def detect_blind_retry(steps: list[dict[str, Any]]) -> DetectionResult:
    """Detect blind retries of failing actions or blind modifications without diagnostic steps."""
    for i in range(len(steps) - 1):
        curr = steps[i]
        nxt = steps[i + 1]

        # Case 1: Failure followed immediately by the identical command
        if curr.get("exit_code", 0) != 0 and curr.get("action") == "run_command":
            if nxt.get("action") == "run_command" and nxt.get("input") == curr.get("input"):
                return DetectionResult(
                    detected=True,
                    reason=f"Blind retry of identical command '{curr.get('input')}' at steps {i + 1} and {i + 2}.",
                )

        # Case 2: Test failure followed by code modification without reading files or diagnostics
        if curr.get("exit_code", 0) != 0 and _is_verification_step(curr):
            if nxt.get("action") in MUTATION_ACTIONS:
                return DetectionResult(
                    detected=True,
                    reason=f"Blind code modification at step {i + 2} immediately following failure at step {i + 1} without diagnostic inspection.",
                )

    return DetectionResult(detected=False, reason="No blind retries detected.")


def audit_trajectory(trajectory: dict[str, Any]) -> TrajectoryAudit:
    steps = trajectory.get("steps", [])
    mv = detect_missing_verification(steps)
    br = detect_blind_retry(steps)
    is_lucky = mv.detected or br.detected
    return TrajectoryAudit(
        trajectory_id=trajectory.get("id", "unknown"),
        is_lucky_pass=is_lucky,
        blind_retry=br,
        missing_verification=mv,
    )


def compute_metrics(y_true: list[bool], y_pred: list[bool]) -> dict[str, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def evaluate_corpus(corpus_path: Path) -> dict[str, Any]:
    with open(corpus_path, encoding="utf-8") as f:
        data = json.load(f)

    trajectories = data.get("trajectories", [])
    results: list[dict[str, Any]] = []

    true_lucky, pred_lucky = [], []
    true_br, pred_br = [], []
    true_mv, pred_mv = [], []

    for traj in trajectories:
        labels = traj.get("labels", {})
        audit = audit_trajectory(traj)

        t_lucky = bool(labels.get("is_lucky_pass", False))
        p_lucky = audit.is_lucky_pass
        t_br = bool(labels.get("blind_retry", False))
        p_br = audit.blind_retry.detected
        t_mv = bool(labels.get("missing_verification", False))
        p_mv = audit.missing_verification.detected

        true_lucky.append(t_lucky)
        pred_lucky.append(p_lucky)
        true_br.append(t_br)
        pred_br.append(p_br)
        true_mv.append(t_mv)
        pred_mv.append(p_mv)

        results.append({
            "id": audit.trajectory_id,
            "expected_lucky": t_lucky,
            "predicted_lucky": p_lucky,
            "blind_retry": asdict(audit.blind_retry),
            "missing_verification": asdict(audit.missing_verification),
        })

    return {
        "n_trajectories": len(trajectories),
        "metrics": {
            "overall_lucky_pass": compute_metrics(true_lucky, pred_lucky),
            "blind_retry": compute_metrics(true_br, pred_br),
            "missing_verification": compute_metrics(true_mv, pred_mv),
        },
        "audits": results,
    }


if __name__ == "__main__":
    corpus = Path(__file__).resolve().parent / "data" / "synthetic_trajectories.json"
    eval_res = evaluate_corpus(corpus)
    print(f"Evaluated {eval_res['n_trajectories']} trajectories:")
    for k, v in eval_res["metrics"].items():
        print(f"  {k}: Precision={v['precision']} Recall={v['recall']} F1={v['f1']} (TP={v['tp']}, FP={v['fp']}, FN={v['fn']}, TN={v['tn']})")
