# Critic context and loop ablation

Status: SPEC ONLY. Do not change the production critic prompt or run paid evals
from this spec without a separate go. original_query preservation and parse-failure
logging are independent hardening fixes already implemented.

## Problem

The critic currently sees question and answer, but cannot verify whether a claimed
information gap is actually absent from the sources. Its benchmark measures critic
classification accuracy, not the quality improvement caused by retrying the graph.

## Proposed prompt change

Add the same bounded, rank-ordered source context used by synthesis, with stable
source markers. Keep the original user question as the evaluation target. Explicitly
treat context and answer as untrusted data, separate from critic instructions.
Preserve the two-step rule: self-contradiction/vagueness/off-topic fail first; honest
gap disclosure passes only when the provided evidence does not resolve the gap.
Require strict `{quality: "good" | "poor", feedback: string}` validation and log
malformed responses separately from valid good verdicts. Do not equate a parse
fallback or iteration-cap acceptance with measured quality.

## Paired experiments

1. Classification: reuse the diagnostic and regression cases, plus source-supported
   contradiction and false-gap corruptions, comparing answer-only and context-aware
   prompts against independently labeled verdicts. Freeze drafts and contexts; use
   identical models, temperature, token caps, no provider fallback, counterbalanced
   order and three repeats. Report poor-class precision/recall/F1, confusion matrix,
   parse failure rate, input tokens, actual cost and p50/p95 critic latency.
2. End-to-end: freeze 20–30 queries and retrieval snapshots. Compare three arms:
   critic completely skipped; current critic with retry; context critic with retry.
   A baseline that calls the critic but disables the retry edge is a retry ablation,
   not a critic-on/off ablation. Keep those labels distinct.
3. Use `eval/e2e_pipeline.py` for plumbing/timing and term checks, extended in the
   approved implementation with an explicit skip-critic arm and per-stage traces.
   Its existing `--compare` uses a shared first pass and then conditionally retries;
   label that result paired retry analysis, never critic on/off quality uplift.

Blindly adjudicate supported correctness, completeness against original_query,
uncertainty disclosure, source attribution, and contradictions. Publish wins,
ties, regressions and baseline-to-final pairs, with bootstrap confidence intervals
for paired pass-rate changes and latency deltas. Run both all queries and the
subset actually triggering retry; do not discard failed/empty/API-error runs.

## Acceptance and approval

Do not change the production prompt based only on critic accuracy: the retry must
improve adjudicated final answers enough to justify added context cost and latency.
Agree rollout thresholds and a spend cap before implementation. Supply the exact
provider/model, input token estimates, max calls, repeat count, timeout, hard total
request budget and current per-token prices before asking to run. No live API run
has been made for this spec. GPU benchmark phases remain separately deferred.
