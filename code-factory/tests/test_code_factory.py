"""Executable pytest suite for code-factory testing all 10 TEST-LOG.md scenarios.

Enforces real executions without mocks, adhering to the documented honest limits:
- Filesystem is a cwd jail, not a full container sandbox.
- Silent backend degradation when forced backend is unavailable.
- Strict timeout process group SIGKILL without lingering processes.
- Env scrubbing and secret_files 0600 isolation.
- Output truncation cap at 64 KiB.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import factory

HERE = Path(__file__).resolve().parent
CLI_PATH = HERE.parent / "factory"


def test_01_hello_world_all_runtimes_api_and_cli():
    """Scenario 1: Hello-world executions across languages via API and CLI."""
    # API tests
    res_py = factory.submit('print("hello api python")', language="python", timeout=15)
    assert res_py.exit_code == 0
    assert "hello api python" in res_py.stdout
    assert not res_py.timed_out

    if factory._runtime_available("node"):
        res_node = factory.submit('console.log("hello api node")', language="node", timeout=15)
        assert res_node.exit_code == 0
        assert "hello api node" in res_node.stdout

    if factory._runtime_available("bash"):
        res_bash = factory.submit('echo "hello api bash"', language="bash", timeout=15)
        assert res_bash.exit_code == 0
        assert "hello api bash" in res_bash.stdout

    # CLI tests
    p = subprocess.run(
        [sys.executable, str(CLI_PATH), "run", "--language", "python", "--timeout", "15", "-"],
        input='print("hello cli python")',
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    assert "hello cli python" in p.stdout


def test_02_factory_backends_probe_and_graceful_degradation():
    """Scenario 2: factory backends status and graceful backend degradation."""
    p = subprocess.run(
        [sys.executable, str(CLI_PATH), "backends"],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    assert "plain-subprocess: available" in p.stdout

    # Honest limit: forcing an unavailable backend (docker-sandbox) degrades gracefully
    docker_ok, _ = factory.docker_status()
    if not docker_ok:
        res = factory.submit('print("degraded fallback")', language="python", backend="docker-sandbox")
        assert res.exit_code == 0
        assert "degraded fallback" in res.stdout
        assert res.backend_used != "docker-sandbox"


def test_03_stderr_and_exit_code_capture():
    """Scenario 3: stderr and custom exit code preservation."""
    code = (
        "import sys\n"
        "sys.stderr.write('error channel message\\n')\n"
        "sys.stdout.write('stdout channel message\\n')\n"
        "sys.exit(42)\n"
    )
    res = factory.submit(code, language="python")
    assert res.exit_code == 42
    assert "stdout channel message" in res.stdout
    assert "error channel message" in res.stderr
    assert not res.timed_out


def test_04_timeout_kill_and_process_cleanup():
    """Scenario 4: Timeout kill and verification of no lingering processes."""
    code = "import time\ntime.sleep(30)\n"
    res = factory.submit(code, language="python", timeout=1.0)
    assert res.timed_out is True
    assert res.exit_code == -1
    assert 0.9 <= res.wall_time_s <= 3.0
    assert "timeout after" in res.stderr

    # Verify no lingering process
    check = subprocess.run(["pgrep", "-f", "time.sleep(30)"], capture_output=True, text=True)
    assert check.stdout.strip() == ""


def test_05_cwd_jail_and_honest_filesystem_limit():
    """Scenario 5: cwd-jail isolation and documented limit (filesystem not sandboxed)."""
    probe_path = Path("/tmp/factory-escape-probe")
    if probe_path.exists():
        probe_path.unlink()

    code = (
        "import os\n"
        "print('CWD:' + os.getcwd())\n"
        "with open('pwned.txt', 'w') as f:\n"
        "    f.write('inside run dir')\n"
        "with open('/tmp/factory-escape-probe', 'w') as f:\n"
        "    f.write('escape probe succeeded')\n"
    )
    res = factory.submit(code, language="python")
    assert res.exit_code == 0
    assert "CWD:" in res.stdout
    run_dir = Path(res.stdout.split("CWD:")[1].strip())
    assert run_dir.exists()
    assert (run_dir / "pwned.txt").exists()

    # Honest limit assertion: absolute write succeeded
    assert probe_path.exists()
    assert probe_path.read_text() == "escape probe succeeded"

    # Cleanup probe
    probe_path.unlink(missing_ok=True)


def test_06_large_output_truncation():
    """Scenario 6: Output truncation at 64 KiB cap."""
    code = "print('X' * 100000)\n"
    res = factory.submit(code, language="python")
    assert res.exit_code == 0
    assert res.truncated is True
    assert len(res.stdout.encode("utf-8")) <= 65536 + len(factory.TRUNCATION_NOTE.encode("utf-8")) + 100
    assert factory.TRUNCATION_NOTE.strip() in res.stdout


def test_07_env_scrubbing_and_passthrough():
    """Scenario 7: Env scrubbing for secrets and safe var passthrough."""
    # Test scrub_env helper directly
    dirty = {
        "MY_API_KEY": "secret123",
        "AUTH_TOKEN": "token456",
        "DB_PASSWORD": "pass",
        "SAFE_PARAM": "public_value",
    }
    clean = factory.scrub_env(dirty)
    assert "MY_API_KEY" not in clean
    assert "AUTH_TOKEN" not in clean
    assert "DB_PASSWORD" not in clean
    assert clean.get("SAFE_PARAM") == "public_value"

    # Test child process environment
    code = (
        "import os, json\n"
        "print(json.dumps(dict(os.environ)))\n"
    )
    res = factory.submit(
        code,
        language="python",
        extra_env={"SAFE_CONFIG": "active_val", "DISALLOWED_TOKEN": "secret_xyz"},
    )
    assert res.exit_code == 0
    child_env = json.loads(res.stdout.strip())
    assert child_env.get("SAFE_CONFIG") == "active_val"
    assert "DISALLOWED_TOKEN" not in child_env


def test_08_network_isolation_configuration():
    """Scenario 8: Network isolation reporting."""
    unshare_present = bool(shutil.which("unshare"))
    res_default = factory.submit('print("net test")', language="python")
    assert res_default.exit_code == 0
    if unshare_present:
        assert res_default.net_isolated is True
    else:
        # Honest limit: on systems lacking unshare, net_isolated is reported as False
        assert res_default.net_isolated is False


def test_09_secret_files_handling():
    """Scenario 9: secret_files 0600 isolation and metadata recording."""
    code = (
        "import os\n"
        "s_dir = os.environ.get('FACTORY_SECRET_DIR', '')\n"
        "assert s_dir, 'Missing FACTORY_SECRET_DIR'\n"
        "file_path = os.path.join(s_dir, 'db_pass')\n"
        "with open(file_path) as f:\n"
        "    val = f.read()\n"
        "assert val == 'dummy-test-data'\n"
        "print('SECRET_READ_OK')\n"
    )
    res = factory.submit(code, language="python", secret_files={"db_pass": "dummy-test-data"})
    assert res.exit_code == 0
    assert "SECRET_READ_OK" in res.stdout
    # Value must never be leaked into stdout or stderr
    assert "dummy-test-data" not in res.stdout
    assert "dummy-test-data" not in res.stderr

    # Check secret file permissions in the run directory
    run_info = factory.get_run(res.run_id)
    assert run_info is not None
    target_path = factory.RUNS_ROOT / res.run_id / "secrets" / "db_pass"
    if target_path.exists():
        mode = oct(os.stat(target_path).st_mode & 0o777)
        assert mode == oct(0o600)


def test_10_cli_json_mode_schema():
    """Scenario 10: CLI JSON mode output schema validation."""
    p = subprocess.run(
        [sys.executable, str(CLI_PATH), "run", "--language", "python", "--timeout", "15", "--json", "-"],
        input='print("json mode test")',
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    data = json.loads(p.stdout)

    required_fields = {
        "run_id": str,
        "language": str,
        "backend_used": str,
        "exit_code": int,
        "wall_time_s": (float, int),
        "timed_out": bool,
        "truncated": bool,
        "net_isolated": bool,
        "stdout": str,
        "stderr": str,
    }

    for field, expected_type in required_fields.items():
        assert field in data, f"Missing field: {field}"
        assert isinstance(data[field], expected_type), f"Field {field} is {type(data[field])}, expected {expected_type}"

    assert "json mode test" in data["stdout"]
