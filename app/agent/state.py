from typing import TypedDict


class AgentState(TypedDict):
    query: str
    conversation_id: str
    sources_to_use: list[str]
    source_ids: list[str]          # empty = no filter; non-empty = restrict to these source_ids
    retrieved_chunks: list[dict]
    answer: str
    critic_feedback: str
    needs_replan: bool
    iteration: int
