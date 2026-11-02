"""Quality gates for generated training examples: format, citation validity, duplicates, abstention rate.

Every rule here exists because the serving prompt (app/agent/nodes/synthesizer.py) asks for it, or because an
earlier evaluation found the defect (for example the answer that listed one source 24 times).
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

from app.agent.nodes.synthesizer import _SYSTEM

from finetune.citations import body_markers, cited_markers, context_markers, split_answer
from finetune.schema import TrainingExample

# The part of the serving prompt before the per-request history and context. Training prompts must start with it
# exactly, so a prompt edit in the app cannot silently leave the fine-tune trained on an old prompt.
SERVING_PREFIX = _SYSTEM.split("Conversation history")[0]
MAX_ANSWER_CHARS = 4000
MAX_QUESTION_CHARS = 400
# Words an abstention should use. The negative controls in the existing evaluation were handled with these.
_ABSTAIN = re.compile(
    r"(does not|do not|doesn't|don't|did not|not) (contain|include|mention|provide|cover|say|specify|state|have)|"
    r"(no|not enough|insufficient|nothing) (relevant )?(information|mention|details?|data)|cannot (find|answer)|"
    r"unable to (find|answer)|isn't (covered|mentioned)|is not (covered|mentioned|stated|specified)",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"^\s{0,3}#{1,6}\s|\*\*[^*\n]+\*\*", re.MULTILINE)


def validate_example(example: TrainingExample) -> list[str]:
    """Return the problems with one example (empty list means it passes)."""
    problems: list[str] = []
    roles = [m.role for m in example.messages]
    if roles != ["system", "user", "assistant"]:
        return [f"messages must be system, user, assistant (got {roles})"]
    if not example.system.startswith(SERVING_PREFIX):
        problems.append("system prompt does not start with the serving prompt")
    if "\nContext:\n" not in example.system:
        problems.append("system prompt has no Context section")
    question, answer = example.question.strip(), example.answer.strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        problems.append("question is empty or too long")
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        problems.append("answer is empty or too long")
    if problems:
        return problems

    supplied = set(context_markers(example.system))
    cited = cited_markers(answer)
    body, section = split_answer(answer)
    if _MARKDOWN.search(answer):
        problems.append("answer uses Markdown headings or bold, which the prompt forbids")
    if body_markers(answer):
        problems.append("citation markers appear in the answer body instead of the Sources section")
    if not body:
        problems.append("answer has no text before Sources")

    if example.kind == "answerable":
        if section is None or not cited:
            problems.append("answerable example has no cited sources")
        if len(set(cited)) != len(cited):
            problems.append("the same source is listed more than once")
        unknown = [m for m in cited if m not in supplied]
        if unknown:
            problems.append(f"cites a marker that was not in the context: {unknown[0]}")
        if _ABSTAIN.search(body) and len(body) < 160:
            problems.append("answerable example reads like an abstention")
    else:
        if cited:
            problems.append("abstention cites sources")
        if not _ABSTAIN.search(body):
            problems.append("abstention does not say the context lacks the information")
    return problems


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _shingles(text: str, n: int = 3) -> set[tuple]:
    tokens = _tokens(text)
    return {tuple(tokens[i:i + n]) for i in range(max(len(tokens) - n + 1, 1))}


def dedupe(examples: list[TrainingExample], threshold: float = 0.7) -> tuple[list[TrainingExample], int]:
    """Drop exact repeats and near-repeats (3-word shingle Jaccard of question plus answer, same documents)."""
    kept: list[TrainingExample] = []
    shingles: list[tuple[tuple, set]] = []
    seen_ids: set[str] = set()
    dropped = 0
    for example in examples:
        key = (tuple(sorted(example.doc_ids)))
        grams = _shingles(example.question + " " + example.answer)
        duplicate = example.id in seen_ids or any(
            k == key and len(grams & other) / max(len(grams | other), 1) >= threshold for k, other in shingles
        )
        if duplicate:
            dropped += 1
            continue
        seen_ids.add(example.id)
        shingles.append((key, grams))
        kept.append(example)
    return kept, dropped


def abstention_rate(examples: list[TrainingExample]) -> float:
    return sum(e.kind == "abstain" for e in examples) / len(examples) if examples else 0.0


def check_abstention_rate(examples: list[TrainingExample], low: float = 0.08, high: float = 0.25) -> float:
    rate = abstention_rate(examples)
    if not low <= rate <= high:
        raise ValueError(f"abstention rate {rate:.1%} is outside the allowed {low:.0%} to {high:.0%}")
    return rate


def summarize(examples: list[TrainingExample]) -> dict:
    answers = [len(e.answer) for e in examples]
    return {
        "examples": len(examples),
        "by_kind": dict(Counter(e.kind for e in examples)),
        "by_split": dict(Counter(e.split for e in examples)),
        "documents": len({d for e in examples for d in e.doc_ids}),
        "abstention_rate": round(abstention_rate(examples), 3),
        "answer_chars": {"min": min(answers, default=0), "max": max(answers, default=0),
                         "mean": round(sum(answers) / len(answers), 1) if answers else 0},
    }


def load_examples(path: Path) -> list[TrainingExample]:
    return [TrainingExample.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def review_sample(examples: list[TrainingExample], n: int = 12, seed: int = 7) -> list[dict]:
    """A reproducible random sample for the manual spot-check, with the question, answer and how it validated."""
    rng = random.Random(seed)
    chosen = rng.sample(examples, min(n, len(examples)))
    return [{"id": e.id, "kind": e.kind, "docs": e.doc_ids, "question": e.question, "answer": e.answer,
             "problems": validate_example(e)} for e in chosen]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("examples", type=Path, help="JSONL of TrainingExample")
    parser.add_argument("--output", type=Path, required=True, help="where to write the examples that pass")
    parser.add_argument("--report", type=Path, help="write the counts and rejection reasons here")
    parser.add_argument("--sample", type=int, default=12)
    args = parser.parse_args()
    examples = load_examples(args.examples)
    rejected: Counter = Counter()
    passing = []
    for example in examples:
        problems = validate_example(example)
        for problem in problems:
            rejected[problem.split(":")[0]] += 1
        if not problems:
            passing.append(example)
    unique, dropped = dedupe(passing)
    report = {"read": len(examples), "passed_rules": len(passing), "duplicates_dropped": dropped,
              "rejected_reasons": dict(rejected), "summary": summarize(unique), "review_sample": review_sample(unique, args.sample)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(e.model_dump_json() + "\n" for e in unique))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
