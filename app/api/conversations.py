from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.conversation import Conversation, Message

router = APIRouter()


class ConversationMove(BaseModel):
    folder_id: str | None = None


@router.get("/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).order_by(Conversation.created_at.desc()))
    convs = result.scalars().all()
    return [
        {"id": c.id, "title": c.title, "folder_id": c.folder_id, "created_at": c.created_at}
        for c in convs
    ]


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    msgs_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    msgs = msgs_result.scalars().all()
    return {
        "id": conv.id,
        "title": conv.title,
        "folder_id": conv.folder_id,
        "created_at": conv.created_at,
        "messages": [
            {"role": m.role.value, "content": m.content, "created_at": m.created_at}
            for m in msgs
        ],
    }


@router.patch("/conversations/{conv_id}")
async def move_conversation(conv_id: str, body: ConversationMove, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.folder_id = body.folder_id
    await db.commit()
    return {"id": conv.id, "title": conv.title, "folder_id": conv.folder_id}
