import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.limiter import limiter
from app.core.security import require_api_key
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message, MessageRole
from app.services import chat, retrieval, reranker
from app.services.semantic_cache import get_semantic_cache

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

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
    from_cache: bool = False


class ConversationSummary(BaseModel):
    id: str
    document_id: str
    document_filename: str
    message_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_history(conversation_id: str, db: AsyncSession) -> list[dict]:
    """Return the LLM history list, with a summarised prefix when the conversation
    is longer than settings.history_summary_threshold.

    Only *complete* messages are included — in-flight streaming replies
    (is_complete=False) are excluded to avoid corrupting the context window.
    """
    # Count total complete messages once
    count_result = await db.execute(
        select(sqlfunc.count(Message.id))
        .where(Message.conversation_id == conversation_id)
        .where(Message.is_complete.is_(True))
    )
    total: int = count_result.scalar() or 0

    # Recent messages (always included)
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.is_complete.is_(True))
        .order_by(Message.created_at.desc())
        .limit(settings.chat_history_limit)
    )
    recent = list(reversed(msgs_result.scalars().all()))
    history = [{"role": m.role.value, "content": m.content} for m in recent]

    # Summarise older messages when the conversation is long
    older_count = total - settings.chat_history_limit
    if (
        settings.history_summary_threshold > 0
        and older_count > 0
        and total > settings.history_summary_threshold
    ):
        older_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.is_complete.is_(True))
            .order_by(Message.created_at.asc())
            .limit(older_count)
        )
        older = list(older_result.scalars().all())
        if older:
            older_hist = [{"role": m.role.value, "content": m.content} for m in older]
            try:
                summary = await chat.summarize_history(older_hist)
                history = [
                    {"role": "system", "content": f"Earlier conversation summary: {summary}"}
                ] + history
            except Exception:
                logger.warning(
                    "history_summarization_failed",
                    extra={"conversation_id": conversation_id},
                )

    return history


async def _run_retrieval_pipeline(
    question: str,
    document_id: str,
    db: AsyncSession,
    conversation_id: str,
) -> tuple[list[str], "np.ndarray | None"]:
    """HyDE expansion → retrieve → re-rank.  Returns (chunks, query_emb)."""
    import numpy as np
    from app.core.metrics import (
        hyde_expansions,
        retrieval_duration,
        rerank_duration,
    )

    # Optional HyDE: embed a hypothetical answer instead of the raw question
    expanded_query: str | None = None
    query_emb = None
    if settings.hyde_enabled:
        try:
            expanded_query = await chat.expand_query_hyde(question)
            hyde_expansions.inc()
        except Exception:
            logger.warning("hyde_expansion_failed", extra={"conversation_id": conversation_id})

    # Embed the query once so it can be shared with the semantic cache lookup
    # and passed into retrieve_chunks (avoiding a second embed call there)
    search_text = expanded_query if expanded_query else question
    query_emb = await retrieval.embed_query(search_text)

    # Retrieve
    t0 = time.perf_counter()
    chunks = await retrieval.retrieve_chunks(
        query=question,
        document_id=document_id,
        db=db,
        top_k=settings.retrieval_top_k,
        expanded_query=expanded_query,
        query_emb=query_emb,
    )
    retrieval_duration.observe(time.perf_counter() - t0)

    # Re-rank when we have more chunks than we'll send to the LLM
    if settings.rerank_enabled and len(chunks) > settings.rerank_top_k:
        t0 = time.perf_counter()
        chunks = await reranker.rerank(question, chunks, settings.rerank_top_k)
        rerank_duration.observe(time.perf_counter() - t0)

    return chunks, query_emb


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """List all conversations with their source document name and message count."""
    rows = await db.execute(
        select(
            Conversation.id,
            Conversation.document_id,
            Conversation.created_at,
            Document.filename.label("document_filename"),
            sqlfunc.count(Message.id).label("message_count"),
        )
        .join(Document, Conversation.document_id == Document.id)
        .outerjoin(
            Message,
            (Message.conversation_id == Conversation.id) & Message.is_complete.is_(True),
        )
        .group_by(Conversation.id, Conversation.document_id, Conversation.created_at, Document.filename)
        .order_by(Conversation.created_at.desc())
    )
    return [
        ConversationSummary(
            id=r.id,
            document_id=r.document_id,
            document_filename=r.document_filename,
            message_count=r.message_count,
            created_at=r.created_at,
        )
        for r in rows.all()
    ]


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

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .options(selectinload(Conversation.messages))
    )
    return result.scalar_one()


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
@limiter.limit("20/minute")
async def send_message(
    request: Request,
    conversation_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.core.metrics import (
        llm_duration,
        semantic_cache_hits,
        semantic_cache_misses,
    )

    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    history = await _load_history(conversation_id, db)
    chunks, query_emb = await _run_retrieval_pipeline(
        body.question, conversation.document_id, db, conversation_id
    )

    # Semantic cache lookup (requires Redis)
    sc = get_semantic_cache()
    if sc is not None and query_emb is not None:
        cached = await sc.get(query_emb, conversation.document_id)
        if cached is not None:
            semantic_cache_hits.inc()
            db.add(Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question))
            db.add(Message(conversation_id=conversation_id, role=MessageRole.assistant, content=cached))
            await db.commit()
            return ChatResponse(conversation_id=conversation_id, answer=cached, from_cache=True)
        semantic_cache_misses.inc()

    try:
        t0 = time.perf_counter()
        answer = await chat.generate_reply(question=body.question, chunks=chunks, history=history)
        llm_duration.observe(time.perf_counter() - t0)
    except Exception as exc:
        logger.exception("chat_generation_failed", extra={"conversation_id": conversation_id})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM request failed. Please try again.")

    # Store in semantic cache for future identical/similar queries
    if sc is not None and query_emb is not None:
        try:
            await sc.set(query_emb, answer, conversation.document_id)
        except Exception:
            logger.warning("semantic_cache_write_failed", extra={"conversation_id": conversation_id})

    db.add(Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question))
    db.add(Message(conversation_id=conversation_id, role=MessageRole.assistant, content=answer))
    await db.commit()

    return ChatResponse(conversation_id=conversation_id, answer=answer)


@router.post("/conversations/{conversation_id}/messages/stream")
@limiter.limit("20/minute")
async def send_message_stream(
    request: Request,
    conversation_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    from app.core.metrics import llm_stream_duration, semantic_cache_hits, semantic_cache_misses

    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    history = await _load_history(conversation_id, db)
    chunks, query_emb = await _run_retrieval_pipeline(
        body.question, conversation.document_id, db, conversation_id
    )

    # Semantic cache check — if hit, return the cached answer as a one-shot stream
    sc = get_semantic_cache()
    if sc is not None and query_emb is not None:
        cached = await sc.get(query_emb, conversation.document_id)
        if cached is not None:
            semantic_cache_hits.inc()
            db.add(Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question))
            db.add(Message(conversation_id=conversation_id, role=MessageRole.assistant, content=cached))
            await db.commit()

            async def _cached_stream():
                yield f"data: {cached}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_cached_stream(), media_type="text/event-stream")
        semantic_cache_misses.inc()

    # Persist user message + placeholder assistant message (is_complete=False)
    # before streaming starts so a dropped connection never leaves a gap.
    user_msg = Message(conversation_id=conversation_id, role=MessageRole.user, content=body.question)
    assistant_msg = Message(
        conversation_id=conversation_id, role=MessageRole.assistant, content="", is_complete=False
    )
    db.add(user_msg)
    db.add(assistant_msg)
    await db.commit()

    assistant_msg_id = assistant_msg.id
    question = body.question
    doc_id = conversation.document_id

    async def event_stream():
        full_reply: list[str] = []
        success = False
        t0 = time.perf_counter()
        try:
            async for token in chat.generate_reply_stream(
                question=question, chunks=chunks, history=history
            ):
                full_reply.append(token)
                yield f"data: {token}\n\n"
            success = True
        except Exception:
            logger.exception("chat_stream_failed", extra={"conversation_id": conversation_id})
            yield "data: [ERROR]\n\n"

        yield "data: [DONE]\n\n"
        llm_stream_duration.observe(time.perf_counter() - t0)

        # Update the pre-created assistant message with full content
        async with AsyncSessionLocal() as bg_db:
            result = await bg_db.execute(select(Message).where(Message.id == assistant_msg_id))
            msg = result.scalar_one_or_none()
            if msg is not None:
                msg.content = "".join(full_reply)
                msg.is_complete = success
                await bg_db.commit()

        # Write to semantic cache
        if success and sc is not None and query_emb is not None:
            try:
                await sc.set(query_emb, "".join(full_reply), doc_id)
            except Exception:
                logger.warning(
                    "semantic_cache_write_failed", extra={"conversation_id": conversation_id}
                )

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
