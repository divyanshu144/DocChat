# Self-hosted inference, benchmarked honestly

This is a short write-up of adding a self-hosted vLLM inference path to DocChat and
measuring it properly against hosted LLM APIs. The numbers below all come from
`eval/BENCHMARK_RESULTS.md`, which has the full tables, commands, and caveats for every
sweep. This document only tells the story and states the conclusions; it does not add
any claim the data there does not already support.

## Why this exists

DocChat already talks to Groq, OpenAI, and Mistral through one provider seam. That is
application-level LLM engineering: streaming, fallback, provider abstraction. It says
nothing about inference serving itself, which is the part that matters for a serving
infrastructure role: continuous batching, KV cache management, GPU throughput and
latency under load. Adding a `local` provider backed by vLLM on a rented GPU, and a
benchmark harness to measure it, closes that gap.

## The measurement mistakes, in the order they were found

A benchmark that looks clean on the first run is usually hiding something. Four real
mistakes got made and fixed here, and the fixing is as much the point as the final
numbers.

**Mistake 1: the workload was 40 to 100 times smaller than what DocChat actually
sends.** The first two sweeps benchmarked `eval/cases.py`'s bare queries, 20 to 90
tokens with no retrieval context. A real DocChat request, built by running the actual
planner-retriever-synthesizer pipeline against real ingested documents, is 3752 to 6801
input tokens. Every number from those first two sweeps described a workload the app
never sends.

**Mistake 2: a wall-time calculation that quietly inflated a throughput number by over
6x.** Once concurrency=1 was changed to run every query sequentially rather than firing
one request, the harness kept computing wall time as `max()` across request durations,
which is correct for concurrent requests but wrong for sequential ones, where total time
is closer to their sum. This made `local`'s concurrency=1 throughput look like 592
tokens per second when the real number was 89.7, a 6.6x overstatement. It was caught
because the number looked wrong on its face: throughput at concurrency 1 should never
beat throughput at concurrency 4, and it did. Fixed by measuring wall-clock time
directly with a timer around the actual batch call instead of inferring it afterward
from per-request numbers.

**Mistake 3: a benchmark that was measuring its own cache, not the GPU.** The third
sweep, run against real-sized prompts, reported `local`'s time to first token as a flat
0.5 to 0.85 seconds at every concurrency level up to 64. That is physically implausible:
64 concurrent requests at roughly 5000 input tokens each is about 320,000 tokens of
prefill, which should take tens of seconds on a single GPU with no caching, not under a
second. The cause was identified before it was proven: the harness reused the same small
set of prompts across every concurrency level, and vLLM's prefix cache was never
disabled, so later cells were very likely served from a cached prefix instead of real
computation. A follow-up sweep added two things to settle it rather than guess: a unique
token prepended to every request so no two requests share a prefix, and live polling of
vLLM's own `/metrics` endpoint so the prefix-cache hit rate could be measured directly
instead of inferred. A positive control ran first, the same prompt sent twice with
busting off and twice with busting on, and it showed exactly the expected split: 49.9%
hit rate with busting off, 0.0% with busting on. The real sweep then also measured 0.0%
hit rate at every cell, and time to first token went from the earlier flat 0.5 to 0.85
seconds to a real 805 milliseconds to 32.9 seconds climbing with load. The cache
inflation hypothesis is confirmed, not just suspected.

**A smaller, related mistake worth naming:** two different reasoning models (OpenAI's
default and Groq's default) were silently spending their entire output token budget on
hidden reasoning and returning zero visible content, which looked like a benchmark bug
before it was traced to the model choice. Both got command-line overrides
(`--openai-model`, `--groq-model`) so a benchmark run can use a non-reasoning model
without touching production configuration.

## What the corrected numbers actually show

**Hosted API rate limits bind before latency does, once the prompts are realistically
sized.** At roughly 5000 input tokens per request, OpenAI returned 429 for 100% of
requests at concurrency 4 and above on this account's tier. This is a property of the
account's tier, not of hosted APIs as a category: a higher tier, a quota increase, or
retry logic would change it. But it is a real, concrete finding, and it is a more
specific argument for self-hosting than a generic cost or throughput number, because it
shows a ceiling that self-hosting genuinely removes: the rented GPU's capacity is set by
its own KV cache, not by a quota someone else controls.

**Self-hosting removes the account-tier ceiling, but does not remove queueing under
load.** The corrected, cache-busted sweep showed the GPU's KV cache climbing from 1.6% to
99.4% full as concurrency went from 1 to 128, with time to first token climbing from 805
milliseconds to 32.9 seconds across the same range. At the highest concurrency level, 13
of 128 requests failed with client-side timeouts caused by genuine queueing pressure
near capacity, not a server error and not a caching artifact. Zero preemptions happened
at any point, meaning vLLM handled the pressure through its waiting queue rather than
evicting already-admitted requests. The honest framing is not "self-hosting has no
ceiling." It is "self-hosting trades someone else's account-tier quota for a ceiling you
can see, size, and control yourself."

**Cost is idle-time-dominated.** A rented GPU is billed by the hour whether it is busy
or not, so the dollar cost per million output tokens improves sharply with load: it
improved 44 times from concurrency 1 to concurrency 64 in one sweep ($4.93 to $0.11),
and 18 times in the real-prompt sweep ($6.24 to $0.34). A self-hosted GPU is not cheaper
in general. It is cheap specifically when it is kept busy, and expensive when it sits
idle.

**Decode speed genuinely drops under concurrent load with large contexts, and the size
of the drop matches a memory-bandwidth calculation, not just an observation.** Per-request
decode speed on `local` dropped from 95.1 to 46.1 tokens per second as concurrency went
from 1 to 64 with real-sized prompts. Decode is memory-bandwidth bound: each generation
step has to read the model's weights plus every active request's KV cache. At
concurrency 64 with roughly 5000-token contexts, that is about 64 times 5000 times 56
kilobytes, or roughly 18 gigabytes of KV cache read per step, on top of the roughly 15
gigabytes of weights, predicting about a 2.2x slowdown. The measured slowdown was 2.06x.
This is the honest shape of continuous batching's tradeoff: aggregate throughput keeps
climbing under load, but it is not free for any single request, and the size of the cost
can be predicted from the hardware, not just measured after the fact.

## What was never tested

- **The actual KV cache limit on a bigger GPU.** The one real-prompt sweep that used an
  A100 80GB never got close to filling its KV cache (roughly 57GB free, about 1 million
  tokens of KV capacity, against about 450,000 tokens in use at concurrency 64). The
  queueing and KV-saturation behavior described above was only directly observed on a
  smaller L40S 48GB GPU. The A100 sweep's "no ceiling" result was real for the load it
  was given, but it did not test where that ceiling actually is.
- **Quantization.** Whether an AWQ or GPTQ build of the same model changes the
  throughput, memory footprint, or answer quality tradeoff has not been measured. A spec
  for this exists (`docs/superpowers/specs/2026-10-01-quantization-comparison-design.md`)
  but no live sweep has run.
- **A direct serial-versus-concurrent comparison at the same batch size.** Every sweep
  so far shows concurrent throughput climbing with load, which is evidence continuous
  batching works, but never a direct before-and-after at a fixed batch size. A spec and
  the harness support for it exist
  (`docs/superpowers/specs/2026-10-01-batching-proof-design.md`, the harness's `--serial`
  flag) but no live sweep has run.
- **A second serving engine.** No comparison against TGI, SGLang, or any engine other
  than vLLM has been attempted.
- **A clean Groq baseline at realistic prompt sizes.** Groq's numbers from the real-prompt
  sweep were excluded because the earlier smoke test used a reasoning model and was
  inconclusive, not because Groq was shown to behave one way or the other at this prompt
  size.

## Cost figures that used placeholder rates

The hosted-provider dollar costs quoted in the first two sweeps used a small static
per-million-token rate table in `eval/inference_benchmark.py`
(`_HOSTED_COST_PER_1M_OUTPUT_TOKENS`), not rates fetched from each provider's live
pricing page, and were explicitly flagged as unverified in those sweep entries. The
self-hosted GPU costs throughout, including the 44x and 18x improvement figures above,
are real: they come from the actual hourly rate paid for the actual rented pod used in
that sweep, not an estimate.

## What this actually demonstrates

Not a finished product. A benchmark harness that catches its own measurement mistakes
before trusting its own output: a wrong workload, an inflated throughput number, and a
cache-contaminated latency measurement were all found and fixed inside this same body of
work, each one verified with direct evidence rather than assumed away. The harness
itself has real instrumentation discipline built in: cache busting by default, a
positive control that refuses to let a sweep proceed if the instrumentation cannot prove
itself, live polling of the serving engine's own metrics, and an explicit per-cell
timeout so a stuck run fails safely instead of hanging. And the corrected findings show
real understanding of what actually constrains GPU-served inference: KV cache capacity,
queueing behavior under load, and a decode-speed cost that can be predicted from memory
bandwidth, not just observed.
