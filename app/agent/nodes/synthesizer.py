from app.agent.state import AgentState
from app.services.llm import chat_complete

_SYSTEM = """\
You are a research assistant. Answer the user's question using ONLY the provided context.
Cite sources inline (e.g., "[PDF — paper.pdf p.3]", "[YouTube — Lecture 1 @120s]", "[Web — example.com]").
If the context doesn't contain enough information, say so clearly — do not fabricate.

Context:
{context}
"""


def _format_chunks(chunks: list[dict]) -> str:
    parts = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        src = chunk.get("source_type", "unknown").upper()
        if src == "PDF":
            label = f"[PDF — {meta.get('filename', '')} p.{meta.get('page_number', '')}]"
        elif src == "YOUTUBE":
            label = f"[YouTube — {meta.get('title', '')} @{meta.get('timestamp_start', '')}s]"
        else:
            label = f"[Web — {meta.get('url', '')}]"
        parts.append(f"{label}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts) if parts else "No context retrieved."


async def synthesizer_node(state: AgentState) -> dict:
    context = _format_chunks(state["retrieved_chunks"])
    messages = [
        {"role": "system", "content": _SYSTEM.format(context=context)},
        {"role": "user", "content": state["query"]},
    ]
    answer = await chat_complete(messages, max_tokens=1024)
    return {"answer": answer}
