"""Read source markers out of prompts and answers, in the format app/core/sources.py::citation_label produces."""
from __future__ import annotations

import re

MARKER = re.compile(r"\[(?:PDF|Web|YouTube) - [^\]\n]+\]")
_CONTEXT_MARKER = re.compile(r"^Source marker: (\[[^\]\n]+\])", re.MULTILINE)
_SOURCES_HEADING = re.compile(r"^\s*Sources:\s*$", re.MULTILINE)


def context_markers(system_prompt: str) -> list[str]:
    """Markers the synthesizer put in front of the retrieved chunks, in order."""
    return _CONTEXT_MARKER.findall(system_prompt)


def split_answer(answer: str) -> tuple[str, str | None]:
    """Return (body, sources_section). The section is None when the answer has no `Sources:` heading."""
    matches = list(_SOURCES_HEADING.finditer(answer))
    if not matches:
        return answer.strip(), None
    last = matches[-1]
    return answer[: last.start()].strip(), answer[last.end():].strip()


def cited_markers(answer: str) -> list[str]:
    _, section = split_answer(answer)
    return MARKER.findall(section) if section else []


def body_markers(answer: str) -> list[str]:
    body, _ = split_answer(answer)
    return MARKER.findall(body)
