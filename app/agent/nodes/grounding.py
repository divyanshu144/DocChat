from app.agent.state import AgentState
from app.services.llm import chat_complete

_SYSTEM = """\
You are a grounding verifier. Your only job is to remove ungrounded sentences from an answer.

You are given:
1. Context chunks (the only valid source of truth)
2. An answer that may contain sentences not supported by those chunks

Rules:
- Keep sentences that are directly supported by the context, even if paraphrased.
- Keep meta-sentences like "Based on the provided context..." or "I don't have enough information..."
- Keep all citation markers like [PDF — ...], [YouTube — ...], [Web — ...].
- DROP sentences that make factual claims not found anywhere in the context.
- Output ONLY the cleaned answer text. No explanations. No preamble.

Context:
{context}
"""


def _format_context(chunks: list[dict]) -> str:
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
    return "\n\n---\n\n".join(parts)


async def grounding_node(state: AgentState) -> dict:
    if not state.get("retrieved_chunks"):
        return {"answer": state["answer"], "grounding_passed": False}

    context = _format_context(state["retrieved_chunks"])
    messages = [
        {"role": "system", "content": _SYSTEM.format(context=context)},
        {"role": "user", "content": state["answer"]},
    ]
    try:
        cleaned = await chat_complete(messages, max_tokens=1024)
        return {"answer": cleaned.strip(), "grounding_passed": True}
    except Exception:
        return {"answer": state["answer"], "grounding_passed": False}
