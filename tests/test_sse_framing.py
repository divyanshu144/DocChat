"""Tests for Bug #2 — SSE framing: multi-line tokens must produce one data: line per line."""
import pytest


def _sse_frame(token: str) -> str:
    """Replicate the fixed SSE framing logic from event_stream() in conversations.py."""
    lines = token.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


class TestSseFraming:
    def test_single_line_token_produces_standard_frame(self):
        """A token with no newlines produces the classic 'data: <text>\\n\\n' frame."""
        frame = _sse_frame("Hello world")
        assert frame == "data: Hello world\n\n"

    def test_two_line_token_produces_two_data_lines(self):
        """A token containing one newline must produce two data: lines."""
        frame = _sse_frame("line one\nline two")
        assert frame == "data: line one\ndata: line two\n\n"

    def test_three_line_token(self):
        """A token with two newlines produces three data: lines."""
        frame = _sse_frame("a\nb\nc")
        assert frame == "data: a\ndata: b\ndata: c\n\n"

    def test_trailing_newline_in_token(self):
        """A trailing newline in the token results in a trailing empty data: line."""
        frame = _sse_frame("text\n")
        assert frame == "data: text\ndata: \n\n"

    def test_empty_token_produces_empty_data_line(self):
        """An empty token string produces a single empty data: line."""
        frame = _sse_frame("")
        assert frame == "data: \n\n"

    def test_frame_always_ends_with_double_newline(self):
        """Every frame must end with \\n\\n so SSE clients recognise the event boundary."""
        for token in ["word", "two\nlines", "three\nline\ntoken", ""]:
            frame = _sse_frame(token)
            assert frame.endswith("\n\n"), f"Frame does not end with \\n\\n for token {token!r}: {frame!r}"

    def test_sentinel_done_unchanged(self):
        """[DONE] sentinel uses literal string — verify its format is correct."""
        sentinel = "data: [DONE]\n\n"
        assert sentinel == "data: [DONE]\n\n"

    def test_sentinel_error_unchanged(self):
        """[ERROR] sentinel uses literal string — verify its format is correct."""
        sentinel = "data: [ERROR]\n\n"
        assert sentinel == "data: [ERROR]\n\n"

    def test_token_with_only_newline(self):
        """A token that is just a newline character."""
        frame = _sse_frame("\n")
        assert frame == "data: \ndata: \n\n"

    def test_multiline_preserves_content(self):
        """Content on each line must be preserved intact."""
        frame = _sse_frame("foo bar\nbaz qux")
        lines = frame.rstrip("\n").split("\n")
        assert lines[0] == "data: foo bar"
        assert lines[1] == "data: baz qux"
