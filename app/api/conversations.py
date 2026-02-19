from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message, MessageRole
from app.services import chat, retrieval

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
    await db.refresh(conversation)

    return conversation


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: str,
    body: ChatRequest,
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

    # Build history for the LLM (last N messages)
    recent = conversation.messages[-settings.chat_history_limit:]
    history = [{"role": m.role.value, "content": m.content} for m in recent]

    # Retrieve relevant chunks
    chunks = await retrieval.retrieve_chunks(
        query=body.question,
        document_id=conversation.document_id,
        db=db,
        top_k=settings.retrieval_top_k,
    )

    # Generate reply (async — does not block the event loop)
    answer = await chat.generate_reply(
        question=body.question,
        chunks=chunks,
        history=history,
    )

    # Persist user message and assistant reply
    db.add(Message(
        conversation_id=conversation_id,
        role=MessageRole.user,
        content=body.question,
    ))
    db.add(Message(
        conversation_id=conversation_id,
        role=MessageRole.assistant,
        content=answer,
    ))
    await db.commit()

    return ChatResponse(conversation_id=conversation_id, answer=answer)


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
