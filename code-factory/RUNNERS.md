# Local Code-Execution Runners — Audit Matrix

**Audit date:** 2026-09-25 AEST · **auditor:** local-runner auditor subagent · **scope:** read-only probing of backends; hardening notes only, no scripts modified

Every "runs?" verdict below was verified by actually executing something, not by reading config files.

| Backend | Runs? | Version | Quirks | Limits | Hardening needed |
|---|---|---|---|---|---|
| agent venv python (`~/workspace/agent-stack/.venv`) | ✅ yes | Python 3.12.3; langchain_core 1.6.4, langgraph 1.2.12, langsmith 0.14.0, deepagents 0.7.17, pydantic 2.13.5 | `langgraph` imports fine but exposes no `__version__` (that's normal for the package); pinned versions.txt lists langchain==1.4.2 against langchain-core==1.6.4 — minor skew, imports still OK | Full-trust code, full fs + net access as root | timeout= mandatory; cwd sandbox dir; env scrub (minimal allowlist); resource.setrlimit for CPU/RSS/CPU-time (verified supported); optional `unshare -n` wrapper for net isolation (verified working as root); cap stdout/stderr |
| system python3 (`/usr/bin/python3`) | ✅ yes | 3.12.3 | plain stdlib only | Full-trust, full fs + net as root | same as venv python (timeout, cwd jail, env scrub, rlimits, unshare net) |
| `/bin/bash` subprocess | ✅ yes | bash 5.2.21 | shells everything — injection surface if any untrusted string reaches it | Full-trust as root; argument-injection risk | prefer argv arrays over shell strings; timeout; cwd jail; env scrub; never build commands from untrusted input |
| Docker (`~/workspace/bin/docker/docker` → local dockerd) | ⚠️ daemon up, `docker run` **broken** | 28.5.1 client+server | Images cached: `python:3.12-slim` (119 MB), `hello-world:latest`. Daemon flags `--iptables=false --bridge=none`. **`docker run` fails two ways today:** (1) `containerd-shim-runc-v2` binary is missing from `~/workspace/bin/docker/` (it IS inside `docker.tgz` — infra fix: extract it; outside factory scope); (2) even `--network host` aborts with `failed to create default sandbox … operation not permitted` — containerd's netns creation is denied in the daemon's context | No iptables → no network isolation possible through this daemon; containers must use host network; run currently impossible at all | after infra fix: hard client-side timeout + kill; `--pids-limit`, `--memory`, `--cpus`, `--read-only`+tmpfs, drop caps, never `--privileged`; treat containers as host-networked (assume full LAN exposure) |
| `~/workspace/bin/docker-pull` (curl h2 + `docker load`) | ✅ script exists & executable (no defect found; images already cached so not re-executed) | N/A (script) | Works around the known egress-proxy HTTP/1.1 registry kill by fetching manifest+blobs via curl | Build-time only; not a code runner | build-time only — no action; keep out of untrusted-input path |
| node (`/usr/bin/node`) | ✅ yes | v24.20.0 | single-shot `node -e` tested OK | Full fs + net as root | run under same subprocess wrapper (timeout, cwd jail, env scrub, unshare net); restrict npm install targets |
| bun (`/opt/hatch-image/bin/bun`) | ✅ yes | 1.3.10 | `bun -e` tested OK | Full fs + net as root; bun can fetch/install packages on demand | same wrapper; consider `--no-install` or pin package cache dir |
| deno | ❌ not installed | — | — | — | N/A (task forbids new heavy installs) |
| Redis `127.0.0.1:6379` | ✅ up (`PING` → `PONG`) | server binary at `~/workspace/bin/redis-server` | state/cache service only — **not a code-execution backend** (Lua scripting exists in Redis but is not exercised here) | — | bind 127.0.0.1 only (verify in redis.conf); no auth needed for localhost-only; do not expose |
| mission-control `mc status` | ✅ healthy | — | Health checks verified live: (1) local JSONL trace store (737 events, last write ~38h ago), (2) LangSmith cloud via APAC proxy, (3) fleet import/key status (claude/codex/sdk/sdk health probes), (4) runtime plane: docker UP, redis UP, 4 agent-ish processes, venv present + imports OK | observability only — not a code runner | none (read-only CLI) |

## Honest sandbox limits (verified, not assumed)

- **Everything runs as root** (`id -u` = 0). There is no user separation anywhere in the stack.
- **Network isolation via Docker is unavailable:** the daemon runs `--iptables=false --bridge=none`, so even after `docker run` is fixed, containers share the host network — no isolation.
- **Network isolation via raw `unshare -n` DOES work** for subprocess-based runners: `unshare --net ip link` as root produced a clean empty namespace (only loopback, down). The factory's subprocess/python/node/bun runners can genuinely net-isolate this way — Docker is the odd one out (containerd's netns creation fails with "operation not permitted" in the daemon's context, for reasons not yet diagnosed).
- **No sandboxing tools installed:** no firejail, bubblewrap, or nsjail.
- **`docker pull` is dead** through the egress proxy (h2/ALPN issue, root-caused 2026-09-24); `docker-pull` workaround exists.
- **Timeout support:** full for subprocess-family (`timeout=` param, and `resource.setrlimit` for CPU/RSS — verified working). For Docker there is no server-side hard run cap; use client-side timeout + kill.
- **cwd jailing:** feasible everywhere that matters — `subprocess(cwd=...)` for python/node/bun/bash, `docker run -w` after the infra fix.
- **Secrets:** there is currently **no secret-injection mechanism**. Never pass secrets via env vars (visible in `/proc/<pid>/environ` to root, leak into logs/dumps). The factory helper should inject via stdin or a restricted file descriptor at spawn time.

## What's broken / missing (for the parent/infra, not the factory)

1. `docker run` broken — missing `containerd-shim-runc-v2` (extract from `~/workspace/bin/docker.tgz` into `~/workspace/bin/docker/`) **and** containerd netns creation denied. Both need an infra-side fix outside `code-factory/`.
2. `deno` not installed — per task instruction, no new heavy installs; record as unavailable.
3. No secret-injection plumbing exists yet — the factory's shared helper must design it (stdin/fd-based), it can't be bolted onto any single runner.
4. Minor: `versions.txt` pins `langchain==1.4.2` against `langchain-core==1.6.4` — worth a consistency check at next rebuild.
