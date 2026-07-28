# Lessons

Chronological. Append after ANY correction or non-obvious discovery.
Format: **what broke** / **root cause** / **what to do next time**.

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
