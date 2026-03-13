from typing import AsyncGenerator

from groq import AsyncGroq

from app.core.config import settings

SYSTEM_PROMPT = """\
You are a helpful assistant that answers questions based strictly on the provided document context.
If the answer is not present in the context, say so clearly — do not make up information.

Document context:
{context}
"""

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


def _build_messages(question: str, chunks: list[str], history: list[dict]) -> list[dict]:
    context = "\n\n---\n\n".join(chunks) if chunks else "No relevant context found."
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        *history,
        {"role": "user", "content": question},
    ]


async def generate_reply(question: str, chunks: list[str], history: list[dict]) -> str:
    """Call Groq LLM with retrieved context and conversation history."""
    response = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=_build_messages(question, chunks, history),
        max_tokens=1024,
    )
    return response.choices[0].message.content


async def generate_reply_stream(
    question: str, chunks: list[str], history: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream Groq LLM tokens as an async generator."""
    stream = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=_build_messages(question, chunks, history),
        max_tokens=1024,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def expand_query_hyde(question: str) -> str:
    """Generate a hypothetical document passage to improve semantic retrieval (HyDE).

    Instead of embedding the question directly, we embed a short passage that
    *would* answer the question.  This passage is closer in embedding-space to
    real answer chunks than the raw question is, which improves recall.
    """
    response = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Write a short factual passage (2-3 sentences) that directly answers "
                    "the question below, as if extracted from a document. "
                    "Do not explain or qualify — just write the passage."
                ),
            },
            {"role": "user", "content": question},
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content


async def summarize_history(history: list[dict]) -> str:
    """Condense a list of past messages into a short paragraph.

    Used when conversation history grows beyond settings.history_summary_threshold
    to keep the prompt size bounded without losing key context.
    """
    response = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize the following conversation in 3-5 sentences. "
                    "Preserve key facts, questions asked, and conclusions reached. "
                    "Write concisely in third person."
                ),
            },
            *history,
            {"role": "user", "content": "Summarize the conversation above."},
        ],
        max_tokens=300,
    )
    return response.choices[0].message.content
