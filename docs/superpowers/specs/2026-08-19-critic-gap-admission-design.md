# Critic Gap-Admission Carve-Out — Design Spec

**Date:** 2026-08-19
**Branch:** feat/openai-sse-chat-quality
**Status:** Implemented and verified 2026-08-19. Needed a second revision — see
"Verification outcome".
**Related:** `2026-05-28-critic-benchmark-design.md`, `2026-08-15-corruption-gen-design.md`

---

## Overview

`CRITIC_PROMPT` defines "good" as *"addresses the full query"*. A correct
"the provided context does not contain this" therefore cannot be represented as good —
it addresses nothing, so it scores poor by construction.

This has been measured, not guessed. Every benchmark run since 2026-07-28 has shown the
same signature: recall 1.00, precision 0.25–0.50. The critic over-fires; it does not
miss. The 2026-08-19 live run flagged `admits_gaps_with_partial_answer` with its own
reasoning attached:

> "The answer provides the access token expiry time but omits the refresh token expiry
> time requested."

That is the critic correctly describing the answer and drawing the wrong conclusion from
it.

## Why now

This was previously filed as "worth doing eventually". It is now a prerequisite, because
the critic became a **data labeller** when the rejection sink landed (`d9aacc3`). Every
rejection it records is training data, so a critic biased against honest gap-admission
teaches a fine-tuned model that refusing to fabricate is a defect — the exact behaviour
RAG needs most. Collecting under the current prompt produces a corpus that has to be
thrown away.

Order is therefore: fix the prompt, then enable the sink. Not the reverse.

## The change

The distinction the prompt is missing is not *whether* the query was fully answered but
**whether the gap was disclosed**:

- Omitting part of the query *silently* → poor. The user cannot tell what is missing.
- Naming what is unavailable → good. The user knows exactly where the boundary is.

Both halves matter. Without the second, honest refusals score poor (today's bug). Without
the first, the critic would accept any answer that hedges, and
`incomplete_two_part_query` / `partially_addresses_multipart` would flip from poor to
good — which would be a worse regression than the one being fixed.

## Cases this must not move

| Case | Expected | Why the new prompt keeps it |
|---|---|---|
| `incomplete_two_part_query` (Layer B) | poor | ChromaDB comparison omitted with no acknowledgement — silent |
| `partially_addresses_multipart` (Layer A) | poor | Chunk size/overlap omitted with no acknowledgement — silent |
| `vague_no_substance`, `off_topic`, `hallucinated_claim` | poor | Untouched by the carve-out |
| `correct_admits_gaps` | good | Names the missing information — the case being fixed |
| `admits_gaps_with_partial_answer` | good | Answers half, discloses the other half |

The two Layer A gap cases are the intended flips. Everything else must hold, which is
what makes this safe to ship behind the existing eval.

## Verification

1. `pytest -m eval` — Layer B regression guard, 8 binary assertions, must stay green.
2. `python eval/benchmark.py` — Layer A. Expect edge-case precision to rise as the
   gap-admission false positives clear; recall must stay 1.00. A recall drop means the
   carve-out is too broad and is now excusing genuine omissions.
3. The generated corruption set must stay at 15/15. `off_topic_swap` includes cases whose
   donor answer is itself a gap-admission; if the carve-out is written carelessly the
   critic may start passing those, which would show up here and nowhere else.

## Verification outcome

**The first draft of the prompt failed its own bar and had to be rewritten.**

Draft 1 stated the rule as a single paragraph: good if honest about gaps, poor if vague,
self-contradictory, off-topic, or silently incomplete. Edge cases went to 5/5 exactly as
intended — but the generated corruption set fell from 15/15 to **12/15**, losing cases in
`contradict_self` and `strip_specifics`. Framing the whole judgement around disclosure
let "answers as far as it honestly can" excuse answers that were self-contradictory or
had been redacted into uselessness. The carve-out leaked into defects it was never meant
to touch — precisely the risk this spec flagged, caught by precisely the check it
specified.

Draft 2 splits the judgement into two ordered steps: step 1 is the defects nothing
excuses (self-contradiction, vagueness, off-topic) and returns poor immediately; step 2
applies the disclosure test to *missing information only*. Explicit precedence, so the
carve-out cannot reach the step-1 defects.

Final measured state, both layers, two consecutive runs:

| Check | Before | After |
|---|---|---|
| Layer A edge cases | 4/5, P=0.50 | **5/5, P=1.00, R=1.00** |
| Layer A generated corruptions | 15/15 | **15/15** (12/15 under draft 1) |
| Layer B regression guard | 4 failed / 4 passed | **8 passed** |

The Layer B improvement is not from the prompt. Those four failures were
`RuntimeError: Event loop is closed` — `app.services.llm` caches one client per provider
and its connection pool binds to the event loop that created it, so every test after the
first hit a dead loop. Confirmed pre-existing by stashing. `tests/conftest.py` now resets
the cache per test. Until that landed, `pytest -m eval` could not validate anything, and
the one real-looking assertion failure turned out to be a symptom of it.

## What this does not cover

- **Giving the critic the retrieved context.** Still unspecced. It would let the critic
  verify that a claimed gap is a real one rather than taking the answer's word for it,
  and would unlock the `contradict_source` corruption. Separate change.
- **The temperature pin.** Landing in the same batch but independent; without it these
  numbers are not reproducible enough to attribute a change to the prompt.
