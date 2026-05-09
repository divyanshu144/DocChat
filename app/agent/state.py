from typing import TypedDict


class AgentState(TypedDict):
    query: str
    conversation_id: str
    sources_to_use: list[str]
    retrieved_chunks: list[dict]
    answer: str
    critic_feedback: str
    needs_replan: bool
    iteration: int
