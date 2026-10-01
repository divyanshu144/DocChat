def truncate_chunk_body(text: str, budget: int) -> str:
    """Trim inside source text, never inside its citation label.

    Prefer a nearby word boundary; a space-free body keeps a hard-cut slice.
    """
    partial = text[:budget]
    if len(text) <= budget or not partial:
        return partial
    boundary = partial.rfind(" ")
    if boundary >= max(0, len(partial) - 80):
        return partial[:boundary]
    return partial
