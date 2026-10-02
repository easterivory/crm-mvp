from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from app.core.constants import RoleName
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.tag import Tag
from app.models.bot import Bot
from app.models.lead_status import LeadStatus
from app.models.tracking import TrackingLink
from app.models.traffic_quality import TrafficQualitySettings, TrafficQualityOverride, TrafficQualityState, TrafficQualityDelivery, TrafficQualityAcknowledgement
from app.models.user import User, UserProjectAccess
from app.models.role import Role
from app.repositories.traffic_quality_repository import TrafficQualityRepository
from app.schemas.traffic_quality import QualityConfig, QualityOverrides, effective_rules
from app.services.access_control import require_project_access, has_project_access
from app.services.traffic_expression import evaluate_expression


def rule_hash(rule, tz):
    return hashlib.sha256(json.dumps([rule.model_dump(mode="json"), tz], sort_keys=True).encode()).hexdigest()


def evaluate_rule(rule, snapshot):
    metrics = snapshot["metrics"]
    sample = metrics.get(rule.sample_metric)
    reason = None
    value = evaluate_expression(rule.expression, metrics)
    if sample is None or sample < rule.min_sample:
        reason = f"Недостаточная выборка: {sample if sample is not None else 'нет данных'} / {rule.min_sample} ({rule.sample_metric})"
    elif rule.min_coverage and (metrics.get("coverage") or 0) < rule.min_coverage:
        reason = f"Оценено менее {rule.min_coverage:g}% лидов"
    elif value is None:
        reason = "Нет данных для формулы или знаменатель равен нулю"
    breached = value is not None and (value < rule.threshold if rule.operator == "lt" else value > rule.threshold)
    recovered = value is not None and (value >= rule.recovery_threshold if rule.operator == "lt" else value <= rule.recovery_threshold)
    return {**snapshot, "rule_id": str(rule.id), "rule_name": rule.name, "expression": rule.expression,
            "value": value, "sample": sample, "threshold": rule.threshold, "operator": rule.operator,
            "reason": reason, "status": "insufficient_data" if reason else ("breach" if breached else "normal"),
            "recovered": recovered and not reason}


class TrafficQualityService:
    def __init__(self, db):
        self.db = db

    async def project(self, project_id, actor, *, write=False, admin_only=False):
        require_project_access(actor, project_id)
        if (write or admin_only) and actor.role_name not in {RoleName.ADMIN, RoleName.SUPER_ADMIN}:
            raise HTTPException(403, "Настройка правил доступна только администратору")
        stmt = select(Project).where(Project.id == project_id, Project.is_deleted.is_(False))
        if write:
            stmt = stmt.with_for_update()
        project = await self.db.scalar(stmt)
        if project is None:
            raise HTTPException(404, "Проект не найден")
        return project

    async def config(self, project_id):
        row = await self.db.get(TrafficQualitySettings, project_id)
        return QualityConfig.model_validate({**row.config, "revision": row.revision}) if row else QualityConfig()

    async def overrides(self, link_id):
        row = await self.db.get(TrafficQualityOverride, link_id)
        return QualityOverrides.model_validate({**row.config, "revision": row.revision}) if row else QualityOverrides()

    async def link(self, link_id, actor, *, write=False):
        link = await self.db.get(TrackingLink, link_id)
        if link is None:
            raise HTTPException(404, "Ссылка не найдена")
        await self.project(link.project_id, actor, write=write)
        if actor.role_name == RoleName.BUYER and link.buyer_id != actor.id:
            raise HTTPException(404, "Ссылка не найдена")
        return link

    async def validate_rules(self, project_id, rules):
        tag_ids = {tag for r in rules for tag in [*r.tag_ids, *r.assessed_tag_ids]}
        bot_ids = {bot for r in rules for bot in r.bot_ids}
        statuses = {code for r in rules for code in r.assessed_status_codes}
        for model, field, expected in ((Tag, Tag.id, tag_ids), (Bot, Bot.id, bot_ids), (LeadStatus, LeadStatus.code, statuses)):
            if expected:
                stmt = select(field).where(field.in_(expected))
                if model is not LeadStatus:
                    stmt = stmt.where(model.project_id == project_id)
                actual = set((await self.db.scalars(stmt)).all())
                if actual != expected:
                    raise HTTPException(422, "Тег, бот или статус отсутствует в этом проекте")

    async def ensure_tag_unused(self, project_id, tag_id):
        config = await self.config(project_id)
        rules = list(config.rules)
        overrides = (await self.db.scalars(select(TrafficQualityOverride).join(TrackingLink, TrackingLink.id == TrafficQualityOverride.link_id).where(TrackingLink.project_id == project_id))).all()
        for row in overrides:
            rules.extend(effective_rules(config, QualityOverrides.model_validate(row.config)))
        if any(tag_id in [*rule.tag_ids, *rule.assessed_tag_ids] for rule in rules):
            raise HTTPException(409, "Тег используется в правилах качества трафика. Сначала уберите его из правил проекта и ссылок")

    async def save_config(self, project_id, actor, config):
        await self.project(project_id, actor, write=True)
        previous = await self.config(project_id)
        if previous.revision != config.revision:
            raise HTTPException(409, "Настройки изменены другим пользователем. Обновите страницу")
        await self.validate_rules(project_id, config.rules)
        # Changing a base rule must not silently invalidate existing overrides.
        rows = (await self.db.scalars(select(TrafficQualityOverride).join(TrackingLink, TrackingLink.id == TrafficQualityOverride.link_id).where(TrackingLink.project_id == project_id))).all()
        try:
            for row in rows:
                await self.validate_rules(project_id, effective_rules(config, QualityOverrides.model_validate(row.config)))
        except ValueError as exc:
            raise HTTPException(422, f"Конфликт с настройками ссылки: {exc}") from exc
        config = config.model_copy(update={"revision": config.revision + 1})
        row = await self.db.get(TrafficQualitySettings, project_id)
        if row is None:
            row = TrafficQualitySettings(project_id=project_id)
            self.db.add(row)
        row.config, row.revision = config.model_dump(mode="json"), config.revision
        self.audit(project_id, actor.id, "traffic_quality_settings", project_id, previous.model_dump(mode="json"), row.config)
        await self.db.flush()
        return config

    async def save_overrides(self, link_id, actor, overrides):
        link = await self.link(link_id, actor, write=True)
        config = await self.config(link.project_id)
        previous = await self.overrides(link_id)
        if previous.revision != overrides.revision:
            raise HTTPException(409, "Настройки ссылки изменены. Обновите страницу")
        if set(overrides.patches) - {r.id for r in config.rules}:
            raise HTTPException(422, "Базовое правило удалено; обновите страницу")
        try:
            rules = effective_rules(config, overrides)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await self.validate_rules(link.project_id, rules)
        overrides = overrides.model_copy(update={"revision": overrides.revision + 1})
        row = await self.db.get(TrafficQualityOverride, link_id)
        if row is None:
            row = TrafficQualityOverride(link_id=link_id)
            self.db.add(row)
        row.config, row.revision = overrides.model_dump(mode="json"), overrides.revision
        self.audit(link.project_id, actor.id, "traffic_quality_override", link.id, previous.model_dump(mode="json"), row.config)
        await self.db.flush()
        return overrides

    def audit(self, project_id, actor_id, entity_type, entity_id, old, new):
        self.db.add(AuditLog(project_id=project_id, actor_id=actor_id, entity_type=entity_type, entity_id=entity_id,
                             action="traffic_quality.updated", meta={"old": old, "new": new}))

    async def preview(self, project_id, actor, config, link_id=None, overrides=None, offset=0):
        project = await self.project(project_id, actor, write=True)
        await self.validate_rules(project_id, config.rules)
        stmt = select(TrackingLink).where(TrackingLink.project_id == project_id, TrackingLink.is_active.is_(True)).order_by(TrackingLink.id)
        if link_id:
            stmt = stmt.where(TrackingLink.id == link_id)
        links = (await self.db.scalars(stmt.offset(offset).limit(21))).all()
        results = []
        now = datetime.now(timezone.utc)
        for link in links[:20]:
            effective = effective_rules(config, overrides if overrides is not None else await self.overrides(link.id))
            await self.validate_rules(project_id, effective)
            for rule in effective:
                if self.applies(rule, link):
                    snapshot = await TrafficQualityRepository(self.db).metrics(project, link, rule, now, config.timezone)
                    results.append({"link_id": str(link.id), "link_title": link.title, **evaluate_rule(rule, snapshot)})
        return {"items": results, "next_offset": offset + 20 if len(links) > 20 else None}

    @staticmethod
    def applies(rule, link):
        return rule.enabled and (rule.destination == "all" or rule.destination == link.destination_type) and (
            not rule.bot_ids or link.bot_id in rule.bot_ids
        ) and (not rule.ad_types or link.ad_type in rule.ad_types)

    async def check_link(self, project, link, config):
        now = datetime.now(timezone.utc)
        rules = effective_rules(config, await self.overrides(link.id))
        valid_ids = {r.id for r in rules if self.applies(r, link)}
        old_states = (await self.db.scalars(select(TrafficQualityState).where(TrafficQualityState.link_id == link.id))).all()
        for state in old_states:
            if state.rule_id not in valid_ids:
                state.active, state.hits, state.status = False, 0, "disabled"
        notifications = {"buyer": [], "admin": []}
        for rule in rules:
            if not self.applies(rule, link):
                continue
            signature = rule_hash(rule, config.timezone)
            state = await self.db.get(TrafficQualityState, (link.id, rule.id))
            # Concurrent workers serialize this link; consecutive checks need time separation.
            if state and state.config_hash == signature and now - state.checked_at < timedelta(minutes=10):
                continue
            try:
                await self.validate_rules(project.id, [rule])
            except HTTPException:
                if state is None:
                    state = TrafficQualityState(link_id=link.id, rule_id=rule.id, config_hash=signature,
                        active=False, generation=0)
                    self.db.add(state)
                state.status, state.hits = "configuration_error", 0
                state.config_hash = signature
                state.snapshot = {"rule_name": rule.name, "reason": "Тег, бот или статус правила удалён из проекта"}
                state.checked_at = now
                continue
            snapshot = evaluate_rule(rule, await TrafficQualityRepository(self.db).metrics(project, link, rule, now, config.timezone))
            if state is None:
                state = TrafficQualityState(link_id=link.id, rule_id=rule.id, config_hash=signature,
                    hits=0, active=False, generation=0, checked_at=now, snapshot={})
                self.db.add(state)
            if state.config_hash != signature:
                state.hits, state.active = 0, False
            state.config_hash, state.checked_at, state.snapshot = signature, now, snapshot
            state.status = snapshot["status"]
            notify = None
            if state.status == "insufficient_data":
                state.hits = 0
            elif state.status == "breach":
                state.hits += 1
                if not state.active and state.hits >= rule.confirmations:
                    state.active, state.generation = True, state.generation + 1
                    notify = "Нарушение"
                elif state.active and (not state.last_notified_at or now - state.last_notified_at >= timedelta(hours=rule.repeat_hours)):
                    notify = "Напоминание"
            elif snapshot["recovered"]:
                state.hits = 0
                if state.active:
                    state.active = False
                    if rule.notify_recovery:
                        notify = "Восстановление"
            else:
                state.hits = 0
            if state.active and state.status != "insufficient_data":
                state.status = "alert"
            if notify:
                state.last_notified_at = now
                payload = {"rule_id": str(rule.id), "config_hash": signature, "active": state.active, "generation": state.generation}
                value = snapshot["value"]
                metrics = snapshot["metrics"]
                period = " — ".join(datetime.fromisoformat(snapshot[k]).astimezone(ZoneInfo(config.timezone)).strftime("%d.%m %H:%M") for k in ("period_from", "period_to"))
                text = (f"{notify}: {rule.name} ({rule.severity})\n{period} ({config.timezone})\n"
                        f"{rule.expression} = {value:.2f}; порог {'<' if rule.operator == 'lt' else '>'} {rule.threshold:g}\n"
                        f"Выборка {rule.sample_metric}: {snapshot['sample']} / минимум {rule.min_sample}\n"
                        f"Лиды: {metrics['leads']}; оценены: {metrics['assessed_leads']}; выбранные теги: {metrics['tagged_leads']}")
                if rule.notify_buyer:
                    notifications["buyer"].append((text, payload))
                if rule.notify_admin:
                    notifications["admin"].append((text, payload))
        await self.db.flush()
        for kind, entries in notifications.items():
            if not entries:
                continue
            recipients = await self.recipients(project.id, link, kind)
            # Bound message size below Telegram's 4096 character limit.
            for index in range(0, len(entries), 3):
                group = entries[index:index + 3]
                body = f"Качество трафика: {project.name}\nСсылка: {link.title} [{link.code}]\n\n" + "\n\n".join(item[0] for item in group)
                for recipient in recipients:
                    # A newer reminder supersedes unsent older reminders, not a
                    # claimed send or a recovery notification.
                    pending = (await self.db.scalars(select(TrafficQualityDelivery).where(
                        TrafficQualityDelivery.link_id == link.id, TrafficQualityDelivery.recipient_id == recipient,
                        TrafficQualityDelivery.status.in_(("pending", "retry")),
                    ))).all()
                    group_ids = {item[1]["rule_id"] for item in group}
                    for previous in pending:
                        previous_ids = {item["rule_id"] for item in previous.payload.get("rules", [])}
                        if previous_ids and previous_ids.issubset(group_ids):
                            previous.status, previous.error = "cancelled", "Заменено актуальным уведомлением"
                    key = f"{link.id}:{kind}:{recipient}:{now.isoformat()}:{index}"
                    self.db.add(TrafficQualityDelivery(project_id=project.id, link_id=link.id, recipient_id=recipient,
                        bot_kind=kind, dedup_key=key, body=body, payload={"rules": [item[1] for item in group]},
                        status="pending", attempts=0, available_at=now))

    async def recipients(self, project_id, link, kind):
        if kind == "buyer":
            return [link.buyer_id] if link.buyer_id else []
        stmt = select(User.id).join(Role, Role.id == User.role_id).where(User.is_deleted.is_(False), (
            (Role.name == RoleName.SUPER_ADMIN) | ((Role.name == RoleName.ADMIN) & (
                (User.project_id == project_id) | User.id.in_(select(UserProjectAccess.user_id).where(UserProjectAccess.project_id == project_id))
            ))))
        return list((await self.db.scalars(stmt)).all())

    async def acknowledge(self, link_id, actor, hours):
        link = await self.link(link_id, actor)
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        states = (await self.db.scalars(select(TrafficQualityState).where(TrafficQualityState.link_id == link_id, TrafficQualityState.active.is_(True)))).all()
        generations = {str(state.rule_id): state.generation for state in states}
        await self.db.execute(insert(TrafficQualityAcknowledgement).values(link_id=link_id, user_id=actor.id, until=until, generations=generations).on_conflict_do_update(
            index_elements=[TrafficQualityAcknowledgement.link_id, TrafficQualityAcknowledgement.user_id],
            set_={"until": until, "generations": generations, "updated_at": datetime.now(timezone.utc)},
        ))
        self.audit(link.project_id, actor.id, "traffic_quality_ack", link.id, None, {"until": until.isoformat()})
        await self.db.flush()
        return {"muted_until": until.isoformat()}
