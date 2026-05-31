from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.conversation import Conversation, Message
from app.models.user import User

router = APIRouter()


class ConversationMove(BaseModel):
    folder_id: str | None = None


async def _get_owned_conversation(
    conv_id: str,
    db: AsyncSession,
    current_user: User,
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    convs = result.scalars().all()
    return [
        {"id": c.id, "title": c.title, "folder_id": c.folder_id, "created_at": c.created_at}
        for c in convs
    ]


@router.get("/conversations/{conv_id}")
async def get_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = await _get_owned_conversation(conv_id, db, current_user)
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
async def move_conversation(
    conv_id: str,
    body: ConversationMove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = await _get_owned_conversation(conv_id, db, current_user)
    conv.folder_id = body.folder_id
    await db.commit()
    return {"id": conv.id, "title": conv.title, "folder_id": conv.folder_id}


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = await _get_owned_conversation(conv_id, db, current_user)
    msgs = await db.execute(select(Message).where(Message.conversation_id == conv_id))
    for msg in msgs.scalars().all():
        await db.delete(msg)
    await db.delete(conv)
    await db.commit()
