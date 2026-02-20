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


async def generate_reply(question: str, chunks: list[str], history: list[dict]) -> str:
    """Call Groq LLM with retrieved context and conversation history."""
    context = "\n\n---\n\n".join(chunks) if chunks else "No relevant context found."

    client = _get_client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        *history,
        {"role": "user", "content": question},
    ]

    response = await client.chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        max_tokens=1024,
    )

    return response.choices[0].message.content
