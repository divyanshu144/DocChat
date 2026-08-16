# Lessons

Chronological. Append after ANY correction or non-obvious discovery.
Format: **what broke** / **root cause** / **what to do next time**.

---

## 2026-07-28 — RESOLVED: venv rebuilt, dependency clash fixed, suite fully green

Both issues below were fixed later the same day by rebuilding the venv from scratch
(`python3.13 -m venv venv` + `pip install -r requirements.txt`). Kept for the reasoning.

Resolution: `fastapi 0.104.1` → `0.140.13` against `starlette 1.3.1`, and a corrected
`activate` path. Baseline went **45 passed / 4 failed / 12 errors → 61 passed, 0 failed**.

The rebuild also surfaced two undeclared/mis-declared dependencies that a fresh
`pip install -r requirements.txt` would always have got wrong — see the entry at the
bottom of this file.

---

## 2026-07-28 — `source venv/bin/activate` silently does nothing

**What broke:** Ran `source venv/bin/activate && pytest`. Tests failed with
`ModuleNotFoundError: No module named 'trafilatura'` even though the package is in
`requirements.txt`. Installing it "fixed" that error and produced the next missing module.

**Root cause:** The venv was built when this project lived at
`/Users/divyanshu/Desktop/FDE_Projects/docchat` and the directory was later moved to
`/Users/divyanshu/Desktop/All Projects/docchat`. `venv/bin/activate` hardcodes the
absolute `VIRTUAL_ENV` path, so activation sets a path that no longer exists, PATH
prepending fails, and every command silently resolves to `/opt/anaconda3/bin/*` instead.
The console scripts (`venv/bin/pip`, `venv/bin/pytest`, `venv/bin/ruff`) have the same
stale path baked into their shebang and fail with `bad interpreter`.

**What to do next time:** Use `venv/bin/python -m <tool>` — the `python` symlink still
resolves correctly, only `activate` and the shebangs are broken. Verify with
`which python` after activating; if it prints anaconda, the venv is not active.
Permanent fix: rebuild the venv (`python3.13 -m venv --clear venv`).

---

## 2026-07-28 — 16 pre-existing test failures are a dependency clash, not code bugs

**What broke:** `pytest -m "not eval"` reports 4 failed / 12 errors, all
`TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`.

**Root cause:** Commit `dd8043b` loosened `fastapi==0.104.1` → `fastapi>=0.115.0` to
unblock Docker builds, but the local venv still holds a Starlette version that predates
the `on_startup` removal. FastAPI and Starlette are now mutually incompatible in the venv.

**What to do next time:** This is the verification baseline — 45 passed / 4 failed /
12 errors. Do not attribute these to your own change; diff against the baseline by
stashing before concluding you caused a regression. Real fix is pinning a compatible
FastAPI+Starlette pair and rebuilding the venv.

---

## 2026-07-28 — Database bind-mounts were tracked in git

**What broke:** Every `docker compose up` dirtied ~1500 binary files; `git status` was
permanently noisy and `.git` had grown to 47M.

**Root cause:** `postgres_data/` and `qdrant_data/` are bind-mounted by
`docker-compose.yml` and were never gitignored, so live database state was committed.

**What to do next time:** Any new bind-mount target in `docker-compose.yml` gets a
`.gitignore` entry in the same commit that introduces it.

---

## 2026-07-28 — A long-lived venv was hiding two broken requirements

**What broke:** Rebuilding the venv from `requirements.txt` produced a suite that failed
in two *new* ways the old venv never showed: `No module named 'mcp.server.fastmcp'`, then
`No module named 'aiosqlite'`.

**Root cause:** The old venv had accumulated correct-by-accident packages over months.
`requirements.txt` was wrong in two places and nobody noticed because nobody reinstalled:

1. `mcp>=1.27.0` was unbounded, so a clean resolve pulled `mcp 2.0.0`, which removed
   `mcp.server.fastmcp.FastMCP` — the API `app/mcp_server.py` is written against.
2. `aiosqlite` was never declared at all, despite `tests/test_models.py` and
   `tests/test_api_auth.py` both using `sqlite+aiosqlite:///:memory:`. It was present in
   the old venv as a leftover.

**What to do next time:** A passing suite in a long-lived venv is not evidence that
`requirements.txt` is correct — it only proves *that machine* works. Rebuild from a clean
venv before trusting the dependency list, and cap any dependency whose major version
would break an API the code calls directly.

---

## 2026-07-29 — Diagnostic metrics must distinguish zero from undefined

**What broke:** `eval/benchmark.py` reported F1 as `N/A` when precision and recall were
both `0.0`, hiding the worst possible critic run behind an undefined-metric label.

**Root cause:** The F1 guard treated `(precision + recall) == 0` like a missing
denominator. `None` means undefined; numeric zero is a real diagnostic result.

**What to do next time:** Metric helpers need explicit regression tests for both
undefined-denominator cases and defined-zero cases. When docs cite a hard test count,
update it in the same patch that adds tests; the latest non-eval gate is 109 passed.

---

## 2026-08-15 — The test-count lesson was violated by the very next change

**What broke:** The 2026-07-29 entry above ends "when docs cite a hard test count, update
it in the same patch that adds tests." The next change added 5 tests
(`tests/test_critic_rejection_sink.py`) and updated none of them. `CLAUDE.md` (twice),
`HANDOFF.md`, and `tasks/agent_memory.md` all still claimed 109 while the suite ran 114.

**Root cause:** Not discipline — duplication. The number is hand-copied prose in four
files, and `CLAUDE.md` states it as a Definition-of-Done gate ("fully green — 109
passed"), so a stale copy makes the DoD itself wrong: a correct 114-passing run reads as
a failure against the written gate.

**What to do next time:** Treat the count as one fact with four copies and grep it
(`grep -rn "<count>" CLAUDE.md HANDOFF.md tasks/`) as part of the DoD, not from memory.
Do not "fix" the historical copies — the checked-off line in `tasks/todo.md` and the
dated entries here are records of what was true then, and rewriting them destroys the log.

---

## 2026-08-15 — A new direct dependency went in unbounded

**What broke:** `app/services/llm.py` started calling `langsmith` APIs directly
(`traceable(reduce_fn=...)`, `run_helpers.get_current_run_tree`) while `requirements.txt`
still declared `langsmith>=0.1.0` — unbounded, and with a floor far below anything that
has those APIs. Same shape as the `mcp>=1.27.0` break recorded 2026-07-28.

**Root cause:** The package was already listed as a transitive-ish dependency of the
LangGraph stack, so adding a *direct* code dependency on it did not feel like adding a
dependency, and nobody revisited the constraint.

**What to do next time:** Importing a package in `app/` for the first time is a
requirements change even when the line already exists. Cap the major in the same patch.
The floor still wants verifying — `0.1.0` is known-wrong, just not yet known-what-instead.

---

## 2026-08-16 — A corruption is only sound if a *correct* critic would fail it

**What broke:** The corruption generator was approved with four transforms —
`contradict_source`, `drop_citation`, `overclaim`, and an enumeration-shortening one.
Reading `app/agent/nodes/critic.py` before writing any code killed the first three.

**Root cause:** `CRITIC_PROMPT` interpolates exactly two fields, Query and Answer. The
critic never receives the retrieved context, and `benchmark.py` reinforced it by
hardcoding `retrieved_chunks: []`. So:

- `contradict_source` — the contradiction is invisible; unwinnable at any quality level.
- `overclaim` — a fabricated version number and a real one are indistinguishable without
  the source. Worse, its de-hedging half makes the answer read *more* confident, so a
  good critic rates it **better** — the case would be mislabelled, not merely hard.
- `drop_citation` — the prompt asks only whether the answer "adequately addresses the
  query" and says nothing about citations. The remaining prose still answers, so a
  correct critic calls it good.

Each would have emitted a `poor` label the critic was right to reject, and the benchmark
would then have measured the critic against a lie.

**What to do next time:** Before designing any auto-labelled eval case, read the judge's
actual prompt and list the fields it receives. The bar is not "this transform degrades
the answer" — it is **"a correct judge, given only the fields it actually gets, would
call this result poor."** Degradation the judge cannot perceive is dataset poison, and it
is invisible: the run still produces numbers, they are just wrong. Related: the same
prompt gap is why the critic cannot approve a correct gap-admission, logged above.
