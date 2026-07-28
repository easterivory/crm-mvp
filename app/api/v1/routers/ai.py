from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.core.constants import RoleName
from app.models.ai import AIProjectSettings, AIProviderConnection
from app.models.user import User
from app.repositories.ai_repository import AIRepository
from app.schemas.ai import (
    AIModelListOut,
    AIProjectSettingsOut,
    AIProjectSettingsUpdate,
    AIProviderConnectionCreate,
    AIProviderConnectionOut,
    AIProviderConnectionUpdate,
    AIProviderOptionOut,
    AIProviderTestIn,
    AIProviderTestOut,
    AIUsageListOut,
    AIUsageLogOut,
    AIUsageSummaryOut,
)
from app.services.access_control import require_project_access
from app.services.ai_credential_service import (
    AICredentialError,
    AICredentialService,
)
from app.services.ai_gateway_service import (
    AIGatewayError,
    AIGatewayService,
    AIProviderSnapshot,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/providers", response_model=list[AIProviderConnectionOut])
async def list_ai_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AIProviderConnectionOut]:
    _ensure_ai_admin(current_user)
    return [_provider_out(item) for item in await AIRepository(db).list_connections()]


@router.post(
    "/providers",
    response_model=AIProviderConnectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_provider(
    data: AIProviderConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIProviderConnectionOut:
    _ensure_super_admin(current_user)
    credential_service = AICredentialService()
    api_key = data.api_key.strip()
    connection = await AIRepository(db).create_connection(
        name=data.name.strip(),
        provider=data.provider.strip().lower(),
        api_style=data.api_style,
        base_url=data.base_url,
        encrypted_api_key=credential_service.encrypt(api_key),
        api_key_last_four=credential_service.last_four(api_key),
        credential_fingerprint=credential_service.fingerprint(api_key),
        default_model=data.default_model,
        is_active=data.is_active,
        request_timeout_seconds=data.request_timeout_seconds,
        supports_json_mode=data.supports_json_mode,
        pricing_json={
            key: value.model_dump(mode="json")
            for key, value in data.pricing.items()
        },
        created_by_user_id=current_user.id,
    )
    await db.commit()
    return _provider_out(connection)


@router.patch("/providers/{connection_id}", response_model=AIProviderConnectionOut)
async def update_ai_provider(
    connection_id: UUID,
    data: AIProviderConnectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIProviderConnectionOut:
    _ensure_super_admin(current_user)
    repo = AIRepository(db)
    current = await repo.get_connection(connection_id)
    if current is None:
        raise HTTPException(status_code=404, detail="AI provider connection not found")
    values = data.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key", "pricing"})
    if data.pricing is not None:
        values["pricing_json"] = {
            key: value.model_dump(mode="json")
            for key, value in data.pricing.items()
        }
    credential_service = AICredentialService()
    if data.api_key is not None:
        api_key = data.api_key.strip()
        values["encrypted_api_key"] = credential_service.encrypt(api_key)
        values["api_key_last_four"] = credential_service.last_four(api_key)
        values["credential_fingerprint"] = credential_service.fingerprint(api_key)
    elif data.clear_api_key:
        values["encrypted_api_key"] = None
        values["api_key_last_four"] = None
        values["credential_fingerprint"] = None
        values["is_active"] = False
    will_have_key = data.api_key is not None or (
        bool(current.encrypted_api_key) and not data.clear_api_key
    )
    will_be_active = bool(values.get("is_active", current.is_active))
    if will_be_active and not will_have_key:
        raise HTTPException(
            status_code=422,
            detail="Active AI provider connection requires an API key",
        )
    if (
        not will_be_active
        and current.is_active
        and await repo.connection_used_by_enabled_project(connection_id)
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Disable AI in projects that use this connection before "
                "deactivating or clearing it"
            ),
        )
    updated = await repo.update_connection(connection_id, **values)
    assert updated is not None
    await db.commit()
    return _provider_out(updated)


@router.delete(
    "/providers/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_ai_provider(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _ensure_super_admin(current_user)
    repo = AIRepository(db)
    if await repo.connection_used_by_enabled_project(connection_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Disable AI in projects that use this connection before deleting it"
            ),
        )
    if not await repo.soft_delete_connection(connection_id):
        raise HTTPException(status_code=404, detail="AI provider connection not found")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/providers/{connection_id}/test", response_model=AIProviderTestOut)
async def test_ai_provider(
    connection_id: UUID,
    data: AIProviderTestIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIProviderTestOut:
    _ensure_super_admin(current_user)
    connection = await AIRepository(db).get_connection(connection_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=404, detail="Active AI provider connection not found")
    model = data.model or connection.default_model
    if not model:
        raise HTTPException(status_code=422, detail="Specify a model for the connection test")
    snapshot = _provider_snapshot(connection)
    await db.rollback()
    try:
        result = await AIGatewayService().execute(
            connection=snapshot,
            model=model,
            system_prompt=(
                "Return only valid JSON with keys messages, extracted_data and "
                "next_route_key. messages must contain one short confirmation."
            ),
            messages=[{"role": "user", "content": "Проверка подключения"}],
            temperature=0,
            max_output_tokens=100,
        )
    except (AIGatewayError, AICredentialError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIProviderTestOut(
        ok=True,
        model=model,
        latency_ms=result.latency_ms,
        message=result.response.messages[0],
    )


@router.get("/providers/{connection_id}/models", response_model=AIModelListOut)
async def list_ai_provider_models(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIModelListOut:
    _ensure_ai_admin(current_user)
    connection = await AIRepository(db).get_connection(connection_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=404, detail="Active AI provider connection not found")
    configured = [connection.default_model] if connection.default_model else []
    snapshot = _provider_snapshot(connection)
    await db.rollback()
    try:
        models = await AIGatewayService().list_models(snapshot)
    except (AIGatewayError, AICredentialError) as exc:
        return AIModelListOut(
            models=configured,
            live=False,
            warning=str(exc),
        )
    return AIModelListOut(models=models or configured, live=True)


@router.get(
    "/projects/{project_id}/provider-options",
    response_model=list[AIProviderOptionOut],
)
async def list_ai_provider_options(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AIProviderOptionOut]:
    require_project_access(current_user, project_id)
    connections = await AIRepository(db).list_connections()
    return [
        AIProviderOptionOut(
            id=connection.id,
            name=connection.name,
            provider=connection.provider,
            default_model=connection.default_model,
        )
        for connection in connections
        if connection.is_active and connection.encrypted_api_key
    ]


@router.get(
    "/projects/{project_id}/settings",
    response_model=AIProjectSettingsOut,
)
async def get_ai_project_settings(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIProjectSettingsOut:
    _ensure_ai_admin(current_user)
    require_project_access(current_user, project_id)
    current = await AIRepository(db).get_project_settings(project_id)
    return _project_settings_out(project_id, current)


@router.put(
    "/projects/{project_id}/settings",
    response_model=AIProjectSettingsOut,
)
async def update_ai_project_settings(
    project_id: UUID,
    data: AIProjectSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIProjectSettingsOut:
    _ensure_ai_admin(current_user)
    require_project_access(current_user, project_id)
    repo = AIRepository(db)
    await _validate_project_connections(repo, data)
    settings_row = await repo.upsert_project_settings(
        project_id,
        **data.model_dump(),
    )
    await db.commit()
    return _project_settings_out(project_id, settings_row)


@router.get("/usage", response_model=AIUsageListOut)
async def list_ai_usage(
    project_id: UUID,
    date_from: date = Query(),
    date_to: date = Query(),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIUsageListOut:
    _ensure_ai_admin(current_user)
    require_project_access(current_user, project_id)
    start_at, end_at = _date_range(date_from, date_to)
    items, total = await AIRepository(db).list_usage(
        project_id=project_id,
        date_from=start_at,
        date_to=end_at,
        limit=limit,
        offset=offset,
    )
    return AIUsageListOut(
        items=[
            AIUsageLogOut(
                id=item.id,
                connection_id=item.connection_id,
                connection_name=connection_name,
                api_key_mask=(
                    f"••••{item.api_key_last_four}"
                    if item.api_key_last_four
                    else None
                ),
                provider=item.provider,
                model=item.model,
                status=item.status,
                used_fallback=item.used_fallback,
                prompt_tokens=item.prompt_tokens,
                completion_tokens=item.completion_tokens,
                total_tokens=item.total_tokens,
                estimated_cost_usd=item.estimated_cost_usd,
                latency_ms=item.latency_ms,
                error_code=item.error_code,
                error_message=item.error_message,
                created_at=item.created_at,
            )
            for item, connection_name in items
        ],
        total=total,
    )


@router.get("/usage/summary", response_model=AIUsageSummaryOut)
async def get_ai_usage_summary(
    project_id: UUID,
    date_from: date = Query(),
    date_to: date = Query(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIUsageSummaryOut:
    _ensure_ai_admin(current_user)
    require_project_access(current_user, project_id)
    start_at, end_at = _date_range(date_from, date_to)
    summary = await AIRepository(db).usage_summary(
        project_id=project_id,
        date_from=start_at,
        date_to=end_at,
    )
    return AIUsageSummaryOut(date_from=start_at, date_to=end_at, **summary)


def _provider_out(connection: AIProviderConnection) -> AIProviderConnectionOut:
    mask = (
        f"••••{connection.api_key_last_four}"
        if connection.api_key_last_four
        else None
    )
    return AIProviderConnectionOut(
        id=connection.id,
        name=connection.name,
        provider=connection.provider,
        api_style=connection.api_style,
        base_url=connection.base_url,
        default_model=connection.default_model,
        is_active=connection.is_active,
        request_timeout_seconds=connection.request_timeout_seconds,
        supports_json_mode=connection.supports_json_mode,
        pricing=connection.pricing_json or {},
        has_api_key=bool(connection.encrypted_api_key),
        api_key_mask=mask,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _provider_snapshot(connection: AIProviderConnection) -> AIProviderSnapshot:
    return AIProviderSnapshot(
        id=connection.id,
        provider=connection.provider,
        api_style=connection.api_style,
        base_url=connection.base_url,
        api_key=AICredentialService().decrypt(connection.encrypted_api_key),
        credential_fingerprint=connection.credential_fingerprint,
        api_key_last_four=connection.api_key_last_four,
        request_timeout_seconds=connection.request_timeout_seconds,
        supports_json_mode=connection.supports_json_mode,
        pricing_json=dict(connection.pricing_json or {}),
    )


def _project_settings_out(
    project_id: UUID,
    settings_row: AIProjectSettings | None,
) -> AIProjectSettingsOut:
    if settings_row is None:
        return AIProjectSettingsOut(project_id=project_id)
    return AIProjectSettingsOut(
        project_id=project_id,
        is_enabled=settings_row.is_enabled,
        primary_connection_id=settings_row.primary_connection_id,
        primary_model=settings_row.primary_model,
        fallback_connection_id=settings_row.fallback_connection_id,
        fallback_model=settings_row.fallback_model,
        master_prompt=settings_row.master_prompt,
        history_message_limit=settings_row.history_message_limit,
        max_context_chars=settings_row.max_context_chars,
        default_temperature=settings_row.default_temperature,
        default_max_output_tokens=settings_row.default_max_output_tokens,
        typing_delay_per_char_ms=settings_row.typing_delay_per_char_ms,
        min_delay_ms=settings_row.min_delay_ms,
        max_delay_ms=settings_row.max_delay_ms,
        daily_budget_usd=settings_row.daily_budget_usd,
        monthly_budget_usd=settings_row.monthly_budget_usd,
        created_at=settings_row.created_at,
        updated_at=settings_row.updated_at,
    )


async def _validate_project_connections(
    repo: AIRepository,
    data: AIProjectSettingsUpdate,
) -> None:
    connections: dict[UUID, AIProviderConnection] = {}
    for connection_id in {
        data.primary_connection_id,
        data.fallback_connection_id,
    } - {None}:
        assert connection_id is not None
        connection = await repo.get_connection(connection_id, active_only=True)
        if connection is None:
            if not data.is_enabled:
                continue
            raise HTTPException(
                status_code=422,
                detail=f"AI provider connection {connection_id} is missing or inactive",
            )
        if not connection.encrypted_api_key:
            if not data.is_enabled:
                continue
            raise HTTPException(
                status_code=422,
                detail=f"AI provider connection {connection_id} has no API key",
            )
        connections[connection_id] = connection

    if not data.is_enabled:
        return

    has_budget = (
        data.daily_budget_usd is not None
        or data.monthly_budget_usd is not None
    )
    if not has_budget:
        return

    configured_models = (
        (data.primary_connection_id, data.primary_model, "primary"),
        (data.fallback_connection_id, data.fallback_model, "fallback"),
    )
    for connection_id, model, label in configured_models:
        if connection_id is None or not model:
            continue
        connection = connections[connection_id]
        if model not in (connection.pricing_json or {}):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Configure token pricing for the {label} model "
                    f"'{model}' before enabling an AI budget"
                ),
            )


def _date_range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must not be before date_from")
    if (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail="Usage range cannot exceed 367 days")
    start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    return start_at, datetime.combine(
        date_to + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )


def _ensure_ai_admin(user: User) -> None:
    if user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(status_code=403, detail="AI settings require admin access")


def _ensure_super_admin(user: User) -> None:
    if user.role_name != RoleName.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only super_admin can manage provider credentials",
        )
