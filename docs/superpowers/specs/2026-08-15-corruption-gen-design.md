# Corruption Generator for the Critic Benchmark — Design Spec

**Date:** 2026-08-15
**Branch:** feat/openai-sse-chat-quality
**Status:** Implemented 2026-08-16 (Option 1 approved). Transform set changed during
implementation — see "Transforms cut during implementation" below.
**Depends on:** `docs/superpowers/specs/2026-05-28-critic-benchmark-design.md` (Layer A)

---

## Overview

`eval/benchmark.py` runs N=5 ambiguous cases. Its own report tells you not to trust the
numbers, and `HANDOFF.md` records the reason: at N=5 a single verdict flip moves precision
~8 points, so back-to-back runs of an identical build scored 3/5 then 2/5.

Hand-writing 20 more borderline cases is slow and the labels drift with the author's mood.
The alternative is **corruption**: take an answer already labelled `good`, apply a
transform that is defensibly answer-degrading, and inherit the label `poor` from the
transform rather than from a fresh human judgement. Ground truth becomes cheap and
auditable — you review 3 transforms once instead of 20 answers individually.

This spec covers the generator only. It does not change the critic.

---

## The blocking finding

**The critic never sees the retrieved context.** `CRITIC_PROMPT` in
`app/agent/nodes/critic.py` interpolates exactly two fields:

```
Query: {query}
Answer: {answer}
```

`benchmark.py:run_case` reinforces this — it hardcodes `"retrieved_chunks": []`.

So a corruption that makes an answer contradict its *source* produces a case the critic
**cannot** get right, no matter how good it is. It would not measure critic accuracy; it
would measure the absence of context in the prompt, which is already known.

This also explains the existing case naming. `contradicts_context` and
`hallucinated_claim` in `CASES` are both labelled as contradiction cases, but read them
closely: each contradicts *itself* within the answer text. They are self-contradiction
cases wearing a context-contradiction name, because self-contradiction is the only kind
the current prompt can detect.

The `CriticCase.context` field that prompted this work was added for
`contradict_source`, and that is precisely the transform the current architecture cannot
support.

### Consequence for the transform set

The preview set was `contradict_source`, `drop_citation`, `overclaim`.
`contradict_source` is **cut** and replaced. Every remaining transform degrades the
answer in a way visible from the query/answer pair alone:

| Transform | What it does | Why the result is `poor` |
|---|---|---|
| `contradict_self` | Appends a clause asserting the negation of the answer's own opening claim | An answer that says both X and not-X cannot address the query |
| `strip_specifics` | Redacts identifiers, numbers and product names, keeping the prose fluent | Reproduces `vague_no_substance` — the query's concrete ask goes unanswered |
| `truncate_enumeration` | Deletes the final clause of an explicit "(1) … (2) … (3)" answer | Reproduces `incomplete_two_part_query`; still promises N, delivers N−1 |
| `off_topic_swap` | Pairs a query with a correct answer to an unrelated question | Reproduces `off_topic` — fluent, accurate, and not about the query |

### Transforms cut during implementation

`drop_citation` and `overclaim` were in the approved set and did **not** survive. Both
fail the same context test that killed `contradict_source`:

- **`overclaim`** appends a fabricated specific. Without the source text, an invented
  version number and a real one are indistinguishable to the critic — the case would be
  unwinnable. Its other half, replacing hedges with absolutes, is worse than unwinnable:
  a de-hedged answer reads *more* confident, so a good critic would rate it **better**,
  and the case would be mislabelled rather than merely hard.
- **`drop_citation`** removes the `Sources:` block. But `CRITIC_PROMPT` asks only whether
  the answer "adequately addresses the query" — it says nothing about citations, and the
  remaining prose still answers. A correct critic would call it good, so labelling it
  poor poisons the dataset.

`strip_specifics` and `off_topic_swap` replaced them. Both degrade the answer in a way
visible from the query/answer pair, which is the bar every transform here must clear.

**Rule this establishes:** a corruption is only sound if a *correct* critic, given just
the query and the answer, would call the result poor. "Degraded" is not sufficient.

`context` is retained on `CriticCase` but is **authoring provenance** — it records what
the answer was grounded in so a human auditing a generated case can check the transform
was fair. It is not fed to the critic. This must be stated in the field's comment, which
currently implies the opposite.

---

## Dataset construction

**Seeds.** Only cases labelled `expected="good"` can be corrupted — corrupting an
already-`poor` answer yields an unlabelable result. Available good seeds:

- `CASES`: `correct_well_grounded`, `correct_multi_part_answer` (2)
- `BENCHMARK_CASES`: `correct_admits_gaps`, `hedged_but_correct`, `correct_but_terse`,
  `admits_gaps_with_partial_answer` (4)

**Not every transform applies to every seed.** `drop_citation` on an answer with no
citation is a no-op; `truncate_multipart` on a single-part answer is meaningless;
`overclaim` on `correct_admits_gaps` would corrupt a gap-admission into a hallucination,
which is a *different* failure mode than intended and muddies the label.

Each transform therefore declares an applicability predicate and **returns `None` when it
does not apply**. A no-op that silently returns the input would inject a `good` answer
labelled `poor` — a poisoned case, and the single most damaging bug this design can have.

**Actual yield: 15 generated cases** — `contradict_self` 4, `strip_specifics` 4,
`truncate_enumeration` 1, `off_topic_swap` 6. With the 5 hand-written originals that is
**N=20**.

The two scores are reported **separately, never merged.** The generated cases are mostly
*not* borderline, so folding them into one number would inflate the headline and destroy
comparability with every edge-case run recorded before they existed. The benchmark also
prints a per-transform breakdown: since all generated cases are "poor", that cut is
recall, and a transform the critic misses wholesale is either a real blind spot or a
badly designed corruption — worth telling apart.

**Generated cases never enter `CASES`.** `eval/cases.py` states that Layer A and Layer B
stay independent, and generated cases are exactly the borderline material the regression
guard must not assert on.

---

## Files

```
eval/corruptions.py          new — the transforms and the generator
eval/cases.py                modified — fix the `context` comment; export seed helper
eval/benchmark.py            modified — run BENCHMARK_CASES + generated
tests/test_corruptions.py    new — the transforms are pure, so they unit-test cleanly
```

`eval/corruptions.py` sketch:

```python
Transform = Callable[[CriticCase], CriticCase | None]

def contradict_self(case: CriticCase) -> CriticCase | None: ...
def drop_citation(case: CriticCase) -> CriticCase | None: ...
def overclaim(case: CriticCase) -> CriticCase | None: ...
def truncate_multipart(case: CriticCase) -> CriticCase | None: ...

TRANSFORMS: list[Transform] = [...]

def generate(seeds: list[CriticCase]) -> list[CriticCase]:
    """Every applicable (seed, transform) pair, label forced to "poor"."""
```

Each generated case carries `label=f"{seed.label}__{transform.__name__}"` so a failure in
the report names both the seed and the transform, and `reason` records that the label came
from a transform rather than a human.

---

## Determinism

The transforms are **pure string functions with no LLM call and no randomness**. Given the
same seeds the generated dataset is byte-identical every run. This is deliberate: the
benchmark already has one unreproducible component (the critic samples at the provider
default temperature), and adding a second in the dataset would make a changed score
uninterpretable — you could not tell a prompt regression from a re-rolled dataset.

**This does not fix the reproducibility blocker.** `HANDOFF.md` and `tasks/todo.md` both
carry pinning `temperature=0` on the classification nodes as the prerequisite for any
provider A/B, and that is still open and still blocking. What N≈18 buys is a smaller
per-flip swing — roughly 8 points down to ~2 — which narrows the noise band but does not
remove it. **Do not read this spec as unblocking the A/B comparison.**

---

## What this does not cover

- **Any change to the critic.** Giving `CRITIC_PROMPT` the retrieved context would make
  `contradict_source` viable and is arguably the higher-value change, but it alters agent
  behaviour and needs its own spec — as does the separate gap-admission prompt fix already
  recorded in `HANDOFF.md`.
- **Pinning temperature.** Prerequisite for A/B, tracked in `tasks/todo.md`, untouched here.
- **Reaching N=20–30.** Needs more hand-written good seeds.
- **End-to-end answer quality.** This measures critic accuracy, same as Layer A always has.

---

## Open Decision 1 — RESOLVED 2026-08-16

Approved: **Option 1**, ship the context-free transforms against today's critic.
`contradict_source` (and a sound `overclaim`) become possible only if `CRITIC_PROMPT`
is given the retrieved context, which remains unspecced and unbuilt.
