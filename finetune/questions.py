"""Ask a teacher model for questions about a window of a document, and parse what comes back."""
from __future__ import annotations

import random
from dataclasses import dataclass

from finetune.teacher import Teacher, parse_json_object

QUESTION_PROMPT = """\
You write test questions for a document question-answering system. Below is an excerpt from one document.

Write exactly {answerable} questions that the excerpt answers clearly and completely, and {unanswerable} questions that
look like they belong to the same document and topic but that the excerpt does NOT answer (they ask for a specific
number, name, date, or rule that is not stated in the excerpt).

Rules:
- Questions must make sense on their own, without saying "the excerpt" or "the text". Name the subject.
- Vary the type: a factual lookup, a how or why explanation, a condition or exception, a comparison inside the text.
- For each answerable question give "facts": one to three short statements taken from the excerpt that a correct
  answer must contain.
- Do not copy whole sentences into questions.

Reply with only this JSON object:
{{"answerable": [{{"question": "...", "facts": ["..."]}}], "unanswerable": ["..."]}}

Excerpt:
{excerpt}
"""


@dataclass
class Window:
    chunk_ids: list[str]
    text: str


def pick_windows(chunk_ids: list[str], texts: dict[str, str], count: int, rng: random.Random,
                 span: int = 2, max_chars: int = 3200) -> list[Window]:
    """`count` windows of up to `span` neighbouring chunks, spread over the document, reproducible from the rng."""
    if not chunk_ids:
        return []
    starts = list(range(0, len(chunk_ids), span))
    rng.shuffle(starts)
    windows = []
    for start in starts[:count]:
        ids = chunk_ids[start:start + span]
        text = "\n\n".join(texts[i] for i in ids)
        windows.append(Window(ids, text[:max_chars]))
    return windows


def ask_questions(teacher: Teacher, window: Window, answerable: int = 3, unanswerable: int = 1) -> tuple[list[dict], list[str]]:
    reply = teacher.complete([{"role": "user", "content": QUESTION_PROMPT.format(
        answerable=answerable, unanswerable=unanswerable, excerpt=window.text)}], max_tokens=700, temperature=0.4)
    data = parse_json_object(reply) or {}
    good = []
    for item in data.get("answerable") or []:
        if isinstance(item, dict) and isinstance(item.get("question"), str) and item["question"].strip():
            facts = [f for f in item.get("facts") or [] if isinstance(f, str) and f.strip()]
            good.append({"question": item["question"].strip(), "facts": facts})
    bad = [q.strip() for q in data.get("unanswerable") or [] if isinstance(q, str) and q.strip()]
    return good[:answerable], bad[:unanswerable]
