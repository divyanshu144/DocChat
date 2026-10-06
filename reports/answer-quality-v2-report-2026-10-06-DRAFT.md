> **SUPERSEDED** by `answer-quality-final-report-v1-v2-2026-10-06.md`. Kept for history only; do not cite.

# DocChat answer-quality review, v2 judge prompt (DRAFT, partly pending)

**Status: draft. LLM-assisted labels, not human-verified.** Sections marked **PENDING** need a v2 judge to
finish all 120 rows, which has not happened because both judge accounts ran out of credits. Nothing here
claims `temperature=0`: every judge model used rejected the `temperature` parameter, so all v2 labels use
provider-default sampling and are not treated as deterministic.

## 1. What changed from v1

The v1 audit found that unsupported-claim scoring depended heavily on prompt calibration. The v2 prompt
(sha256 `4f21114b...2844e0`) therefore:

- lists each distinct fact once (no duplicate or restated claims) and ignores formatting, hedges,
  suggestions and abstention statements;
- gives every claim a status: `supported`, `minor_imprecision` or `unsupported`;
- treats wording-equivalent paraphrases as supported, glosses and dropped qualifiers as
  `minor_imprecision`, and contradictions, new specific facts and over-guarantees as `unsupported`;
- defines `answer_correct` so that extra unsupported elaboration affects `fully_supported`, not
  correctness, with `partial` for omitted expected facts or one contradiction and `no` only for a missed
  central fact;
- derives `fully_supported` from the claim statuses and the strict validator rejects any label that
  disagrees with them (no silent repair);
- uses generic examples only, so the audited v1 cases were not written into the prompt.

The v1 files, the audit and the corrected-label report are unchanged.

## 2. Judges and run status

| judge | prompt | rows judged | state |
|---|---|---|---|
| `claude-opus-5-5` (Anthropic Messages API) | v2 | 22 of 120 | **stopped**: HTTP 400, credit balance too low. Resumable. |
| `gpt-6-astra` (OpenAI) | v2 | 66 of 120 | **stopped**: HTTP 429 `insufficient_quota` (no credits). Resumable. |
| `gpt-5.6-luna` (OpenAI) | v1 | 120 of 120 | complete; corrected by the audit layer |

Parse status for the 22 Opus rows: all `ok`. Parse status for the 66 astra rows: all `ok`. Both models rejected
`temperature`; the Opus labels record the served model name, the astra labels record the requested name only.

## 3. Opus v2 versus v1 (22 rows, the first 22 in pack order)

Agreement with v1 on the same rows (v1 original and v1 audit-corrected give the same picture):

| field | agreement with v1-corrected | differences |
|---|---|---|
| `answer_correct` | 22/22 | none |
| `citation_correct` | 22/22 | none |
| `abstention_correct` | 22/22 | none |
| `fully_supported` | 16/22 (0.73) | 1 `no`->`partial`, 5 `partial`->`yes` |

On these rows v2 reports 15 unsupported claims across 9 rows and 23 `minor_imprecision` claims. For
reference, v1 original on the full 119 rows reported 146 unsupported claims across 61 rows, and the v1 audit
brought that to 111 (strict) or 43 (full). The 22-row v2 figures are not comparable to those totals.

## 4. Opus versus astra on the same 22 rows

| field | agreement | differences |
|---|---|---|
| `answer_correct` | 22/22 | none |
| `citation_correct` | 22/22 | none |
| `abstention_correct` | 22/22 | none |
| `fully_supported` | 19/22 | 3, all `partial` (Opus) to `yes` (astra) |

Unsupported claims barely differ (Opus 15 across 9 rows, astra 16 across 8 rows). The gap is in
`minor_imprecision` (Opus 23, astra 14), which is why Opus gives fewer `fully_supported: yes` (6 versus 9 of 22).
They differ on 7 rows (`4b6c85`, `f99645`, `693d25`, `2579be`, `e713f3`, `eb6a44`, `8c3aa4`); neither judge is
consistently closer to the v1 audit. The blinded sheet for human adjudication is
`reports/quality-judge-disagreement-sheet.md`. Caveats: 22 non-random rows, and sampling noise cannot be separated
from judge differences.

## 5. Corrected v1 metrics by format and split

Unchanged from `reports/answer-quality-final-report-2026-10-06.md` (answer correctness, abstention and
citation use the audit-corrected labels; unsupported-claim scoring is exploratory). Held-out answer yes-rate:
AWQ 0.75, fp16 0.88, GPTQ 0.88; development 0.96 for all formats; 9 of 9 negative controls handled correctly.

## 6. Paired per-case comparison across formats (v1 corrected labels)

Each case is answered by all three formats, so formats are compared on the same case. Win/loss/tie counts,
exact two-sided sign-test p-values and bootstrap 95% intervals are descriptive and wide at 16 to 24 cases.
Source: `reports/quality-paired-format-comparison-v1-corrected.json`.

| split | comparison | metric | first better / second better / tie | mean diff (95% CI) | sign-test p |
|---|---|---|---|---|---|
| development (24) | fp16 vs AWQ | answer score | 1 / 1 / 22 | 0.00 (-0.06, 0.06) | 1.00 |
| development (23) | fp16 vs GPTQ | answer score | 1 / 1 / 21 | 0.00 (-0.07, 0.07) | 1.00 |
| development (23) | AWQ vs GPTQ | answer score | 0 / 0 / 23 | 0.00 (0.00, 0.00) | n/a |
| held_out (16) | fp16 vs AWQ | answer score | 3 / 1 / 12 | +0.06 (-0.06, 0.19) | 0.63 |
| held_out (16) | fp16 vs GPTQ | answer score | 2 / 2 / 12 | 0.00 (-0.13, 0.13) | 1.00 |
| held_out (16) | AWQ vs GPTQ | answer score | 1 / 3 / 12 | -0.06 (-0.19, 0.06) | 0.63 |
| held_out (16), exploratory | fp16 vs AWQ | fully supported (yes) | 7 / 0 / 9 | +0.44 (+0.19, +0.69) | 0.016 |
| held_out (16), exploratory | AWQ vs GPTQ | fully supported (yes) | 0 / 4 / 12 | -0.25 (-0.50, -0.06) | 0.125 |

Reading: answer correctness shows no format difference on the same cases; almost every case is a tie. The one
pattern that stands out is exploratory: on held-out, fp16 is fully supported more often than AWQ (7 cases to 0).
It rests on the prompt-sensitive support label and is not tested across many comparisons, so it is a hypothesis
to confirm with the v2 labels, not a finding.

## 7. v2 results by format and split

**PENDING.** Both paid judges ran out of credits (Anthropic after 22 rows, OpenAI after 66), so no judge has yet
scored all 120 rows under v2. The astra aggregate files in `reports/*-v2-gpt-6-astra.json` cover only the first 66
rows (all of development, 2 held-out AWQ rows, no held-out GPTQ rows) and **must not be quoted**. To fill once a
judge can finish the remaining rows:

```bash
python -m eval.aggregate_judge_labels --labels reports/quality-judge-labels-v2-gpt-6-astra.jsonl
python -m eval.paired_format_comparison --labels reports/quality-judge-labels-v2-gpt-6-astra.jsonl
python -m eval.compare_judge_labels --v2 reports/quality-judge-labels-v2-gpt-6-astra.jsonl   # versus v1 and v1-corrected
```

Planned content: answer correctness, abstention, citation correctness and the exploratory support metrics by
format and split from astra v2; agreement of astra v2 with v1-corrected over all rows; whether the held-out
fp16-versus-AWQ support gap survives under v2.

## 8. Other fixes made while waiting

- **Citation regex.** The pack's `emitted_citations` matched any bracketed text, including `[26 weeks]`. A shared
  pattern (`eval/citations.py`) now matches only `[PDF`, `[Web` and `[YouTube` markers. A corrected pack copy,
  `reports/quality-review-pack-citations-fixed.jsonl`, changes 2 rows; the original pack and blind ids are untouched.
- **Comparison tooling.** `eval/compare_judge_labels.py` has a pairwise mode for any two label files;
  `eval/paired_format_comparison.py` and `eval/build_disagreement_sheet.py` are new, each with tests.

## 9. Limitations

1. LLM-assisted labels; the v1 correction layer was also produced by an LLM. Neither has been checked by a human.
2. Provider-default sampling for every judge (all rejected `temperature`); run-to-run agreement is unmeasured.
3. Opus covers only 22 non-random rows because the run stopped on billing; the Opus-versus-astra comparison is
   limited to those rows.
4. Judges differ in strictness on `minor_imprecision`, so `fully_supported` is not comparable across judges.
5. The astra labels record the requested model name only.
6. Small samples: 16 to 24 cases per split, 9 negative controls, 9 answers with citations; intervals are wide.
7. Narrow evidence (one PDF, one Wikipedia article); development answers are near ceiling.
8. The judge has not been shown a fabricated answer to a negative control or a clearly wrong citation.
9. The paired exploratory support comparison was not corrected for the number of comparisons made.

## 10. Recommendation

Do not use unsupported-claim counts as a headline metric until the v2 results are complete, a human has adjudicated
the 7 disagreement rows, and the 8 low-confidence v1 audit rows are checked. After that, re-run the paired comparison
on the v2 labels and decide whether the fp16-versus-AWQ support gap holds.

## 11. Wording

Use: "Answer quality was assessed with LLM-assisted labels from two blinded LLM judges and a revised prompt (v2).
The judges rejected temperature=0, so labels were generated with provider-default sampling and are not treated as
deterministic. Labels have not been fully human-verified."

Avoid: "human evaluation", "ground truth", "validated", "statistically significant", "production guarantee", and any
claim of temperature 0.
