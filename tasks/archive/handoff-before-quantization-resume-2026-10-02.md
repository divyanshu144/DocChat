# DocChat session handoff

Updated: 2026-10-01. Branch: `master` (merged hardening branch).
Current checklist: [tasks/todo.md](tasks/todo.md).

## ACTIVE PAID POD — user explicitly said keep it running

**Latest instruction: "keep the pod as it". Do NOT terminate merely because this
session ends.** User requested this handoff before their rate-limit allowance gets
low. Finish writing state, then yield; AWQ/GPTQ are next-session work.

- Pod: `ryy03s0132en85`, name `docchat-quantization-20261001`.
- Created **2026-10-01 17:25:42 UTC**, Secure **L40S 48GB**, **US-MO-1**, **$1.09/hr**.
- Image `vllm/vllm-openai:v0.30.0`, 80GB ephemeral disk, no network volume attached.
- Driver **580.159.03**, CUDA **13.0**, PyTorch **2.13.0+cu130**, vLLM **0.30.0**.
  GPU tensor computation and real model requests passed. No CUDA 12.4 workaround needed.
- **Total cap remains $5.** Budget from original creation, including idle time and
  startup. Conservative termination deadline: **2026-10-01 21:45 UTC (22:45 London)**,
  earlier if billed storage/other charges require it. GPU-only $5 point is ~22:00 UTC.
  There is **NO automatic shutdown**. On resume, check clock/billing immediately.
- Billing endpoint returned no records at ~17:39 UTC; that is reporting lag, NOT free
  compute. Use elapsed time × rate until actual charges appear.
- Keep retained network volume `owdj19ss50` (50GB, US-TX-3). Do not delete it.

## Access and current serving

Direct SSH currently `root@64.247.206.218 -p 17194`; re-read `get_pod` if it changes.
Use the temporary key `/tmp/docchat-quant-trial-key` (private key; never print it).
Known-hosts file: `/tmp/docchat-quant-known-hosts`. These are LOCAL machine files,
not committed. The user's normal SSH key requires a passphrase and is not loaded
in ssh-agent, so batch authentication cannot sign; do not waste time retrying it.
Temporary public key was installed ONLY in this pod, not account-wide.

```bash
ssh -i /tmp/docchat-quant-trial-key -p 17194 \
  -o IdentitiesOnly=yes -o BatchMode=yes \
  -o UserKnownHostsFile=/tmp/docchat-quant-known-hosts root@64.247.206.218
```

FP16 server runs on pod **127.0.0.1:8000**, accessible only over SSH. Local tunnel
was started with `-N -L 127.0.0.1:18000:127.0.0.1:8000` (exec session 31660).
Check localhost:18000/health; recreate tunnel with the SSH options above if needed.
Do not expose unauthenticated inference publicly. Remote executable is
`/usr/local/bin/vllm`, Python `/usr/bin/python3`; `/opt/venv` does not exist in this image.

Remote PID file `/workspace/quantization/server.pid`; logs
`/workspace/quantization/fp16-server.log`; model cache `/workspace/huggingface`.
Container restart changes mapped SSH port and wipes ephemeral files — switch server
processes via the supplied script, do not restart the pod between model variants.

## Results and exact remaining work

Artifacts: **`reports/quantization-2026-10-01/`**. `setup.json` records hardware,
image digest, settings, transport, and the excluded initial attempt.

- Positive control passed: 49.924% hits without cache busting, **0%** with busting.
- FP16 quality: edge cases **1/5**, precision **0.20**, recall **1.00**, F1 **0.3333**;
  all four acceptable edge-case answers were falsely rejected. Generated corruptions
  **15/15** caught, no parse/errors. This is a critic diagnostic, NOT end-to-end quality.
- Corrected FP16 sweep **complete**: c=1 **8/8**, c=16 **16/16**, c=64 **63/64**.
  One c=64 request failed: RemoteProtocolError: Server disconnected without sending a response.
  TTFT p50: **0.982s / 7.280s / 26.624s**. Aggregate tok/s: **40.6 / 142.5 / 180.6**.
  Prefix-cache hit rate **0%**, preemptions **0** at all three cells.
  Raw rows: `fp16-speed.jsonl`; logs: `fp16-sweep.log`. Do not hide the c=64 error.
- **AWQ and GPTQ have not been started.** No comparison claim is justified yet.

Important setup correction: initial `max_model_len=8192` rejected the longest prompt
plus 1,400 output tokens (HTTP 400). Those results are preserved under
`initial-8192-context/` and MUST be excluded. Correct settings for ALL variants:
**float16, max_model_len=16384, gpu_memory_utilization=0.90, prefix caching ON,
client cache busting ON, max_tokens=1400, concurrency=1,16,64**. The old Fourth sweep
used BF16 and a different transport; don't treat its absolute values as this baseline.

1. Check pod status, clock and remaining $5 budget. Preserve existing authorization:
   one L40S, Secure first/Community fallback, three formats, concurrency 1/16/64.
   No need to re-ask for a go. GPU startup already passed within the 15-minute trial.
2. FP16 is complete; use saved corrected rows as baseline. The c=64 server disconnect is
   a measured result, not a reason to silently drop a request or repeat until green.
3. Switch to AWQ using the saved script (local file piped into remote Bash):
   `bash -s -- awq Qwen/Qwen2.5-7B-Instruct-AWQ awq < reports/quantization-2026-10-01/start-serving.sh`
   appended after the full SSH command. This terminates only the old vLLM process
   group, launches the replacement, and keeps model weights cached. Wait for health
   and inspect server log; then run `python3 reports/quantization-2026-10-01/run-serving.py awq`.
4. Repeat for GPTQ with script arguments
   `gptq Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4 gptq`, then `run-serving.py gptq`.
   Record the actual backend from logs (AWQ/GPTQ may choose different kernels).
5. The runner runs positive control → quality → concurrency sweep; control failure
   stops it. It uses local `venv/bin/python`, fallback disabled, tunnel URL, per-run
   environment overrides; persistent `.env` is untouched. Do not overwrite prior
   completed artifacts accidentally. Archive a failed/repeated attempt first.
6. Save remote logs and model revisions locally. Generate comparison with
   `eval/quantization_compare.py` using explicit run timestamp windows; include critic
   metrics separately. Add a dated entry in `eval/BENCHMARK_RESULTS.md` and update
   `docs/inference-writeup.md` with measured results and limitations.
7. Terminate when remaining work finishes or before the cost cap; confirm pod list.
   Current instruction to keep it is for session continuity, not permission to exceed
   $5. Preserve the unrelated network volume. Record actual billing when available.
8. Update checklist/handoff. Phase 4 batching remains deferred. Working tree also has
   unrelated `Claude outputs/`; leave it untouched. No commits made this session.

13 tests in `tests/test_quantization_compare.py` passed this session. No production
code changed. Prior comprehensive checks below remain historical, not rerun today.

## Status

The codebase hardening work is complete; Phase 3 measurement is still in progress. Auth gaps,
folder ownership and default-secret startup refusal were already committed before
this session. SSE whitespace preservation and frontend decoder/build were also done.
This completion pass covers:

- Configured chat history limit, removed dead YouTube API key setting.
- Lazy Qdrant URL, reused HTTP client per event loop, API/MCP shutdown cleanup;
  retrieval query embedding runs in a worker thread.
- Original user question survives all planner rewrites; synthesis and critique use it.
- Partial context truncation searches within the body and preserves citation labels.
- Independent CPU embedding batches, off-loop ingestion indexing, shared source
  deletion/replacement; successful shorter re-ingests leave no orphan chunks.
- Bounded uploads (50 MiB by default), ordered awaited PDF progress, startup recovery
  of queued/running jobs left by restart; temp files cleaned on failure.
- Dependency-aware health (503 if DB or Qdrant fails), bounded per-IP auth/chat limits,
  atomic refresh rotation and user-wide refresh-session revocation on replay.
- Critic JSON failure warnings; benchmark no longer scores parse fallback as good.
- Real-corpus retrieval comparison and both requested redesign specs.
- Current docs/skills reconciled with one source_chunks collection and independent
  embeddings; historical audit/design claims clearly marked as provenance.

## Verification

- `venv/bin/ruff check .`: All checks passed!
- `venv/bin/python -m pytest -m "not eval" -q`: 368 passed, 8 deselected.
  13 warnings from python-jose's deprecated UTC timestamp helper.
- `cd frontend && npm test -- --run`: 3 test files, 6 tests passed.
- No frontend code changed in this completion pass; existing SSE build is retained.
- Approved live critic diagnostic using OpenAI `gpt-5.5`, reasoning=none,
  temperature=0, max_completion_tokens=150, fallback disabled: 5/5 edge cases,
  15/15 corruptions, 20 requests, no errors/parse failures, every finish_reason=stop.
  Report: [critic benchmark](reports/critic-benchmark-gpt55.md), raw JSON alongside.
  This was a per-run override; persistent provider/model config was not changed.
- Retrieval eval: 24 real-corpus questions, 17 chunks from the PDF declaration and
  Wikipedia RAG article. Recall@3 dense 0.8750, lexical 0.9792, cross-encoder 1.0000.
  Cross-encoder ranking averaged 1.17 seconds on CPU; production ranker unchanged.
  [Report](reports/retrieval-evaluation.md), golden labels and raw rankings retained.

## Operational limits

One application worker is the current model. Job recovery, in-memory IP limits,
and source-write locks are process-local; use shared ownership/queue/limiter before
scaling to independent workers. Qdrant delete plus batched upsert is not transactional;
retry failed indexing jobs. Replay revokes refresh tokens, not existing access JWTs.

A production restart requires a real JWT_SECRET_KEY (or DEBUG=true for local dev).
The prior running Compose app lacked that setting; do not expose the shipped key.
Host-side scripts must use localhost:6333 and Postgres port 5433, rather than Docker's
qdrant/postgres DNS names. Do not read/print .env secrets in session output.

## Explicitly deferred

Phase 3 is in progress; see the ACTIVE POD and next steps above. Phase 4 batching
remains deferred. Do not confuse older termination records with the current live pod.
The retained network volume owdj19ss50 (50GB, US-TX-3) has cached Qwen weights and its
own storage charge; user chose to keep it. Do not delete it without a specific go.

Grounding verdict/removal and context-aware critic redesigns stop at these specs:
- [Grounding](docs/superpowers/specs/2026-10-01-grounding-verdict-design.md)
- [Critic context/ablation](docs/superpowers/specs/2026-10-01-critic-context-ablation-design.md)

They contain concrete paired quality/latency experiments. No production redesign or
critic-on/off quality-lift claim has been made. A 20/20 classification diagnostic is
not evidence that the retry loop improves end-to-end answers.

## History and next action

The hardening checklist is complete; the authorized Phase 3 live run remains pending.
The hardening branch was pushed
and merged into the repository's default `master` branch without conflicts. Merge
commit `77a2abb` is published on `origin/master`. Checks on the integrated branch:
368 Python tests passed, 6 frontend tests passed, and Ruff clean.
Unrelated `Claude outputs/` is untouched.
Older handoff: [archive](tasks/archive/handoff-before-hardening-completion-2026-10-01.md).
Older inference checklist: [archive](tasks/archive/inference-todo-prior-sessions.md).
Historical counts and obsolete pending entries there are not current instructions.
