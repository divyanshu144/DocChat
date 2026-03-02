import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message, MessageRole
from app.services import chat, retrieval

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Schemas ---

class ConversationCreate(BaseModel):
    document_id: str


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    document_id: str
    created_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str


# --- Helpers ---

async def _load_recent_history(conversation_id: str, db: AsyncSession) -> list[dict]:
    """Fetch the last N messages for a conversation as LLM history dicts."""
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(settings.chat_history_limit)
    )
    recent = list(reversed(msgs_result.scalars().all()))
    return [{"role": m.role.value, "content": m.content} for m in recent]


# --- Endpoints ---

@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == body.document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if document.status != DocumentStatus.ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is not ready for chat (status: {document.status}).",
        )

    conversation = Conversation(document_id=body.document_id)
    db.add(conversation)
    await db.commit()

    # Re-fetch with eager-loaded messages to satisfy the response schema
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .options(selectinload(Conversation.messages))
    )
    return result.scalar_one()


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    # Fetch only the last N messages from the DB — no full table scan in memory
    history = await _load_recent_history(conversation_id, db)

    chunks = await retrieval.retrieve_chunks(
        query=body.question,
        document_id=conversation.document_id,
        db=db,
        top_k=settings.retrieval_top_k,
    )

    try:
        answer = await chat.generate_reply(
            question=body.question,
            chunks=chunks,
            history=history,
        )
    except Exception as exc:
        logger.exception("chat_generation_failed", extra={"conversation_id": conversation_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM request failed: {exc}",
        )

    db.add(Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question))
    db.add(Message(conversation_id=conversation_id, role=MessageRole.assistant, content=answer))
    await db.commit()

    return ChatResponse(conversation_id=conversation_id, answer=answer)


@router.post("/conversations/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    history = await _load_recent_history(conversation_id, db)

    chunks = await retrieval.retrieve_chunks(
        query=body.question,
        document_id=conversation.document_id,
        db=db,
        top_k=settings.retrieval_top_k,
    )

    # Persist the user message before streaming begins
    db.add(Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question))
    await db.commit()

    question = body.question  # capture for the closure

    async def event_stream():
        full_reply: list[str] = []
        try:
            async for token in chat.generate_reply_stream(
                question=question,
                chunks=chunks,
                history=history,
            ):
                full_reply.append(token)
                yield f"data: {token}\n\n"
        except Exception:
            logger.exception("chat_stream_failed", extra={"conversation_id": conversation_id})
            yield "data: [ERROR]\n\n"
            return

        yield "data: [DONE]\n\n"

        # Persist the assistant message after the stream completes
        async with AsyncSessionLocal() as bg_db:
            bg_db.add(Message(
                conversation_id=conversation_id,
                role=MessageRole.assistant,
                content="".join(full_reply),
            ))
            await bg_db.commit()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    return conversation
