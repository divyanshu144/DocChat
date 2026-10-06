"""Shared citation-marker pattern: only real source markers, not any bracketed text."""
import re

# Context markers look like "[PDF - file.pdf p.1]", "[Web - page]" and "[YouTube — Lecture @120s]".
# Matching any "[...]" also caught plain text such as "[26 weeks]".
CITATION_MARKER = re.compile(r"\[(?:PDF|Web|YouTube)\b[^\]\n]*\]")
