"""Code factory — a tiny local code-execution service.

Importable API + a thin CLI (see ./factory). Localhost-only by design:
there is no network server here at all, so there is nothing to bind.

Sandbox model (honest):
  * Every run executes with its working directory jailed inside
    ~/workspace/agent-stack/code-factory/runs/<run-id>/ .
  * Network is ISOLATED by default: subprocess backends are wrapped with
    `unshare --net` (verified working as root on this host; loopback-only,
    interface down). Opt in with limits.network=True. If `unshare` is
    absent we run without isolation and record net_isolated=False honestly.
  * Resource limits via preexec_fn setrlimit (best-effort, skipped where
    unsupported): RLIMIT_CPU (defaults to the wall timeout), RLIMIT_AS
    (virtual memory; language-specific floors — V8-based runtimes reserve
    huge virtual address space, so node needs >=2GB AS, bun >=1GB),
    RLIMIT_NPROC (this kernel counts threads and enforces the limit even
    for root, so the effective floor is live task count + 128 measured at
    spawn; a lower floor makes fork() fail with EAGAIN). No cgroups on
    this kernel, so these are process-local limits, not container-grade
    guarantees.
  * Every execution path has a wall-clock timeout, and on timeout the WHOLE
    process tree is killed (process-group SIGKILL), not just the parent.
  * The environment is scrubbed: any variable whose name matches
    *KEY/*TOKEN/*SECRET*/*PASSWORD*/*AUTH*/*CREDENTIAL*/*PRIVATE*
    *BEARER*/*SESSION*/*COOKIE* is dropped, never passed through.
    Secrets must NOT travel via env at all — use secret_files=, which
    writes per-run 0600 files and exposes only their directory via the
    FACTORY_SECRET_DIR env var (paths, never values).
  * stdout/stderr are capped (default 64 KiB) with a truncation note.
  * Everything runs as root on this VM. uid/gid dropping is a FUTURE
    hardening item, not implemented here.

Backend preference order (per language):
    python: venv-subprocess -> plain-subprocess -> docker-sandbox
    bash/node/bun: plain-subprocess
docker-sandbox is OPT-IN by probe: it is only selected when the one-time
init probe (`docker run --rm ... true`) passes. Right now the daemon is
up but `docker run` is BROKEN (containerd-shim-runc-v2 binary missing
from ~/workspace/bin/docker/, and netns creation is denied), so the probe
fails and the backend degrades away. Repair path: extract
containerd-shim-runc-v2 from ~/workspace/bin/docker.tgz into
~/workspace/bin/docker/ and restart the daemon via
~/workspace/bin/start-docker.sh (needs a privileged operator).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# Paths and constants
# ----------------------------------------------------------------------------

FACTORY_ROOT = Path(__file__).resolve().parent
RUNS_ROOT = FACTORY_ROOT / "runs"

VENV_PYTHON = Path.home() / "workspace" / "agent-stack" / ".venv" / "bin" / "python"
DOCKER_BIN = Path.home() / "workspace" / "bin" / "docker" / "docker"
DOCKER_IMAGE = "python:3.12-slim"

OUTPUT_CAP_BYTES = 64 * 1024
TRUNCATION_NOTE = "\n...[output truncated at 64 KiB]"

SECRET_DIR_ENV = "FACTORY_SECRET_DIR"

SUPPORTED_LANGUAGES = ("python", "bash", "node", "bun")

# run-id must be filesystem-safe; generated internally, never from user input.
_RUN_ID_RE = re.compile(r"^[0-9a-zA-Z\-_]{1,64}$")

# Secret filenames: plain basenames only, no paths, no dotfiles.
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")

# Any env var whose NAME matches one of these is dropped, never passed through.
_SECRET_ENV_RE = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL|PRIVATE|BEARER|SESSION|COOKIE",
    re.IGNORECASE,
)

# Minimal safe environment. PATH is rebuilt from scratch to avoid inheriting
# anything attacker-controlled; everything else sensitive is dropped.
_SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": os.environ.get("HOME", "/root"),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": os.environ.get("TZ", "UTC"),
}

_CODE_FILENAME = {
    "python": "code.py",
    "bash": "code.sh",
    "node": "code.js",
    "bun": "code.js",
}

# V8-based runtimes reserve large virtual address spaces at startup, so
# RLIMIT_AS needs a high floor for them (measured: node dies below ~2GB).
_AS_FLOOR_BYTES = {"node": 2 * 1024**3, "bun": 1 * 1024**3}
# RLIMIT_NPROC counts threads, not just processes, and this kernel enforces
# it even for root — so the effective floor is measured at spawn time
# (current task count + headroom), never below the configured value.
_NPROC_HEADROOM = 128


def _task_count() -> int:
    """Best-effort count of live tasks (threads) system-wide."""
    n = 0
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                n += len(os.listdir(f"/proc/{pid}/task"))
            except OSError:
                pass
    except OSError:
        pass
    return n


# ----------------------------------------------------------------------------
# Public data types
# ----------------------------------------------------------------------------

@dataclass
class RunLimits:
    """Per-run limits.

    network=False (default) means the run is net-isolated via `unshare --net`.
    Set network=True to opt into network access.
    cpu_s defaults to timeout_s. memory_mb is enforced via RLIMIT_AS
    (subject to per-language floors); max_processes via RLIMIT_NPROC.
    All rlimits are best-effort: skipped gracefully where unsupported."""

    timeout_s: float = 30.0
    max_output_bytes: int = OUTPUT_CAP_BYTES
    memory_mb: int = 256
    # RLIMIT_NPROC counts threads and is enforced even for root; the
    # effective value is max(max_processes, live_tasks + 128 at spawn).
    max_processes: int = 256
    cpu_s: float | None = None
    network: bool = False


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    wall_time_s: float
    backend_used: str
    timed_out: bool
    truncated: bool
    net_isolated: bool
    run_id: str
    language: str


class FactoryError(Exception):
    """Base error for factory failures."""


class UnsupportedLanguageError(FactoryError):
    pass


class BackendUnavailableError(FactoryError):
    pass


# ----------------------------------------------------------------------------
# Docker probe — eager, once, at import. Never raises.
# docker-sandbox is only selectable when this passes.
# ----------------------------------------------------------------------------

def _run_docker_probe() -> tuple[bool, str]:
    if not (DOCKER_BIN.exists() and os.access(DOCKER_BIN, os.X_OK)):
        return False, f"docker client missing at {DOCKER_BIN}"
    try:
        p = subprocess.run(
            [str(DOCKER_BIN), "image", "inspect", DOCKER_IMAGE],
            capture_output=True, timeout=15, env=dict(_SAFE_ENV),
        )
    except Exception as exc:
        return False, f"docker image inspect failed: {exc}"
    if p.returncode != 0:
        return False, f"image {DOCKER_IMAGE} not present locally"
    try:
        p = subprocess.run(
            [str(DOCKER_BIN), "run", "--rm", "--network", "host",
             DOCKER_IMAGE, "true"],
            capture_output=True, timeout=30, env=dict(_SAFE_ENV),
        )
    except Exception as exc:
        return False, f"docker run canary failed: {exc}"
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        # Prefer the daemon's error line over the generic usage hint.
        reason = next(
            (ln for ln in err if ln and "Run 'docker run" not in ln),
            err[-1] if err else f"exit {p.returncode}",
        )
        return False, f"docker run canary failed: {reason}"
    return True, "ok"


_DOCKER_STATUS: tuple[bool, str] | None = None
try:
    _DOCKER_STATUS = _run_docker_probe()
except Exception as exc:  # never let the probe break the import
    _DOCKER_STATUS = (False, f"probe crashed: {exc}")


def docker_available() -> bool:
    return _DOCKER_STATUS[0]


def docker_status() -> tuple[bool, str]:
    """(available, reason). reason is a short human string, never a secret."""
    return _DOCKER_STATUS


def _venv_available() -> bool:
    return VENV_PYTHON.exists() and os.access(VENV_PYTHON, os.X_OK)


def _runtime_available(name: str) -> bool:
    return shutil.which(name) is not None


def _runtime_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise BackendUnavailableError(f"{name} runtime not installed")
    return path


# ----------------------------------------------------------------------------
# Working-dir jail
# ----------------------------------------------------------------------------

def _make_run_dir() -> tuple[str, Path]:
    """Create runs/<run-id>/ and return (run_id, path). Raises if the
    resolved path escapes RUNS_ROOT (defense in depth)."""
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    if not _RUN_ID_RE.match(run_id):
        raise FactoryError("generated run-id failed validation")
    run_dir = (RUNS_ROOT / run_id).resolve()
    if run_dir.parent != RUNS_ROOT.resolve():
        raise FactoryError("run dir escapes the runs root")
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


# ----------------------------------------------------------------------------
# Env scrubbing
# ----------------------------------------------------------------------------

def scrub_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a scrubbed environment: the minimal safe set plus inherited
    and caller-supplied vars, with any secret-looking NAMES dropped.
    Secret VALUES must never be passed via env — use secret_files=."""
    env = dict(_SAFE_ENV)
    for src in (os.environ, extra or {}):
        for k, v in src.items():
            if _SECRET_ENV_RE.search(k):
                continue
            if k in env:
                continue  # safe defaults win over inherited values
            env[k] = v
    return env


# ----------------------------------------------------------------------------
# Secret files — secrets via files, never via env
# ----------------------------------------------------------------------------

def _write_secret_files(run_dir: Path, secret_files: dict[str, str]) -> Path | None:
    """Write each secret to <run_dir>/secrets/<name> with 0600 perms
    (dir 0700). Returns the secrets dir, or None when empty."""
    if not secret_files:
        return None
    secrets_dir = run_dir / "secrets"
    secrets_dir.mkdir(mode=0o700, exist_ok=False)
    for name, content in secret_files.items():
        if not _SECRET_NAME_RE.match(name):
            raise FactoryError(f"bad secret filename: {name!r}")
        path = (secrets_dir / name).resolve()
        if path.parent != secrets_dir.resolve():
            raise FactoryError(f"secret path escapes secrets dir: {name!r}")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
    return secrets_dir


# ----------------------------------------------------------------------------
# Output capture with cap
# ----------------------------------------------------------------------------

def _cap(text: str, cap: int) -> tuple[str, bool]:
    raw = text.encode("utf-8", "replace")
    if len(raw) > cap:
        return raw[:cap].decode("utf-8", "replace") + TRUNCATION_NOTE, True
    return text, False


# ----------------------------------------------------------------------------
# rlimits (best-effort) + net isolation + whole-tree kill on timeout
# ----------------------------------------------------------------------------

def _limit_child(limits: RunLimits, language: str, task_floor: int):
    def _preexec():
        import resource

        try:
            # Floor at live task count + headroom: the kernel counts threads
            # and enforces NPROC even for root; a floor below the current
            # count makes fork() fail with EAGAIN (observed).
            nproc = max(limits.max_processes, task_floor)
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        except Exception:
            pass
        try:
            cpu = int(limits.cpu_s if limits.cpu_s else limits.timeout_s)
            if cpu > 0:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        except Exception:
            pass
        try:
            if limits.memory_mb and limits.memory_mb > 0:
                as_bytes = max(
                    limits.memory_mb * 1024 * 1024,
                    _AS_FLOOR_BYTES.get(language, 0),
                )
                resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        except Exception:
            pass

    return _preexec


def _maybe_isolate(argv: list[str], limits: RunLimits) -> tuple[list[str], bool]:
    """Wrap argv with `unshare --net` unless the caller opted into network.
    Returns (argv, net_isolated). If unshare is absent we run without
    isolation and say so honestly."""
    if limits.network:
        return argv, False
    unshare = shutil.which("unshare")
    if unshare is None:
        return argv, False
    return [unshare, "--net", "--"] + argv, True


def _run_local(
    argv: list[str],
    run_dir: Path,
    language: str,
    limits: RunLimits,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int, float, bool, bool]:
    """Run argv jailed in run_dir. Returns
    (stdout, stderr, exit_code, wall_time_s, timed_out, net_isolated).
    Kills the whole process group on timeout."""
    argv, net_isolated = _maybe_isolate(argv, limits)
    task_floor = _task_count() + _NPROC_HEADROOM
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(run_dir),
        env=env or scrub_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group -> killpg kills the tree
        preexec_fn=_limit_child(limits, language, task_floor),
    )
    try:
        out, err = proc.communicate(timeout=limits.timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = proc.communicate()  # reap; drains pipes after kill
        timed_out = True
    wall = time.monotonic() - start
    return out, err, proc.returncode if not timed_out else -1, wall, timed_out, net_isolated


# ----------------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------------

def _backend_docker(code_path: Path, run_id: str, limits: RunLimits) -> tuple:
    """Run code.py inside python:3.12-slim. Only reachable when the init
    probe passed. Honest limits: no cgroup support on this kernel, so
    --memory/--cpus/--pids-limit are discarded by the daemon; we pass only
    flags verified to work here. Uses --network host, so net_isolated=False.
    Secret files are NOT wired into the container (files exist in the run
    dir, which is mounted read-only, but FACTORY_SECRET_DIR is not set)."""
    container = f"codefactory-{run_id}"
    argv = [
        str(DOCKER_BIN), "run", "--rm",
        "--name", container,
        "--network", "host",
        "--read-only",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        "--workdir", "/tmp",
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "-v", f"{code_path.parent}:/work:ro",
        DOCKER_IMAGE,
        "python", "/work/" + code_path.name,
    ]
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(code_path.parent),
        env=scrub_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=limits.timeout_s)
        timed_out = False
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        # The docker CLI is dead but the container may live on: remove it.
        subprocess.run(
            [str(DOCKER_BIN), "rm", "-f", container],
            capture_output=True, timeout=15, env=scrub_env(),
        )
        out, err, timed_out, rc = "", "", True, -1
    return out, err, rc, time.monotonic() - start, timed_out, False


def _backend_venv(code_path: Path, language: str, limits: RunLimits,
                  env: dict[str, str]) -> tuple:
    return _run_local([str(VENV_PYTHON), str(code_path)], code_path.parent,
                      language, limits, env=env)


def _backend_plain(language: str, code_path: Path, limits: RunLimits,
                   env: dict[str, str]) -> tuple:
    if language == "python":
        argv = [sys.executable or "python3", str(code_path)]
    elif language == "bash":
        argv = ["/bin/bash", str(code_path)]
    elif language == "node":
        # Absolute path: the scrubbed child PATH may not contain the
        # directory where node lives (e.g. /opt/.../bin).
        argv = [_runtime_path("node"), str(code_path)]
    elif language == "bun":
        argv = [_runtime_path("bun"), str(code_path)]
    else:  # unreachable; submit() validates
        raise UnsupportedLanguageError(language)
    return _run_local(argv, code_path.parent, language, limits, env=env)


# ----------------------------------------------------------------------------
# Backend selection
# ----------------------------------------------------------------------------

def select_backend(language: str, override: str | None = None) -> str:
    """Return the backend name to use. Preference chain:
    python: venv-subprocess -> plain-subprocess -> docker-sandbox
    bash/node/bun: plain-subprocess (net-isolated, rlimited)

    docker-sandbox is only eligible when the init probe passed.
    An explicit override is honored only if that backend is available;
    otherwise we degrade to the preference chain."""
    if language == "python":
        chain = ["venv-subprocess", "plain-subprocess", "docker-sandbox"]
    elif language in ("bash", "node", "bun"):
        chain = ["plain-subprocess"]
    else:
        raise UnsupportedLanguageError(f"unsupported language: {language!r}")

    if language in ("node", "bun") and not _runtime_available(language):
        raise BackendUnavailableError(f"{language} runtime not installed")

    candidates = ([override] if override else []) + chain
    available = {
        "docker-sandbox": docker_available(),
        "venv-subprocess": _venv_available(),
        "plain-subprocess": True,
    }
    for name in candidates:
        if available.get(name):
            return name
    raise BackendUnavailableError("no execution backend available")


# ----------------------------------------------------------------------------
# Optional paperclip clip hook — STUB, off by default, never raises
# ----------------------------------------------------------------------------

def _maybe_clip(result: RunResult) -> None:
    """Best-effort hook: shell out to clip.py for significant runs.

    STUB — disabled unless CODE_FACTORY_CLIP=1. Wraps everything in
    try/except and logs to stderr only; NEVER raises."""
    try:
        if os.environ.get("CODE_FACTORY_CLIP") != "1":
            return
        clip_py = FACTORY_ROOT / "clip.py"
        if not clip_py.exists():
            return
        subprocess.run(
            [sys.executable, str(clip_py), result.run_id],
            capture_output=True, timeout=10, env=scrub_env(),
        )
    except Exception as exc:  # noqa: BLE001 — hook must never raise
        print(f"[code-factory] clip hook skipped: {exc}", file=sys.stderr)


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def submit(
    code: str,
    language: str = "python",
    timeout: float = 30.0,
    limits: RunLimits | None = None,
    backend: str | None = None,
    extra_env: dict[str, str] | None = None,
    secret_files: dict[str, str] | None = None,
    save_run: bool = True,
) -> RunResult:
    """Execute code and return a RunResult.

    - code:         source text to execute.
    - language:     'python' | 'bash' | 'node' | 'bun'.
    - timeout:      hard wall-clock timeout in seconds (overrides limits).
    - limits:       RunLimits (timeout_s ignored when `timeout` is given).
                    network=False (default) => net-isolated via unshare.
    - backend:      force a backend ('venv-subprocess'|'plain-subprocess'|
                    'docker-sandbox'); degrades gracefully if unavailable.
    - extra_env:    extra env vars; secret-looking names are dropped.
    - secret_files: {filename: content} — written 0600 into the run dir;
                    the directory path (never values) is exposed via
                    FACTORY_SECRET_DIR. Subprocess backends only.
    - save_run:     persist runs/<run-id>/{code file, secrets/, result.json}.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguageError(
            f"unsupported language {language!r}; choose from {SUPPORTED_LANGUAGES}"
        )
    lim = limits or RunLimits()
    lim = RunLimits(
        timeout_s=max(0.1, float(timeout)),
        max_output_bytes=lim.max_output_bytes,
        memory_mb=lim.memory_mb,
        max_processes=lim.max_processes,
        cpu_s=lim.cpu_s,
        network=lim.network,
    )

    run_id, run_dir = _make_run_dir()
    code_path = run_dir / _CODE_FILENAME[language]
    code_path.write_text(code, encoding="utf-8")
    secrets_dir = _write_secret_files(run_dir, secret_files or {})

    chosen = select_backend(language, override=backend)
    env = scrub_env(extra_env)
    if secrets_dir is not None and chosen != "docker-sandbox":
        # Paths only — never values. Docker backend deliberately unwired.
        env[SECRET_DIR_ENV] = str(secrets_dir)

    if chosen == "docker-sandbox":
        out, err, rc, wall, timed_out, net_isolated = _backend_docker(
            code_path, run_id, lim)
    elif chosen == "venv-subprocess":
        out, err, rc, wall, timed_out, net_isolated = _backend_venv(
            code_path, language, lim, env)
    elif chosen == "plain-subprocess":
        out, err, rc, wall, timed_out, net_isolated = _backend_plain(
            language, code_path, lim, env)
    else:
        raise BackendUnavailableError(f"unknown backend {chosen!r}")

    stdout, t1 = _cap(out or "", lim.max_output_bytes)
    stderr, t2 = _cap(err or "", lim.max_output_bytes)
    if timed_out:
        note = f"[timeout after {lim.timeout_s:g}s; process tree killed]"
        stderr = (stderr + "\n" + note) if stderr else note

    result = RunResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=int(rc),
        wall_time_s=round(wall, 3),
        backend_used=chosen,
        timed_out=timed_out,
        truncated=t1 or t2,
        net_isolated=net_isolated,
        run_id=run_id,
        language=language,
    )

    if save_run:
        payload = asdict(result)
        if secrets_dir is not None:
            # Record secret NAMES for auditability; never values.
            payload["secret_names"] = sorted((secret_files or {}).keys())
        (run_dir / "result.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    _maybe_clip(result)
    return result


def get_run(run_id: str) -> dict | None:
    """Return the stored result.json for a run-id, or None."""
    if not _RUN_ID_RE.match(run_id):
        return None
    p = (RUNS_ROOT / run_id / "result.json").resolve()
    if p.parent.parent != RUNS_ROOT.resolve() or not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
