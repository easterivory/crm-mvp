"""
/api/v1/chats — chat listing and retrieval.

Project-bound users receive project_id from their authenticated context.
super_admin users pass project_id as a query parameter for scoped requests.

Implemented endpoints cover chat listing, retrieval, audit history,
creation, read state, reset, and saved filter presets.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.models.user import User
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.chat import (
    ChatCreate,
    ChatFavoriteUpdate,
    ChatFilters,
    ChatLanguageUpdate,
    ChatOut,
    ChatWorkspaceCountsOut,
    ChatWorkspaceView,
)
from app.schemas.chat_event_log import ChatEventLogOut
from app.schemas.chat_filter_preset import (
    ChatFilterPresetCreate,
    ChatFilterPresetOut,
    ChatFilterPresetUpdate,
)
from app.schemas.common import PaginatedResponse
from app.schemas.funnel import (
    ChatFunnelControlOut,
    ChatFunnelResumeIn,
    ChatFunnelSmartResumeIn,
    FunnelRuntimeLogOut,
)
from app.services.chat_filter_preset_service import ChatFilterPresetService
from app.services.chat_audit_service import ChatAuditService
from app.services.chat_service import ChatService
from app.services.funnel_runtime_service import FunnelRuntimeService

router = APIRouter(prefix="/chats", tags=["chats"])

CHAT_TRACE_ROLES = {
    RoleName.SUPER_ADMIN,
    RoleName.ADMIN,
    RoleName.MANAGER,
    RoleName.BUYER,
    RoleName.OPERATOR,
}


def _ensure_chat_trace_access(current_user: User) -> None:
    if current_user.role_name not in CHAT_TRACE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only operator, manager, admin or super_admin can view funnel trace",
        )


def _ensure_chat_language_access(current_user: User) -> None:
    if current_user.role_name not in RoleName.ALL or current_user.role_name == RoleName.BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only operator, manager, admin or super_admin can update chat language",
        )


def _ensure_chat_destructive_access(current_user: User) -> None:
    if current_user.role_name not in RoleName.ALL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user cannot manage dialog lifecycle",
        )
    if current_user.role_name in {RoleName.MANAGER, RoleName.BUYER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers cannot reset or block dialogs",
        )


@router.get("", response_model=PaginatedResponse[ChatOut])
async def list_chats(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unread: Optional[bool] = Query(default=None),
    unanswered: Optional[bool] = Query(default=None),
    has_unanswered_incoming: Optional[bool] = Query(default=None),
    is_red: Optional[bool] = Query(default=None),
    is_hot_lead: Optional[bool] = Query(default=None),
    manager_id: Optional[UUID] = Query(default=None),
    assigned_user_id: Optional[UUID] = Query(default=None),
    unassigned: Optional[bool] = Query(default=None),
    bot_id: Optional[UUID] = Query(default=None),
    bot_ids: Optional[str] = Query(default=None),
    bot_ids_array: Optional[list[UUID]] = Query(default=None, alias="bot_ids[]"),
    q: Optional[str] = Query(default=None, max_length=255),
    tracking_link_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
    tag_ids: Optional[str] = Query(default=None),
    tag_ids_array: Optional[list[UUID]] = Query(default=None, alias="tag_ids[]"),
    tag_mode: str = Query(default="any", pattern="^(any|all)$"),
    lead_statuses: Optional[str] = Query(default=None),
    lead_statuses_array: Optional[list[str]] = Query(
        default=None,
        alias="lead_statuses[]",
    ),
    funnel_state: Optional[str] = Query(
        default=None,
        pattern="^(in_funnel|waiting_for_answer|paused|completed|manual)$",
    ),
    current_step_id: Optional[UUID] = Query(default=None),
    sort_by: str = Query(default="latest", pattern="^(latest|priority)$"),
    workspace_view: Optional[ChatWorkspaceView] = Query(default=None, alias="view"),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ChatOut]:
    """
    Returns a paginated list of chats for the current project.

    Filters (all optional, additive):
      - unread=true      — only chats with unread messages
      - unanswered=true  — only chats waiting for a manager reply
      - is_red=true      — only chats that breached the SLA threshold
      - is_hot_lead=true — only sales-hot chats with high lead quality
      - manager_id=<uuid> — only chats whose lead is assigned to this manager
      - assigned_user_id=<uuid> — same as manager_id, preferred frontend name
      - unassigned=true — only chats without manager
      - bot_id=<uuid>    — only chats for one bot
      - bot_ids=<csv>    — only chats for multiple bots
      - q=<text>         — search lead/chat/tracking/message fields
      - tracking_link_id=<uuid> — only chats attributed to a link
      - date_from/date_to — filter by the visible latest chat activity
      - timezone_offset_minutes — browser UTC offset used for local date boundaries
      - tag_ids=<csv>    — only chats whose lead has selected tags
      - tag_mode=any|all — tag matching mode
      - lead_statuses=<csv> — only chats whose lead status code matches
      - funnel_state=in_funnel|waiting_for_answer|paused|completed|manual

    Sort order:
      - latest: latest dialog activity first
      - priority: SLA-red, unanswered, then latest activity
    """
    date_from_dt, date_to_dt = ChatService.date_range_to_datetimes(
        date_from,
        date_to,
        timezone_offset_minutes=timezone_offset_minutes,
    )
    filters = ChatFilters(
        q=q,
        unread=unread,
        unanswered=unanswered,
        has_unanswered_incoming=has_unanswered_incoming,
        is_red=is_red,
        is_hot_lead=is_hot_lead,
        manager_id=manager_id,
        assigned_user_id=assigned_user_id,
        unassigned=unassigned,
        bot_id=bot_id,
        bot_ids=_merge_uuid_values(_parse_bot_ids(bot_ids), bot_ids_array),
        tracking_link_id=tracking_link_id,
        date_from=date_from_dt,
        date_to=date_to_dt,
        tag_ids=_merge_uuid_values(
            _parse_uuid_csv(tag_ids, "tag_ids"),
            tag_ids_array,
        ),
        tag_mode=tag_mode,
        lead_statuses=_merge_string_values(
            _parse_string_csv(lead_statuses),
            lead_statuses_array,
        ),
        funnel_state=funnel_state,
        current_step_id=current_step_id,
        sort_by=sort_by,
        workspace_view=workspace_view,
    )
    items, total = await ChatService(db).get_chat_list(
        project_id=project_id,
        filters=filters,
        limit=limit,
        offset=offset,
        actor=current_user,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


def _parse_bot_ids(value: Optional[str]) -> list[UUID]:
    return _parse_uuid_csv(value, "bot_ids")


def _parse_uuid_csv(value: Optional[str], field_name: str) -> list[UUID]:
    if not value:
        return []

    ids: list[UUID] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            ids.append(UUID(item))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must be a comma-separated list of UUIDs",
            ) from exc
    return ids


def _parse_string_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _merge_uuid_values(
    csv_values: list[UUID],
    array_values: Optional[list[UUID]],
) -> list[UUID]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for value in [*csv_values, *(array_values or [])]:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _merge_string_values(
    csv_values: list[str],
    array_values: Optional[list[str]],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_value in [*csv_values, *(array_values or [])]:
        value = raw_value.strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


@router.get("/workspace-counts", response_model=ChatWorkspaceCountsOut)
async def get_chat_workspace_counts(
    bot_id: Optional[UUID] = Query(default=None),
    bot_ids: Optional[str] = Query(default=None),
    bot_ids_array: Optional[list[UUID]] = Query(default=None, alias="bot_ids[]"),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatWorkspaceCountsOut:
    return await ChatService(db).get_workspace_counts(
        project_id=project_id,
        actor=current_user,
        bot_id=bot_id,
        bot_ids=_merge_uuid_values(_parse_bot_ids(bot_ids), bot_ids_array),
    )


@router.get("/filter-presets", response_model=list[ChatFilterPresetOut])
async def list_filter_presets(
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatFilterPresetOut]:
    return await ChatFilterPresetService(db).list_presets(
        actor=current_user,
        project_id=project_id,
    )


@router.post(
    "/filter-presets",
    response_model=ChatFilterPresetOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_filter_preset(
    data: ChatFilterPresetCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatFilterPresetOut:
    return await ChatFilterPresetService(db).create_preset(
        actor=current_user,
        data=data,
    )


@router.patch("/filter-presets/{preset_id}", response_model=ChatFilterPresetOut)
async def update_filter_preset(
    preset_id: UUID,
    data: ChatFilterPresetUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatFilterPresetOut:
    return await ChatFilterPresetService(db).update_preset(
        preset_id=preset_id,
        actor=current_user,
        data=data,
    )


@router.delete("/filter-presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filter_preset(
    preset_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ChatFilterPresetService(db).delete_preset(
        preset_id=preset_id,
        actor=current_user,
    )


@router.get("/{chat_id}", response_model=ChatOut)
async def get_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    """Returns a single chat with computed flags (unread, unanswered, is_red)."""
    return await ChatService(db).get_chat(
        chat_id=chat_id,
        project_id=project_id,
        actor=current_user,
    )


@router.patch("/{chat_id}/favorite", response_model=ChatOut)
async def update_chat_favorite(
    chat_id: UUID,
    data: ChatFavoriteUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    _ensure_chat_trace_access(current_user)
    return await ChatService(db).set_favorite(
        chat_id=chat_id,
        project_id=project_id,
        is_favorite=data.is_favorite,
    )


@router.patch("/{chat_id}/language", response_model=ChatOut)
async def update_chat_language(
    chat_id: UUID,
    data: ChatLanguageUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    _ensure_chat_language_access(current_user)
    return await ChatService(db).update_language(
        chat_id=chat_id,
        project_id=project_id,
        data=data,
    )


@router.get("/{chat_id}/audit-logs", response_model=list[ChatEventLogOut])
async def list_chat_audit_logs(
    chat_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatEventLogOut]:
    events = await ChatAuditService(db).list_events(
        chat_id=chat_id,
        project_id=project_id,
        actor=current_user,
        limit=limit,
        offset=offset,
    )
    return [ChatEventLogOut.from_event(event) for event in events]


@router.get("/{chat_id}/funnel-trace", response_model=list[FunnelRuntimeLogOut])
async def get_funnel_trace(
    chat_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FunnelRuntimeLogOut]:
    _ensure_chat_trace_access(current_user)
    chat = await ChatService(db).get_chat(chat_id=chat_id, project_id=project_id)
    logs = await FunnelRepository(db).list_runtime_logs_by_chat(
        chat_id=chat_id,
        limit=limit,
        since=chat.current_cycle_started_at,
    )
    return [FunnelRuntimeLogOut.from_runtime_log(log) for log in logs]


@router.get("/{chat_id}/funnel-control", response_model=ChatFunnelControlOut)
async def get_chat_funnel_control(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatFunnelControlOut:
    _ensure_chat_trace_access(current_user)
    control = await FunnelRuntimeService(db).get_manager_funnel_control(
        chat_id=chat_id,
        project_id=project_id,
    )
    return ChatFunnelControlOut.model_validate(control)


@router.post("/{chat_id}/funnel-resume", response_model=ChatFunnelControlOut)
async def resume_chat_funnel(
    chat_id: UUID,
    data: ChatFunnelResumeIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatFunnelControlOut:
    _ensure_chat_trace_access(current_user)
    if current_user.role_name == RoleName.BUYER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Buyers have read-only chat access")
    try:
        resumed = await FunnelRuntimeService(db).resume_from_manager_step(
            chat_id=chat_id,
            project_id=project_id,
            step_id=data.step_id,
            actor=current_user,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if resumed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The funnel is not paused or the selected step is unavailable.",
        )
    control = await FunnelRuntimeService(db).get_manager_funnel_control(
        chat_id=chat_id,
        project_id=project_id,
    )
    return ChatFunnelControlOut.model_validate(control)


@router.post("/{chat_id}/resume-funnel", response_model=ChatFunnelControlOut)
async def smart_resume_chat_funnel(
    chat_id: UUID,
    data: ChatFunnelSmartResumeIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatFunnelControlOut:
    _ensure_chat_trace_access(current_user)
    if current_user.role_name == RoleName.BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers have read-only chat access",
        )
    try:
        resumed = await FunnelRuntimeService(db).resume_funnel_from_manager(
            chat_id=chat_id,
            project_id=project_id,
            actor=current_user,
            target_step_id=data.target_step_id,
            manager_approved=data.manager_approved,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if not resumed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The funnel is not paused or the requested resume mode is unavailable.",
        )
    control = await FunnelRuntimeService(db).get_manager_funnel_control(
        chat_id=chat_id,
        project_id=project_id,
    )
    return ChatFunnelControlOut.model_validate(control)


@router.post("", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
async def create_chat(
    data: ChatCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    if current_user.role_name == RoleName.BUYER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Buyers have read-only chat access")
    return await ChatService(db).create_chat(project_id=project_id, data=data)


@router.post("/{chat_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_as_read(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Sets last_read_at = now(). Clears the computed unread flag."""
    await ChatService(db).mark_as_read(chat_id=chat_id, project_id=project_id)


@router.post("/{chat_id}/reset", response_model=ChatOut)
async def reset_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    """Soft-clears the active dialog cycle without deleting Telegram history."""
    _ensure_chat_destructive_access(current_user)
    return await ChatService(db).reset_chat(
        chat_id=chat_id,
        project_id=project_id,
        actor_id=current_user.id,
    )


@router.post("/{chat_id}/block", response_model=ChatOut)
async def block_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    _ensure_chat_destructive_access(current_user)
    return await ChatService(db).set_chat_blocked(
        chat_id=chat_id,
        project_id=project_id,
        actor_id=current_user.id,
        is_blocked=True,
    )


@router.post("/{chat_id}/unblock", response_model=ChatOut)
async def unblock_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    _ensure_chat_destructive_access(current_user)
    return await ChatService(db).set_chat_blocked(
        chat_id=chat_id,
        project_id=project_id,
        actor_id=current_user.id,
        is_blocked=False,
    )
