# Live GPU session: run plan (2026-10-06) - DRAFT, NOT APPROVED

Nothing here has been run. No pod is rented, no paid API is called, and nothing is spent until you approve this plan
and the cap in section 2. Estimates are derived from the earlier FP16 held-out run
(`reports/heldout-serving-evaluation-2026-10-05.md`) and `reports/quantization-2026-10-01/setup.json`; they are not
predictions of what this pod will do and no number below is a measurement of the new run.

## 1. Decisions I need from you

1. **Requests per cell: 64 or 100?** The earlier FP16 run used 64 with `--min-samples 64`. Over 64 samples a p99 is just
   the maximum, so p99 would be `unavailable`; and at 64 requests the c=32/c=64 cells last only about 31 s (64 requests
   at about 2.06 requests/s), right at the 30 s window floor. **I recommend 100**: windows of about 48 s at c=32/64, and p99
   becomes reportable but weak (with 100 samples it is the second-largest latency; I will label it descriptive). Cost of
   100 versus 64: about 8 extra minutes of sweep.
2. **The failure-behaviour test cannot show a hosted fallback.** In `app/services/llm.py`, a hosted fallback exists only for the Groq
   provider (`_can_fallback_to_openai`, used in the `groq` branch). With `LLM_PROVIDER=local` there is no fallback. So the
   test will measure: errors, time to first error, `/health/serving` state while vLLM is down, and recovery time. It
   will confirm that no fallback occurs. Describing it as a fallback test would be false. (Decided: name it a failure-behaviour test; add no fallback.) A local-to-hosted fallback would be a
   production behaviour change and is out of scope unless you ask for it separately.
3. **Cost cap.** I propose a **hard cap of $4.00** with a stop-and-ask checkpoint at **$2.50** (section 2).
4. **Optional extras** (prefix-cache on versus off; serial versus concurrent): include them, or run the core session only?
5. **Network volume** `owdj19ss50` (50 GB, US-TX-3, retained from October): the earlier L40S pods ran in US-MO-1 and
   EUR-IS-2, so it cannot attach there. Keep it (ongoing storage charge, amount unverified) or delete it after the session?

## 2. Budget and time (estimates)

Provider RunPod, one **L40S 48 GB (Secure)**, last quoted **$1.09/hour** on 2026-10-01/02 for the earlier pods. I will
re-quote the live price and availability before asking you to approve the spend.

| Step | Basis | Estimate |
|---|---|---|
| Provision, image pull, 15 GB model download, vLLM start | unmeasured; the earlier setup note says a couple of minutes on first launch | 20 min budgeted |
| Health checks, app smoke test, positive control, offset, sampler | manual steps | 20 min |
| Clean sweep, 100 requests/cell, 2 repeats | sum of 100/RPS from the earlier FP16 run: 0.271, 0.912, 2.029, 2.083, 2.064 RPS at c=1,4,16,32,64 gives about 624 s per repeat | about 21 min, plus warmups and drains |
| Copy back, dry-check, attach | manual | 5 min |
| **Core subtotal** | | **about 1.1 h, about $1.2** |
| Failure-behaviour test (stall, then kill and restart) | restart reloads the model from disk | about 20 min, about $0.4 |
| Extras (cache-off restart plus sweep; serial versus concurrent) | | about 35 min, about $0.65 |
| **All-in** | | **about 2.1 h, about $2.3** |

The earlier three-format held-out session was billed about $0.64 (posted charges, with billing lag; not a final invoice).
At the cap, $4.00 is about 3.7 hours at the quoted rate. I will read actual billing back after termination and report
the real figure, flagging lag.

## 3. Pre-flight (free, local)

```bash
venv/bin/ruff check . && venv/bin/python -m pytest -m "not eval" -q          # record counts
venv/bin/python -m eval.inference_benchmark sustained --target replay \
  --workloads data/heldout-quality-workload.json --out-dir /tmp/not-created --validate-only
# expect workload_sha256 65e6df6515525e1ea78ab54631400f9702b0b7bc4ccc89f2c2846b9c8a6c06a9 (verified offline today)
export RUN=reports/gpu-live-2026-10-DD; mkdir -p $RUN
```

Also required: the local stack up (Docker Compose Qdrant and PostgreSQL with the existing two-document corpus ingested)
for the app smoke test, and Phase 1 tooling approved and merged into the working tree.

## 4. Session steps (each paid step waits for your "go")

1. **Provision** the L40S with image `vllm/vllm-openai:v0.30.0` (digest recorded earlier as
   `sha256:8a69ffad015f138d7170c4ddc429e230a3bc1c1719f67e14324749df200a4b90`; I will check it against the live pod and use
   only what I observe). Record start time and pod id. **Set a hard stop time now**: start plus 3 hours.
2. **Observe the manifest from the pod** (never guessed): `nvidia-smi --query-gpu=name,driver_version,memory.total
   --format=csv`, CUDA from the `nvidia-smi` header, `pip show vllm torch`, the image digest from the provider, the model
   and tokenizer commit from the Hugging Face cache, and the chat-template hash. Any field I cannot observe stays null and I
   say so. Fill a copy of `deploy/vllm-manifest.example.json` into `$RUN/deployment.json`.
3. **Start vLLM** with the earlier flags: `--served-model-name Qwen2.5-7B-Instruct --dtype float16 --max-model-len 16384
   --gpu-memory-utilization 0.90 --api-key <random, kept in an env var only> --port 8000`, prefix caching left at the engine
   default (recorded from the log, not assumed). Open `ssh -N -L 18000:127.0.0.1:8000`.
4. **Checks:** `curl /v1/models`; start the app locally with `LLM_PROVIDER=local LOCAL_BASE_URL=http://127.0.0.1:18000/v1
   LOCAL_CHAT_MODEL=Qwen2.5-7B-Instruct LOCAL_API_KEY=<env>` supplied as process environment (no `.env` edit), then
   `GET /api/v1/health/serving`, then one real document question through `/api/v1/chat`. Save the three outputs.
5. **Positive control** before the sweep: `python eval/positive_control.py --prompts-file data/bench_prompts.jsonl`
   (legacy harness; expects a high hit rate with busting off and about zero with it on). Exit code 1 means stop.
6. **Sampler:** copy `eval/gpu_sampler.py` to the pod; `nohup python3 /tmp/gpu_sampler.py /tmp/gpu-samples.jsonl
   --interval 1.0 > /tmp/gpu-sampler.log 2>&1 & echo $! > /tmp/gpu-sampler.pid`; check the first line shows a real backend, not
   `unavailable`. Use `--interval 0.5` only if cells prove short.
7. **Clock offset** (three trials): read the client clock, read the pod clock over SSH, read the client clock again; use
   the midpoint of the two client readings; `clock_offset_s = gpu_host_clock - benchmark_client_clock`. Save the raw
   readings to `$RUN/clock-offset.json`. Trials must agree to within a fraction of a second.
8. **Clean sweep** (nothing else running on the pod):
   ```bash
   LOCAL_BASE_URL=http://127.0.0.1:18000/v1 LOCAL_CHAT_MODEL=Qwen2.5-7B-Instruct LOCAL_API_KEY=$VLLM_API_KEY \
   venv/bin/python -m eval.inference_benchmark sustained --target replay --provider local \
     --workloads data/heldout-quality-workload.json --deployment-manifest $RUN/deployment.json \
     --concurrency 1,4,16,32,64 --repeats 2 --warmup 2 --duration 600 --requests 100 --timeout 120 \
     --min-samples 100 --cache-mode bust --metrics-url http://127.0.0.1:18000/metrics --out-dir $RUN/sweep
   ```
   (`--requests 64 --min-samples 64` if you choose to replicate the earlier run exactly.) Snapshot the sampler file back
   after each repeat, since the pod can disappear.
9. **Stop the sampler** with `kill -TERM $(cat /tmp/gpu-sampler.pid)`; confirm the last line is `sampler_stop`; copy the file back.
10. **Attach:** `python -m eval.gpu_utilization attach $RUN/sweep $RUN/gpu-samples.jsonl --clock-offset-s <S> --dry-check`;
    fix anything it shows; then the same command without `--dry-check`.
11. **Failure-behaviour test** (Phase 1 mode; separate output directory and a second sampler file so the clean numbers are not
    polluted): fixed concurrency, `kill -STOP` the vLLM process for a fixed interval and `kill -CONT`, then a hard `kill`
    and restart. Record errors, time to first error, `/health/serving` state, time to recovery, and confirm no fallback.
12. **Extras if approved:** cache-off restart plus a sweep subset; serial versus concurrent comparison.
13. **Terminate:** copy every artifact locally first; `delete-pod`; `list-pods` must show it gone; read billing back.

## 5. Artifacts (all under `reports/`, no credentials, no raw logs staged)

`gpu-live-<date>/deployment.json`, `clock-offset.json`, `sweep/` (manifest, events, `gpu-utilization.json`),
`failure/` (events, its own GPU file), `gpu-samples*.jsonl`, health and smoke outputs, `billing-readback.json`, and the
Phase 3 report `reports/gpu-live-<date>.md`.

## 6. Stop conditions

Stop and terminate on: reaching $2.50 (ask) or $4.00 (stop); any error I cannot explain; a pod that stops responding;
a failed positive control; a result that looks implausible (for example throughput above a higher concurrency's, or
flat latency under load). I investigate it before reporting it.

## 7. What this can and cannot support

Single run, single GPU, one model, one 40-prompt two-document workload, closed-loop replay, provider-default sampling.
Utilization is the share of the sample period in which at least one kernel was running; it does not mean efficient use.
It cannot support capacity guarantees, multi-GPU claims, SGLang comparisons, or any quality claim.
