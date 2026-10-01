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

---

## 2026-08-19 — "Config set" is not "setting applied"

**What broke:** `temperature=0` was threaded through the seam and pinned on the critic
and planner, tests proved it reached every provider, and the benchmark was still not
reproducible: two runs scored 12/15 with *different cases failing*.

**Root cause:** `gpt-5.6-luna` rejects it — `400 Unsupported value: 'temperature' does
not support 0 with this model. Only the default (1) value is supported.` The
drop-and-retry fallback written for exactly this case worked perfectly and logged at
WARNING, which nothing was displaying. The pin was a silent no-op, and every critic and
planner call was quietly making two HTTP requests instead of one.

**What to do next time:** A parameter is applied when the *provider* accepted it, not
when the code sent it. Unit tests assert the request shape; only a live call proves the
response. When a fallback exists to swallow a rejection, that fallback is exactly what
hides the failure — check its log line explicitly, and cache the rejection so the cost is
paid once rather than on every call forever. Verified the pin does work where the model
allows it: two Groq/`qwen3.6-27b` runs were byte-identical across all 20 verdicts.

---

## 2026-08-19 — A broken test fixture looked like four critic failures

**What broke:** `pytest -m eval` reported 4 failed / 4 passed. Three failures said
`RuntimeError: Event loop is closed`; one looked like a genuine critic disagreement on
`hallucinated_claim`, and arrived in the same run as a prompt change — the obvious
reading was that the new prompt had broken it.

**Root cause:** `app.services.llm` caches one client per provider for the process, and an
httpx/AsyncGroq connection pool binds to the event loop that created it. pytest-asyncio
gives every test a fresh loop, so every real-API test after the first hit a dead one.
Resetting the cache per test in `tests/conftest.py` took the suite to 8 passed — the
"real" disagreement was a symptom too.

**What to do next time:** Stash-diff before attributing a failure to your change — the
project rule, and it paid for itself here: the baseline showed the same failures without
the prompt change. And when a suite fails with a mix of infrastructure errors and
assertions, fix the infrastructure before reading the assertions at all. A shared cache
keyed by process but bound to a loop is the recurring shape of this bug.

---

## 2026-08-19 — Provider model IDs rot, and the default rotted first

**What broke:** Running the benchmark against Groq to test determinism returned 20
identical `404 model_not_found` errors. `llama-3.3-70b-versatile` — the `chat_model`
default in `config.py` and the value shipped in `.env.example` — no longer exists.

**Root cause:** Nobody had exercised the Groq path since the local `.env` switched to
OpenAI on 2026-07-29. A provider decommissioned a model and the default rotted silently,
because the only thing that would have caught it was a live call nobody was making.

**What to do next time:** Hosted model IDs are external state with no compile-time check
and no test coverage — a fallback provider that is never exercised is not a fallback.
Query `GET /models` before setting one, and treat "the unused provider still works" as an
assumption to verify, not a fact. Second-order trap found the same day:
`qwen/qwen3.6-27b` returns valid JSON for every case and rates all of them good
(recall 0.00). A model can be alive, fast, correctly wired, and still useless as a judge.

---

## 2026-09-29 — `docker compose restart` does not reload `.env`

**What broke:** Updated `.env` with `LLM_PROVIDER=local` for the vLLM smoke test, ran
`docker compose restart app`, confirmed the app was healthy, ran two real chat queries —
both went to `api.openai.com`, not the local pod. `docker exec ... printenv LLM_PROVIDER`
inside the running container still showed `openai`.

**Root cause:** `restart` restarts the existing container process; it does not re-read
`env_file`/`environment` from the compose file. Those are only applied when the
container is *created*. The container had been running for 2 months, so its environment
was frozen at whatever `.env` held back then.

**What to do next time:** Any `.env` change to a service requires recreating its
container, not restarting it — `docker compose up -d <service>` (or
`--force-recreate` if compose doesn't detect the diff). Verify with
`docker exec <container> printenv <VAR>` rather than assuming a restart picked it up.
Caution: `--force-recreate` on one service can cascade to its `depends_on` dependencies
if *their* containers have also drifted from the compose definition — this is what
surfaced pre-existing WAL/ID-tracker corruption in `postgres_data`/`qdrant_data` that had
sat dormant for two months because neither process had done a real restart-recovery
sequence in that time. A plain `docker compose restart <service>` (no recreate) is safe
from that cascade; reach for it first if only the running process needs a bounce.

---

## 2026-09-30 — RunPod bills GPU time for a Stopped/Exited pod, not just a Terminated one

**What broke:** A vLLM pod crashed with a CUDA init error within ~2 minutes of creation
and sat `EXITED` (RunPod's stopped state) for the next ~2.5 hours before being fully
Terminated. Real billing data (`list-pod-billing`) showed **$1.87** charged for that pod
— GPU-rate cost for the whole window it existed, not just the ~2 minutes it actually ran.

**Root cause:** Assumed (and had documented in `docs/vllm_setup.md`) that Stop halts GPU
compute billing and only Terminate is needed to avoid the storage trickle charge. Real
data contradicts that: an `EXITED`-but-not-`Terminated` pod kept accruing GPU cost the
whole time it existed in that state.

**What to do next time:** Use **Terminate**, not Stop, as the actual cost control when
done with a rented GPU pod — don't trust a platform's UI-level distinction between the
two without checking real billing history first. `docs/vllm_setup.md` §6 corrected to
say this plainly, with the $1.87 figure as the cited evidence.

---

## 2026-09-30 — A reasoning model can spend its whole token budget and return nothing

**What broke:** Exactly half of `openai`'s requests at concurrency 16/64 in the first
benchmark sweep had `output_tokens=0` — silently, no error, no exception. The benchmark
just recorded a real but empty result.

**Root cause:** `gpt-5.6-luna` (the configured `OPENAI_CHAT_MODEL`) is a reasoning
model. Sent all 8 eval queries directly with `max_tokens=128` and read `finish_reason` +
`usage.completion_tokens_details.reasoning_tokens`: 6/8 consumed the entire 128-token
budget on hidden reasoning tokens and were truncated (`finish_reason: length`) before a
single visible character was emitted. The chunk-count-based token proxy the harness used
at the time couldn't tell "zero visible tokens" apart from "the request never happened."

**What to do next time:** A streaming harness that only counts yielded chunks cannot
distinguish a genuinely empty response from one that never arrived, and cannot tell you
*why* it was empty. Request `usage` (`stream_options: {"include_usage": true}`) and
`finish_reason` explicitly rather than inferring behavior from content alone — the fix
here was adding an optional `usage_sink` to `chat_stream()` and giving every benchmark
result an explicit `status` (ok/error/empty) instead of just a token count. Before
benchmarking any model's throughput, check whether it's a reasoning model first — a
reasoning-family model's `max_tokens` budget has to survive its own reasoning phase
before any output is possible, so a budget sized for a non-reasoning model's decode
speed will silently starve it of real content.

---

## 2026-09-30 — Sequential-batch wall time must be measured, not inferred from `max()`

**What broke:** The concurrency=1 fix (run every query sequentially instead of just
one) shipped in the same change as `wall_time_s = max(r["total_s"] for r in results)`.
That formula is correct for genuinely concurrent requests (wall time ≈ the slowest one
overlapping with the rest) but silently wrong for the new sequential case — 8
non-overlapping requests don't share a wall clock the way 8 concurrent ones do, so their
real wall time is close to the *sum* of their durations, not the max of any one of them.
First live re-run showed `local`'s concurrency=1 throughput at 592 tok/s; after the fix,
89.7 tok/s — a >6x overstatement, caught by the number being implausibly *higher* at
concurrency=1 than at concurrency=4 (throughput going down as load goes up should be
the surprising direction, not the default one).

**Root cause:** Deriving a summary statistic from the shape of per-request data instead
of measuring the thing itself. `max(total_s)` is a plausible-looking proxy for wall
time that happens to be correct in one case (true concurrency) and wrong in another
(sequential execution) — and nothing about the code would have complained, since both
cases return a syntactically valid number.

**What to do next time:** When two different call patterns (concurrent vs sequential)
feed the same aggregation function, don't let the aggregator infer which pattern
produced its input — measure the actual wall-clock duration at the call site
(`time.monotonic()` before/after the batch) and pass it in explicitly. A derived number
that's "usually right" is worse than an explicit one that's always right, because the
usually-right version fails exactly where you're least likely to notice: a case you
just added and haven't built intuition for yet.

---

## 2026-09-30 — `.env`'s `QDRANT_HOST=qdrant` only resolves inside docker-compose

**What broke:** `eval/capture_bench_prompts.py` (run directly on the host, not through
`docker compose exec`) failed in `retriever_node` with
`[Errno 8] nodename nor servname provided, or not known`.

**Root cause:** `.env` sets `QDRANT_HOST=qdrant`, the docker-compose service name —
correct for the `app` container (which resolves it via the compose network) but not a
hostname the host machine's DNS knows anything about. Any script run with
`python eval/...` directly, outside the container, inherits that same `.env` value.

**What to do next time:** A host-side script that needs Qdrant needs
`QDRANT_HOST=localhost` (Qdrant's port is published to the host per
`docker-compose.yml`), not whatever `.env` has for the containerized app. Override at
invocation — `QDRANT_HOST=localhost python eval/some_script.py` — rather than editing
`.env` itself, which would just break the containerized app the same way in reverse.

---

## 2026-09-30 — A benchmark that reuses identical prompts is measuring its own cache

**What broke (caught by review, not by the benchmark itself):** The Third sweep's
`local` TTFT was 0.5-0.85s at every concurrency level including c=64. Flagged as
physically implausible: ~320k tokens of prefill at c=64 should take tens of seconds on
one A100 with no caching (~10k prefill tok/s for a 7B model), not under a second.

**Root cause:** The harness cycled the same 8 fixed prompts across every concurrency
level (`prompts[i % len(prompts)]`), and concurrency=1 ran first, sequentially
processing all 8 before c=4/16/64 started — so by the time higher-concurrency cells ran,
every prompt they'd send had already been through the engine once. Combined with vLLM's
default `enable_prefix_caching=True` (never disabled, confirmed in every pod's startup
log this session), the structural conditions for a prefix-cache hit were present on
every cell after the first. No test caught this because nothing in the test suite
exercises identical-prompt reuse against a real cache — it's an interaction between the
benchmark's own workload design and the server's own default behavior, invisible to
mocked unit tests.

**What to do next time:** A benchmark harness that reuses a fixed prompt set across
multiple measurement cells has to either (a) make every request's prompt unique (cache
busting — implemented as `_bust_prompt()`, prepending a `request_id: <uuid4>` line,
default ON) or (b) instrument the thing being benchmarked well enough to prove whether
caching happened (vLLM `/metrics` polling, added the same session) — ideally both, since
(a) without (b) is trust without verification, and a >10% hit rate with busting
supposedly on now prints a loud warning rather than failing silently. A suspiciously
fast or suspiciously flat number under load is itself a signal to check for caching,
not just "the system is fast."

---

## 2026-09-30 — Guessed Prometheus metric names were wrong on the first real check

**What broke:** `_VLLM_METRIC_CANDIDATES["gpu_cache_usage_perc"]` had one candidate,
`vllm:gpu_cache_usage_perc`, written entirely from memory/guesswork (Part B of the
cache-busting task was explicitly code-only, no pod). Hitting a live vLLM v0.30.0
`/metrics` endpoint for the first time (positive control + health checks before the
Fourth sweep) showed this metric doesn't exist on this version — it's
`vllm:kv_cache_usage_perc`. Every other guessed name (`prefix_cache_queries_total`,
`prefix_cache_hits_total`, `num_preemptions_total`, `num_requests_waiting`,
`num_requests_running`) happened to be right, which made the one wrong guess easy to
miss if not checked explicitly.

**What to do next time:** before trusting any code written against an external
service's *documented or remembered* field/metric names with zero live verification,
do one live probe (`curl .../metrics | grep <topic>`) as the very first thing once real
access exists — before running anything that depends on the name being right. Here that
probe was already built into the plan (the positive control's explicit job), which is
why this got caught instead of silently reporting `peak_gpu_cache_usage_pct: None` for
every cell of a real, paid sweep. The general pattern: when code that talks to an
external surface is written before that surface is reachable, treat every literal name
in it as a hypothesis, not a fact, until the first live call confirms or corrects it.

---

## 2026-10-01 — A word-boundary trim can silently erase a whole chunk

**What broke (caught by a test, not shipped):** `_format_chunks`/`_format_context`'s
partial-inclusion path does `entry[:remaining].rsplit(" ", 1)[0]` to avoid cutting a
chunk mid-word when it doesn't fully fit the remaining budget. Writing a test for the
new drop-count logging used a chunk made of one repeated character with no spaces
(`"b" * 700`). The label before it (`"Source marker: [PDF - doc.pdf]\n"`) has spaces,
so `rsplit(" ", 1)` found its last space *inside the label*, not inside the chunk body,
and cut everything from that point onward, including the entire space-free chunk body.
A test asserting the partial chunk's content should appear in the output failed because
of this, not because of anything the new logging code did.

**What to do next time:** when testing a word-boundary truncation helper, don't use
repeated-character test fixtures with no spaces in them. More importantly: this is a
real, pre-existing bug in the partial-inclusion logic, not something this session's
change introduced — a chunk whose body happens to have no space near the cut point (or
no space at all) can lose its entire partial slice silently, with the label surviving
and the actual content gone. Not fixed here (out of scope for the logging-only task),
but worth a follow-up: `rsplit` should search within the chunk's own text, not the
combined `entry` string that includes the label, or fall back to a hard character cut
when no space is found within some reasonable distance of the end.

---

## 2026-10-01 completion notes

- The default `.venv` lacked pytest/ruff; this project's working environment is
  `venv/`. Use its explicit executables rather than assuming a directory name.
- A startup lifecycle test that mocks schema creation must also isolate the new
  interrupted-job recovery query. Recovery itself is tested against real SQLite;
  do not let an offline lifecycle test accidentally connect to Docker DNS names.
- Independent embeddings were hidden behind `embed_late`, which ignored segment
  context. That name and its dead parameters are removed; docs describe what runs.
- A critic parse fallback accepts without a real verdict. Benchmarks must record
  malformed/empty responses as errors, not score the fallback as a good verdict.
- GPT-5.5 defaults to reasoning that can exhaust a tiny classification output cap.
  For the approved short critic diagnostic, explicitly selected reasoning=none;
  live usage confirmed zero reasoning tokens and no truncated/empty verdicts.
- The e2e harness still looked up synthetic fixtures by per-type collection names
  after production switched to source_chunks. Its adapter now applies payload source
  filters. Its compare mode measures first pass versus retry, not critic on/off.
