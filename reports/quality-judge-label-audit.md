# Judge label audit (LLM-assisted labels, audited by an LLM reviewer)

**Status: suggested corrections, not human-verified.** The original labels in `reports/quality-judge-labels.jsonl` are unchanged (sha256 `fde8cb93ff88256a...`). Corrections are in `reports/quality-judge-label-audit.jsonl`. The audit was performed by reading the supplied evidence for each flagged claim; it has the same class of limitation as the judge itself and should be spot-checked, starting with `low`/`medium` confidence rows.

## Summary

- Rows audited: 79 (59 corrected, 1 flagged only, 19 confirmed unchanged).
- Total unsupported claims: 146 -> 43 across 119 scored rows.
- Rows with at least one unsupported claim: 61 -> 28.
- Reclassified claims by category: minor_imprecision 68, entailed_by_evidence 20, wording_equivalent 4, duplicate_claim 4, omitted_qualifier 4, not_a_factual_claim 3.
- Claims left as unsupported are contradictions of the evidence or new checkable details (examples, definitions with content, properties not in the evidence, over-guarantees).

## Calibration rules applied

1. `45 minutes after 9 hours` vs evidence `45 minutes for over 9 hours`: wording-equivalent, not unsupported.
2. Central expected fact present plus wrong/unsupported details: `answer_correct` is `partial`, not `no`.
3. Omitted qualifiers (`knowingly`, `average`): `fully_supported` stays `partial`, not an unsupported claim.
4. Unsupported means contradicted, or adds new checkable detail. Minor imprecision, duplicates, entailed paraphrases and non-claims do not count.

## 45-minute / 9-hour consistency

The same wording was judged inconsistently. Some rows flagged it unsupported; others passed it because the judge silently rewrote the claim as 'over 9 hours' before judging.

| blind_id | judge claim flagged? | suggestion |
|---|---|---|
| review-4c308495aab5 | flagged unsupported | treat as wording-equivalent |
| review-60731b99edf3 | flagged unsupported | treat as wording-equivalent |
| review-d13f75103b53 | flagged unsupported | treat as wording-equivalent |
| review-fad6904cb327 | flagged unsupported | treat as wording-equivalent |

Rows that mention it but were passed by the judge (no change needed): `403bec`, `51c529`, `48692a`, `915eb1`, `2579be`, `27bdd3`, `51bc83`, `101b0d`.

## Sensitivity: does the correction change the format comparison?

Uses the unblinding key (aggregation-stage only). Preliminary and LLM-assisted. `strict` applies every correction except the subjective `minor_imprecision` reclassifications, so it is the conservative bound; `full` applies all of them.

| split | format | n | fully supported before / strict / full | unsupported per answer before / strict / full | answer yes before -> after |
|---|---|---|---|---|---|
| development | awq | 24 | 0.50 / 0.50 / 0.50 | 1.54 / 1.25 / 0.50 | 0.96 -> 0.96 |
| development | fp16 | 24 | 0.42 / 0.46 / 0.46 | 1.67 / 1.42 / 0.50 | 0.96 -> 0.96 |
| development | gptq | 23 | 0.57 / 0.57 / 0.57 | 0.78 / 0.61 / 0.30 | 0.96 -> 0.96 |
| held_out | awq | 16 | 0.25 / 0.31 / 0.31 | 1.56 / 0.94 / 0.44 | 0.69 -> 0.75 |
| held_out | fp16 | 16 | 0.75 / 0.75 / 0.75 | 0.62 / 0.38 / 0.12 | 0.81 -> 0.88 |
| held_out | gptq | 16 | 0.44 / 0.56 / 0.56 | 1.00 / 0.75 / 0.19 | 0.75 -> 0.88 |

## Per-row audit

`conf` is the lowest confidence among the row's decisions. Labels shown as original -> suggested (answer / supported / unsupported count / citation).

| blind_id | status | issues | original | suggested | conf | reason |
|---|---|---|---|---|---|---|
| review-32d098023f30 | corrected | minor_imprecision | yes/partial/4/not_applicable | yes/partial/3/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-76bc07039f7b | corrected | answer_no_with_central_fact | no/partial/2/not_applicable | partial/partial/2/not_applicable | high | Rule 2: the central fact '48 hours per week' is present; the 26-week-default and 52-week claims are wrong. |
| review-fc1bf209234a | corrected | not_a_factual_claim | yes/partial/1/not_applicable | yes/yes/0/not_applicable | high | Suggestion attached to a correct abstention; not a claim about the evidence. |
| review-a8ce860a2557 | corrected | entailed_by_evidence | yes/partial/4/not_applicable | yes/partial/2/not_applicable | medium | Evidence: RAG improves the accuracy of LLMs. (+1 more) |
| review-fc87fe0ddb55 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-c2f7e90e6ab0 | corrected | entailed_by_evidence, minor_imprecision | yes/partial/3/not_applicable | yes/partial/1/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. (+1 more) |
| review-4b81b70f2ef1 | corrected | entailed_by_evidence, minor_imprecision | partial/partial/3/not_applicable | partial/partial/1/not_applicable | medium | Evidence: Retro incurs the 'high cost of training runs'. (+1 more) |
| review-13fc5c101b0d | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-d13f75103b53 | corrected | flag, wording_equivalent | partial/partial/1/yes | yes/yes/0/yes | high | Only issue was the 45-minute/9-hour wording; remaining content matches the evidence. |
| review-4c6d51113c0b | corrected | entailed_by_evidence, flag, minor_imprecision | yes/partial/5/not_applicable | yes/partial/1/not_applicable | medium | Evidence: augment the external knowledge base with updated information. (+3 more) |
| review-d46c021238d6 | flagged | flag | yes/yes/0/yes | yes/yes/0/yes | high | degenerate_repetition: the Sources list repeats the same marker 24 times. Citations are correct, but this is a generation defect worth repor |
| review-6eb5251275dc | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/1/not_applicable | medium | Evidence: LLMs can misinterpret context; 'requires careful handling' is advice. |
| review-4a686e159a89 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-f8873f18d26c | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-3dd8eb1c2c77 | confirmed | - | yes/yes/0/yes | yes/yes/0/yes | high | verified; no change |
| review-05af11225e81 | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/1/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-4d11f72579be | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Breaks are stated as MUST; the health-and-safety purpose is stated for the Regulations generally. |
| review-b1afbb27bdd3 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-6b40b4301e84 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-4eaee9323a73 | confirmed | - | yes/partial/1/not_applicable | yes/partial/1/not_applicable | high | verified; 1 unsupported claim(s) retained: Semi-structured data includes JSON or XML. |
| review-81c8b833798d | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Evidence: chart is filled 'as if you were engaged in other work'; 'paid employment' narrows it. |
| review-0b4fde3d95ce | corrected | entailed_by_evidence, minor_imprecision | yes/partial/4/not_applicable | yes/partial/1/not_applicable | low | Restates the question; evidence: high cost of training runs. (+2 more) |
| review-1f041e402026 | corrected | entailed_by_evidence, minor_imprecision | yes/partial/3/not_applicable | yes/partial/0/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. (+2 more) |
| review-4efc1b403bec | corrected | minor_imprecision | partial/partial/3/not_applicable | partial/partial/2/not_applicable | low | Evidence ties the records requirement to operations under EU drivers' hours rules; 'aim' is a loose paraphrase. |
| review-377eea428060 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Evidence: augment the knowledge base when new information appears. |
| review-716bf4443dfa | corrected | minor_imprecision, not_a_factual_claim | yes/partial/4/not_applicable | yes/partial/1/not_applicable | low | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. (+2 more) |
| review-475be74548d2 | confirmed | - | yes/yes/0/yes | yes/yes/0/yes | high | verified; no change |
| review-bf70cd45a3ed | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | low | Evidence mentions retrieving top-k vectors (training context) and selecting the most relevant documents; the answer merges them. |
| review-49da6548692a | corrected | minor_imprecision | yes/partial/3/not_applicable | yes/partial/0/not_applicable | low | Evidence: workers must accurately record Working Time; employment businesses must keep records. (+2 more) |
| review-fad6904cb327 | corrected | duplicate_claim, omitted_qualifier, wording_equivalent | partial/partial/5/not_applicable | partial/partial/0/not_applicable | medium | Evidence: '45 minutes for over 9 hours'. 'After 9 hours' states materially the same requirement; at most a wording caveat. (+4 more) |
| review-f6672b4dfcd1 | corrected | minor_imprecision, not_a_factual_claim | yes/partial/3/not_applicable | yes/partial/0/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. (+2 more) |
| review-df49464e8417 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-91cee04fdad0 | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/1/not_applicable | medium | Loose restatement of 'no retraining needed'. |
| review-5951ab500a82 | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/0/not_applicable | medium | Tautological gloss of a term in the question; adds no checkable fact. (+1 more) |
| review-ceba2951bc83 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-89fe7b51c529 | corrected | answer_no_with_central_fact, entailed_by_evidence | no/partial/3/not_applicable | partial/partial/2/not_applicable | high | Rule 2: both sources are compared correctly; the charity-work treatment and a vague synthesis claim are wrong/unsupported. |
| review-cb39855381fb | confirmed | - | yes/yes/0/yes | yes/yes/0/yes | high | verified; no change |
| review-0e370a548c2b | corrected | duplicate_claim | partial/partial/2/not_applicable | partial/partial/1/not_applicable | high | Restates the 52-week claim already counted. |
| review-c08d2a58b4ea | corrected | minor_imprecision | yes/partial/1/yes | yes/partial/0/yes | medium | Evidence: both types must be declared, and charity work is charted 'as if other work'; 'regular work assignments' blends the two. |
| review-601cfd60a453 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-bee0f663c48f | corrected | entailed_by_evidence, minor_imprecision | yes/partial/10/not_applicable | yes/partial/5/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. (+4 more) |
| review-78a5ee671389 | corrected | minor_imprecision | yes/partial/1/yes | yes/partial/0/yes | medium | Evidence: 'greater transparency'; accountability is a near-synonym gloss. |
| review-343610693d25 | corrected | minor_imprecision | yes/partial/6/not_applicable | yes/partial/5/not_applicable | medium | Evidence: RAG can be used on unstructured (usually text), semi-structured or structured data. |
| review-1625456c778c | corrected | minor_imprecision | yes/partial/3/not_applicable | yes/partial/1/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. (+1 more) |
| review-a2f6f26d422b | corrected | citation_label, omitted_qualifier | partial/partial/1/yes | yes/partial/0/not_applicable | low | Only issue was the omitted 'average' qualifier on the 48-hour limit (caveat). |
| review-318338735b1c | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Evidence is healthcare-specific (reviews note evaluation, ethics, clinical-reliability challenges); answer generalises it to RAG. Scope broa |
| review-fb0a257379a8 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-7d26ab7966af | corrected | citation_label | yes/yes/0/yes | yes/yes/0/not_applicable | medium | No source marker or source reference in the answer; 'Regulation 18 of the RTWT Regulations' is part of the stated fact, not a citation. |
| review-b0ccf6843843 | corrected | entailed_by_evidence, minor_imprecision | yes/partial/4/not_applicable | yes/partial/1/not_applicable | medium | Evidence: sparse vectors encode word identity; dense vectors encode meaning. (+2 more) |
| review-461cb686be01 | corrected | entailed_by_evidence, minor_imprecision | yes/no/6/not_applicable | yes/partial/2/not_applicable | low | Evidence: 'high cost of training runs'. (+3 more) |
| review-9ab1ff8c3aa4 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. |
| review-0da3dd915eb1 | corrected | entailed_by_evidence | partial/partial/1/yes | yes/yes/0/yes | medium | Only issue was '48 hours over 26 weeks', which the declaration itself applies. |
| review-9304ac91674a | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. (+1 more) |
| review-6f4646916caa | corrected | minor_imprecision | yes/partial/2/not_applicable | yes/partial/1/not_applicable | medium | Evidence is healthcare-specific (reviews note evaluation, ethics, clinical-reliability challenges); answer generalises it to RAG. Scope broa |
| review-4c308495aab5 | corrected | omitted_qualifier, wording_equivalent | partial/partial/2/not_applicable | yes/partial/0/not_applicable | medium | Remaining issues are the 45/9 wording and the omitted 'knowingly' qualifier (caveats). (+1 more) |
| review-f96f0795f744 | confirmed | - | yes/partial/1/not_applicable | yes/partial/1/not_applicable | high | verified; 1 unsupported claim(s) retained: Prompt stuffing can introduce its own biases and inaccuracies. |
| review-60731b99edf3 | corrected | flag, minor_imprecision, wording_equivalent | partial/partial/2/yes | partial/partial/0/yes | medium | Evidence: '45 minutes for over 9 hours'. 'After 9 hours' states materially the same requirement; at most a wording caveat. (+1 more) |
| review-dc9f329c0604 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-51c848a49ed8 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-b193f3a69617 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-3852caae4de7 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-134028b16d48 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. |
| review-8c420eb97ba5 | corrected | minor_imprecision | yes/partial/4/not_applicable | yes/partial/1/not_applicable | medium | Evidence describes hallucinations as invented policies/cases; 'nonsensical' is an added gloss. (+2 more) |
| review-9d3b5cc6add3 | corrected | minor_imprecision | yes/partial/5/not_applicable | yes/partial/1/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. (+3 more) |
| review-8f71b7c7afa2 | corrected | duplicate_claim, minor_imprecision | partial/partial/2/not_applicable | partial/partial/0/not_applicable | medium | Hedged gloss, not a firm claim. (+1 more) |
| review-f2e784d114ea | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-435c75d13470 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-20f94bd142ef | confirmed | - | partial/partial/1/not_applicable | partial/partial/1/not_applicable | high | verified; 1 unsupported claim(s) retained: Lacking sufficient information leads to prompt stuffing. |
| review-3872c7d21513 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-758358d25880 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-2acc14e414d9 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Adds 'efficient/quick' to the supported statement that embeddings are stored in a vector database to allow retrieval. |
| review-54c156e713f3 | corrected | entailed_by_evidence | yes/partial/1/not_applicable | yes/yes/0/not_applicable | medium | The 60-hour weekly limit is its own bullet, independent of the averaging reference period. |
| review-5a7a93ea96e0 | corrected | minor_imprecision | yes/partial/1/not_applicable | yes/partial/0/not_applicable | medium | Generic evaluative gloss on a supported statement; no new checkable fact. |
| review-5ac79aeb6a44 | corrected | entailed_by_evidence, minor_imprecision | yes/partial/2/not_applicable | yes/partial/0/not_applicable | medium | Evidence: users can verify the cited sources. (+1 more) |
| review-8c926cee41bd | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
| review-afbedaf210f8 | corrected | answer_no_with_central_fact | no/partial/1/not_applicable | partial/partial/1/not_applicable | high | Rule 2: purposes and key facts of both sources are covered; one wrong detail (reference-period start dates). |
| review-1c33d8f99645 | corrected | entailed_by_evidence, minor_imprecision | yes/partial/6/not_applicable | yes/partial/1/not_applicable | low | Evidence: sparse vectors encode a word's identity and are dictionary-length. (+4 more) |
| review-b8cfd9f99a75 | corrected | answer_no_with_central_fact, entailed_by_evidence, minor_imprecision | no/partial/4/not_applicable | partial/partial/1/not_applicable | medium | Rule 2: the answer covers RAG's capabilities, limits and verification; one overclaim ('ensures grounded') does not make it incorrect. (+2 more) |
| review-33b0a1ff99f6 | confirmed | - | yes/yes/0/not_applicable | yes/yes/0/not_applicable | high | verified; no change |
