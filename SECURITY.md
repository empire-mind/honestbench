# Security Policy — honestbench

## Status

This project is **pre-v1**: no tagged release exists yet. The supported
version is `main` (see the table below).

## Supported versions

| Version         | Supported with security updates |
|-----------------|---------------------------------|
| `main` (pre-v1) | ✅                               |

Security fixes land on `main`. Once versioned releases exist, the latest
release will also receive security fixes.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Use GitHub's **private vulnerability reporting**: on this repository's page,
open the **Security** tab and choose **"Report a vulnerability"**. Your
report stays visible only to you and the maintainers until a fix is ready
and a public advisory is published.

What to include:

- A description of the vulnerability
- Steps to reproduce (the exact harness/factory invocation and config)
- The potential impact
- A suggested fix, if you have one

## Scope

**In scope:**

- Vulnerabilities in the eval harness (`evals/`) and the execution plane
  (`code-factory/`) on this repository's default branch — in particular,
  escapes from the documented execution-plane isolation (cwd jail, env
  scrubbing, output caps, process-group kill)
- Supply-chain issues in declared dependencies (see the Dependabot note
  below)
- Misconfigurations in this repository's CI workflows

**Out of scope:**

- Theoretical issues without a plausible exploit path
- Findings in forked copies or stale branches
- Social engineering or physical attacks
- Gaps already documented as honest limits (e.g. `code-factory/CODE-FACTORY.md`
  states there is no filesystem sandboxing) — unless you can demonstrate an
  escape beyond what the limits doc already concedes

## Response expectations

We will acknowledge your report within **7 calendar days**. For confirmed
issues we will share a remediation plan or timeline within **14 days** of
acknowledgement. We ask that you do not disclose the vulnerability publicly
until a fix is available.

## Secret scanning and Dependabot

- GitHub **secret scanning** and **push protection** are enabled on this
  repository.
- **Dependabot security updates** are enabled.
- CI runs on every pull request and must be green before merge.
- Org-level policy: [empire-mind/.github SECURITY.md](https://github.com/empire-mind/.github/blob/main/SECURITY.md)
