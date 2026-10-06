# DocChat answer-quality review: final report (v1 complete, v2 partial)

**Status: LLM-assisted labels; not human-verified. The v2 rerun was stopped before completion.**
The v1 judge run covers all 120 answers and has an audit correction layer; it is the basis for every headline
number below. The v2 rerun (revised prompt) did not finish because all three judge accounts hit limits, so v2 is
reported only as partial evidence about judge behaviour, not as a result about the model formats.

Sampling: `gpt-5.6-luna` (v1), Opus and `gpt-6-astra` all rejected `temperature=0`, so those labels use
provider-default sampling and are not deterministic. Only the Groq `gpt-oss-120b` labels (53 rows, v2) were
produced with `temperature=0` applied.

## 1. Method

- **Data:** 120 blinded answers (72 `development`, 48 `held_out`) from three serving formats of one model (fp16, AWQ,
  GPTQ; 40 each). Held-out: 18 document_qa, 9 long_context, 9 negative_control, 6 summarisation, 6 multi_document.
  Evidence is one working-time declaration PDF and one Wikipedia article on RAG (29 distinct chunks).
- **Blinding:** the judge saw the question, evidence chunks only (generation prompt and history stripped), expected
  facts, the answer, the expected-abstention flag and emitted citations. No model name, split, case id, file name or
  `blind_id`. The unblinding key was read only at aggregation.
- **v1:** `gpt-5.6-luna`, prompt v1, strict schema validation with one retry. 119 rows parsed; one row
  (`review-ec6f5335912c`, development, GPTQ) failed twice and is excluded, not repaired.
- **Audit correction layer (v1):** each flagged claim and each abstention, citation and `no` row was re-read against
  the evidence by an LLM reviewer; 79 rows audited, 59 changed. Corrections are separate per-claim decisions
  (category, reason, confidence); the original labels file is unchanged (sha256 `fde8cb93...`).
- **v2 prompt (sha256 `4f21114b...`):** distinct claims listed once; each claim `supported`, `minor_imprecision` or
  `unsupported`; wording-equivalent paraphrases are supported; `answer_correct` is not lowered by extra elaboration;
  `fully_supported` is derived from the claim statuses and inconsistent labels are rejected. Only generic examples
  are in the prompt; the audited v1 cases are not.

## 2. v1 results (headline; corrected answer, abstention and citation labels)

95% intervals are Wilson intervals and are wide. Development and held-out are separate.

### Answer correctness

| split | format | scored | yes | partial | no | yes-rate (95% CI) |
|---|---|---|---|---|---|---|
| development | AWQ | 24 | 23 | 1 | 0 | 0.96 (0.80-0.99) |
| development | fp16 | 24 | 23 | 1 | 0 | 0.96 (0.80-0.99) |
| development | GPTQ | 23 (+1 parse failure) | 22 | 1 | 0 | 0.96 (0.79-0.99) |
| held_out | AWQ | 16 | 12 | 4 | 0 | 0.75 (0.51-0.90) |
| held_out | fp16 | 16 | 14 | 2 | 0 | 0.88 (0.64-0.97) |
| held_out | GPTQ | 16 | 14 | 2 | 0 | 0.88 (0.64-0.97) |

### Abstention and citations

- **All 9 negative controls were handled correctly after the audit** (3 of 3 per format on held-out; 0 false
  abstentions on 13 answerable held-out questions per format). Development has none. This only tests correct
  abstention; no answer fabricated a response to a negative control.
- **Cited-answer handling needed small corrections.** Only 9 answers contain real source markers (development: 2 AWQ;
  held-out: 1 AWQ, 3 fp16, 3 GPTQ), all judged correct. Corrections: two answers labelled `yes` with no marker became
  `not_applicable`; two pack rows matched `[26 weeks]` as a citation (fixed in a corrected pack copy); two answers cite
  a `p.1-2` range that is not an exact marker (kept `yes`, flagged); one answer repeats the same source 24 times.

### Paired per-case comparison (same case, three formats; corrected v1 labels)

Win/loss/tie counts, exact two-sided sign tests and bootstrap intervals are descriptive.

| split | comparison | metric | first / second better / tie | mean diff (95% CI) | sign-test p |
|---|---|---|---|---|---|
| development (24) | fp16 vs AWQ | answer score | 1 / 1 / 22 | 0.00 (-0.06, 0.06) | 1.00 |
| development (23) | fp16 vs GPTQ | answer score | 1 / 1 / 21 | 0.00 (-0.07, 0.07) | 1.00 |
| development (23) | AWQ vs GPTQ | answer score | 0 / 0 / 23 | 0.00 | n/a |
| held_out (16) | fp16 vs AWQ | answer score | 3 / 1 / 12 | +0.06 (-0.06, 0.19) | 0.63 |
| held_out (16) | fp16 vs GPTQ | answer score | 2 / 2 / 12 | 0.00 (-0.13, 0.13) | 1.00 |
| held_out (16) | AWQ vs GPTQ | answer score | 1 / 3 / 12 | -0.06 (-0.19, 0.06) | 0.63 |

Answer correctness shows no format difference on the same cases; almost every case is a tie.

### Exploratory only: unsupported-claim scoring

Not a headline metric. Across 119 scored rows, unsupported claims fall from 146 (v1 original) to 111 (strict
corrections) or 43 (full corrections); rows with an unsupported claim fall from 61 to 54 or 28. The "fully supported"
yes-rate barely moves (58/119 to 62/119). On held-out, AWQ has the most unsupported claims and fp16 the fewest in all
three versions, and fp16 is fully supported more often than AWQ in 7 cases to 0 (sign-test p = 0.016, interval +0.19
to +0.69). That rests on the prompt-sensitive support label, was not adjusted for multiple comparisons and is a
hypothesis, not a finding.

## 3. v2 rerun: what was done and why it stopped

| judge | prompt | rows judged | `temperature=0` applied | stopped because |
|---|---|---|---|---|
| `claude-opus-5-5` | v2 | 22 of 120 | no | Anthropic: credit balance too low |
| `gpt-6-astra` | v2 | 66 of 120 | no | OpenAI: HTTP 429 `insufficient_quota` |
| Groq `gpt-oss-120b` | v2 | 53 of 120 | yes | Groq: daily token cap (200k per day) |

All judged rows parsed (`ok`). Retry/backoff was added for rate limits and fails fast on quota and daily-cap errors.
The first astra run was initially reported as finished in error; the partial astra aggregates were removed.

### Coverage: no v2 format comparison is possible

Rows were judged in pack order, so coverage is not balanced:

| judge | development fp16 | development AWQ | development GPTQ | held-out fp16 | held-out AWQ | held-out GPTQ |
|---|---|---|---|---|---|---|
| Opus v2 | 22 | 0 | 0 | 0 | 0 | 0 |
| astra v2 | 24 | 24 | 0 | 16 | 2 | 0 |
| Groq v2 | 24 | 13 | 0 | 16 | 0 | 0 |

No v2 judge scored any GPTQ row, and held-out AWQ and GPTQ are essentially uncovered. v2 therefore says nothing about
format differences.

### Judge agreement on shared rows

Agreement is exact label match on the rows both judges scored.

| pair | shared rows | answer_correct | fully_supported | citation_correct | abstention_correct |
|---|---|---|---|---|---|
| v1-corrected vs Opus v2 | 22 | 22/22 | 16/22 | 22/22 | 22/22 |
| v1-corrected vs astra v2 | 66 | 60/66 | 53/66 | 65/66 | 66/66 |
| v1-corrected vs Groq v2 | 53 | 49/53 | 38/53 | 52/53 | 53/53 |
| Opus vs astra | 22 | 22/22 | 19/22 | 22/22 | 22/22 |
| Opus vs Groq | 22 | 21/22 | 16/22 | 21/22 | 22/22 |
| astra vs Groq | 53 | 46/53 | 34/53 | 51/53 | 53/53 |

- Abstention labels agree everywhere. Answer-correctness disagreements are `yes`/`partial` swaps in both directions;
  no `no` labels are involved. Agreement on answer correctness is lower on the larger overlaps (87% to 92%) than on
  the first 22 rows (100%), so "answer correctness is judge-robust" is only supported at roughly that level.
- Unsupported-claim totals depend heavily on the judge even with the same v2 prompt: on the same 53 rows astra reports
  33 unsupported claims and Groq 16, and on the 66 shared rows astra reports 46 against 26 for audited v1. The revised
  prompt did not make unsupported-claim counts converge across judges.
- Two citation disagreements are unexamined: Groq labelled one row `no` where others had `not_applicable`, and astra
  labelled one row `partial` where v1 had `yes`.
- A blinded sheet for human adjudication of the 7 Opus-vs-astra disagreements is
  `reports/quality-judge-disagreement-sheet.md`.

## 4. Evaluator failure modes

1. **Minor wording imprecision counted as unsupported** ("after 9 hours" vs "over 9 hours" was flagged in some rows
   and passed in others because the judge silently rewrote the claim).
2. **Duplicate claims** inflating counts (one answer produced three claims for one point).
3. **Missing qualifiers** ("knowingly", "average") treated as unsupported claims instead of caveats.
4. **Partial-vs-no calibration:** four answers with the central fact but wrong details were `no` and became `partial`.
5. **Judge strictness differs by model** on `minor_imprecision` and unsupported claims, even under the same prompt.

## 5. What this report does and does not support

| claim | supported? |
|---|---|
| Answer correctness is high and shows no format difference on matched cases (v1, corrected) | yes, at 16 to 24 cases per split |
| All 9 negative controls handled correctly | yes (correct abstentions only) |
| fp16 is more fully supported than AWQ on held-out | hypothesis only; prompt-sensitive and unadjusted |
| v2 improves or changes format conclusions | no; v2 has no GPTQ and almost no held-out AWQ/GPTQ coverage |
| Unsupported-claim counts are a reliable metric | no; they differ 2x between judges under the same prompt |
| Any label is deterministic | no, except the 53 Groq rows |
| Any label is human-verified | no |

## 6. Limitations

1. LLM-assisted labels; the v1 correction layer was also produced by an LLM and not checked by a human.
2. Provider-default sampling for v1, Opus and astra; run-to-run agreement unmeasured.
3. v2 covers 22, 66 and 53 of 120 rows from three different judges, in pack order, with no GPTQ rows.
4. Judges differ in strictness, so `fully_supported` and unsupported counts are not comparable across judges.
5. Small samples: 16 to 24 cases per split, 9 negative controls, 9 answers with citations; intervals are wide.
6. Narrow evidence (one PDF, one Wikipedia article); development answers are near ceiling.
7. The judge has not been shown a fabricated answer to a negative control or a clearly wrong citation.
8. The paired exploratory support comparison was not corrected for multiple comparisons.
9. The astra labels record the requested model name only.
10. Two citation disagreements and the 8 low-confidence v1 audit rows are unexamined by a human.

## 7. Recommendation

Report answer correctness, abstention and citations from the corrected v1 labels. Do not headline unsupported-claim
counts. Before treating any support result as a finding: finish one v2 judge on all 120 rows (Groq `gpt-oss-120b` is
the only one that applied `temperature=0`; the run resumes with the same command once its daily cap or tier allows),
adjudicate the 7 disagreement rows and the low-confidence audit rows by hand, then rerun the paired comparison on
those labels.

## 8. Wording

Report: "Answer quality was assessed with LLM-assisted labels from a blinded LLM judge plus an audit correction layer.
The judge rejected temperature=0, so labels were generated with provider-default sampling and are not treated as
deterministic. A revised-prompt rerun was only partially completed and is not used for conclusions. Labels have not
been fully human-verified."

Resume-safe bullet: "Built a blinded LLM-as-judge pipeline for RAG answer quality (answer correctness, citation
correctness, abstention) across FP16, AWQ and GPTQ serving formats; audited the judge, finding that unsupported-claim
scoring varied about 2x between judge models even with the same prompt."

Avoid: "human evaluation", "ground truth", "validated", "statistically significant", "production guarantee", any claim
of temperature 0 for v1, Opus or astra, and "manually spot-checked" unless that check is done.

## 9. Artifacts and reproduction

- v1: `reports/quality-judge-labels.jsonl` (unchanged), `quality-judge-label-audit.{jsonl,md}`,
  `quality-judge-aggregate-corrected.json`, `quality-paired-format-comparison-v1-corrected.json`,
  `answer-quality-final-report-2026-10-06.md` (v1-only report).
- v2 (partial): `quality-judge-labels-v2.jsonl` (Opus, 22), `quality-judge-labels-v2-gpt-6-astra.jsonl` (66),
  `quality-judge-labels-v2-groq-gpt-oss-120b.jsonl` (53), `quality-v2-partial-summary.json`,
  `quality-judge-compare-opus-vs-astra-22.json`, `quality-judge-disagreement-{sheet.md,verdicts.jsonl,selection.json}`.
- Corrected pack copy: `quality-review-pack-citations-fixed.jsonl`. Superseded draft:
  `answer-quality-v2-report-2026-10-06-DRAFT.md`.
- Tools: `eval/judge_prompt.py`, `judge_answer_review_pack.py`, `aggregate_judge_labels.py`, `audit_judge_labels.py`,
  `compare_judge_labels.py`, `paired_format_comparison.py`, `summarize_judge_runs.py`, `build_disagreement_sheet.py`,
  `build_spot_check_sheet.py`, `refresh_pack_citations.py`, `citations.py`, each with tests.

```bash
python -m eval.summarize_judge_runs --judge opus_v2=reports/quality-judge-labels-v2.jsonl \
  --judge astra_v2=reports/quality-judge-labels-v2-gpt-6-astra.jsonl \
  --judge groq_v2=reports/quality-judge-labels-v2-groq-gpt-oss-120b.jsonl
python -m eval.paired_format_comparison --audit reports/quality-judge-label-audit.jsonl
# resume Groq (same command, skips judged rows):
python -m eval.judge_answer_review_pack --judge-provider groq --judge-model openai/gpt-oss-120b \
  --output reports/quality-judge-labels-v2-groq-gpt-oss-120b.jsonl
```
