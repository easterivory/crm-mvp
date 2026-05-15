from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_db
from app.schemas.bot import BotCreate, BotOut, BotStepOut, BotUpdate, BotWebhookOut
from app.schemas.common import PaginatedResponse
from app.services.bot_service import BotService

router = APIRouter(tags=["bots"])


@router.get("/bots", response_model=PaginatedResponse[BotOut])
async def list_bots(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: Optional[UUID] = Query(default=None),
    current_project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[BotOut]:
    items, total = await BotService(db).list_bots(
        project_id=project_id or current_project_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/bots", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    data: BotCreate,
    current_project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    return await BotService(db).create_bot(project_id=current_project_id, data=data)


@router.get("/bot_steps", response_model=list[BotStepOut])
async def list_bot_steps(
    bot_id: UUID = Query(...),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> list[BotStepOut]:
    return await BotService(db).list_bot_steps(bot_id=bot_id, project_id=project_id)


@router.get("/bots/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    return await BotService(db).get_bot(bot_id=bot_id, project_id=project_id)


@router.patch("/bots/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: UUID,
    data: BotUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    return await BotService(db).update_bot(
        bot_id=bot_id,
        project_id=project_id,
        data=data,
    )


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await BotService(db).delete_bot(bot_id=bot_id, project_id=project_id)


@router.post("/bots/{bot_id}/webhook", response_model=BotWebhookOut)
async def set_bot_webhook(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BotWebhookOut:
    return await BotService(db).set_webhook(bot_id=bot_id, project_id=project_id)
