import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.conversation import Conversation, Folder

router = APIRouter()


class FolderCreate(BaseModel):
    name: str


class FolderRename(BaseModel):
    name: str


@router.post("/folders", status_code=201)
async def create_folder(body: FolderCreate, db: AsyncSession = Depends(get_db)):
    folder = Folder(id=str(_uuid.uuid4()), name=body.name.strip())
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "created_at": folder.created_at, "conversation_count": 0}


@router.get("/folders")
async def list_folders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).order_by(Folder.created_at))
    folders = result.scalars().all()

    counts: dict[str, int] = {}
    if folders:
        count_result = await db.execute(
            select(Conversation.folder_id, func.count(Conversation.id))
            .where(Conversation.folder_id.isnot(None))
            .group_by(Conversation.folder_id)
        )
        counts = dict(count_result.all())

    return [
        {
            "id": f.id,
            "name": f.name,
            "created_at": f.created_at,
            "conversation_count": counts.get(f.id, 0),
        }
        for f in folders
    ]


@router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderRename, db: AsyncSession = Depends(get_db)):
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    folder.name = body.name.strip()
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "created_at": folder.created_at}


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    await db.execute(
        update(Conversation).where(Conversation.folder_id == folder_id).values(folder_id=None)
    )
    await db.delete(folder)
    await db.commit()
