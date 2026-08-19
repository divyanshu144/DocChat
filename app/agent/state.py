from typing import TypedDict


class AgentState(TypedDict):
    query: str
    conversation_id: str
    conversation_history: list[dict]
    sources_to_use: list[str]
    source_ids: list[str]          # empty = no filter; non-empty = restrict to these source_ids
    retrieved_chunks: list[dict]
    answer: str
    critic_feedback: str
    needs_replan: bool
    iteration: int
    grounding_passed: bool
    # Set by the critic when it rejects a draft, cleared when the pair is written.
    # It exists because the two halves of a training example are produced by different
    # passes: the rejected answer by this one, its replacement by the next.
    pending_rejection: dict | None
