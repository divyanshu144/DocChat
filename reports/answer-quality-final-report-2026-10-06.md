# DocChat answer-quality review: final report (v1 labels + audit correction layer)

**Status: LLM-assisted labels, audited by an LLM reviewer. Not human-verified.**
Answer quality was assessed with LLM-assisted labels using `gpt-5.6-luna`. The configured judge
rejected `temperature=0`, so labels were generated with provider-default sampling and are not
treated as deterministic. A correction layer produced by an LLM audit (not a human) is applied to
answer, abstention and citation labels. Unsupported-claim scoring is exploratory only.

## 1. Method

- **Data:** 120 blinded answers (72 `development`, 48 `held_out`) produced by three serving
  formats of one model (fp16, AWQ, GPTQ; 40 each). Held-out rows: 18 document_qa, 9 long_context,
  9 negative_control, 6 summarisation, 6 multi_document. Evidence is one working-time declaration
  PDF and one Wikipedia article on RAG (29 distinct chunks).
- **Judge:** `gpt-5.6-luna` via the existing provider facade, prompt `v1` (sha256
  `dbafa2f8...e3df22c`). Temperature `0` was requested but the model returned HTTP 400 for it, so the
  facade silently dropped it; every row records `temperature_applied: false`,
  `sampling: provider_default`. Labels may change on re-run; run-to-run agreement was not measured.
- **Blinding:** the judge saw only the question, evidence chunks (generation prompt and history
  stripped), expected facts, the answer, the expected-abstention flag and emitted citations. No model
  name, split, case id, file name or `blind_id`. The unblinding key was read only at aggregation.
- **Parsing:** strict schema validation, one retry. 119 rows parsed; 1 row
  (`review-ec6f5335912c`, development, GPTQ) failed twice with a claim-count mismatch and is excluded
  and counted as a parse failure. Not repaired.
- **Audit/correction layer:** each flagged claim and each abstention, citation and `no` row was
  re-read against the evidence by an LLM reviewer. Corrections are explicit per-claim decisions with a
  category, reason and confidence, stored separately. The original labels file is unchanged
  (sha256 `fde8cb93ff88256a...`). 79 rows were audited; 59 changed.
  Details: `reports/quality-judge-label-audit.{jsonl,md}`.

## 2. Key metrics (corrected labels)

Corrected labels are used for answer correctness, abstention correctness and citation correctness.
Development and held-out are reported separately. 95% intervals are Wilson intervals and are wide.

### Answer correctness

| split | format | scored | yes | partial | no | yes-rate (95% CI) |
|---|---|---|---|---|---|---|
| development | AWQ | 24 | 23 | 1 | 0 | 0.96 (0.80-0.99) |
| development | fp16 | 24 | 23 | 1 | 0 | 0.96 (0.80-0.99) |
| development | GPTQ | 23 (+1 parse failure) | 22 | 1 | 0 | 0.96 (0.79-0.99) |
| held_out | AWQ | 16 | 12 | 4 | 0 | 0.75 (0.51-0.90) |
| held_out | fp16 | 16 | 14 | 2 | 0 | 0.88 (0.64-0.97) |
| held_out | GPTQ | 16 | 14 | 2 | 0 | 0.88 (0.64-0.97) |

`partial` is kept separate from `yes`. Development answers are near ceiling for all formats. On
held-out, AWQ has more `partial` answers (4 vs 2), but the intervals overlap heavily and no format
difference should be claimed from these data.

### Abstention (negative controls)

| split | format | negative controls handled correctly | false abstentions on answerable questions |
|---|---|---|---|
| held_out | AWQ | 3 / 3 | 0 / 13 |
| held_out | fp16 | 3 / 3 | 0 / 13 |
| held_out | GPTQ | 3 / 3 | 0 / 13 |

**All 9 negative controls were handled correctly after the audit.** Each answer states that the
context does not contain the requested DocChat-specific information (Slack incident ID, service owner
and on-call number, auto-approval threshold). One carried a spurious unsupported-claim flag for a
suggestion attached to a correct abstention; the audit removed it. Development has no negative
controls. Caveat: this only tests correct abstentions, since no answer fabricated a response to a
negative control, so the judge has not been shown to penalise one.

### Citation correctness

| split | format | answers with real citation markers | judged correct |
|---|---|---|---|
| development | AWQ | 2 | 2 |
| development | fp16 | 0 | n/a |
| development | GPTQ | 0 | n/a |
| held_out | AWQ | 1 | 1 |
| held_out | fp16 | 3 | 3 |
| held_out | GPTQ | 3 | 3 |

Only 9 answers contain source markers. **Cited-answer handling needed small corrections:**
- Two answers (`7966af`, `6d422b`) were labelled `yes` although they contain no citation marker;
  changed to `not_applicable` (the second is low confidence).
- Two pack rows were counted as cited because a regex matched `[26 weeks]`, which is not a citation
  (the judge already ignored them).
- Two answers cite a page range (`p.1-2`) that is not an exact context marker. Both chunks do support
  the answer, so the label stays `yes`, but the deterministic citation audit would count the marker
  invalid; report that audit alongside the judge.
- One answer lists the same source 24 times, a generation defect (`1238d6`), flagged separately.

With 9 cited answers and no `partial`/`no` citation label ever produced, this metric has not been
stress-tested.

## 3. Evaluator failure modes found by the audit

1. **Minor wording imprecision counted as unsupported.** The evidence says "45 minutes for over 9
   hours"; answers saying "after 9 hours" were flagged unsupported in 4 rows but passed in others
   because the judge silently rewrote the claim. Generic glosses ("enhances trust", "efficient
   retrieval") were counted the same as contradictions.
2. **Duplicate claims.** The judge listed restatements separately (one answer produced three claims
   for one 45/9 point; another two near-identical 52-week claims), inflating counts.
3. **Missing qualifiers.** "Knowingly" (criminal offence) and "average" (48-hour limit) were counted
   as unsupported claims; they are better treated as caveats that make a row `partial`.
4. **Partial-vs-no calibration.** Four answers containing the central fact or covering the question
   but with wrong surrounding details were labelled `no`; all four became `partial`. In the other
   direction, one answer keeps a contradicted claim yet is `yes`, so correctness was lenient while
   support was harsh.

## 4. Exploratory only: unsupported-claim scoring

Not a headline metric. The audit found strong sensitivity to how small imprecisions are treated:
across 119 scored rows, unsupported claims fall from 146 (original) to 111 under strict
(objective-only) corrections and to 43 under full corrections, and rows with at least one unsupported
claim fall from 61 to 54 and 28. The "fully supported" yes-rate moves little (58/119 original to
62/119) because corrected rows mostly become `partial`.

| split | format | fully supported (original / strict / full) | unsupported per answer (original / strict / full) |
|---|---|---|---|
| development | AWQ | 0.50 / 0.50 / 0.50 | 1.54 / 1.25 / 0.50 |
| development | fp16 | 0.42 / 0.46 / 0.46 | 1.67 / 1.42 / 0.50 |
| development | GPTQ | 0.57 / 0.57 / 0.57 | 0.78 / 0.61 / 0.30 |
| held_out | AWQ | 0.25 / 0.31 / 0.31 | 1.56 / 0.94 / 0.44 |
| held_out | fp16 | 0.75 / 0.75 / 0.75 | 0.62 / 0.38 / 0.12 |
| held_out | GPTQ | 0.44 / 0.56 / 0.56 | 1.00 / 0.75 / 0.19 |

On held-out, AWQ has the most unsupported claims and fp16 the fewest in all three versions; on
development the order is not stable. Neither is a reliable result at 16 rows per cell, and the
`full` column rests on 68 subjective reclassifications made by an LLM reviewer.

## 5. Recommendation

Rerun with a revised `v2` prompt before using unsupported-claim counts as a headline metric. v2
should: dedupe claims; add a separate `minor_imprecision` label distinct from `unsupported`; state
the wording-equivalence and partial-vs-no rules; and ideally use a judge that accepts
`temperature=0`. Until then, report answer, abstention and citation results (with this correction
layer) and present unsupported-claim numbers only as the exploratory ranges above. Also spot-check the
8 low-confidence audit rows (`3d95ce`, `403bec`, `443dfa`, `45a3ed`, `48692a`, `6d422b`, `86be01`,
`f99645`) and a sample of the corrected rows by hand.

## 6. Resume-safe bullet

> Built a blinded LLM-as-judge pipeline for RAG answer quality (answer correctness, citation
> correctness, abstention) across FP16, AWQ and GPTQ serving formats, and audited the judge's labels,
> finding that unsupported-claim scoring was highly sensitive to prompt calibration.

Do not add "manually spot-checked" or "human-verified" unless that check is actually done.

## 7. Limitations

1. LLM-assisted labels; the correction layer was also produced by an LLM and has not been verified
   by a human.
2. Provider-default sampling (`temperature=0` rejected): not deterministic, run-to-run agreement
   unmeasured.
3. One judge model and one audit reviewer; no second judge and no human agreement estimate.
4. Small samples: 16 rows per held-out cell, 9 negative controls, 9 answers with citations. Intervals
   are wide and no format difference is claimed.
5. Narrow evidence (one PDF, one Wikipedia article); the first judged rows were one easy case family
   and the targeted batch was chosen by category.
6. Answer correctness is near ceiling in development, so it separates formats little.
7. Negative controls only show correct abstention; the judge was never shown a fabricated answer to
   one. Citation labels never produced `partial` or `no`.
8. One row is a parse failure and is excluded; the pack's citation regex had false positives.
9. Unsupported-claim metrics are exploratory and prompt-sensitive; 68 of the reclassifications are
   subjective.
10. The judge was not a Qwen model, but no further independence checks were made.

## 8. Reproduction and artifacts

```bash
python -m eval.aggregate_judge_labels --audit reports/quality-judge-label-audit.jsonl \
  --output reports/quality-judge-aggregate-corrected.json
```

- `reports/quality-judge-labels.jsonl` (original, unchanged), `reports/quality-judge-aggregate.json`
  (uncorrected), `reports/quality-judge-aggregate-corrected.json` (corrected),
  `reports/quality-judge-label-audit.{jsonl,md}`, `reports/answer-quality-llm-judge-2026-10-05.md`
  (earlier process report).
- Code: `eval/judge_prompt.py`, `eval/judge_answer_review_pack.py`, `eval/aggregate_judge_labels.py`,
  `eval/audit_judge_labels.py`, `eval/build_spot_check_sheet.py`, with tests.
