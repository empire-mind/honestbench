# Code Factory — design & operations

**Last updated:** 2026-09-25 AEST · **build:** `factory.py` + `factory` CLI, this directory
**Status:** 10/10 tests PASS (see `tests/TEST-LOG.md`); runner audit in `RUNNERS.md`

## What it is

A unified **local code-execution plane** for the agent stack: any agent or
workflow submits source code in a supported language and gets back captured
stdout/stderr, an exit code, timing, and a record of what actually ran. Two
interfaces:

- **Python API** — `import factory; factory.submit(code, language="python", ...)`
  returns a `RunResult`.
- **CLI** — `./factory run --language python --timeout 10 - < code.py`;
  `./factory backends` lists backend availability.

There is **no HTTP server by design** (localhost-only, no listener, nothing to
bind). Every run is persisted under `runs/<run-id>/` as evidence.

## Architecture

```
submit() → select_backend() → hardened subprocess → RunResult + runs/<run-id>/
```

1. **Submit** — code is written to `runs/<run-id>/code.<ext>`; a UTC run ID
   (`YYYYMMDDTHHMMSS-<8 hex>`) is generated and validated (filesystem-safe
   regex + resolved-path confinement under `runs/`).
2. **Backend selection** — a preference chain per language; `docker-sandbox`
   is opt-in by probe (the one-time `docker run` canary at import must pass
   before it becomes eligible). An explicit `--backend` override is honored
   **only if that backend is actually available**; otherwise it degrades down
   the chain. **Check `backend_used` in the result — a forced-but-unavailable
   backend degrades silently** (see honest limits).
3. **Hardened subprocess** — runs inside the run dir (cwd jail) with:
   scrubbed env, `unshare --net` net isolation (unless opted in),
   preexec rlimits (RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC, best-effort), a
   hard wall timeout with whole-process-group SIGKILL on expiry, and
   64 KiB stdout/stderr caps. Result is serialized to `result.json`.

## Backends (preference order)

| Backend | Used for | Status (2026-09-25) |
|---|---|---|
| `venv-subprocess` | python | **preferred** — agent venv python 3.12.3 (`~/workspace/agent-stack/.venv`) |
| `plain-subprocess` | python (fallback), bash, node, bun | available |
| `docker-sandbox` | python (last resort, opt-in by probe) | **unavailable** — `docker run` broken |

**Why docker-sandbox is out:** the daemon is up, but `docker run` fails two
ways: (1) the `containerd-shim-runc-v2` binary is missing from
`~/workspace/bin/docker/` (it *is* inside `~/workspace/bin/docker.tgz` —
infra fix, outside factory scope); (2) even `--network host` aborts with
`failed to create a netlink handle … operation not permitted` — containerd's
netns creation is denied in the daemon's context. **Repair path:** extract
the shim from `~/workspace/bin/docker.tgz` into `~/workspace/bin/docker/`,
restart the daemon via `~/workspace/bin/start-docker.sh` (needs a privileged
operator), then re-run `factory backends` to confirm the canary passes.

Even after repair, this daemon's containers would be host-networked
(`--iptables=false --bridge=none`), so docker-sandbox would offer **no**
network isolation — the subprocess backends' `unshare --net` isolation is
stronger and is the default.

node (`/usr/bin/node` v24.20.0) and bun (`/opt/hatch-image/bin/bun` 1.3.10)
run via `plain-subprocess`; deno is not installed. `factory backends`
always reports live probe results, never cached guesses.

## Languages

`python`, `bash`, `node`, `bun`. Unsupported languages raise
`UnsupportedLanguageError`.

## Limits enforced

- **Wall timeout** (default 30s): on expiry the **whole process tree** is
  SIGKILLed (process group kill), not just the parent. Verified: `sleep 30`
  with `--timeout 3` → `timed_out: True`, wall ≈ 3.0s, exit −1, no linger
  processes.
- **RLIMIT_CPU** — defaults to the wall timeout.
- **RLIMIT_AS** (virtual memory) — language floors required by V8's address
  reservation: **node needs ≥ 2 GB AS, bun ≥ 1 GB** (node dies below ~2 GB;
  measured, not assumed).
- **RLIMIT_NPROC** — this kernel counts *threads* and enforces the limit
  **even for root**; a floor below the live count makes `fork()` fail with
  `EAGAIN` (observed). The factory floors it at **live task count + 128**,
  measured at spawn.
- **Output cap** — stdout and stderr each capped at **64 KiB**, with
  `...[output truncated at 64 KiB]` and `truncated: True`.
- **cwd jail** — every run executes with cwd = `runs/<run-id>/`; relative
  writes land in the run dir. Defense-in-depth: run dirs resolve-confined
  under `runs/`, run IDs and secret names are validated by regex.
- **Env scrub** — any variable whose **name** matches
  `KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL|PRIVATE|BEARER|SESSION|COOKIE`
  (case-insensitive) is dropped. `PATH` is rebuilt from scratch; `HOME`,
  `LANG`, `LC_ALL`, `TZ` carry minimal safe defaults. Caller `extra_env`
  passes through only for non-secret-looking names.
- **secret_files** — secrets never travel via env. `secret_files={"name":
  "value"}` writes `<run-dir>/secrets/<name>` with **0600** (dir 0700) and
  exposes only the directory path via the `FACTORY_SECRET_DIR` env var —
  values never appear in env, result.json, or logs; `result.json` records
  **secret names only** for audit. Filenames are restricted to plain
  basenames (no paths, no dotfiles).
- **Net isolation (default)** — subprocess backends are wrapped with
  `unshare --net` (verified: loopback-only, interface down; connects fail
  with `ENETUNREACH`). Opt **in** with `limits.network=True` (CLI
  `--network`); if `unshare` is absent the run proceeds and
  `net_isolated=False` is recorded honestly.

## Security model (honest)

- **cwd jail only.** The filesystem is **NOT** sandboxed: everything runs
  as root, so absolute-path writes (e.g. `/tmp/...`) succeed. Test #5 proved
  this with a live `/tmp` write probe. Treat the factory as a cwd jail +
  timeout + net-isolation tool, **not** a filesystem container for untrusted
  code.
- **No sandboxing tools installed** (no firejail, bubblewrap, or nsjail);
  there are no cgroups on this kernel — rlimits are process-local, not
  container-grade guarantees.
- **uid/gid dropping is future work**, not implemented.
- Bash runs accept arbitrary strings — prefer argv-style invocation and
  never build commands from untrusted input (RUNNERS.md).

## Test evidence (2026-09-25)

**10/10 PASS**, real executions, no mocks. Full log: `tests/TEST-LOG.md`.

1. Hello-world × 4 languages (CLI) + python/node via API — all PASS.
2. `factory backends` — docker-sandbox correctly reported *unavailable* with
   the live canary failure reason; everything else available — PASS.
3. stderr/exit-code capture (exit 42 preserved, channels separated) — PASS.
4. Timeout kill, CLI + API (timed_out, ≈3 s, no lingering `sleep`) — PASS.
5. cwd-jail escape attempt — jail holds; **/tmp write probe succeeded
   (documented limit, not a failure)** — PASS with honest limit.
6. Large-output truncation (1 MB → 64 KiB cap + truncation note) — PASS.
7. Env scrubbing (`FAKE_TEST_API_KEY` dropped by name; `SAFE_VAR` passes
   through) — PASS.
8. Net isolation default + `--network` opt-in (raw TCP to 8.8.8.8:53
   succeeds only with the flag) — PASS.
9. secret_files (0600, path-only env, value absent from result.json) — PASS.
10. CLI JSON mode (all 10 `RunResult` fields, correct types) — PASS.

**Honest-limit findings to keep in mind:**

1. **Filesystem not sandboxed** (see Security model above).
2. **Forcing an unavailable backend degrades silently** — `--backend
   docker-sandbox` fell back to `venv-subprocess` with no warning in the
   human-readable line. Callers must check `backend_used`, never assume the
   requested backend ran.
3. **Test-harness note:** secrets typed into the *invoking shell* can
   resurface via the runtime's own `JARVIS_TRACE_CONTEXT` env var (it
   captured a literal `export FAKE_TEST_API_KEY=...` line) — a harness
   artifact, not a factory defect. Never paste real secrets into test
   commands; use `secret_files` instead.

## Operational notes

- **runs/ layout:** `runs/<run-id>/{code.py|code.sh|code.js, result.json,
  secrets/}`. `result.json` carries the 10 `RunResult` fields plus
  `secret_names` (names only) when secret_files were used. Run IDs are UTC;
  keep representative run dirs, prune the rest.
- **No HTTP server by design** — `mc status` includes a factory health
  check (smoke only; see below).
- **Clip hook:** `_maybe_clip` is a best-effort paperclip-clip stub that
  runs **only** when `CODE_FACTORY_CLIP=1` is set in the environment. When
  enabled it shells out to `clip.py` (if present) for the run ID; it is
  wrapped in try/except, logs to stderr only, and **never raises** — a
  failing hook cannot break a run. Off by default; **do not enable it
  globally** (opt-in per environment only).
- **Docker repair** (when the infra operator fixes `docker run`): restart
  the daemon, then verify with `factory backends` — docker-sandbox becomes
  eligible automatically via the probe, no factory changes needed.
- Minor cosmetic notes (not bugs): run IDs use UTC; the CLI exits 1 when
  the child exits nonzero.
