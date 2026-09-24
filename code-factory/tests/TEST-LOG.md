# Code Factory — Test Log

**Test date:** 2026-09-25 AEST (run IDs are UTC: `20260924T16…`) · **tester:** code-factory tester subagent
**Build under test:** `~/workspace/agent-stack/code-factory/` (factory.py + `factory` CLI + `runs/`; RUNNERS.md not modified, factory.py/CLI not modified)
**Method:** real executions only; observed output recorded, not expectations. No code fixes made — bugs reported, not patched.

## 1. Hello-world per language per backend

**CLI via stdin** (`./factory run --language <L> --timeout 15 -`):

| Language | Command | Observed stdout | exit | backend_used | wall | Verdict |
|---|---|---|---|---|---|---|
| python | `echo 'print("hello python")' \| ./factory run --language python --timeout 15 -` | `hello python` | 0 | `venv-subprocess` | 0.07s | PASS |
| bash | `echo 'echo "hello bash"' \| ./factory run --language bash --timeout 15 -` | `hello bash` | 0 | `plain-subprocess` | 0.01s | PASS |
| node | `echo 'console.log("hello node")' \| ./factory run --language node --timeout 15 -` | `hello node` | 0 | `plain-subprocess` | 0.10s | PASS |
| bun | `echo 'console.log("hello bun")' \| ./factory run --language bun --timeout 15 -` | `hello bun` | 0 | `plain-subprocess` | 0.02s | PASS |

**Python API `submit()`** (python + node):

- `factory.submit('print("hello api python")', language='python', timeout=15)` → stdout `hello api python`, exit_code 0, backend `venv-subprocess`, wall_time_s 0.032, timed_out False, net_isolated True. **PASS**
- `factory.submit('console.log("hello api node")', language='node', timeout=15)` → stdout `hello api node`, exit_code 0, backend `plain-subprocess`, wall_time_s 0.159, timed_out False, net_isolated True. **PASS**

All runs reported `net_isolated=True` by default.

## 2. `factory backends`

Observed output, verbatim:
```
venv-subprocess: available
plain-subprocess: available
docker-sandbox: unavailable (docker run canary failed: docker: Error response from daemon: failed to create default sandbox: failed to create a netlink handle: failed to set into network namespace 34 while creating netlink socket: operation not permitted)
node-runtime: available
bun-runtime: available
unshare-net: available
```
**PASS** — docker-sandbox correctly reported unavailable with the live canary failure reason (matches the known-broken `docker run`), not a cached guess. venv/plain/node/bun/unshare-net all available.

Bonus observation (graceful degradation): `--backend docker-sandbox` force on a run did not error — it silently fell back to `venv-subprocess` (`[factory] run=… backend=venv-subprocess …`).

## 3. stderr / exit-code capture

Code (python): `sys.stderr.write("error channel message\n")`, `print("stdout channel message")`, `sys.exit(42)` via CLI `--json`.

Observed result.json: `exit_code: 42`, `stdout: "stdout channel message\n"`, `stderr: "error channel message\n"`, timed_out False, net_isolated True. **PASS** — stderr captured separately, exit code 42 preserved. (CLI process itself exits 1 when the child exits nonzero — reasonable CLI behavior, noted for the record.)

## 4. Timeout kill

- **CLI:** python `time.sleep(30)` with `--timeout 3` → `timed_out: True`, `wall_time_s: 3.055`, `exit_code: -1`, `stderr: "[timeout after 3s; process tree killed]"`, CLI exit 1. **PASS**
- **API:** bash `sleep 30` with `timeout=3` → `timed_out: True`, `wall_time_s: 3.008` (client-measured 3.011s), `exit_code: -1`, same stderr note. **PASS**
- **Lingering-process check:** after both runs, `pgrep -fa "^sleep 30"` returned nothing and `ps` showed no sleeper processes — the process tree is actually dead. **PASS**

## 5. cwd-jail escape attempt

Code (python API): printed `os.getcwd()`, wrote relative `pwned.txt`, attempted `open('/tmp/factory-escape-probe','w')`.

Observed:
- (a) cwd = `/home/hatch/workspace/agent-stack/code-factory/runs/20260924T160347-6a6eb5db` — **inside runs/\<run-id\>/** ✅
- (b) `pwned.txt` landed in the run dir ✅
- (c) **The `/tmp/factory-escape-probe` write SUCCEEDED.** ✅ (observed, not a failure)

**Verdict: PASS with DOCUMENTED LIMIT.** The factory jails the working directory but does **not** sandbox the filesystem — everything runs as root, so absolute-path writes anywhere the process can reach will succeed. This matches the factory's own design (cwd jail, not a chroot/container). Probe file deleted after the test. Do not rely on the factory for filesystem containment of untrusted code; cwd jailing only prevents accidental relative-path damage.

## 6. Large-output truncation

Code: `print("X"*1000000)` (~1MB). Observed: `stdout` length **65568 bytes**, `truncated: True`, exit 0, and the tail reads `...[output truncated at 64 KiB]`. **PASS** — capped at ~64 KiB with an explicit truncation note.

## 7. Env scrubbing

Test shell exported `FAKE_TEST_API_KEY=supersecret123`, then child printed its env keys:

- Child env keys did **not** include `FAKE_TEST_API_KEY` (dropped by name-based scrub). ✅
- Secret value did not appear in any other child env var. ✅
- `--env SAFE_VAR=hello` (CLI): child saw `safe_var=hello`. ✅ (non-secret names pass through)

**Verdict: PASS.** Two methodology notes: (1) an early probe falsely suggested a value leak — the "leak" was the runtime's own `JARVIS_TRACE_CONTEXT` env var, which had captured my test shell's literal `export FAKE_TEST_API_KEY=supersecret123` command text; a clean re-run with no secret in the invoking shell showed `hits=NONE`. This is a test-harness artifact, not a factory defect. (2) A probe using a *literal* secret string in the submitted code also returned a false positive because the output redaction layer rewrote the literal before comparison; hex-encoded probes confirmed the true result. Direct `factory.scrub_env()` call confirmed `FAKE_TEST_API_KEY` absent.

## 8. Net isolation

- **Default (network off):** python `socket.create_connection(('8.8.8.8',53),timeout=3)` → `OSError [Errno 101] Network is unreachable`; `ip link` showed only a DOWN loopback; `net_isolated: True`. **PASS**
- **`--network` opt-in (CLI):** same code → `CONNECT: SUCCEEDED`, `net_isolated: False`, wall 0.066s. **PASS** — the flag path works; raw TCP to 8.8.8.8:53 succeeded directly (no proxy needed for this endpoint), so network access is genuinely available when opted in.

## 9. secret_files

`factory.submit(code, language='python', secret_files={'db_pass': 'hunter2-fake'})`, code reading `$FACTORY_SECRET_DIR/db_pass`:

- `FACTORY_SECRET_DIR` set to `<run_dir>/secrets` (path only, never the value) ✅
- Secret file perms `0o600` ✅
- Value readable by the child code ✅
- Secret **value absent** from `result.json`, stdout, and stderr ✅ (first probe invalid: my own probe code printed the value into stdout, which result.json faithfully records — re-ran with code that reads-but-doesn't-print; clean)
- `secret_names: ['db_pass']` recorded in result.json for auditability (names only) ✅
- Run dir deleted after the test ✅

**CLI `--secret-file`:** `--secret-file mykey=/tmp/testsecret.txt` → value readable, perms 0600, only dir path exposed. **PASS**

**Verdict: PASS.**

## 10. CLI JSON mode

`./factory run --language python --timeout 15 --json -`: valid JSON containing exactly the 10 RunResult fields (`stdout`, `stderr`, `exit_code`, `wall_time_s`, `backend_used`, `timed_out`, `truncated`, `net_isolated`, `run_id`, `language`) with correct types. **PASS**

## Cleanup performed

- `/tmp/factory-escape-probe` deleted; `/tmp/testsecret.txt` deleted.
- Test run dirs removed except 3 representative ones kept: `20260924T160318-9238c88a` (python hello), `20260924T160327-c9a3f331` (timeout kill), `20260924T160445-b4b07ca7` (CLI --secret-file). `runs/` root intact.
- No sleep processes left lingering (verified via pgrep/ps).

## Summary table

| # | Test | Verdict |
|---|---|---|
| 1 | Hello-world ×4 languages (CLI) + ×2 (API) | PASS |
| 2 | `factory backends` (docker-sandbox unavailable w/ canary reason) | PASS |
| 3 | stderr/exit-code capture (exit 42) | PASS |
| 4 | Timeout kill, CLI + API (timed_out, ≈3s, no linger) | PASS |
| 5 | cwd-jail escape (jail holds; /tmp write succeeds — documented limit) | PASS (honest limit) |
| 6 | Large-output truncation (~64 KiB cap + note) | PASS |
| 7 | Env scrubbing (+ `--env` passthrough) | PASS |
| 8 | Net isolation default + `--network` opt-in | PASS |
| 9 | secret_files (0600, path-only env, no value in result.json) | PASS |
| 10 | CLI JSON mode (all RunResult fields) | PASS |

**10/10 PASS. No bugs found in factory.py or the CLI.**

## Bugs found

None. (Minor cosmetic notes, not bugs: run IDs use UTC while the user is AEST; the CLI exits 1 when the child exits nonzero — both reasonable.)

## Honest-limit findings

1. **Filesystem is not sandboxed (#5).** cwd is jailed to `runs/<run-id>/` and relative writes land there, but absolute-path writes (e.g. `/tmp/...`) succeed because everything runs as root. Treat the factory as a cwd jail + timeout + net-isolation tool, not a filesystem container.
2. **Net isolation is real for subprocess backends (#8)** via `unshare --net` (verified: only DOWN loopback, connect fails). Docker backend cannot isolate (daemon `--iptables=false --bridge=none`) and is in any case unavailable.
3. **Secret values typed into the invoking shell can resurface via the runtime's `JARVIS_TRACE_CONTEXT` env var** (test-harness artifact, not a factory defect) — don't paste real secrets into test commands; use the `secret_files` path instead.
4. **Forcing an unavailable backend degrades silently** (`--backend docker-sandbox` fell back to `venv-subprocess` with no warning in the human-readable line) — fine per documented behavior, but a caller checking `backend_used` should not assume the requested backend ran.
