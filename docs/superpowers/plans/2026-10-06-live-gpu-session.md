# Live GPU session: run plan (2026-10-06, revised after Phase 1) - AWAITING EXPLICIT GO

Nothing here has been run. No pod is rented and nothing is spent until you say go. Estimates come from the earlier FP16
held-out run (`reports/heldout-serving-evaluation-2026-10-05.md`), `reports/quantization-2026-10-01/setup.json` and the live
quote below; they are not predictions of what this pod will do, and no figure here is a measurement of the new run.
Pre-flight state: Phase 1 is committed locally as `f6efb01` (not pushed); `ruff check .` clean, 627 offline tests passed.

## 1. Decisions (all yours, all recorded)

1. **100 requests per cell**, 2 repeats, concurrency 1, 4, 16, 32, 64, `--min-samples 100` (p99 is therefore reportable but
   weak: with 100 samples it is the second-largest value).
2. **The fault test is a failure-behaviour test.** It measures errors, health and recovery; it adds no hosted fallback and
   does not exercise one (none exists for provider `local`). A local-to-hosted fallback is listed for the Phase 3 report as a
   separate production-behaviour decision.
3. **Cost cap:** hard $4.00, stop-and-ask at $2.50. Price re-quoted live (section 2) before anything is rented.
4. **Order:** core session first (clean sweep, then the failure-behaviour test), all artifacts saved locally. The hard-kill
   restart and the extras (prefix-cache on/off, serial vs concurrent) run **only if spend is under $2.50 after the core session**;
   otherwise they are skipped and the report says so.
5. **Network volume `owdj19ss50`** (name `docchat-vllm-models`, 50 GB, US-TX-3): the provider API returns only its metadata
   (name, size, type, data center), not its contents. Listing the contents would require attaching it to a pod, which costs
   money and is not possible from EUR-IS-2. So I cannot yet say whether anything on it is unrecoverable; it will not be
   deleted, and I will ask again before any deletion.

## 2. Live quote (read from the provider just now, 2026-10-06)

| Item | Value |
|---|---|
| Provider / GPU | RunPod, **NVIDIA L40S 48 GB, Secure cloud** (same class as the earlier runs) |
| Price | **$1.09/hour** Secure (community is $0.79 but is a different, shared class; not used, for comparability) |
| Availability | **LOW**, only data center **EUR-IS-2** (the data center used for the earlier GPTQ run); CUDA 13.0 available, which the pinned image needs |
| Current account state | 0 pods; 1 network volume (above) |
| Image | `vllm/vllm-openai:v0.30.0`, digest recorded earlier as `sha256:8a69ffad015f138d7170c4ddc429e230a3bc1c1719f67e14324749df200a4b90` (checked against the live pod before use) |

At $1.09/hour a minute of pod time is about $0.0182. I track estimated spend as elapsed pod minutes at that rate (from the
pod's creation time) and read real billing back afterwards, flagging that billing lags.

| Step | Basis | Minutes | Cumulative |
|---|---|---|---|
| Provision, image pull, 15 GB model download, vLLM start | unmeasured (the earlier setup note says a couple of minutes on first launch) | 20 | 20 |
| Health checks, app smoke question, positive control, clock offset, sampler start | manual | 20 | 40 |
| Clean sweep, 100 requests/cell, 2 repeats | sum of 100/RPS from the earlier FP16 run (0.271, 0.912, 2.029, 2.083, 2.064 RPS at c=1,4,16,32,64) is about 624 s per repeat, plus warmups and drains | 23 | 63 |
| Failure-behaviour test (SIGSTOP/SIGCONT), 240 s load plus setup and checks | duration set by the test | 8 | 71 |
| Stop sampler, copy back, dry-check, attach to both runs | manual | 7 | 78 |
| **Core session** | | **about 78 min = about $1.42** (allow up to about $1.9 for slower startup) | |
| Optional: hard kill and restart, recovery labelled "includes model load" | restart reloads the model; load time unmeasured | about 12 | 90 |
| Optional: prefix-cache off restart plus a sweep subset | | about 20 | 110 |
| Optional: serial vs concurrent (legacy harness, N=4 and 16) | | about 10 | 120 |
| **All-in** | | **about 120 min = about $2.18** (with a 25% buffer about $2.7) | |

Checkpoints: **$2.50 is about 138 minutes of pod time; I stop and ask there.** **$4.00 is about 220 minutes.** I will terminate
by minute 200 (about $3.63) at the latest, whatever is unfinished. Optional steps start only if estimated spend is under $2.50.

## 3. The fault: exactly what will run

The fault is a **stall of the vLLM server process**: `SIGSTOP`, then `SIGCONT`, on the `vllm serve` process whose PID I record
when I start it (`/tmp/vllm.pid`). Only that process is signalled. What other processes vLLM has under it, and how they
behave while it is stopped, I will observe with `ps` on the pod and report; I am not assuming it.

vLLM is started on the pod (pod-side, once) with its PID saved:

```
nohup vllm serve Qwen/Qwen2.5-7B-Instruct --served-model-name Qwen2.5-7B-Instruct --dtype float16 \
  --max-model-len 16384 --gpu-memory-utilization 0.90 --port 8000 --api-key "$VLLM_API_KEY" \
  > /tmp/vllm.log 2>&1 & echo $! > /tmp/vllm.pid
```

The two commands the test runs (they execute on this machine, without a shell, and reach the pod over SSH; `<KEYFILE>`,
`<SSH_PORT>` and `<POD_IP>` are the pod's own SSH details, which exist only once it is provisioned; nothing else is a placeholder):

```
inject : ssh -i <KEYFILE> -p <SSH_PORT> -o BatchMode=yes -o ConnectTimeout=10 root@<POD_IP> "kill -STOP $(cat /tmp/vllm.pid)"
restore: ssh -i <KEYFILE> -p <SSH_PORT> -o BatchMode=yes -o ConnectTimeout=10 root@<POD_IP> "kill -CONT $(cat /tmp/vllm.pid)"
```

The remote command is passed to `ssh` as one literal argument, so `$(cat /tmp/vllm.pid)` is expanded by the pod's shell, not
locally (checked offline with a stand-in `ssh`: both commands exit 0 and the artifacts contain neither the host, the key path nor
the command text, only SHA-256 hashes and exit codes). The test itself:

```
LOCAL_BASE_URL=http://127.0.0.1:18000/v1 LOCAL_CHAT_MODEL=Qwen2.5-7B-Instruct LOCAL_API_KEY=$VLLM_API_KEY \
venv/bin/python -m eval.inference_benchmark failure-behaviour --target replay --provider local \
  --workloads data/heldout-quality-workload.json --deployment-manifest $RUN/deployment.json \
  --concurrency 16 --duration 240 --fault-at 60 --fault-duration 60 --timeout 30 --cache-mode bust \
  --inject-cmd '<inject command above>' --restore-cmd '<restore command above>' \
  --health-url http://127.0.0.1:8081/api/v1/health/serving --health-interval 1.0 \
  --yes-run-fault-commands --out-dir $RUN/failure-behaviour
```

60 s of baseline, a 60 s stall, then 120 s to observe recovery. The inject command's own latency (an SSH round trip) is
measured and kept out of the clean `during` window. **The GPU sampler keeps running through this test** (it is the same
continuous file as the clean sweep; the two runs are attached separately by their recorded windows).

Optional hard kill and restart (only if spend is under $2.50 after the core session): `kill -9 $(cat /tmp/vllm.pid)` over SSH
as the inject, and a restart (the vLLM command above, rewriting `/tmp/vllm.pid`) as the restore. Its recovery time includes
the model load and is labelled "includes model load" everywhere it appears; it is not comparable with the stall's recovery time.

## 4. Pre-flight (done, free, local)

`ruff check .` clean and 627 offline tests passed; the held-out workload fingerprint verified
(`65e6df6515525e1ea78ab54631400f9702b0b7bc4ccc89f2c2846b9c8a6c06a9`); Phase 1 committed locally as `f6efb01`.
Still needed on the day: the local Qdrant and PostgreSQL stack up with the existing two-document corpus, and `export RUN=reports/gpu-live-<date>`.

## 5. Session steps (each paid step waits for your "go")

1. **Provision** the L40S (EUR-IS-2 if stock allows; LOW availability may mean it is not available when I try, and I would stop and tell you rather than substitute another GPU). Record the start time; set the hard stop at minute 200.
2. **Observe the manifest from the pod, never guess:** `nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv`, CUDA from the `nvidia-smi` header, `pip show vllm torch`, the image digest from the provider, model and tokenizer commits from the Hugging Face cache, the chat-template hash. Any field I cannot observe stays null. Fill `$RUN/deployment.json` from `deploy/vllm-manifest.example.json`.
3. **Start vLLM** (command above) and open `ssh -N -L 18000:127.0.0.1:8000 ...`; record from the log whether prefix caching is on.
4. **Checks:** `/v1/models`; start the app locally with `LLM_PROVIDER=local` and the `LOCAL_*` values as process environment (no `.env` edit); `GET /api/v1/health/serving`; one real document question. Save the outputs. Also confirm cancellation behaviour before load.
5. **Positive control:** `python eval/positive_control.py --prompts-file data/bench_prompts.jsonl` (legacy harness; exit 1 means stop).
6. **GPU sampler on the pod:** copy `eval/gpu_sampler.py`; `nohup python3 /tmp/gpu_sampler.py /tmp/gpu-samples.jsonl --interval 1.0 > /tmp/gpu-sampler.log 2>&1 & echo $! > /tmp/gpu-sampler.pid`; the first line must show a real backend, not `unavailable`. It keeps running until step 10.
7. **Clock offset**, three trials (client clock, pod clock over SSH, client clock again; midpoint); `clock_offset_s = gpu_host_clock - benchmark_client_clock`; raw readings to `$RUN/clock-offset.json`; trials must agree to a fraction of a second.
8. **Clean sweep** (nothing else running):
   ```
   LOCAL_BASE_URL=http://127.0.0.1:18000/v1 LOCAL_CHAT_MODEL=Qwen2.5-7B-Instruct LOCAL_API_KEY=$VLLM_API_KEY \
   venv/bin/python -m eval.inference_benchmark sustained --target replay --provider local \
     --workloads data/heldout-quality-workload.json --deployment-manifest $RUN/deployment.json \
     --concurrency 1,4,16,32,64 --repeats 2 --warmup 2 --duration 600 --requests 100 --timeout 120 \
     --min-samples 100 --cache-mode bust --engine vllm --metrics-url http://127.0.0.1:18000/metrics --out-dir $RUN/sweep
   ```
   Snapshot the sampler file back after each repeat (the pod can disappear).
9. **Failure-behaviour test** (section 3), immediately after the sweep, sampler still running.
10. **Stop the sampler** (`kill -TERM $(cat /tmp/gpu-sampler.pid)`, last line must be `sampler_stop`), copy it back, then `python -m eval.gpu_utilization attach $RUN/sweep SAMPLES --clock-offset-s S --dry-check`, fix anything, attach for real, and attach `$RUN/failure-behaviour` too.
11. **Checkpoint:** compute estimated spend. Under $2.50: continue to the optional steps. Otherwise skip them and say so.
12. **Optional, in this order:** hard kill and restart (labelled "includes model load"); prefix-cache on vs off; serial vs concurrent.
13. **Terminate:** copy every artifact locally first; delete the pod; list pods and volumes to confirm nothing is running; read billing back.

## 6. Artifacts (under `reports/`, no credentials, raw logs not staged)

`gpu-live-<date>/deployment.json`, `clock-offset.json`, `sweep/` and `failure-behaviour/` (manifest, events, `gpu-utilization.json`),
`gpu-samples.jsonl`, health and smoke outputs, `billing-readback.json`, and the report `reports/gpu-live-<date>.md`.

## 7. Stop conditions

Stop and terminate on: $2.50 reached (ask) or minute 200 (stop); any error I cannot explain; a pod that stops responding; a failed
positive control; unavailable stock; or a result that looks implausible (for example throughput above a higher concurrency's, or
flat latency under load). I investigate before reporting it.

## 8. What this can and cannot support

Single run, single GPU, one model, one 40-prompt two-document workload, closed-loop replay, provider-default sampling. GPU
utilization is the share of the sample period in which at least one kernel was running; it does not mean the GPU is fully used.
The failure-behaviour test is one fault on one deployment, not an availability or reliability claim. It cannot support capacity
guarantees, multi-GPU claims, SGLang comparisons, or any quality claim.
