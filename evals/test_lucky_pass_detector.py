"""Unit tests for lucky_pass_detector."""
from pathlib import Path

from evals.lucky_pass_detector import audit_trajectory, evaluate_corpus


def test_evaluate_corpus():
    corpus_path = Path(__file__).resolve().parent / "data" / "synthetic_trajectories.json"
    results = evaluate_corpus(corpus_path)
    assert results["n_trajectories"] == 20

    overall = results["metrics"]["overall_lucky_pass"]
    assert overall["precision"] == 1.0
    assert overall["recall"] == 1.0
    assert overall["f1"] == 1.0

    br = results["metrics"]["blind_retry"]
    assert br["precision"] == 1.0
    assert br["recall"] == 1.0

    mv = results["metrics"]["missing_verification"]
    assert mv["precision"] == 1.0
    assert mv["recall"] == 1.0


def test_clean_trajectory():
    traj = {
        "id": "clean_sample",
        "steps": [
            {"action": "edit_file", "input": "app.py"},
            {"action": "run_command", "input": "pytest tests/", "exit_code": 0},
            {"action": "finish", "input": "Done"},
        ],
    }
    audit = audit_trajectory(traj)
    assert not audit.is_lucky_pass
    assert not audit.blind_retry.detected
    assert not audit.missing_verification.detected


def test_missing_verification_detected():
    traj = {
        "id": "unverified_sample",
        "steps": [
            {"action": "edit_file", "input": "app.py"},
            {"action": "finish", "input": "Done"},
        ],
    }
    audit = audit_trajectory(traj)
    assert audit.is_lucky_pass
    assert audit.missing_verification.detected


def test_blind_retry_detected():
    traj = {
        "id": "retry_sample",
        "steps": [
            {"action": "run_command", "input": "pytest tests/", "exit_code": 1},
            {"action": "run_command", "input": "pytest tests/", "exit_code": 0},
        ],
    }
    audit = audit_trajectory(traj)
    assert audit.is_lucky_pass
    assert audit.blind_retry.detected
