# Inference Benchmark Results

Raw per-request data: `data/inference_benchmark.jsonl` (append-only — each run adds new
rows, never overwrites). This file is the human-readable summary; regenerate a section
by running `python eval/inference_benchmark.py --providers <...> --concurrency <...>`
and appending a dated entry below.

---

## 2026-10-02 — Phase 3: FP16 / AWQ / GPTQ-Int4

Completed the October 1 FP16/AWQ artifacts with an October 2 GPTQ run.
[Full report, raw data and logs](../reports/quantization-2026-10-01/README.md).

**Setup:** Qwen2.5-7B-Instruct, vLLM 0.30.0, L40S 48GB, float16 compute,
max_model_len=16384, GPU utilization setting 0.90, 1,400 speed-output-token cap,
eight captured DocChat prompts, fallback disabled, prefix caching on and client
cache busting on. Each serving passed the cache positive control (49.924% off,
0% on); all nine sweep cells measured 0% hits and zero preemptions.

**Provenance limitation:** FP16/AWQ share the original US-MO-1 pod. That pod was
already absent on resume, so GPTQ ran on a replacement in EUR-IS-2. GPU, driver,
CUDA, PyTorch and image digest match, but host/network/location/run time differ.
GPTQ's speed deltas therefore do not isolate quantization. Its backend was
Marlin (`auto_gptq`, `MarlinLinearKernel`). Original AWQ backend and FP16/AWQ
model revisions were not saved; do not infer them from the replacement.

| Format | Concurrency | OK/total | TTFT p50 (s) | Decode tok/s p50 | Aggregate tok/s |
|---|---:|---:|---:|---:|---:|
| FP16 | 1 | 8/8 | 0.982 | 48.5 | 40.6 |
| FP16 | 16 | 16/16 | 7.280 | 17.2 | 142.5 |
| FP16 | 64 | 63/64 | 26.624 | 5.7 | 180.6 |
| AWQ | 1 | 8/8 | 0.878 | 119.9 | 83.5 |
| AWQ | 16 | 16/16 | 6.078 | 29.3 | 227.3 |
| AWQ | 64 | 64/64 | 25.735 | 6.0 | 208.3 |
| GPTQ | 1 | 8/8 | 0.600 | 126.2 | 93.7 |
| GPTQ | 16 | 16/16 | 3.905 | 31.5 | 279.6 |
| GPTQ | 64 | 64/64 | 16.022 | 8.0 | 290.1 |

One FP16 c=64 request disconnected (`RemoteProtocolError`); retained as measured.
AWQ aggregate throughput increased 105.8% / 59.6% / 15.3% at c=1/16/64;
the gain narrowed under load. Single sweeps and varying generated output lengths
limit interpretation. The archived 8192-context attempt is excluded.

**Critic diagnostic (150-token cap, temperature 0, separate from speed):**

| Format | Edge correct | Edge precision / recall / F1 | Edge errors | Corruptions caught/all | Corruption errors |
|---|---:|---|---:|---:|---:|
| FP16 | 1/5 | 0.20 / 1.00 / 0.33 | 0 | 15/15 | 0 |
| AWQ | 3/5 | 0.33 / 1.00 / 0.50 | 0 | 15/15 | 0 |
| GPTQ | 1/5 | 0.33 / 1.00 / 0.50 | 2 | 9/15 | 6 |

GPTQ emitted Markdown-fenced JSON on 8/20 cases, rejected by the current strict
parser. Precision/recall/F1 exclude errors; its printed corruption recall 1.00
must be read alongside **9/15 caught across all cases (60%)**, not as perfect
reliability. FP16/AWQ caught all corruptions but falsely rejected four/two
acceptable edge answers. This is not end-to-end answer quality or critic-loop lift.

**Memory:** FP16 server log reports model-loading allocation 14.29 GiB and KV
capacity 429,552 tokens; GPTQ reports 5.27 GiB and 615,456 tokens on the replacement
host. AWQ allocation log is unavailable. These are not matched peak-VRAM measurements.

**Cost/lifecycle:** per-cell costs use measured batch wall time × $1.09/hour and
exclude setup/idle time; they are not total account charges. Original pod reported
$0.5284245586954057; replacement billing records had not appeared at final check.
Replacement `54caxtprn07c1r` was terminated by 00:39:23 UTC; pod list confirmed
empty. Retained volume `owdj19ss50` is untouched. Phase 4 remains deferred.

13 comparison tests passed. Reports generated with explicit timestamp windows;
no production code or persistent provider configuration changed.

---

## 2026-09-30 — Fourth sweep: cache-busted, /metrics-instrumented — confirms the warning above

**Verdict on the Third sweep's cache-inflation warning: CONFIRMED.** This sweep repeats
the Third sweep's real-prompt workload with client-side cache busting (unique
`request_id` per request, default ON) and live vLLM `/metrics` polling. A positive
control ran first: the same prompt sent twice with busting OFF measured a **49.9%**
prefix-cache hit rate (`vllm:prefix_cache_queries_total` / `vllm:prefix_cache_hits_total`
— both confirmed against this server's live `/metrics`, not guessed); twice with busting
ON measured **0.0%**. Instrumentation proven before trusting the sweep below (see
`eval/positive_control.py`).

**Setup:** `Qwen2.5-7B-Instruct`, bf16, vLLM `v0.30.0`, 1x **L40S 48GB** (Secure Cloud,
`US-TX-3`, $1.09/hr) — **not the same GPU as the Third sweep's A100 80GB**, so absolute
throughput/TTFT numbers below are not directly comparable to it; the *shape* of the
TTFT curve is what's comparable. Network volume `owdj19ss50` was mounted and used
(`HF_HOME=/runpod-volume/huggingface`) — this was the volume's first real use; the
model was not yet cached on it (startup log: "Loading model from scratch", weights
downloaded in 24.2s) but is now cached there for any future pod in `US-TX-3`.

```bash
python eval/inference_benchmark.py --providers local \
  --prompts-file data/bench_prompts.jsonl --concurrency 1,4,16,64,128 \
  --max-tokens 1400 --gpu-cost-per-hr 1.09
```

| Concurrency | n (ok/total) | error% | TTFT p50 | Latency p50 | decode tok/s p50 | agg tok/s | Cost | KV peak | waiting peak | preemptions |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1   | 8/8     | 0%  | 805ms   | 3.37s  | 48.7 | 40.2  | $0.0140 ($7.54/1M tok) | 1.6%  | 0  | 0 |
| 4   | 4/4     | 0%  | 1293ms  | 4.45s  | 32.9 | 73.0  | $0.0030 ($4.15/1M tok) | 5.6%  | 0  | 0 |
| 16  | 16/16   | 0%  | 3980ms  | 12.58s | 22.6 | 175.5 | $0.0058 ($1.72/1M tok) | 21.6% | 12 | 0 |
| 64  | 64/64   | 0%  | 14645ms | 42.45s | 8.3  | 253.7 | $0.0165 ($1.19/1M tok) | 71.9% | 60 | 0 |
| 128 | 115/128 | 10% | 32938ms | 91.02s | 4.3  | 230.3 | $0.0317 ($1.31/1M tok) | 99.4% | 96 | 0 |

Prefix-cache hit rate was **0.0% at every cell** — busting worked in the real sweep, not
just the positive control.

**TTFT now scales with concurrency the way physics predicts** — 805ms → 32.9s, c=1→128
— instead of the Third sweep's suspiciously flat ~0.5-0.85s at every level. With no
cache to hide behind, prefill queueing is visible: at c=128 the KV cache reached 99.4%
full (429,552-token capacity on this GPU) and **13 of 128 requests failed with
client-side `ReadTimeout`/`PoolTimeout`** — genuine queueing/admission pressure near
capacity, not a server error and not a caching artifact. 0 preemptions at every cell:
vLLM handled the pressure entirely via the waiting queue (`num_requests_waiting` peaked
at 96) rather than evicting and re-running already-admitted requests.

**What this changes about the Third sweep's reading:** the "local has no ceiling"
framing there was itself softened by cache inflation — a fresh, uncached A100 run at
real concurrency would very likely show the same TTFT-climbs-with-load pattern seen
here, just starting from a higher KV-capacity ceiling (A100 80GB's ~1M-token KV vs this
L40S's 429k). The corrected framing: self-hosting removes the hosted API's *account-tier
rate limit*, but it does not remove queueing under load — that's a real, physical
constraint of any single GPU, cache-inflation-free or not.

---

## 2026-09-30 — Third sweep: real prompts, and the actual headline finding

⚠️ **Local TTFT at c≥4 in this sweep was inflated by vLLM prefix caching.** Verdict:
**CONFIRMED** (updated 2026-09-30 after the Fourth sweep below) — 8 prompts were
replayed after c=1 warmed the cache, with no cache-busting yet and
`enable_prefix_caching=True` on. The Fourth sweep reran this same real-prompt workload
with cache-busting + `/metrics` instrumentation: prefix-cache hit rate measured 0.0% at
every cell with busting on (vs. a 49.9% hit rate in a same-prompt-twice positive
control), and TTFT went from this entry's suspiciously flat ~0.5-0.85s to a real
805ms→32.9s climb with concurrency. **Do not treat this entry's TTFT/latency numbers as
real measurements of local's capacity under load** — use the Fourth sweep instead.

**Every prior sweep measured the wrong workload.** `eval/cases.py`'s bare queries carry
no retrieval context — 20-90 input tokens. `eval/capture_bench_prompts.py` (this
session) ran the real planner→retriever→synthesizer pipeline against real ingested
Qdrant data and captured what DocChat actually sends: **3752-6801 input tokens**, real
system prompt, real retrieved chunks. This sweep uses those real prompts
(`data/bench_prompts.jsonl`, via `--prompts-file`) with `--max-tokens 1400` (matching
`synthesizer_node`'s real call), instead of the toy queries.

**Setup:** `Qwen2.5-7B-Instruct`, bf16, vLLM `v0.30.0`, 1x A100 SXM 80GB (Secure Cloud,
`US-MD-1`, $1.59/hr, host CUDA 13.0). `--openai-model gpt-4.1`. Groq excluded from this
run (already known broken for this workload — see below). TTFT figures include real
network round-trip time from the operator's client (UK) to the pod's region (`US-MD-1`)
and to OpenAI's edge — not pure server-side time-to-first-token.

```bash
python eval/inference_benchmark.py --providers openai,local \
  --prompts-file data/bench_prompts.jsonl --concurrency 1,4,16,64 \
  --max-tokens 1400 --openai-model gpt-4.1 --gpu-cost-per-hr 1.59
```

| Provider | Concurrency | n (ok/total) | error% | TTFT p50 | Latency p50 | decode tok/s p50 | agg tok/s | Cost |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| openai ⚠️ | 1  | 6/8   | 25% | 948ms | 1.98s | 130.9 | 58.9 | $0.0102 |
| openai ⚠️ | 4  | 0/4   | **100%** | n/a | n/a | n/a | n/a | $0.0000 |
| openai ⚠️ | 16 | 1/16  | **94%**  | n/a | n/a | n/a | n/a | $0.0008 |
| openai ⚠️ | 64 | 1/64  | **98%**  | n/a | n/a | n/a | n/a | $0.0004 |
| **local** | 1  | 8/8   | 0% | 654ms | 2.21s | 95.1 | 70.8   | $0.0104 ($6.2403/1M tok) |
| **local** | 4  | 4/4   | 0% | 827ms | 2.72s | 90.9 | 209.8  | $0.0019 ($2.1056/1M tok) |
| **local** | 16 | 16/16 | 0% | 564ms | 3.29s | 76.7 | 586.4  | $0.0029 ($0.7532/1M tok) |
| **local** | 64 | 64/64 | 0% | 844ms | 5.08s | 46.1 | 1313.9 | $0.0045 ($0.3361/1M tok) |

### The actual headline finding

**On this account's OpenAI tier, the rate limit binds before latency does.** Each real
DocChat request reserves roughly 6.5k tokens (about 5k input plus max_tokens 1400)
against the tokens-per-minute quota, so even 4 concurrent requests returned 429 for
every request, and 2 of 8 failed at concurrency 1. This is an account-tier limit, not a
property of hosted APIs in general: higher tiers, quota increases, or retry-with-backoff
would change it. The contrast with `local` is who owns the ceiling: the rented GPU's
capacity is bounded by its KV cache, which we size and control, rather than by a quota
set by the provider.

Groq was not included; its earlier smoke test used a reasoning model and is
inconclusive.

**`local` has no such ceiling.** 0% error at every concurrency level, all the way to 64
concurrent real-sized requests — the only meaningful constraint is the GPU's own KV
cache capacity, not an account-level API quota. **This is the actual argument for
self-hosting**, more concrete than a throughput or cost number: a rented GPU has no
artificial per-minute request/token ceiling imposed by someone else's shared
infrastructure being shared with every other customer on that API key's tier. Note: on
an A100 80GB the KV cache was never close to full (roughly 57GB free, about 1M tokens of
KV, versus about 450k tokens at c=64), so this sweep did not test the KV limit.

**Per-request decode speed on `local` drops under concurrency this time** (95.1 → 46.1
tok/s, 1→64) — unlike the earlier bare-query sweep where it stayed roughly flat. With
real ~5000-token contexts, more of each batch step is prefill/attention-over-longer-KV,
so per-request generation speed genuinely costs more as concurrent context grows.
Decode is memory-bandwidth bound: each step reads the weights (~15GB) plus every active
request's KV cache. At c=64 with ~5k-token contexts that is about 64 x 5k x 56KB ≈ 18GB
of KV per step, so each step reads ~33GB instead of ~15GB, predicting about a 2.2x
per-request slowdown. Measured: 95.1 → 46.1 tok/s, a 2.06x slowdown. This is the more
honest, more complete picture of continuous batching's tradeoff: aggregate throughput
keeps climbing (70.8 → 1313.9 tok/s) but it's not free per request. Cost per 1M tokens
still improves sharply with load (**$6.24 → $0.34, ~18x, c=1→c=64**) — the same
idle-time-dominated-cost story as before, now measured against a real workload instead
of a toy one.

### Not yet measured

A Groq run with `--groq-model` fixed to a non-reasoning, higher-RPM-tier model (to
separate "Groq's model choice was wrong" from "Groq's real rate limit," same distinction
already made for OpenAI). Quantized (AWQ/GPTQ) throughput/memory tradeoff (Phase 3). A
batching-only proof isolating `local`'s own curve (Phase 4). A second serving engine
(Phase 4).

---

## 2026-09-30 — Second sweep, after fixing three real bugs the first sweep exposed

**Setup:** `Qwen2.5-7B-Instruct`, bf16, vLLM `v0.30.0`, 1x A100 SXM 80GB (Secure Cloud,
`EUR-IS-1`, $1.59/hr, host CUDA 13.0). 8 queries from `eval/cases.py`, `max_tokens=256`,
concurrency 1/4/16/64, `--openai-model gpt-4.1` (see below), `--gpu-cost-per-hr 1.59`.

Three bugs found and fixed since the first sweep, in order of discovery:

1. **OpenAI's default model (`gpt-5.6-luna`) is a reasoning model** — spends its whole
   `max_tokens` budget on hidden reasoning and can return zero visible content. Root
   cause of the first sweep's 50% `output_tokens=0` rows. Fixed by adding
   `--openai-model` to override it for benchmarking only (verified `gpt-4.1`:
   `reasoning_tokens=0` on a direct test call). Production `OPENAI_CHAT_MODEL` is
   untouched.
2. **`_groq_stream`'s `stream_options` request crashed the installed Groq SDK version**
   (`TypeError: AsyncCompletions.create() got an unexpected keyword argument
   'stream_options'`) — 100% error rate for Groq on the first attempt at this sweep.
   Fixed with a catch-and-retry-without-it in `app/services/llm.py`.
3. **`wall_time_s` was derived as `max(total_s)` across requests, which is wrong for
   the concurrency=1 sequential case** added this session (item #5) — sequential
   requests don't overlap, so real wall time is close to their *sum*, not their max.
   This silently inflated every concurrency=1 throughput number in the first version of
   this sweep (e.g. `local` showed 592 tok/s at c=1 before the fix, 89.7 tok/s after —
   a >6x overstatement). Fixed by measuring real wall-clock time with
   `time.monotonic()` around the batch in `_run_provider` and passing it into
   `_summarize` explicitly, instead of inferring it after the fact.

**A fourth issue was found and diagnosed, not yet fixed:** Groq's configured model
(`openai/gpt-oss-120b`) is *also* a reasoning model — same signature as bug #1
(`output_tokens=256` per real usage, `finish_reason=length`, zero visible content),
confirmed from this sweep's raw data. At concurrency 64 a fifth, unrelated thing shows
up: genuine `429 RateLimitError` (Groq's `on_demand` tier RPM/TPM limits), correctly
surfaced as visible errors rather than masked by fallback — this is real Groq
infrastructure behavior, not a bug, and it's exactly what disabling fallback for
benchmark runs (this session's item #2) was for. **Read the `local` and `openai` rows
below; don't trust `groq`'s numbers from this sweep** — a `--groq-model` override,
mirroring `--openai-model`, is the natural next fix.

| Provider | Concurrency | n (ok/total) | error% | empty% | TTFT p50 | Latency p50 | decode tok/s p50 | agg tok/s | Cost |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| groq ⚠️ | 1  | 4/8   | 0%  | 50% | 533ms | 0.80s | 856  | 164.7  | $0.0002 |
| groq ⚠️ | 4  | 2/4   | 0%  | 50% | 382ms | 0.69s | 834  | 497.7  | $0.0001 |
| groq ⚠️ | 16 | 10/16 | 0%  | 38% | 690ms | 0.89s | 1125 | 1328.3 | $0.0005 |
| groq ⚠️ | 64 | 4/64  | 94% | 0%  | 533ms | 0.81s | 814  | 162.2  | $0.0002 |
| openai | 1  | 8/8   | 0% | 0% | 644ms | 3.27s | 94.5  | 67.5   | $0.0189 |
| openai | 4  | 4/4   | 0% | 0% | 654ms | 3.17s | 74.1  | 154.5  | $0.0078 |
| openai | 16 | 16/16 | 0% | 0% | 605ms | 2.89s | 107.7 | 816.1  | $0.0389 |
| openai | 64 | 64/64 | 0% | 0% | 775ms | 2.97s | 108.4 | 2864.8 | $0.1528 |
| **local** | 1  | 8/8   | 0% | 0% | **104ms** | 2.69s | 97.3 | 89.7   | $0.0086 ($4.9252/1M tok) |
| **local** | 4  | 4/4   | 0% | 0% | **473ms** | 2.73s | 97.7 | 313.9  | $0.0014 ($1.4071/1M tok) |
| **local** | 16 | 16/16 | 0% | 0% | **266ms** | 2.96s | 93.7 | 1124.4 | $0.0014 ($0.3928/1M tok) |
| **local** | 64 | 64/64 | 0% | 0% | **346ms** | 3.54s | 79.7 | 3992.0 | $0.0016 ($0.1106/1M tok) |

Cost figures for `groq`/`openai` still use the placeholder rates in
`eval/inference_benchmark.py` — unverified against live pricing, see the module
docstring.

### The actual finding, corrected

`local` again shows lower TTFT than `openai` at every concurrency level, and decode
throughput holding up reasonably (97 → 80 tok/s, 1→64 concurrency) — the continuous
batching story from the first sweep survives the wall-time fix. **What the fix changed
is the cost picture, and it's a better, more honest story than before:** `local`'s
`$/1M output tokens` **improves 44x from c=1 to c=64** ($4.93 → $0.11) — the corrected
number shows self-hosting is *expensive per token when the GPU sits mostly idle* and
*only cheap under real concurrent load*. The pre-fix numbers (flat ~$0.0005 cost at
every concurrency level) hid this completely — utilization-dependent economics is
exactly the kind of thing an inference-engineering role should be able to explain, and
it only shows up because the measurement bug got fixed rather than shipped.

### Not yet measured

Quantized (AWQ/GPTQ) throughput/memory tradeoff (Phase 3), a `--groq-model` override to
get a clean Groq baseline, a batching-only proof isolating `local`'s curve without a
hosted-provider distraction (Phase 4), a second serving engine (Phase 4).

---

## 2026-09-30 — Phase 2 first real sweep

**Setup:** `Qwen2.5-7B-Instruct`, bf16, vLLM `v0.30.0`, 1x L40S (Secure Cloud,
`US-TX-4`, $1.09/hr, host CUDA 13.0). 8 queries from `eval/cases.py`, `max_tokens=128`,
concurrency levels 1/4/16/64. Command:

```bash
python eval/inference_benchmark.py --providers groq,openai,local --concurrency 1,4,16,64 --max-tokens 128
```

### ⚠️ Groq numbers in this run are unreliable — read the local/openai rows, not groq

61% of Groq requests in this sweep (52/85) failed and silently fell back to OpenAI
(`groq_stream_failed_retrying_openai`, logged that many times). `GROQ_FALLBACK_CHAT_MODEL`
is unset, so any transient Groq error — most likely real rate-limiting at concurrency
16/64 — skips straight to the OpenAI fallback with zero same-provider retry. The `groq`
row below is therefore a mix of real Groq responses and silently-substituted OpenAI
ones, not a clean Groq measurement. Before trusting a Groq number, either set
`GROQ_FALLBACK_CHAT_MODEL` to a second Groq model to distinguish "Groq is down" from
"Groq is rate-limited," or re-run with `--providers groq` alone at low concurrency.

| Provider | Concurrency | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | tok/s (avg) | Cost/level* |
|---|---:|---:|---:|---:|---:|---:|---:|
| groq ⚠️ | 1  | 794ms  | 794ms  | 0.79s | 0.79s | 0.0†  | $0.0000 |
| groq ⚠️ | 4  | 451ms  | 546ms  | 0.45s | 0.60s | 10.8  | $0.0000 |
| groq ⚠️ | 16 | 646ms  | 1315ms | 0.65s | 1.37s | 9.0   | $0.0000 |
| groq ⚠️ | 64 | 7408ms | 9366ms | 7.61s | 9.37s | 3.7   | $0.0002 |
| openai  | 1  | 2148ms | 2148ms | 2.15s | 2.15s | 0.0†  | $0.0000 |
| openai  | 4  | 1960ms | 5217ms | 2.20s | 5.22s | 10.6  | $0.0009 |
| openai  | 16 | 2171ms | 3015ms | 2.52s | 3.12s | 10.5  | $0.0040 |
| openai  | 64 | 2173ms | 3267ms | 2.47s | 3.52s | 9.7   | $0.0146 |
| **local** | 1  | **862ms** | 862ms  | 3.43s | 3.43s | **37.3** | $0.0005 |
| **local** | 4  | **446ms** | 723ms  | 3.10s | 3.37s | **40.4** | $0.0005 |
| **local** | 16 | **514ms** | 908ms  | 3.19s | 3.57s | **39.2** | $0.0005 |
| **local** | 64 | **571ms** | 635ms  | 3.85s | 3.89s | **33.6** | $0.0005 |

\* Cost uses the **placeholder rates** in `eval/inference_benchmark.py`
(`_HOSTED_COST_PER_1M_OUTPUT_TOKENS`, `_LOCAL_GPU_COST_PER_HR`) — not fetched live, not
fully verified against each provider's current pricing page. Verify before quoting
externally.

† `n=1` at concurrency 1 for both groq and openai returned zero content chunks for
that single request — the harness correctly reports 0 tok/s (not a fabricated number)
rather than papering over a degenerate single-sample result; treat concurrency=1 as
unmeasured for those two rows.

### The actual finding

**`local` (self-hosted vLLM on a rented L40S) held per-request throughput roughly flat
(37.3 → 33.6 tok/s) as concurrency went 1 → 64** — an 11% drop while serving 64x the
concurrent load. That's continuous batching visibly doing its job: vLLM is absorbing a
64x increase in concurrent requests without a proportional per-request slowdown, which
is the mechanism this whole showcase exists to demonstrate. TTFT on `local` was also
faster than both hosted providers at every concurrency level (446–862ms vs. 1960–7408ms
groq/openai). Cost on `local` stayed flat per sweep (GPU-time-metered, not
token-metered) rather than scaling with request volume the way the hosted providers'
cost did.

**Caveat on the win:** this compares a dedicated GPU serving one small model against
shared hosted infrastructure serving many customers — it is not a fair "which is
cheaper for me" comparison without factoring idle GPU time between bursts, which hosted
APIs don't charge for and a rented pod does. The throughput/TTFT comparison is real; the
cost comparison needs the idle-time caveat spelled out if it's ever quoted externally.

**Not yet measured:** quantized (AWQ/GPTQ) throughput/memory tradeoff (Phase 3), a
clean batching-only proof isolating `local`'s own 1→64 curve without a hosted-provider
distraction (Phase 4), and a second serving engine for comparison (Phase 4).
