from app.agent.state import AgentState
from app.services.llm import chat_complete

_SYSTEM = """\
You are DocChat's research assistant. Give useful, well-structured answers using ONLY
the provided context.

Core rules:
- Answer the user's actual question directly. Do not dump raw notes from the context.
- If the context supports a clear answer, lead with the answer in 1-3 sentences.
- Then add structure only where it helps: short sections, bullets, or numbered steps.
- Keep paragraphs short. Prefer concrete details, named entities, dates, numbers, and
  tradeoffs over generic summaries.
- If the question asks for analysis, explain the reasoning from the sources, not just the
  conclusion.
- If the context is incomplete, say what is missing and give the best supported partial
  answer. Do not fabricate or fill gaps from outside knowledge.
- Avoid boilerplate like "Based on the provided context" unless the limitation matters.

Formatting:
- Use plain text formatting that renders cleanly without Markdown.
- Do not use Markdown heading markers like # or ##.
- Do not use Markdown emphasis markers like **bold**.
- Put each section label on its own line, followed by a blank line.
- Use short section labels followed by a colon, for example "Summary:" or "Key points:".
- For most answers, a direct paragraph plus bullets is enough.
- Put each bullet on its own line. Do not write bullets inline inside a paragraph.
- For multi-part questions, answer each part under a clear label.
- For comparisons, use compact bullets with consistent labels.

Citation rules:
- Do not put citation markers inside the answer body.
- Put citations only at the end in a short "Sources:" section.
- List each supporting source once, using the exact source markers from the context
  (e.g., "[PDF — paper.pdf p.3]", "[YouTube — Lecture 1 @120s]", "[Web — example.com]").

Conversation history (oldest to newest, last 10 messages):
{conversation_history}

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
        parts.append(f"Source marker: {label}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts) if parts else "No context retrieved."


def _format_history(history: list[dict]) -> str:
    if not history:
        return "none"
    return "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}"
        for item in history
        if item.get("content")
    ) or "none"


async def synthesizer_node(state: AgentState) -> dict:
    context = _format_chunks(state["retrieved_chunks"])
    messages = [
        {
            "role": "system",
            "content": _SYSTEM.format(
                context=context,
                conversation_history=_format_history(state.get("conversation_history", [])),
            ),
        },
        {"role": "user", "content": state["query"]},
    ]
    answer = await chat_complete(messages, max_tokens=1400)
    return {"answer": answer}
