import uuid as _uuid
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


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    sources: list[str] | None = None
    source_ids: list[str] | None = None  # restrict to specific ingested sources


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

    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(10)
    )
    history = [
        {"role": m.role.value, "content": m.content}
        for m in history_result.scalars().all()
    ]

    initial_state: AgentState = {
        "query": req.query,
        "conversation_id": conv.id,
        "sources_to_use": req.sources or ["pdf", "youtube", "web"],
        "source_ids": req.source_ids or [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }

    final_state = await agent_graph.ainvoke(initial_state)
    answer = final_state["answer"]

    db.add(Message(conversation_id=conv.id, role=MessageRole.user, content=req.query))
    db.add(Message(conversation_id=conv.id, role=MessageRole.assistant, content=answer))
    await db.commit()

    async def sse_stream():
        for word in answer.split():
            yield f"data: {word} \n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"X-Conversation-Id": conv.id},
    )
