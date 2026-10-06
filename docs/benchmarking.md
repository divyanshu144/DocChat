# Sustained DocChat workloads (schema v2)

Phase 2 extends `python -m eval.inference_benchmark` with a `sustained` subcommand.
Historical invocations, JSONL files and burst statistics remain unchanged. New files
are separate, versioned artifacts; do not append them to historical JSONL or compare
burst throughput directly to sustained throughput.

## Workload preparation

Start with `data/workloads.example.json`. It is an authoring template, **not an
executed benchmark or a labeled dataset**. Replace placeholder source/chunk IDs,
questions and the zero corpus hash using a fixed, redistributable corpus. Use the
same normalized corpus fingerprint convention as `eval/retrieval_eval.py` (sorted
point IDs and chunk text). The runner records the supplied fingerprint but does not
independently verify the live Qdrant index. Avoid concurrent ingestion while measuring.

Cases have unique IDs, a category, query, source filters, output token budget and
optional evidence labels. Categories: document_qa, summarisation, long_context,
multi_document, negative_control. Labels categorize intent; they do not prove prompt
length or evidence coverage. The existing 12,000-character context cap still applies.
Summaries cover retrieved context, not necessarily a complete document. Check actual
provider input-token counts before claiming long-context performance. Add more cases
and distractors before making externally meaningful claims.

Offline schema check, with no service calls or output directory creation:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target api --workloads data/workloads.example.json \
  --out-dir /tmp/not-created --validate-only
```

For prompt replay, capture each real planner/retriever/synthesizer prompt:

```bash
venv/bin/python -m eval.capture_bench_prompts \
  --workloads /path/to/authored-workloads.json \
  --out /path/to/captured-workloads.json
```

**Capture calls the configured planner model** and reads the real index. It can
incur API cost. It does not generate synthesis answers. No-context or failed cases
abort capture rather than silently changing the dataset. Negative controls that
produce no synthesis prompt belong in API mode. Capture refuses existing outputs.
Captured manifests contain document text; keep private corpora out of source control.
The legacy no-argument capture command retains its original JSONL behavior.

## Prompt replay

Prepare the local serving config and deployment manifest described in
`serving-observability.md` and `vllm_setup.md`. Then, only when a server is ready:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target replay --provider local \
  --workloads /path/to/captured-workloads.json \
  --deployment-manifest /path/to/actual-deployment.json \
  --concurrency 1,4,16,32,64 --duration 60 --requests 1000 \
  --repeats 3 --warmup 4 --timeout 120 --min-samples 100 \
  --cache-mode bust --latency-slo 30 \
  --metrics-url http://127.0.0.1:18000/metrics \
  --out-dir reports/my-new-sustained-run
```

Each cell maintains the requested in-flight concurrency until its duration or request
limit, then drains outstanding requests within their deadlines. Levels and repeats
run sequentially. Warmup requests are written but excluded from measurement. Record
cold start separately. `--cache-mode bust` prepends a unique prefix as the legacy
harness does; it changes the prompt. `reuse` preserves prompts. Measure both separately
and verify actual prefix-cache behavior from server samples.

Replay disables both cross-provider and Groq model fallback for the duration and
restores settings/clients afterward. It uses provider sampling defaults; repeats
therefore assess variation, not bitwise deterministic generation. Do not run this
standalone CLI inside an application worker with shared settings.

For arrival-rate testing, specify rates and an in-flight safety limit:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target replay --provider local --workloads /path/to/captured-workloads.json \
  --concurrency 64 --arrival-rates 0.5,1,2,4 \
  --duration 120 --requests 2000 --repeats 3 --out-dir reports/my-rate-run
```

Arrivals use a fixed cadence, not a Poisson distribution. Capacity-exceeding arrivals
are counted as **load-generator rejections**, never an invisible queue. If the event
loop misses an arrival by an entire interval it records `missed_schedule` instead
of catching up with a burst. Inspect rejection and scheduling-lag records; offered
rate is not accepted throughput. Run the load generator near the serving host for
engine comparisons and record network/location differences separately.

## End-to-end API mode

Use an isolated benchmark account/database/index. Every request creates a new
conversation and persists messages through the normal application. Use a token file
containing a current access token; the CLI does not sign up, refresh or bypass auth.
Ensure token lifetime exceeds the sweep. Restrict source IDs to the benchmark corpus.

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target api --api-base-url http://127.0.0.1:8081/api/v1/ \
  --auth-token-file /private/path/benchmark-access-token \
  --workloads /path/to/authored-workloads.json \
  --concurrency 1,4,16,32,64 --duration 60 --requests 1000 \
  --repeats 3 --out-dir reports/my-api-run
```

Default chat limits are 30 requests/minute/IP. Set an explicit higher limit only in
the isolated benchmark deployment; the client never bypasses production limits.
HTTP 429/401 and SSE error events are failures. Configure and record server fallback
policy yourself: API mode cannot change remote configuration. Output limits remain
server-defined (the manifest's per-case cap applies only to replay).

API timing includes planning, retrieval, verification and persistence. Status events
are not first answer. Success requires answer content and the normal done marker.
A 200 with an error event or incomplete stream fails. API SSE carries no model-token
usage or model TTFT, so those fields stay null; correlate request IDs with app traces
and Prometheus. API mode preserves queries and only supports cache reuse.

## Artifacts and interpretation

Each new output directory contains `manifest.json` and flushed `events.jsonl`:

- Manifest: run ID, corpus/workload hashes, prompt hashes, source commit and Python
  source hash (including uncommitted Python changes), load settings and allowlisted
  deployment fields. No authorization values or token-file paths are copied.
- Request: cell/request/case/category IDs, warmup/measurement phase, status, timing,
  provider token usage and finish reason where available. No prompts or answers.
- Cell summary: errors, timeouts, cancellations, generator rejections, empty outputs,
  truncations, success p50/p95, model TTFT/first answer p95, requests/sec, tokens/sec,
  optional latency-SLO goodput, and category summaries.
  Each cell also records a wall-clock `window` (start, end, clock source) so external
  samples such as GPU utilization can be aligned to its measured span.
  Cell summaries also carry `latency_p99_s`, `ttft_p99_s` and `p99_min_samples` (see "p99" below).
- Run summary: mean/min/max/sample standard deviation across repeats for each load.
  This is observed run-to-run variation, not a confidence interval.
- Optional engine samples preserve labels/histogram buckets and per-series counter
  deltas; each cell's `engine_counter_changes` event also carries a `prefix_cache` hit-rate
  summary (see "Prefix caching on versus off"). Missing series and observed resets yield unknown deltas. Sampling can miss
  resets between polls. Shared server traffic cannot be attributed to this run.
- Final outcome distinguishes completed, failed and cancelled sweeps. Interrupted
  cells persist partial rows and a summary where graceful cancellation is possible.
  Abrupt process termination may leave no final summary; never call it complete.

Percentiles describe successful requests only; always read error rates beside them.
By default p95 requires at least 100 successes **per reported group**; p99 needs at least
`max(--min-samples, 100)` successes and is null below that (see "p99"). A category
may lack enough samples even when the overall cell has enough. P50 from smaller
samples remains descriptive. No p99 or confidence claim is made.

Token throughput is null unless every successful request reported output usage;
stream chunk counts are never treated as tokens. Decode speed is explicitly a client
estimate. Throughput denominator includes the final drain, and category rates are
contributions to the mixed workload over the same wall time. A request-limited run
may finish before the configured duration; `stop_reason` records why it stopped.
This alone is not an SLO-certified sustainable-capacity result.

Total request latency starts at scheduled arrival; `service_s` starts at dispatch.
Model TTFT and API first-answer timings start at dispatch. Scheduling lag is separate,
not GPU queue time. For latency-SLO goodput, failures and rejected requests contribute
zero. Truncated successful responses remain in throughput but are counted separately;
answer completeness/groundedness is Phase 3 work.

For schema-v2 speed comparisons:

```bash
venv/bin/python -m eval.quantization_compare \
  --baseline-run reports/fp16-sustained --variant-run reports/awq-sustained
```

The tool refuses incomplete runs, mismatched IDs/workloads/load settings/source
snapshots, and missing or incompatible core deployment metadata. It does not verify
physical host identity or isolate quantization causally. API comparisons additionally
require matching declared `application_revision` and `application_config_sha256`
in the deployment manifests: the runner source hash is not the remote server hash. Legacy timestamp comparisons
still work. Neither mode establishes answer quality.

## p99 latency and p99 TTFT

Cell summaries report `latency_p99_s` and `ttft_p99_s` (nearest rank, like p95). They are
**null unless the cell has at least `max(--min-samples, 100)` successes**: with fewer, a p99
is just the maximum. With exactly 100 successes it is the second-largest value, so treat it as
descriptive, not as a tail guarantee. `p99_min_samples` records the floor that applied. The
earlier 64-request cells therefore report no p99; use `--requests 100` or more per cell.

`eval.capacity_plan` reports, per level, `latency_p99_s_each`, `latency_p99_s_worst`,
`ttft_p99_s_worst` and `p99_repeats_available`. The worst-repeat value is null unless every
repeat had a p99. p99 is never used to decide whether a level meets the SLO. Run-to-run
`statistics` do not include p99, so comparing a new run with an older one is unaffected.

## Cost per request and per 1K output tokens

`eval.capacity_plan` adds `cost_per_request_usd` and `cost_per_1k_output_tokens_usd` next to the
existing per-million figures, from `hourly_cost_usd` in the deployment manifest (or
`--hourly-cost`). Request cost uses the conservative requests per second of the selected level;
token cost uses the mean token rate and is null when token usage is unknown. If no cost is known the
cost fields are omitted. The basis is GPU rental only, assuming linear scaling: storage, egress
and idle time are excluded (`assumptions.cost_basis` says so in the output).

## Engine selection (`--engine`)

The replay request path is an OpenAI-compatible `/v1/chat/completions` stream, so the same
workload and prompts can be pointed at any server that speaks it by changing the `LOCAL_*`
endpoint settings. Only metrics parsing is engine-specific. `--engine {vllm,sglang}` (default
`vllm`) selects the metric-name prefix and is recorded in the manifest as `engine_family` with an
`engine_metrics_status` string.

- **vllm:** series names were observed on vLLM v0.30.0 by the earlier harness; other versions are
  not verified.
- **sglang:** **unverified.** The `sglang:` prefix and series names have not been observed against a
  live SGLang server. The harness keeps whatever `sglang:` series it finds, derives no cache hit
  rate from them (the summary says why), and nothing here should be read as SGLang support.

Cross-engine comparison still refuses by design (the comparison requires matching engine and image
digest); relaxing that is a separate decision.

## Prefix caching on versus off

Each cell's `engine_counter_changes` event carries a `prefix_cache` summary: token queries, hits and
hit rate from the engine's prefix-cache counters, or `unavailable` with a reason when the counters
are missing, a counter reset, or there were no queries. Compare two runs with caching on (baseline)
and off (variant):

```bash
venv/bin/python -m eval.quantization_compare --prefix-cache-comparison \
  --baseline-run reports/<run-caching-on> --variant-run reports/<run-caching-off>
```

It first applies every existing comparability check, then also requires the same non-null
`model_repository`, the same `weight_quantization`, and explicit `prefix_caching: true` (baseline)
versus `false` (variant) in the deployment manifests. The output adds a per-cell hit-rate column for
each arm, pooled as total hits over total queries across repeats. `design.cache_mode` matters: with
`bust` every request has a unique prefix, so both arms should show about 0% and the result is a
**control**, not a measurement of the caching effect; use `reuse` to see reuse. `warnings` flag a
caching-off arm that shows hits, a reuse-mode caching-on arm with none, and hits despite busting.
One run per arm, no causal claim, and the same physical host is not verified.

## Fixed-batch serial versus concurrent

The legacy burst harness runs a fixed batch of N requests either strictly one at a time
(`--serial`) or all at once, and tags each row with `mode`. Compare the two for each shared N:

```bash
venv/bin/python -m eval.batching_compare --jsonl data/inference_benchmark.jsonl \
  --since <T0> --until <T1> --provider local
```

For each N above 1 present in both modes it reports the wall-time speedup (serial wall divided by
concurrent wall) and the throughput ratio. A pair is comparable only with equal request counts and
no failures on either side; otherwise the ratios are null with a reason. If total output length
differs by more than 10% a caveat says the ratio mixes batching with output length. Duplicate rows
for the same N and mode are refused as ambiguous; narrow the time window. This is a ratio of two
single runs and says nothing about per-request latency.

## Failure-behaviour test

A separate mode that measures what happens while a fault is injected into the model server and then
restored. It is a **failure-behaviour test**: for `LLM_PROVIDER=local` the documented behaviour is that
there is no hosted fallback, so failures surface to the caller. The test confirms that and does not
add or exercise any fallback.

```bash
venv/bin/python -m eval.inference_benchmark failure-behaviour \
  --target replay --provider local --workloads /path/to/captured-workloads.json \
  --concurrency 16 --duration 180 --fault-at 30 --fault-duration 60 \
  --inject-cmd "<command that injects the fault>" --restore-cmd "<command that undoes it>" \
  --health-url http://127.0.0.1:8081/api/v1/health/serving --yes-run-fault-commands \
  --out-dir reports/my-failure-behaviour-run
```

Safety: the inject and restore commands are run **without a shell** (shell-quote any path that contains
a space) and only with `--yes-run-fault-commands`; they are recorded only as SHA-256 hashes and exit
codes, never as text. After any attempted inject the restore runs exactly once, even if the run is
cancelled or fails, so a faulted server is not left faulted. The fault must end before the load does.

What it records, all from one fixed-concurrency closed loop:

- **Windows.** `before` (requests that *completed* before the fault), `in_flight_at_injection`
  (sent before the fault, still running when it hit; these are casualties of the fault, kept out of
  the baseline), `during` (sent while the fault was active) and `after` (sent after the restore), each
  with an error rate and status counts. A request sent in the last moments before the restore can
  finish after it and succeed; that boundary effect is real and is not hidden: the `during` entry reports
  `of_which_finished_after_restore` (how many of its requests only finished after the restore, and how many of
  those succeeded) so the headline rate is not misread. With a stall fault and a request timeout, whether the
  timeout cycle lines up with the restore changes how many requests land there, so read those counts, not just the rate.
- **Time to first error:** the first failed completion after the injection. Null, with a note, if
  none occurred (which can mean the fault did not take effect).
- **Time to recovery:** from the restore being issued to the first request *sent after* the restore
  that succeeds. A request sent during the fault that completes after the restore does not count.
  Also reported from when the restore command returned.
- **`/health/serving` against its documented behaviour** (200 when the configured model is listed,
  503 when the probe fails): healthy before the fault, unhealthy during it, healthy after the restore,
  and the delays. With no `--health-url`, nothing is claimed.
- **Hosted fallback:** the documented behaviour (none for provider `local`) and whether any request
  *sent after the inject command returned* succeeded *before the restore*. Zero is "no fallback
  observed". Any such request is flagged `UNEXPECTED`: either the fault did not take effect or
  something other than the model server answered.

The output directory has no `run_summary`, so the comparison and capacity tools refuse it. Run it
separately from the clean sweep so clean numbers are not polluted; a GPU sampler can run alongside and
be attached with `eval.gpu_utilization attach` (the load cell records a wall-clock window). One fault on
one deployment is not an availability or reliability claim.

## GPU utilization (optional, separate signal)

vLLM's `/metrics` endpoint does **not** expose GPU compute utilization, and the benchmark client may run on a
different machine from the GPU. GPU utilization therefore comes from a small standalone sampler that runs **on the
GPU host**, and is attached to a finished run afterwards. **Status: built and tested offline with fixture files only.
No live measurement has been taken yet**; the first real run still needs an approved GPU endpoint.

### What it means (and does not)

The number is the share of the sample period in which at least one kernel was running, so 100 percent does not mean
the GPU is fully used. It shows the GPU was busy, not that it was efficient: a memory-bound decode loop can read high
while delivering little throughput, and a low reading does not show where a limit was. Read it beside KV-cache usage
and queue depth; it replaces neither (see the reading table in [serving observability](serving-observability.md)). It
is not memory bandwidth, achieved FLOPs or per-request GPU time.

### Pieces

- `eval/gpu_sampler.py`: standard library only (optional `pynvml`), imports nothing from this repository, so copy the
  single file to the pod. Backends in order: `pynvml`, then the `nvidia-smi` CSV query; if neither works it writes an
  explicit "unavailable" header, prints a message and exits with status 3 (no invented samples). Output is JSONL and is
  never overwritten (status 4 if the file exists). Fields: UTC host-clock timestamp, GPU index, `util_pct`,
  `mem_used_mib`, `mem_total_mib`, `power_w` (null when the GPU does not report it). It records no prompts, answers,
  process lists, names or hostname.
- `eval/gpu_utilization.py attach`: aligns the samples to each **measurement** cell's recorded window (warmup cells
  are separate and skipped) and writes `RUN_DIR/gpu-utilization.json`. It never modifies `manifest.json` or
  `events.jsonl`, and it refuses to overwrite an earlier attachment. Schema stays v2; every addition is optional, so
  older artifacts still load and the capacity tool is unaffected.

### Runbook

1. **Copy the sampler to the pod** (one file; the repo is not needed):
   `scp eval/gpu_sampler.py <pod>:/tmp/` (or your provider's file transfer).
2. **Start it before the sweep**, on the pod:
   `nohup python3 /tmp/gpu_sampler.py /tmp/gpu-samples-<run-label>.jsonl --interval 1.0 > /tmp/gpu-sampler.log 2>&1 &`
   then check the first line says a real backend, not `unavailable`: `head -1 /tmp/gpu-samples-<run-label>.jsonl`.
3. **Run the sweep** from the benchmark client as usual (the `sustained` command above), keeping the sampler running
   for the whole sweep.
4. **Stop the sampler** on the pod: `kill -TERM <pid>` (it writes a final `sampler_stop` record). Confirm the last line
   is `sampler_stop`.
5. **Copy the file back**: `scp <pod>:/tmp/gpu-samples-<run-label>.jsonl .`
6. **Measure the clock offset** (do this; it is the step most likely to be skipped). The sign convention is defined once,
   in `eval/gpu_utilization.py`, and quoted here verbatim:

   > clock_offset_s = gpu_host_clock - benchmark_client_clock; a sample's time on the client clock is its timestamp minus the offset

   To measure it, read the epoch time on both machines at the same moment and subtract:
   `date -u +%s.%N` on the GPU host, and `date -u +%s.%N` on the benchmark client. The two reads are never exactly
   simultaneous, so read the client clock immediately before and immediately after the remote read and use the midpoint
   of the two client readings; the error is about half the round trip. Repeat three times and check the results agree
   to within a fraction of a second. Then pass the result: `--clock-offset-s <GPU host minus client>`.

   *Worked example. These numbers are made up to illustrate the sign; they are not a measurement.* The GPU host prints
   `1760000042.50` while the client's midpoint reading is `1760000012.20`. The offset is
   `1760000042.50 - 1760000012.20 = +30.30`, so you pass `--clock-offset-s 30.30` (the GPU host runs ahead). If the GPU
   host had printed `1759999990.00` instead, the offset would be `-22.20` (the GPU host runs behind). Getting the sign
   backwards doubles the error instead of removing it, and the cell usually comes back `unavailable`.

   If you omit the flag the artifact records `assumed_zero_not_measured`, and the attach step prints a warning when any
   cell's measured window is under 30 s, because that is where a small drift is enough to push samples out of the window.
   Do not read an assumed-zero attachment as aligned. There is no automatic clock sync.
7. **Preview before attaching** (reads only; writes nothing, so it is safe to repeat):
   `venv/bin/python -m eval.gpu_utilization attach reports/<run-dir> gpu-samples-<run-label>.jsonl --clock-offset-s <S> --dry-check`
   prints, per cell, the window length, the expected sample count (window length divided by the sampler interval), the
   actual count per GPU and the status, then the first and last sample times against the first and last window times.
   Fix any problem here (see "First live run") before the real attach, which refuses to overwrite.
8. **Attach**:
   `venv/bin/python -m eval.gpu_utilization attach reports/<run-dir> gpu-samples-<run-label>.jsonl --clock-offset-s <S>`
   (`--min-samples` defaults to 10).
9. **Compare** exactly as before. `eval.quantization_compare` adds a `gpu_utilization` column per cell when at least
   one of the two runs has the file; it is not part of any comparability check.

### First live run

Cell status: `ok` means every sampled GPU had enough samples that cover the cell's window; `partial` means some GPUs
did and some did not (the reason names which); `unavailable` means no GPU produced usable data, and the reason says why.
Nothing is estimated for a cell that is not `ok`.

A healthy result has all of these: status `ok`; per GPU, a sample count roughly equal to the window length divided by
the sampler interval (illustration only, not a measurement: a 60 s window sampled every 1 s should give about 60);
one per-GPU row for each GPU in the manifest's `gpu_count` (`gpu_count.matches_manifest` is true); an offset recorded as
`operator_supplied`; and no entries in `warnings`.

The three most likely reasons a cell comes back `unavailable`, and the fix for each:

1. **Short window.** The reason reads "N usable sample(s) in the window; minimum is 10". A cell that hits its request
   limit finishes before its duration, and a short cell at a 1 s interval yields few samples. Fix: lengthen the cell
   (`--duration` and `--requests`), or sample faster (`--interval 0.5` on the sampler). Lowering `--min-samples` makes the
   statistic rest on fewer samples; do that knowingly, not to turn a cell green.
2. **Clock offset.** The reason reads "samples do not cover the measured window", and the first (or last) sample is off
   by roughly the size of the offset. Fix: measure the offset (step 6), pass it with the sign convention above, and use
   `--dry-check` to confirm the sample span contains the window span. A flipped sign doubles the error.
3. **Sampler started late or stopped early.** The reason is the same "do not cover" message, but the sample span itself
   starts after the first window or ends before the last window, whatever the offset. Fix: start the sampler before
   the first cell and stop it after the last. Missed cells cannot be recovered after the fact; repeat the sweep.

Also check the sampler file's first line: a `backend` of `unavailable` means the GPU host had no usable `pynvml` or
`nvidia-smi`, and every cell will report that reason.

### What gets recorded per cell

Per GPU index: `n_samples`, `mean_pct`, `p95_pct` (nearest rank, the same method as the latency percentiles),
`max_pct`, plus peak memory used and mean power when reported. Shape (placeholders, not measurements):

```json
{"cell_id": "r1-c16-rateNone", "status": "ok",
 "window": {"started_at": "<UTC time>", "ended_at": "<UTC time>"},
 "per_gpu": {"0": {"status": "ok", "n_samples": "<n>", "mean_pct": "<mean>", "p95_pct": "<p95>", "max_pct": "<max>"}}}
```

`alignment` records the sampler and window clock sources, the applied offset and whether it was operator-supplied.
Nothing is filled in or estimated. A cell is `unavailable`, with a reason, when the file is missing, the sampler
reported no backend, the artifact has no recorded window, a GPU has fewer than `--min-samples` samples in the window,
or the samples do not cover the window (more than two sampler intervals at either end). On a multi-GPU host each GPU
is reported separately; there is no cross-GPU average, a cell is `partial` when only some GPUs have data, and a
sampled-GPU count that differs from the manifest's `gpu_count` is flagged, not corrected.

### Limits

Clock skew between the two machines moves samples across window edges, which is why the offset is explicit and
recorded. A 1 s interval gives few samples for very short cells (they report `unavailable`). The attach step cannot
tell whether the GPU host was shared or running other work. The sampler's own overhead was not measured here.

No GPU or live throughput run was performed while implementing Phase 2.
GPU utilization support was added later, offline-tested only; no live GPU run has taken place.
