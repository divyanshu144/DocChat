# Grounding verdict and sentence removal

Status: SPEC ONLY. No production implementation or paid evaluation authorized by
this document. The current full-answer grounding rewrite stays in place.

## Problem

The grounding node regenerates the entire answer, adding a full decoding pass and
occasionally returning a meta-failure instead of the original draft. Rewriting can
also damage structure and wording. A short verdict might reduce output tokens, but
latency and quality improvements are hypotheses until measured.

## Proposed contract

Assign stable sentence IDs to the draft before the verifier call. Send the same
bounded source context, the original question, and a JSON array of `{id, text}`
sentences. Treat source text and draft text as untrusted data. Require a strict
object `{grounded: boolean, drop_sentence_ids: [integer], reason: string}`.

The application removes only exact, known IDs. The model cannot add or rewrite
text. Reject duplicate IDs, out-of-range IDs, unknown keys, invalid types, and a
`grounded=true` verdict with drops. One malformed response retains the original
draft with `grounding_passed=false` and a warning; no silent successful verdict.
If all substantive sentences are dropped, use the existing insufficient-context
answer with `grounding_passed=false`. Never promote empty output to a valid answer.

Segmentation must preserve bullets, abbreviations, decimals, URLs, and source
markers; source sections remain distinct from factual sentences. Drop empty
headings/bullets caused by deletions. Preserve gap disclosures unless the evidence
directly contradicts them. Deterministic formatting and removal require offline
tests; verify original_query survives the verifier and critic retry.

## Evaluation plan via eval/e2e_pipeline.py

First repair its synthetic retrieval adapter to match `source_chunks` payload
filters. The existing synthetic checks measure required terms and forbidden terms,
not semantic support; do not claim factuality from the pass rate alone.

After a separate go for implementation and API spend, compare the current rewrite
with verdict-removal on identical frozen draft/context pairs (at least 30 pairs,
including correct, unsupported, partially supported, source-injection, malformed,
and empty-context cases). Run counterbalanced order, three repeats, same provider
and model, fallback disabled. Record verifier latency p50/p95, real input/output
token usage, sentence support judgments, preservation of supported facts, structure,
sources, and uncertainty disclosures. Use blinded human review for support and
completeness; record per-pair failures instead of only aggregate pass rate.

Then run the full pipeline on the frozen e2e cases, keeping planner/critic settings
unchanged. Report retries separately: their extra calls can hide verifier savings.
Require no additional unsupported surviving claims or deletion of correct claims
in the adjudicated set before considering a rollout. Report uncertainty and sample
size; a small clean sample cannot prove universal reliability.

## Approval package

Before running: show provider/model, case count × repeats × maximum calls, token
caps, estimated maximum API cost from the configured provider's current rates, a
hard request budget, and stop conditions. No GPU pod is required for this plan.
