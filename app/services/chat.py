import anthropic

from app.core.config import settings

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """\
You are a helpful assistant that answers questions based strictly on the provided document context.
If the answer is not present in the context, say so clearly — do not make up information.

Document context:
{context}
"""


def generate_reply(question: str, chunks: list[str], history: list[dict]) -> str:
    """Call Claude Opus 4.6 with retrieved context and conversation history."""
    context = "\n\n---\n\n".join(chunks) if chunks else "No relevant context found."

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    messages = history + [{"role": "user", "content": question}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT.format(context=context),
        messages=messages,
    )

    return response.content[0].text
