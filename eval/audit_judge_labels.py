"""Audit/calibration overlay for the LLM-assisted judge labels.

Original labels are never modified. Every suggested correction is an explicit,
per-claim decision (category + reason + confidence) made by reading the supplied
evidence; the script only applies and validates them. The audit itself was done by
an LLM reviewer, so suggestions are proposals for human verification.

Reclassification categories (claim was flagged unsupported but should not count):
  duplicate_claim      restates a claim already counted
  not_a_factual_claim  suggestion/opinion/abstention rationale, not a claim about the evidence
  wording_equivalent   materially the same as the evidence ("over 9 hours" vs "after 9 hours")
  entailed_by_evidence directly supported or a trivial consequence of the evidence
  minor_imprecision    gloss/paraphrase with no new checkable fact (fully_supported stays partial)
  omitted_qualifier    missing qualifier such as "knowingly"/"average" (fully_supported stays partial)
Claims with no decision are retained as unsupported (contradicted, or new checkable detail).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from eval.judge_prompt import validate_labels

RECLASSIFIED = {"duplicate_claim", "not_a_factual_claim", "wording_equivalent",
                "entailed_by_evidence", "minor_imprecision", "omitted_qualifier"}
CAVEAT = {"minor_imprecision", "omitted_qualifier"}  # keep fully_supported at "partial"
_RANK = {"low": 0, "medium": 1, "high": 2}

W45 = ("wording_equivalent", "Evidence: '45 minutes for over 9 hours'. 'After 9 hours' states materially "
       "the same requirement; at most a wording caveat.", "high")
W45_DUP = ("duplicate_claim", "Restates the 45-minute/9-hour point already counted.", "high")
TAUTOLOGY = ("minor_imprecision", "Tautological gloss of a term in the question; adds no checkable fact.", "medium")
GLOSS = ("minor_imprecision", "Generic evaluative gloss on a supported statement; no new checkable fact.", "medium")
SCOPE = ("minor_imprecision", "Evidence is healthcare-specific (reviews note evaluation, ethics, clinical-reliability "
         "challenges); answer generalises it to RAG. Scope broadened, not invented.", "medium")
EFFICIENT = ("minor_imprecision", "Adds 'efficient/quick' to the supported statement that embeddings are stored in a "
             "vector database to allow retrieval.", "medium")


def D(substring, spec, occurrence=None):
    category, reason, confidence = spec
    return (substring, category, reason, confidence, occurrence)


def d(substring, category, reason, confidence="medium", occurrence=None):
    return (substring, category, reason, confidence, occurrence)


# blind_id suffix -> per-claim reclassifications. Anything not listed stays "unsupported".
DECISIONS: dict[str, list[tuple]] = {
    # --- working-time declaration rows -------------------------------------------------
    "e713f3": [d("This limit applies regardless", "entailed_by_evidence",
                 "The 60-hour weekly limit is its own bullet, independent of the averaging reference period.")],
    "58b4ea": [d("Both types of work should be filled out", "minor_imprecision",
                 "Evidence: both types must be declared, and charity work is charted 'as if other work'; "
                 "'regular work assignments' blends the two.")],
    "103b53": [D("45-minute break is required after 9 hours", W45)],
    "99edf3": [D("45-minute break is required after 9 hours", W45),
               d("26-week rolling reference period", "minor_imprecision",
                 "The declaration applies a 26-week rolling/calendar period; attributing it to 'the Regulations' "
                 "blurs the default 17 weeks versus this operator's 26 weeks.")],
    "915eb1": [d("48 hours per week over a 26-week", "entailed_by_evidence",
                 "Evidence: this declaration calculates average Working Time over a 26-week reference period "
                 "(default 17 weeks, extendable to 26).")],
    "2579be": [d("These breaks are mandatory to ensure", "minor_imprecision",
                 "Breaks are stated as MUST; the health-and-safety purpose is stated for the Regulations generally.")],
    "33798d": [d("as if it were paid employment", "minor_imprecision",
                 "Evidence: chart is filled 'as if you were engaged in other work'; 'paid employment' narrows it.")],
    "91674a": [D("ensures compliance with the RTWT", GLOSS), D("helps maintain accurate records for both", GLOSS)],
    "95aab5": [D("45-minute break after 9 hours", W45),
               d("Failure to comply with these regulations", "omitted_qualifier",
                 "Evidence limits the criminal offence to knowingly breaking the rules; qualifier omitted, so "
                 "partial support rather than an unsupported claim.")],
    "548c2b": [d("is extendable to 52 weeks", "duplicate_claim", "Restates the 52-week claim already counted.", "high")],
    "500a82": [D("Transport work means any work involving", TAUTOLOGY),
               D("Non-transport work means any work not involving", TAUTOLOGY)],
    "403bec": [d("aim to maintain compliance with EU drivers", "minor_imprecision",
                 "Evidence ties the records requirement to operations under EU drivers' hours rules; 'aim' is a loose "
                 "paraphrase.", "low")],
    "4cb327": [D("45-minute break is required after 9 hours", W45),
               D("Breaks are required after 9 hours", W45_DUP), D("Breaks are mandatory after 9 hours", W45_DUP),
               d("Failing to report other work", "omitted_qualifier",
                 "Evidence: failing to inform the employer about other work is an example of *knowingly* breaking "
                 "the rules; qualifier omitted."),
               d("Non-compliance can result in criminal penalties", "omitted_qualifier",
                 "Qualifier 'knowingly' omitted.")],
    "51c529": [d("serve different purposes and operate in distinct domains", "entailed_by_evidence",
                 "A working-time declaration and a RAG article plainly cover different topics.", "high")],
    "6d422b": [d("strict limits on working hours, including a maximum of 48", "omitted_qualifier",
                 "Evidence: 48 hours is a maximum *average* over the reference period; 'average' omitted.")],
    "60a453": [D("requirement is to ensure accurate record-keeping", GLOSS)],
    "48692a": [d("Employers must report all working time accurately", "minor_imprecision",
                 "Evidence: workers must accurately record Working Time; employment businesses must keep records."),
               d("Mobile workers and employers must update each other", "minor_imprecision",
                 "Evidence: the worker must inform the employer; a reciprocal duty is not stated.", "low"),
               D("vector database stores embeddings for efficient retrieval", EFFICIENT)],
    # --- negative control --------------------------------------------------------------
    "09234a": [d("Additional details from relevant logs", "not_a_factual_claim",
                 "Suggestion attached to a correct abstention; not a claim about the evidence.", "high")],
    # --- RAG / Wikipedia rows ----------------------------------------------------------
    "671389": [d("This provides accountability", "minor_imprecision",
                 "Evidence: 'greater transparency'; accountability is a near-synonym gloss.")],
    "45a3ed": [d("top-k most relevant documents", "minor_imprecision",
                 "Evidence mentions retrieving top-k vectors (training context) and selecting the most relevant "
                 "documents; the answer merges them.", "low")],
    "b97ba5": [d("Hallucinations are false or nonsensical", "minor_imprecision",
                 "Evidence describes hallucinations as invented policies/cases; 'nonsensical' is an added gloss."),
               D("Source verification enhances trust", GLOSS),
               D("significantly improves the model's utility", GLOSS)],
    "113c0b": [d("can be updated by modifying documents", "entailed_by_evidence",
                 "Evidence: augment the external knowledge base with updated information.", "high"),
               d("ensures that the model uses the latest", "minor_imprecision",
                 "Overstated 'ensures'; core point (no retraining needed) is supported."),
               D("incorporate new information seamlessly", GLOSS),
               d("leverages the existing model architecture", "minor_imprecision",
                 "Loose restatement of 'no retraining needed'.")],
    "eb6a44": [d("Users can access these sources", "entailed_by_evidence",
                 "Evidence: users can verify the cited sources.", "high"),
               D("enhances the credibility and reliability", GLOSS)],
    "8c3aa4": [D("indexed in the vector database for quick lookup", EFFICIENT)],
    "693d25": [d("primarily designed to handle unstructured", "minor_imprecision",
                 "Evidence: RAG can be used on unstructured (usually text), semi-structured or structured data.")],
    "402026": [D("stored in a vector database to facilitate efficient", EFFICIENT),
               d("retriever compares the query with stored embeddings", "entailed_by_evidence",
                 "Evidence: 'This comparison can be done using a variety of methods' after the query is received."),
               D("ensures that the LLM has access to the most pertinent", GLOSS)],
    "023f30": [D("enhances the comprehensiveness and accuracy", GLOSS)],
    "f99645": [d("Each position in a sparse vector corresponds", "entailed_by_evidence",
                 "Evidence: sparse vectors encode a word's identity and are dictionary-length.", "medium"),
               d("Only positions corresponding to words present", "minor_imprecision",
                 "Follows loosely from 'encode the identity of a word' and 'mostly zeros'.", "low"),
               D("Dense vectors allow more nuanced and context-aware", GLOSS),
               D("These differences impact how text is processed", GLOSS),
               D("These differences influence performance and accuracy", GLOSS)],
    "d13470": [D("enhances the model's ability to understand", GLOSS)],
    "4e8417": [D("enhances the model's ability to understand", GLOSS)],
    "0f2ef1": [d("requires substantial computational resources and time", "entailed_by_evidence",
                 "Evidence: Retro incurs the 'high cost of training runs'."),
               D("trade-off involving domain-specific knowledge", GLOSS)],
    "4dfcd1": [D("stored in a vector database for efficient", EFFICIENT), D("Evaluating RAG effectiveness remains", SCOPE),
               d("continued research and improvement", "not_a_factual_claim",
                 "Concluding opinion, not a claim about the evidence.")],
    "f99a75": [d("Retrieved information is not guaranteed", "entailed_by_evidence",
                 "Evidence: RAG poisoning/misleading or outdated sources.", "high"),
               D("Detailed context from retrieved sources helps", GLOSS),
               d("Users must verify information using provided sources", "minor_imprecision",
                 "Evidence: users can cross-check sources; 'must' and 'independent checks' are advice.")],
    "6c778c": [D("updates the model's knowledge base incrementally", GLOSS), D("increases the trustworthiness", GLOSS)],
    "428060": [d("regularly updated", "minor_imprecision", "Evidence: augment the knowledge base when new information appears.")],
    "c6add3": [D("used for efficient retrieval", EFFICIENT), D("allows quick access to relevant documents", EFFICIENT),
               D("enhances the performance of retrieval-augmented", GLOSS), D("fast and accurate document retrieval", GLOSS)],
    "63c48f": [D("RAG can integrate structured data to provide detailed", GLOSS),
               d("RAG can parse and utilize semi-structured data", "entailed_by_evidence",
                 "Evidence: RAG can be used on semi-structured data; 'effectively' is a gloss."),
               D("Unstructured text includes free-form text", TAUTOLOGY), D("RAG excels at processing", GLOSS),
               d("RAG's flexibility allows it to handle a wide range", "entailed_by_evidence",
                 "Evidence: RAG can be used on unstructured, semi-structured or structured data.")],
    "225e81": [D("enhances the overall accuracy and reliability", GLOSS)],
    "843843": [d("Sparse vectors indicate the presence or absence", "entailed_by_evidence",
                 "Evidence: sparse vectors encode word identity; dense vectors encode meaning."),
               D("Dense vectors capture semantic and contextual", GLOSS), D("Using both types improves", GLOSS)],
    "86be01": [d("Retro requires extensive training runs", "entailed_by_evidence",
                 "Evidence: 'high cost of training runs'.", "high"),
               d("original RAG scheme avoids frequent retraining", "entailed_by_evidence",
                 "Evidence: the cost 'the original RAG scheme avoided'.", "high"),
               d("high-cost training run is necessary to incorporate domain knowledge", "minor_imprecision",
                 "Evidence links domain knowledge to training, but not as the cause of the cost.", "low"),
               d("Retro requires substantial resources", "entailed_by_evidence", "Evidence: high training cost.")],
    "d114ea": [D("These differences impact how the vectors are used", GLOSS)],
    "a49ed8": [D("differences affect the overall performance", GLOSS)],
    "c7afa2": [d("This could potentially improve the accuracy", "minor_imprecision",
                 "Hedged gloss, not a firm claim.", "medium", 0),
               d("This could potentially improve the accuracy", "duplicate_claim",
                 "Identical to the previous claim.", "high", 1)],
    "159a89": [D("scoring or reranking scoring improves", GLOSS)],
    "ea96e0": [D("enhances the accuracy of the final response", GLOSS)],
    "916caa": [D("ongoing challenges in evaluating the effectiveness", SCOPE)],
    "735b1c": [D("ongoing issues with evaluating", SCOPE)],
    "0e6ab0": [D("Citing sources enhances trust", GLOSS),
               d("RAG remains subject to RAG poisoning", "entailed_by_evidence",
                 "Evidence has a RAG poisoning section.", "high")],
    "0a2557": [d("improve the accuracy and reliability", "entailed_by_evidence",
                 "Evidence: RAG improves the accuracy of LLMs."),
               d("RAG can reduce misinformation", "entailed_by_evidence", "Evidence: RAG helps reduce hallucinations.")],
    "4fdad0": [d("leverages the existing model architecture", "minor_imprecision",
                 "Loose restatement of 'no retraining needed'.")],
    "9c0604": [D("transparency helps ensure the reliability", GLOSS)],
    "e414d9": [D("facilitates efficient document retrieval", EFFICIENT)],
    "b16d48": [D("facilitates efficient document retrieval", EFFICIENT)],
    "3d95ce": [d("significant training-cost disadvantage compared to other", "entailed_by_evidence",
                 "Restates the question; evidence: high cost of training runs.", "high"),
               d("Training from scratch incurs a high cost", "entailed_by_evidence",
                 "Evidence: trained from scratch, incurring the high cost of training runs."),
               d("Other models can leverage existing pre-trained", "minor_imprecision",
                 "Evidence: the original RAG scheme avoided this cost; 'pre-trained models' is a loose paraphrase.", "low")],
    "443dfa": [D("stored in a vector database for efficient retrieval", EFFICIENT),
               D("ongoing challenges in evaluating RAG's effectiveness", SCOPE),
               d("significant advancement in leveraging", "not_a_factual_claim",
                 "Evaluative opinion, not a claim about the evidence.", "low")],
    "1275dc": [d("requires careful handling to ensure contextual", "minor_imprecision",
                 "Evidence: LLMs can misinterpret context; 'requires careful handling' is advice.")],
}

ANSWER_OVERRIDES: dict[str, tuple[str, str]] = {
    "f99a75": ("partial", "Rule 2: the answer covers RAG's capabilities, limits and verification; one overclaim "
                          "('ensures grounded') does not make it incorrect."),
    "f210f8": ("partial", "Rule 2: purposes and key facts of both sources are covered; one wrong detail (reference-period "
                          "start dates)."),
    "51c529": ("partial", "Rule 2: both sources are compared correctly; the charity-work treatment and a vague synthesis "
                          "claim are wrong/unsupported."),
    "039f7b": ("partial", "Rule 2: the central fact '48 hours per week' is present; the 26-week-default and 52-week claims "
                          "are wrong."),
    "103b53": ("yes", "Only issue was the 45-minute/9-hour wording; remaining content matches the evidence."),
    "915eb1": ("yes", "Only issue was '48 hours over 26 weeks', which the declaration itself applies."),
    "95aab5": ("yes", "Remaining issues are the 45/9 wording and the omitted 'knowingly' qualifier (caveats)."),
    "6d422b": ("yes", "Only issue was the omitted 'average' qualifier on the 48-hour limit (caveat)."),
}

CITATION_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "7966af": ("not_applicable", "No source marker or source reference in the answer; 'Regulation 18 of the RTWT "
                                 "Regulations' is part of the stated fact, not a citation.", "medium"),
    "6d422b": ("not_applicable", "No source markers. Naming the PDF/Wikipedia article is the answer to 'which source', "
                                 "not a citation of a claim.", "low"),
}

FLAGS: dict[str, list[str]] = {
    "103b53": ["citation_marker_not_exact: '[PDF ... p.1-2]' is not an exact context marker (p.1 and p.2 are separate); "
               "both chunks do support the answer, so the label is kept at 'yes'. The deterministic citation audit "
               "would count it invalid."],
    "99edf3": ["citation_marker_not_exact: '[PDF ... p.1-2]' page range, see 103b53."],
    "1238d6": ["degenerate_repetition: the Sources list repeats the same marker 24 times. Citations are correct, "
               "but this is a generation defect worth reporting separately."],
    "113c0b": ["consistency: retains a contradicted claim ('dynamically updates the model') yet answer_correct='yes'; "
               "the judge was lenient here while harsh on glosses. No override made."],
}

ANSWER_NO_CENTRAL = {"f99a75", "f210f8", "51c529", "039f7b"}


def _match(unsupported: list[tuple[int, dict]], substring: str, occurrence: int | None, suffix: str) -> int:
    hits = [index for index, claim in unsupported if substring in claim["text"]]
    if occurrence is not None:
        hits = hits[occurrence:occurrence + 1]
    if len(hits) != 1:
        raise ValueError(f"{suffix}: decision {substring!r} matched {len(hits)} unsupported claims, expected 1")
    return hits[0]


def audit_row(row: dict, suffix: str, apply_minor: bool = True) -> dict:
    labels = row["labels"]
    claims = [dict(claim) for claim in labels["claims"]]
    unsupported = [(i, c) for i, c in enumerate(claims) if not c["supported"]]
    decisions, used = [], set()
    for substring, category, reason, confidence, occurrence in DECISIONS.get(suffix, []):
        assert category in RECLASSIFIED, category
        if category == "minor_imprecision" and not apply_minor:
            continue
        pool = unsupported if occurrence is not None else [(i, c) for i, c in unsupported if i not in used]
        index = _match(pool, substring, occurrence, suffix)
        used.add(index)
        claims[index]["supported"] = True
        decisions.append({"claim": labels["claims"][index]["text"], "category": category,
                          "reason": reason, "confidence": confidence})
    retained = [c["text"] for c in claims if not c["supported"]]
    reclassified = {x["category"] for x in decisions}
    if retained:
        supp = "no" if len(retained) / len(claims) > 0.5 else "partial"
    else:
        supp = "partial" if reclassified & CAVEAT else ("yes" if decisions or labels["fully_supported"] == "yes"
                                                          else labels["fully_supported"])
    answer, answer_reason = ANSWER_OVERRIDES.get(suffix, (labels["answer_correct"], ""))
    citation, citation_reason, citation_conf = CITATION_OVERRIDES.get(
        suffix, (labels["citation_correct"], "", "high"))
    suggested = {"answer_correct": answer, "fully_supported": supp, "unsupported_claim_count": len(retained),
                 "citation_correct": citation, "abstention_correct": labels["abstention_correct"],
                 "claims": claims, "notes": labels["notes"]}
    validate_labels(suggested)
    changed = {k: [labels[k], suggested[k]] for k in
               ("answer_correct", "fully_supported", "unsupported_claim_count", "citation_correct",
                "abstention_correct") if labels[k] != suggested[k]}
    issues = sorted(reclassified | ({"answer_no_with_central_fact"} if suffix in ANSWER_NO_CENTRAL else set())
                    | ({"citation_label"} if suffix in CITATION_OVERRIDES else set())
                    | ({"flag"} if suffix in FLAGS else set()))
    confs = [x["confidence"] for x in decisions] + ([citation_conf] if suffix in CITATION_OVERRIDES else [])
    return {"blind_id": row["blind_id"], "audit_status": "corrected" if changed else
            ("flagged" if suffix in FLAGS else "confirmed"),
            "issue_types": issues, "original": {k: labels[k] for k in
                                                ("answer_correct", "fully_supported", "unsupported_claim_count",
                                                 "citation_correct", "abstention_correct")},
            "suggested": {k: suggested[k] for k in ("answer_correct", "fully_supported", "unsupported_claim_count",
                                                    "citation_correct", "abstention_correct")},
            "changed": changed, "claim_decisions": decisions, "retained_unsupported": retained,
            "answer_correct_reason": answer_reason, "citation_reason": citation_reason, "flags": FLAGS.get(suffix, []),
            "confidence": min(confs, key=_RANK.__getitem__) if confs else "high",
            "label_source": "llm_assisted_audit", "human_verified": False,
            "suggested_labels_full": suggested}


def select_suffixes(pack: dict, rows: list[dict]) -> dict[str, dict]:
    """Rows to audit: any with a decision/override/flag, plus verification-only focus rows."""
    by_suffix: dict[str, dict] = {}
    for row in rows:
        by_suffix.setdefault(row["blind_id"][-6:], row)
    keys = set(DECISIONS) | set(ANSWER_OVERRIDES) | set(CITATION_OVERRIDES) | set(FLAGS)
    missing = keys - set(by_suffix)
    if missing:
        raise ValueError(f"unknown blind_id suffixes: {sorted(missing)}")
    for row in rows:
        p = pack[row["blind_id"]]
        if row["parse_status"] != "ok":
            continue
        label = row["labels"]
        if (p["expected_abstention"] or p["emitted_citations"] or re.search(r"45[- ]min", p["answer"])
                or label["unsupported_claim_count"] > 0 or label["answer_correct"] != "yes"
                or label["fully_supported"] != "yes"):
            keys.add(row["blind_id"][-6:])
    return {k: by_suffix[k] for k in sorted(keys)}


def sensitivity(labels_path: Path, audit_rows: dict[str, dict], strict_rows: dict[str, dict],
                key_path: Path, pack: dict) -> list[dict]:
    """Before/after fully-supported and unsupported-claim rates by split and format (needs the key)."""
    key = {r["blind_id"]: r for r in json.loads(key_path.read_text())["records"]}
    cell: dict[tuple, list] = defaultdict(list)
    for line in labels_path.read_text().splitlines():
        row = json.loads(line)
        if row["parse_status"] != "ok":
            continue
        after = audit_rows.get(row["blind_id"], {}).get("suggested") or row["labels"]
        strict = strict_rows.get(row["blind_id"], {}).get("suggested") or row["labels"]
        fmt = re.search(r"answers-(fp16|awq|gptq)", key[row["blind_id"]]["answer_file"]).group(1)
        cell[(pack[row["blind_id"]]["split"], fmt)].append((row["labels"], after, strict))
    out = []
    for (split, fmt), pairs in sorted(cell.items()):
        n = len(pairs)
        out.append({"split": split, "format": fmt, "n": n,
                    "supported_before": sum(b["fully_supported"] == "yes" for b, _, _ in pairs) / n,
                    "supported_after": sum(a["fully_supported"] == "yes" for _, a, _ in pairs) / n,
                    "supported_strict": sum(t["fully_supported"] == "yes" for _, _, t in pairs) / n,
                    "unsupported_per_answer_before": sum(b["unsupported_claim_count"] for b, _, _ in pairs) / n,
                    "unsupported_per_answer_after": sum(a["unsupported_claim_count"] for _, a, _ in pairs) / n,
                    "unsupported_per_answer_strict": sum(t["unsupported_claim_count"] for _, _, t in pairs) / n,
                    "answer_yes_before": sum(b["answer_correct"] == "yes" for b, _, _ in pairs) / n,
                    "answer_yes_after": sum(a["answer_correct"] == "yes" for _, a, _ in pairs) / n})
    return out


def render_markdown(results: list[dict], orig_rows: list[dict], sens: list[dict] | None, labels_sha: str) -> str:
    ok = [r for r in orig_rows if r["parse_status"] == "ok"]
    after = {r["blind_id"]: r for r in results}
    tot_before = sum(r["labels"]["unsupported_claim_count"] for r in ok)
    tot_after = sum((after[r["blind_id"]]["suggested"] if r["blind_id"] in after else r["labels"])
                    ["unsupported_claim_count"] for r in ok)
    rows_before = sum(r["labels"]["unsupported_claim_count"] > 0 for r in ok)
    rows_after = sum((after[r["blind_id"]]["suggested"] if r["blind_id"] in after else r["labels"])
                     ["unsupported_claim_count"] > 0 for r in ok)
    cats = Counter(x["category"] for r in results for x in r["claim_decisions"])
    status = Counter(r["audit_status"] for r in results)
    lines = [
        "# Judge label audit (LLM-assisted labels, audited by an LLM reviewer)", "",
        "**Status: suggested corrections, not human-verified.** The original labels in "
        "`reports/quality-judge-labels.jsonl` are unchanged "
        f"(sha256 `{labels_sha[:16]}...`). Corrections are in `reports/quality-judge-label-audit.jsonl`. "
        "The audit was performed by reading the supplied evidence for each flagged claim; it has the same class of "
        "limitation as the judge itself and should be spot-checked, starting with `low`/`medium` confidence rows.", "",
        "## Summary", "",
        f"- Rows audited: {len(results)} ({status['corrected']} corrected, {status['flagged']} flagged only, "
        f"{status['confirmed']} confirmed unchanged).",
        f"- Total unsupported claims: {tot_before} -> {tot_after} across {len(ok)} scored rows.",
        f"- Rows with at least one unsupported claim: {rows_before} -> {rows_after}.",
        "- Reclassified claims by category: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()) + ".",
        "- Claims left as unsupported are contradictions of the evidence or new checkable details (examples, "
        "definitions with content, properties not in the evidence, over-guarantees).", "",
        "## Calibration rules applied", "",
        "1. `45 minutes after 9 hours` vs evidence `45 minutes for over 9 hours`: wording-equivalent, not unsupported.",
        "2. Central expected fact present plus wrong/unsupported details: `answer_correct` is `partial`, not `no`.",
        "3. Omitted qualifiers (`knowingly`, `average`): `fully_supported` stays `partial`, not an unsupported claim.",
        "4. Unsupported means contradicted, or adds new checkable detail. Minor imprecision, duplicates, entailed "
        "paraphrases and non-claims do not count.", ""]
    lines += ["## 45-minute / 9-hour consistency", "",
              "The same wording was judged inconsistently. Some rows flagged it unsupported; others passed it because "
              "the judge silently rewrote the claim as 'over 9 hours' before judging.", "",
              "| blind_id | judge claim flagged? | suggestion |", "|---|---|---|"]
    for r in sorted(results, key=lambda r: r["blind_id"]):
        if any(re.search(r"45|9 hours", x["claim"]) for x in r["claim_decisions"]):
            lines.append(f"| {r['blind_id']} | flagged unsupported | treat as wording-equivalent |")
    lines += ["", "Rows that mention it but were passed by the judge (no change needed): "
              "`403bec`, `51c529`, `48692a`, `915eb1`, `2579be`, `27bdd3`, `51bc83`, `101b0d`.", ""]
    if sens:
        lines += ["## Sensitivity: does the correction change the format comparison?", "",
                  "Uses the unblinding key (aggregation-stage only). Preliminary and LLM-assisted. "
                  "`strict` applies every correction except the subjective `minor_imprecision` reclassifications, so "
                  "it is the conservative bound; `full` applies all of them.", "",
                  "| split | format | n | fully supported before / strict / full | unsupported per answer before / "
                  "strict / full | answer yes before -> after |", "|---|---|---|---|---|---|"]
        for t in sens:
            lines.append(f"| {t['split']} | {t['format']} | {t['n']} | {t['supported_before']:.2f} / "
                         f"{t['supported_strict']:.2f} / {t['supported_after']:.2f} | "
                         f"{t['unsupported_per_answer_before']:.2f} / {t['unsupported_per_answer_strict']:.2f} / "
                         f"{t['unsupported_per_answer_after']:.2f} | {t['answer_yes_before']:.2f} -> "
                         f"{t['answer_yes_after']:.2f} |")
        lines.append("")
    lines += ["## Per-row audit", "",
              "`conf` is the lowest confidence among the row's decisions. Labels shown as original -> suggested "
              "(answer / supported / unsupported count / citation).", "",
              "| blind_id | status | issues | original | suggested | conf | reason |", "|---|---|---|---|---|---|---|"]
    for r in results:
        o, s = r["original"], r["suggested"]
        reason = (r["answer_correct_reason"] or r["citation_reason"]
                  or (r["claim_decisions"][0]["reason"] if r["claim_decisions"] else "")
                  or (r["flags"][0] if r["flags"] else "")
                  or (f"verified; {len(r['retained_unsupported'])} unsupported claim(s) retained: "
                      f"{r['retained_unsupported'][0]}" if r["retained_unsupported"] else "verified; no change"))
        extra = f" (+{len(r['claim_decisions']) - 1} more)" if len(r["claim_decisions"]) > 1 else ""
        lines.append(f"| {r['blind_id']} | {r['audit_status']} | {', '.join(r['issue_types']) or '-'} | "
                     f"{o['answer_correct']}/{o['fully_supported']}/{o['unsupported_claim_count']}/{o['citation_correct']} | "
                     f"{s['answer_correct']}/{s['fully_supported']}/{s['unsupported_claim_count']}/{s['citation_correct']} | "
                     f"{r['confidence']} | {reason[:140].replace('|', '/')}{extra} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--labels", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/quality-judge-label-audit.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("reports/quality-judge-label-audit.md"))
    parser.add_argument("--key", type=Path, help="Optional: adds the by-format sensitivity table")
    args = parser.parse_args()
    for path in (args.output, args.summary):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    pack = {r["blind_id"]: r for r in map(json.loads, args.pack.read_text().splitlines()) if r}
    raw = args.labels.read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    selected = select_suffixes(pack, rows)
    results = [audit_row(row, suffix) for suffix, row in selected.items() if row["parse_status"] == "ok"]
    by_id = {r["blind_id"]: r for r in results}
    strict = {r["blind_id"]: r for r in (audit_row(row, suffix, apply_minor=False)
                                         for suffix, row in selected.items() if row["parse_status"] == "ok")}
    sens = sensitivity(args.labels, by_id, strict, args.key, pack) if args.key else None
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results))
    args.summary.write_text(render_markdown(results, rows, sens, hashlib.sha256(raw).hexdigest()))
    assert hashlib.sha256(args.labels.read_bytes()).hexdigest() == hashlib.sha256(raw).hexdigest()
    print(json.dumps({"audited_rows": len(results), "status": dict(Counter(r["audit_status"] for r in results)),
                      "output": str(args.output), "summary": str(args.summary)}, indent=2))


if __name__ == "__main__":
    main()
