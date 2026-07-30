import uuid as _uuid
import logging
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncGenerator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.conversation import Conversation, Message, MessageRole
from app.models.user import User
from app.agent.graph import agent_graph
from app.agent.state import AgentState

router = APIRouter()
logger = logging.getLogger(__name__)

_NODE_STATUS = {
    "planner": "Planning which sources to search",
    "retriever": "Retrieving relevant passages",
    "synthesizer": "Drafting a grounded answer",
    "grounding": "Checking answer against retrieved context",
    "critic": "Reviewing answer quality",
}


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    sources: list[str] | None = None
    source_ids: list[str] | None = None  # restrict to specific ingested sources


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _stream_error_message(exc: Exception) -> str:
    text = str(exc)
    if "429" in text or "rate limit" in text.lower() or "too many requests" in text.lower():
        return "The model provider is rate-limiting requests. Wait a moment and try again."
    return "The assistant run failed before an answer was generated."


async def _run_agent_with_status(initial_state: AgentState) -> AsyncGenerator[tuple[str, str | AgentState], None]:
    """Stream graph progress updates and return the final merged state as a final item."""
    final_state: AgentState = initial_state.copy()
    last_non_empty_answer = ""

    yield "status", "Reading your question"
    async for update in agent_graph.astream(initial_state, stream_mode="updates"):
        if not isinstance(update, dict):
            continue
        for node_name, node_update in update.items():
            if isinstance(node_update, dict):
                answer = node_update.get("answer")
                if isinstance(answer, str) and answer.strip():
                    last_non_empty_answer = answer
                final_state.update(node_update)
                if final_state.get("answer", "").strip() == "" and last_non_empty_answer:
                    final_state["answer"] = last_non_empty_answer
            status_message = _NODE_STATUS.get(node_name)
            if status_message:
                yield "status", status_message

    if final_state.get("answer", "").strip() == "" and last_non_empty_answer:
        final_state["answer"] = last_non_empty_answer
    yield "final", final_state


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == req.conversation_id,
                Conversation.user_id == current_user.id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = Conversation(id=str(_uuid.uuid4()), title=req.query[:100], user_id=current_user.id)
        db.add(conv)
        await db.flush()
        await db.commit()

    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = list(reversed(history_result.scalars().all()))
    history = [
        {"role": m.role.value, "content": m.content}
        for m in recent_messages
    ]

    initial_state: AgentState = {
        "query": req.query,
        "conversation_id": conv.id,
        "conversation_history": history,
        "sources_to_use": req.sources or ["pdf", "youtube", "web"],
        "source_ids": req.source_ids or [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }

    async def sse_stream():
        final_state: AgentState | None = None
        try:
            async for kind, payload in _run_agent_with_status(initial_state):
                if kind == "status":
                    yield _sse("status", str(payload))
                elif kind == "final":
                    final_state = cast(AgentState, payload)
        except Exception as exc:
            logger.exception("chat_stream_failed")
            yield _sse("error", _stream_error_message(exc))
            return

        if final_state is None:
            yield _sse("error", "The assistant run ended without producing an answer.")
            return

        answer = final_state["answer"].strip()
        if not answer:
            answer = (
                "I couldn't produce a usable answer from the retrieved context. "
                "Try rephrasing the question or selecting a more specific source."
            )

        now = datetime.now(timezone.utc)
        db.add(Message(
            conversation_id=conv.id,
            role=MessageRole.user,
            content=req.query,
            created_at=now,
        ))
        db.add(Message(
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=answer,
            created_at=now + timedelta(microseconds=1),
        ))
        await db.commit()

        yield _sse("status", "Writing the response")
        for word in answer.split():
            yield _sse("token", f"{word} ")
        yield _sse("done", "[DONE]")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"X-Conversation-Id": conv.id},
    )
