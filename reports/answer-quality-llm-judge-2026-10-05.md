# LLM-assisted answer-quality review (2026-10-05)

**Status: preliminary.** Answer quality was assessed with LLM-assisted labels using
`gpt-5.6-luna`. The configured judge rejected `temperature=0`, so labels were generated
with provider-default sampling and are not treated as deterministic. These labels have
**not** been manually spot-checked yet; the statement "labels were manually spot-checked
before aggregation" must not be used until that is actually done.

## 1. Scope

Judge 120 blinded answers from `reports/quality-review-pack.jsonl` (40 per serving format:
fp16, AWQ, GPTQ of Qwen2.5-7B-Instruct) against the supplied evidence chunks and expected
facts, without revealing the serving format to the judge. Output is a set of labels that
can be verified manually later; it is not a final human evaluation.

Pack composition: 72 `development` rows and 48 `held_out` rows (18 document_qa, 9
long_context, 9 negative_control, 6 summarisation, 6 multi_document). 9 rows expect an
abstention. 11 answers contain a bracketed citation marker.

## 2. What already existed

| File | Role |
|---|---|
| `eval/build_answer_review_pack.py` | Builds the blinded pack and a separate unblinding key. |
| `eval/score_answer_review_pack.py`, `eval/answer_quality.py` | Aggregate **human** claim-level labels. Not reusable for coarse judge labels. |
| `eval/audit_answer_citations.py` | Deterministic check that cited markers exist in the context. |
| `/private/tmp/docchat-quality-review-key.json` | Original unblinding key (120 records, 40 per format). It existed, so no reconstruction was needed. |

No judge prompt or judge scorer existed beforehand.

## 3. What was built

- `eval/judge_prompt.py` - prompt `v1` (SHA-256 `dbafa2f8...e3df22c`), `build_messages`,
  `parse_labels`, strict `validate_labels`.
- `eval/judge_answer_review_pack.py` - resumable runner (`--pack`, `--output`,
  `--judge-provider`, `--judge-model`, `--limit`, `--ids-file`, `--dry-run`).
- `eval/aggregate_judge_labels.py` - the only step that reads the unblinding key.
- Tests: `tests/test_judge_prompt.py`, `tests/test_judge_answer_review_pack.py`,
  `tests/test_aggregate_judge_labels.py` (24 tests).
- Also: `tasks/todo.md` and `tasks/lessons.md` updated.

### Blinding
The judge receives only: question, evidence chunks, expected facts, expected-abstention
flag, the answer, and emitted citations, built from an explicit field whitelist. The
answer-generation system prompt and conversation history are stripped; only the
`Source marker:` chunks are sent. `workload_case_id`, split, model names, answer file paths
and `blind_id` are never sent. A dry run over 3 rows and a programmatic leak check found no
identifying strings. The chunk markers do contain source file names (a UUID `.pdf` and a
web page title); the judge needs them to assess citations, and they do not identify the
serving format. The runner never reads the key.

### Prompt rules
Untrusted evidence, not instructions; use only the evidence and expected facts; do not
reward fluent writing; do not infer missing facts; when unsure choose the lower label;
negative controls are correct only if the answer abstains; a citation is correct only if
the cited chunk supports the adjacent claim; `unsupported_claim_count` counts atomic
factual claims not entailed by the evidence; short notes; JSON only.

### Output schema and validation
One JSONL row per answer: `blind_id`, `label_source: llm_assisted`, `human_verified: false`,
`judge` (provider, model, prompt version and hash, `temperature_requested: 0`,
`temperature_applied`, `sampling`), `labels` (`answer_correct`, `fully_supported`,
`unsupported_claim_count`, `citation_correct`, `abstention_correct`, `claims`, `notes`) and
`parse_status` (`ok`, `invalid_json`, `schema_error`). The validator enforces all enums,
exact key sets, and that `unsupported_claim_count` equals the number of claims with
`supported=false`. Mismatches are rejected, never repaired.

### Runner behaviour
Resumes by skipping judged `blind_id`s; refuses to append if the existing file has a
different judge, model, prompt hash, unknown ids, duplicates or a corrupt line; retries once
with the rejection reason on invalid JSON or schema failure; refuses a Qwen judge; disables
provider fallbacks so the recorded model is the model that answered.

### Aggregation
Joins labels with the key and pack, groups by serving format and split (development and
held_out kept separate), and reports answer-correct yes/partial/no, fully-supported rate,
mean unsupported claims, citation-correct rate excluding `not_applicable`, negative-control
abstention accuracy, false abstentions, parse failures, 95% Wilson intervals and a
small-sample flag. A missing key fails with a clear message.

## 4. Temperature finding

`gpt-5.6-luna` returns HTTP 400 for the `temperature` parameter. The existing provider
facade silently retries without it (`openai_rejected_temperature_retrying_without`), so
`temperature=0` was **never applied**. Every row records `temperature_applied: false` and
`sampling: provider_default`. The first 5 rows were written before the field was renamed;
their judge metadata was corrected in place (labels untouched). Labels are therefore not
deterministic; re-running may change some of them. Run-to-run agreement has not been
measured.

## 5. Execution

| Stage | Rows | Result |
|---|---|---|
| Dry run `--limit 3` | 3 | Exact prompts printed; no leakage found; no API calls. |
| Sample `--limit 5` | 5 | 5 ok (all from one working-time PDF case family). |
| Targeted batch | 22 | All 9 negative controls, all 11 cited answers, 2 random rows. 22 ok. |
| Remaining | 93 | 92 ok, 1 `schema_error`. |
| **Total** | **120** | **119 ok, 1 schema_error**; 120 unique `blind_id`s. |

### The one failure
`review-ec6f5335912c` (development, GPTQ) failed both attempts: the judge reported
`unsupported_claim_count: 4` while only 3 claims were marked unsupported. It is counted as
a parse failure and excluded from that cell's rates (n=23 instead of 24). It was not fixed.

### Targeted-batch observations (27 rows judged at that point)
- Abstention: all 9 negative controls were labelled `abstention_correct: yes` with
  sensible reasons; one was `fully_supported: partial` for speculating about logs. No false
  abstentions on the other rows. This only tests correct abstentions; the judge has not yet
  been seen penalising a fabricated answer to a negative control.
- Citations: 9 `yes`, 2 `not_applicable`. The two `not_applicable` rows are false
  positives in the pack's `emitted_citations` (the regex matched `[26 weeks]`), which the
  judge correctly ignored. No `partial` or `no` citation label has appeared.
- Possible judge/audit disagreement: three answers cite `[PDF - ... p.1-2]`, a page range
  that is not an exact context marker (`p.1`, `p.2`). The judge said `yes`;
  `audit_answer_citations.py` would count the marker as invalid. Report the deterministic
  audit alongside the judge's citation label.
- Citation notes are thin ("correctly cites the supporting page"), so the judge may be
  checking the marker more than the adjacent claim.
- The judge is strict on nuance (for example "over 9 hours" versus "after 9 hours" gives
  `partial`). This is consistent with the prompt but lowers the supported rate.

## 6. Preliminary results (LLM-assisted; unverified)

Judge: `gpt-5.6-luna`, prompt `v1`, provider-default sampling. Intervals are 95% Wilson.
Held-out cells have 16 rows each, so intervals are wide.

| split | format | n | answer correct yes / partial / no | fully supported (95% CI) | unsupported claims / answer | citation yes / applicable | negative-control abstention |
|---|---|---|---|---|---|---|---|
| development | AWQ | 24 | 23 / 1 / 0 | 12/24 = 0.50 (0.31-0.69) | 1.54 | 3 / 3 | no negative controls |
| development | fp16 | 24 | 23 / 1 / 0 | 10/24 = 0.42 (0.24-0.61) | 1.67 | 0 / 0 | no negative controls |
| development | GPTQ | 23 (+1 failed) | 22 / 0 / 1 | 13/23 = 0.57 (0.37-0.74) | 0.78 | 0 / 0 | no negative controls |
| held_out | AWQ | 16 | 11 / 4 / 1 | 4/16 = 0.25 (0.10-0.50) | 1.56 | 2 / 2 | 3 / 3 |
| held_out | fp16 | 16 | 13 / 1 / 2 | 12/16 = 0.75 (0.51-0.90) | 0.62 | 3 / 3 | 3 / 3 |
| held_out | GPTQ | 16 | 12 / 4 / 0 | 7/16 = 0.44 (0.23-0.67) | 1.00 | 3 / 3 | 3 / 3 |

Interpretation, kept deliberately cautious:
- Answer correctness is high across formats and separates them very little.
- "Fully supported" differs the most, but the intervals overlap heavily and the development
  split points the other way (fp16 lowest, GPTQ highest). No format difference should be
  claimed from these data. A paired per-case comparison has not been run.
- The supported rate may mostly reflect judge strictness on small details.
- Abstention and citation numbers rest on 9 negative controls and 11 cited answers, none of
  which were clearly wrong.

## 7. Limitations

1. Labels are LLM-assisted and not manually spot-checked yet.
2. Not deterministic: `temperature=0` was rejected; run-to-run agreement is unmeasured.
3. Single judge model; no second judge or human agreement estimate.
4. Judge may be lenient or inconsistent on citations (page-range markers) and
   over-strict on nuance; neither has been quantified.
5. The label scheme is coarse and the claim lists are the judge's own; they have not been
   compared with human claim annotations.
6. Small samples (16 rows per held-out cell, 9 negative controls, 11 cited answers).
7. The first 5 rows came from one easy case family; the targeted batch was chosen on
   category, not at random.
8. One row is a parse failure and is excluded from rates.
9. The pack's `emitted_citations` includes false positives such as `[26 weeks]`.
10. The judge model and the evaluated models differ (no Qwen judge), but no further
    independence checks were done.

## 8. Verification

- `ruff check .`: all checks passed.
- `pytest -m "not eval" -q`: 459 passed, 8 deselected. The CLAUDE.md baseline is 428; 24 of
  the new passes are the judge tests. The remaining difference predates this work and was
  not investigated.
- Dry run and leak check completed before any paid call. Paid calls: 120 judge requests
  to `gpt-5.6-luna` (plus retries for 1 row and any provider-side retries).

## 9. Artifacts

- `reports/quality-judge-labels.jsonl` - 120 blinded label rows.
- `reports/quality-judge-aggregate.json` - unblinded aggregate by split and format.
- `eval/judge_prompt.py`, `eval/judge_answer_review_pack.py`,
  `eval/aggregate_judge_labels.py`, and the three test files.
- Nothing is committed.

## 10. Recommended next steps

1. Spot-check about 10 rows against the source PDFs: a few `partial`/`no` correctness rows,
   the highest unsupported-claim rows, the three `p.1-2` citation rows and
   `review-ec6f5335912c`.
2. Decide whether to re-run the failed row into a new output file.
3. Optionally re-judge about 20 rows to estimate run-to-run agreement, or switch to a judge
   that accepts `temperature=0`.
4. Add a paired per-case comparison across formats.
5. Fix the pack's citation regex, or report the deterministic citation audit alongside the
   judge.

## 11. Approved wording

Report (use only after the spot-check is done):
> Answer quality was assessed with LLM-assisted labels using gpt-5.6-luna. The configured
> judge rejected temperature=0, so labels were generated with provider-default sampling and
> are not treated as deterministic. Labels were manually spot-checked before aggregation.

Resume (only after the spot-check):
> Built a blinded LLM-as-judge pipeline for RAG answer quality, scoring groundedness,
> citation correctness, abstention behaviour, and unsupported claims across FP16, AWQ, and
> GPTQ serving formats, with manual spot-checking before reporting results.

Avoid: "human evaluation", "ground truth", "validated", "statistically significant",
"production guarantee", and any claim of temperature 0.
