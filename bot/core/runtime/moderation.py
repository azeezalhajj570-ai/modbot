from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.core.runtime.actions import AddWarningAction, BanUserAction, ClearWarningsAction, DeleteMessageAction, MaybeMuteUserAction, RestrictUserAction, SendNoticeAction
from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, RuntimeAuditService, serialize_guard_result
from bot.core.runtime.events import RuntimeEvent, RuntimeEventType
from bot.core.runtime.executors import ActionExecutorRegistry
from bot.core.runtime.guards import GuardDecision, GuardPipeline, GuardResult
from bot.db.models import Group, Warning
from bot.services.moderation_enforcement_service import (
    add_warning,
    maybe_mute_user,
    maybe_mute_user_on_warning_limit,
    maybe_remove_user_on_warning_limit,
    moderation_incident_count,
)
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.moderation_notice_service import build_rule_notice
from bot.services.permission_service import PermissionService


@dataclass
class FlaggedMessageModerationRequest:
    group_id: int
    chat_id: int
    message_id: int
    target_user_id: int | None
    source: str
    reason: str | None
    score: float | None = None
    notice_key: str | None = None
    feature_key: str | None = None
    delete_log_action: str = "delete_message"
    mute_setting_key: str | None = None
    mute_threshold_key: str | None = None
    mute_log_action: str | None = None
    incident_actions: tuple[str, ...] = field(default_factory=tuple)
    target_is_admin: bool = False
    lang: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlaggedWarningModerationRequest:
    group_id: int
    chat_id: int
    target_user_id: int
    source: str
    reason: str | None
    score: float | None = None
    notice_key: str | None = None
    log_action: str = "warn"
    mute_setting_key: str | None = None
    mute_threshold_key: str | None = None
    mute_log_action: str | None = None
    lang: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModerationActionRequest:
    group_id: int
    actor_user_id: int | None
    user_id: int
    action: str
    reason: str | None
    count: int = 1
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)
    target_is_admin: bool = False


@dataclass
class GroupExistsGuard:
    session: AsyncSession

    async def evaluate(self, event: RuntimeEvent, action: Any) -> GuardResult:
        group = (
            await self.session.execute(select(Group.id).where(Group.id == event.group_id))
        ).scalar_one_or_none()
        if group is None:
            return GuardResult(decision=GuardDecision.DENY, reason="Group not found")
        return GuardResult(decision=GuardDecision.ALLOW)


@dataclass
class FeatureEnabledGuard:
    session: AsyncSession

    async def evaluate(self, event: RuntimeEvent, action: Any) -> GuardResult:
        feature_key = str(event.payload.get("feature_key") or "").strip()
        if not feature_key:
            return GuardResult(decision=GuardDecision.ALLOW)
        enabled = await ModerationSettingsStore(self.session).is_feature_enabled(
            event.group_id,
            feature_key,
            default=True,
        )
        if not enabled:
            return GuardResult(decision=GuardDecision.DENY, reason=f"{feature_key} disabled")
        return GuardResult(decision=GuardDecision.ALLOW)


@dataclass
class TargetNotGroupAdminGuard:
    async def evaluate(self, event: RuntimeEvent, action: Any) -> GuardResult:
        if bool(event.payload.get("target_is_admin")):
            return GuardResult(decision=GuardDecision.DENY, reason="Target is a group administrator")
        return GuardResult(decision=GuardDecision.ALLOW)


@dataclass
class ModerationRuntimeService:
    session: AsyncSession

    async def list_warnings(self, *, group_id: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Warning.user_id, Warning.reason, Warning.count, Warning.issued_by, Warning.created_at)
                .where(Warning.group_id == group_id)
                .order_by(desc(Warning.created_at))
            )
        ).all()
        return [
            {
                "user_id": row.user_id,
                "reason": row.reason,
                "count": row.count,
                "issued_by": row.issued_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def clear_warnings(self, *, group_id: int, actor_user_id: int, user_id: int) -> dict[str, Any]:
        result = await self._perform_user_action(
            ModerationActionRequest(
                group_id=group_id,
                actor_user_id=actor_user_id,
                user_id=user_id,
                action="clear",
                reason=None,
                source="webapp",
            ),
            audit_action="clear_warnings",
            event_type=RuntimeEventType.MODERATION_WARNING_REVIEW_REQUESTED,
        )
        return {"status": "ok", "deleted": int(result.get("deleted") or 0)}

    async def add_warning(
        self,
        *,
        group_id: int,
        actor_user_id: int,
        user_id: int,
        reason: str | None,
        count: int = 1,
    ) -> dict[str, Any]:
        result = await self._perform_user_action(
            ModerationActionRequest(
                group_id=group_id,
                actor_user_id=actor_user_id,
                user_id=user_id,
                action="warn",
                reason=reason,
                count=count,
                source="runtime",
            ),
            audit_action="warn",
            event_type=RuntimeEventType.MODERATION_USER_ACTION_REQUESTED,
        )
        return {"status": "ok", "count": int(result.get("count") or 0)}

    async def apply_action(
        self,
        *,
        group_id: int,
        actor_user_id: int,
        user_id: int,
        action: str,
        reason: str | None,
        count: int = 1,
    ) -> dict[str, Any]:
        return await self._perform_user_action(
            ModerationActionRequest(
                group_id=group_id,
                actor_user_id=actor_user_id,
                user_id=user_id,
                action=action,
                reason=reason,
                count=count,
                source="runtime",
            ),
            audit_action="approve_warning" if action == "approve" else None,
            event_type=(
                RuntimeEventType.MODERATION_WARNING_REVIEW_REQUESTED
                if action == "approve"
                else RuntimeEventType.MODERATION_USER_ACTION_REQUESTED
            ),
        )

    async def enforce_flagged_warning(
        self,
        request: FlaggedWarningModerationRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        group = await self._get_group_or_404(request.group_id)
        event = RuntimeEvent(
            name=RuntimeEventType.MODERATION_WARNING_TRIGGERED,
            group_id=request.group_id,
            actor_user_id=None,
            subject_type="user",
            subject_id=str(request.target_user_id),
            source=request.source,
            payload={
                "chat_id": request.chat_id,
                "target_user_id": request.target_user_id,
                "reason": request.reason,
                "score": request.score,
                "notice_key": request.notice_key,
                "log_action": request.log_action,
            },
        )
        registry = self._build_registry(bot=bot, group=group)
        warning_action = AddWarningAction(
            kind="add_warning",
            group_id=request.group_id,
            actor_user_id=None,
            target_user_id=request.target_user_id,
            reason=request.reason,
            count=1,
            metadata={
                **dict(request.metadata),
                "source": request.source,
                "score": request.score,
                "mute_setting_key": request.mute_setting_key,
                "mute_threshold_key": request.mute_threshold_key,
                "mute_log_action": request.mute_log_action,
            },
        )
        guard_result = await GuardPipeline(guards=[GroupExistsGuard(self.session)]).evaluate(event, warning_action)
        if guard_result.decision == GuardDecision.DENY:
            return {"status": "skipped", "reason": guard_result.reason}

        result = await registry.execute(warning_action)
        notice_text = None
        if request.notice_key:
            notice_key = "warn_limit_remove" if result.get("removed") else request.notice_key
            notice_text = build_rule_notice(
                request.lang,
                notice_key,
                count=int(result.get("count") or 1),
                limit=int(result.get("warning_limit") or result.get("removal_limit") or 3),
            )
            await registry.execute(
                SendNoticeAction(
                    kind="send_notice",
                    group_id=request.group_id,
                    chat_id=request.chat_id,
                    notice_text=notice_text,
                    metadata={"source": request.source},
                )
            )

        await self._write_audit(
            AuditEntry(
                action=request.log_action,
                action_type="add_warning",
                event_type=event.name,
                group_id=request.group_id,
                actor_user_id=None,
                target_user_id=request.target_user_id,
                reason=request.reason,
                subject_type="user",
                subject_id=str(request.target_user_id),
                source_runtime="moderation.runtime",
                correlation_id=event.correlation_id,
                details={
                    **dict(request.metadata),
                    "source": request.source,
                    "score": request.score,
                    "selected_actions": ["add_warning"] + (["send_notice"] if notice_text else []),
                    "guard_outcomes": [serialize_guard_result(guard_result)],
                    "execution_result": {**dict(result), "notice_sent": bool(notice_text)},
                    **result,
                },
            )
        )
        await self.session.commit()
        return {
            "status": "ok",
            "action": request.log_action,
            "count": int(result.get("count") or 0),
            "muted": bool(result.get("muted")),
            "removed": bool(result.get("removed")),
            "notice_sent": bool(notice_text),
        }

    async def _perform_user_action(
        self,
        request: ModerationActionRequest,
        *,
        audit_action: str | None,
        event_type: RuntimeEventType,
    ) -> dict[str, Any]:
        permissions = PermissionService(self.session)
        required_action = "group.moderation.warn" if request.action in {"approve", "clear", "warn"} else "group.moderation.ban"
        if request.actor_user_id is not None and not await permissions.can(request.group_id, request.actor_user_id, required_action):
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User does not have permission for this action")
        group = await self._get_group_or_404(request.group_id)
        event = RuntimeEvent(
            name=event_type,
            group_id=request.group_id,
            actor_user_id=request.actor_user_id,
            subject_type="user",
            subject_id=str(request.user_id),
            source=request.source,
            payload={"reason": request.reason, "action": request.action, "count": request.count, **dict(request.metadata)},
        )
        bot = Bot(token=get_settings().bot_token)
        try:
            registry = self._build_registry(bot=bot, group=group)
            action_obj, resolved_audit_action = self._build_user_action(request, audit_action=audit_action)
            guards = [GroupExistsGuard(self.session)]
            if request.target_is_admin and request.action in {"mute", "ban"}:
                guards.append(TargetNotGroupAdminGuard())
            guard_result = await GuardPipeline(guards=guards).evaluate(event, action_obj)
            if guard_result.decision == GuardDecision.DENY:
                return {"status": "skipped", "reason": guard_result.reason, "action": request.action}
            result = await registry.execute(action_obj)
        finally:
            await bot.session.close()

        await self._write_audit(
            AuditEntry(
                action=resolved_audit_action,
                action_type=action_obj.kind,
                event_type=event.name,
                group_id=request.group_id,
                actor_user_id=request.actor_user_id,
                target_user_id=request.user_id,
                reason=request.reason,
                subject_type="user",
                subject_id=str(request.user_id),
                source_runtime="moderation.runtime",
                correlation_id=event.correlation_id,
                details={
                    "source": request.source,
                    **dict(request.metadata),
                    "selected_actions": [action_obj.kind],
                    "guard_outcomes": [serialize_guard_result(guard_result)],
                    "execution_result": dict(result),
                    **result,
                },
            )
        )
        await self.session.commit()
        return {"status": "ok", "action": request.action, **result}

    async def enforce_flagged_message(
        self,
        request: FlaggedMessageModerationRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        event = RuntimeEvent(
            name=RuntimeEventType.MODERATION_MESSAGE_FLAGGED,
            group_id=request.group_id,
            actor_user_id=None,
            payload={
                "source": request.source,
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "target_user_id": request.target_user_id,
                "reason": request.reason,
                "score": request.score,
                "notice_key": request.notice_key,
                "feature_key": request.feature_key,
                "delete_log_action": request.delete_log_action,
                "mute_setting_key": request.mute_setting_key,
                "mute_threshold_key": request.mute_threshold_key,
                "mute_log_action": request.mute_log_action,
                "target_is_admin": request.target_is_admin,
            },
        )
        delete_action = DeleteMessageAction(
            kind="delete_message",
            group_id=request.group_id,
            chat_id=request.chat_id,
            message_id=request.message_id,
            target_user_id=request.target_user_id,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        guard_pipeline = GuardPipeline(
            guards=[
                GroupExistsGuard(self.session),
                FeatureEnabledGuard(self.session),
                TargetNotGroupAdminGuard(),
            ]
        )
        guard_result = await guard_pipeline.evaluate(event, delete_action)
        if guard_result.decision == GuardDecision.DENY:
            return {"status": "skipped", "reason": guard_result.reason}

        group = (await self.session.execute(select(Group).where(Group.id == request.group_id))).scalar_one()
        registry = self._build_registry(bot=bot, group=group)

        delete_result = await registry.execute(delete_action)
        if not delete_result.get("deleted"):
            return {"status": "failed", "action": request.delete_log_action}

        muted = False
        incident_actions = request.incident_actions or (request.delete_log_action,)
        incident_count = await moderation_incident_count(
            self.session,
            group_id=request.group_id,
            user_id=request.target_user_id or 0,
            actions=incident_actions,
        ) + 1
        if request.mute_setting_key and request.mute_threshold_key and request.mute_log_action:
            mute_action = MaybeMuteUserAction(
                kind="maybe_mute_user",
                group_id=request.group_id,
                chat_id=request.chat_id,
                target_user_id=request.target_user_id,
                reason=request.reason,
                metadata={
                    **dict(request.metadata),
                    "message_id": request.message_id,
                    "score": request.score,
                    "setting_key": request.mute_setting_key,
                    "threshold_key": request.mute_threshold_key,
                    "log_action": request.mute_log_action,
                    "current_count": incident_count,
                },
            )
            mute_result = await registry.execute(mute_action)
            muted = bool(mute_result.get("muted"))

        await self.session.commit()

        notice_sent = False
        if request.notice_key:
            notice_action = SendNoticeAction(
                kind="send_notice",
                group_id=request.group_id,
                chat_id=request.chat_id,
                notice_text=build_rule_notice(request.lang, request.notice_key),
                metadata={"source": request.source},
            )
            notice_result = await registry.execute(notice_action)
            notice_sent = bool(notice_result.get("sent"))

        await self._write_audit(
            AuditEntry(
                action=request.delete_log_action,
                action_type="delete_message",
                event_type=event.name,
                group_id=request.group_id,
                actor_user_id=None,
                target_user_id=request.target_user_id,
                reason=request.reason,
                subject_type="message",
                subject_id=str(request.message_id),
                source_runtime="moderation.runtime",
                correlation_id=event.correlation_id,
                details={
                    **dict(request.metadata),
                    "message_id": request.message_id,
                    "score": request.score,
                    "source": request.source,
                    "selected_actions": [
                        "delete_message",
                        *(
                            ["maybe_mute_user"]
                            if request.mute_setting_key and request.mute_threshold_key and request.mute_log_action
                            else []
                        ),
                        *(["send_notice"] if request.notice_key else []),
                    ],
                    "guard_outcomes": [serialize_guard_result(guard_result)],
                    "execution_result": {
                        **dict(delete_result),
                        "muted": muted,
                        "notice_sent": notice_sent,
                        "incident_count": incident_count,
                    },
                },
            )
        )

        return {
            "status": "ok",
            "action": request.delete_log_action,
            "deleted": True,
            "muted": muted,
            "notice_sent": notice_sent,
        }

    async def _execute_delete_message(self, action: DeleteMessageAction, *, bot: Bot) -> dict[str, Any]:
        try:
            await bot.delete_message(chat_id=action.chat_id, message_id=action.message_id)
        except Exception as exc:
            return {"deleted": False, "message_id": action.message_id, "error": str(exc)}
        return {"deleted": True, "message_id": action.message_id}

    async def _execute_send_notice(self, action: SendNoticeAction, *, bot: Bot) -> dict[str, Any]:
        try:
            await bot.send_message(chat_id=action.chat_id, text=action.notice_text)
        except Exception as exc:
            return {"sent": False, "error": str(exc)}
        return {"sent": True}

    async def _execute_maybe_mute(self, action: MaybeMuteUserAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        muted = await maybe_mute_user(
            self.session,
            group=group,
            bot=bot,
            user_id=action.target_user_id,
            admin_user_id=None,
            setting_key=str(action.metadata.get("setting_key") or ""),
            threshold_key=str(action.metadata.get("threshold_key") or ""),
            log_action=str(action.metadata.get("log_action") or "mute_user"),
            reason=action.reason,
            current_count=int(action.metadata.get("current_count") or 0),
            details={
                "message_id": action.metadata.get("message_id"),
                "score": action.metadata.get("score"),
                "source": action.metadata.get("source"),
            },
        )
        return {"muted": muted}

    async def _execute_add_warning(self, action: AddWarningAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        warning = await add_warning(
            self.session,
            group_id=action.group_id,
            user_id=action.target_user_id,
            issued_by=action.actor_user_id,
            reason=action.reason,
            count=max(action.count, 1),
        )
        muted = False
        mute_setting_key = str(action.metadata.get("mute_setting_key") or "")
        mute_threshold_key = str(action.metadata.get("mute_threshold_key") or "")
        mute_log_action = str(action.metadata.get("mute_log_action") or "")
        if mute_setting_key and mute_threshold_key and mute_log_action:
            muted = await maybe_mute_user(
                self.session,
                group=group,
                bot=bot,
                user_id=action.target_user_id,
                admin_user_id=action.actor_user_id,
                setting_key=mute_setting_key,
                threshold_key=mute_threshold_key,
                log_action=mute_log_action,
                reason=action.reason,
                current_count=warning.count,
                details={
                    "source": action.metadata.get("source"),
                    "score": action.metadata.get("score"),
                    "message_id": action.metadata.get("message_id"),
                    "count": warning.count,
                },
            )
        removal_limit = await maybe_remove_user_on_warning_limit(
            self.session,
            group=group,
            bot=bot,
            user_id=action.target_user_id,
            admin_user_id=action.actor_user_id,
            warning=warning,
            reason=action.reason,
            details={
                "source": action.metadata.get("source"),
                "score": action.metadata.get("score"),
                "message_id": action.metadata.get("message_id"),
            },
        )
        mute_limit = await maybe_mute_user_on_warning_limit(
            self.session,
            group=group,
            bot=bot,
            user_id=action.target_user_id,
            admin_user_id=action.actor_user_id,
            warning=warning,
            reason=action.reason,
            details={
                "source": action.metadata.get("source"),
                "score": action.metadata.get("score"),
                "message_id": action.metadata.get("message_id"),
            },
        )
        warning_limit = (await ModerationSettingsStore(self.session).get_settings(action.group_id)).warn_limit
        return {
            "count": int(warning.count),
            "muted": muted or (mute_limit is not None),
            "removed": removal_limit is not None,
            "removal_limit": removal_limit,
            "mute_limit": mute_limit,
            "warning_limit": warning_limit,
        }

    async def _execute_clear_warnings(self, action: ClearWarningsAction) -> dict[str, Any]:
        rows = (
            await self.session.execute(select(Warning).where(Warning.group_id == action.group_id, Warning.user_id == action.target_user_id))
        ).scalars().all()
        for row in rows:
            await self.session.delete(row)
        return {"deleted": len(rows)}

    async def _execute_restrict_user(self, action: RestrictUserAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        await bot.restrict_chat_member(
            group.tg_group_id,
            action.target_user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        return {"restricted": True}

    async def _execute_ban_user(self, action: BanUserAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        await bot.ban_chat_member(group.tg_group_id, action.target_user_id)
        return {"banned": True}

    async def _execute_unrestrict_user(self, action: RestrictUserAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        await bot.restrict_chat_member(
            group.tg_group_id,
            action.target_user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            ),
        )
        return {"unrestricted": True}

    async def _execute_unban_user(self, action: BanUserAction, *, bot: Bot, group: Group) -> dict[str, Any]:
        await bot.unban_chat_member(group.tg_group_id, action.target_user_id)
        return {"unbanned": True}

    async def _write_audit(self, entry: AuditEntry) -> None:
        await RuntimeAuditService(ModerationLogAuditSink(self.session)).record(entry)

    async def _get_group_or_404(self, group_id: int) -> Group:
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        return group

    def _build_registry(self, *, bot: Bot, group: Group) -> ActionExecutorRegistry:
        registry = ActionExecutorRegistry()
        registry.register("delete_message", lambda action: self._execute_delete_message(action, bot=bot))
        registry.register("send_notice", lambda action: self._execute_send_notice(action, bot=bot))
        registry.register("maybe_mute_user", lambda action: self._execute_maybe_mute(action, bot=bot, group=group))
        registry.register("add_warning", lambda action: self._execute_add_warning(action, bot=bot, group=group))
        registry.register("clear_warnings", self._execute_clear_warnings)
        registry.register("restrict_user", lambda action: self._execute_restrict_user(action, bot=bot, group=group))
        registry.register("unrestrict_user", lambda action: self._execute_unrestrict_user(action, bot=bot, group=group))
        registry.register("ban_user", lambda action: self._execute_ban_user(action, bot=bot, group=group))
        registry.register("unban_user", lambda action: self._execute_unban_user(action, bot=bot, group=group))
        return registry

    def _build_user_action(
        self,
        request: ModerationActionRequest,
        *,
        audit_action: str | None,
    ) -> tuple[AddWarningAction | ClearWarningsAction | RestrictUserAction | BanUserAction, str]:
        if request.action == "approve":
            return (
                ClearWarningsAction(
                    kind="clear_warnings",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    metadata=dict(request.metadata),
                ),
                audit_action or "approve_warning",
            )
        if request.action == "clear":
            return (
                ClearWarningsAction(
                    kind="clear_warnings",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    metadata=dict(request.metadata),
                ),
                audit_action or "clear_warnings",
            )
        if request.action == "warn":
            return (
                AddWarningAction(
                    kind="add_warning",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    count=max(request.count, 1),
                    metadata=dict(request.metadata),
                ),
                audit_action or "warn",
            )
        if request.action == "mute":
            return (
                RestrictUserAction(
                    kind="restrict_user",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    metadata=dict(request.metadata),
                ),
                audit_action or "mute_user",
            )
        if request.action == "unmute":
            return (
                RestrictUserAction(
                    kind="unrestrict_user",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    metadata=dict(request.metadata),
                ),
                audit_action or "unmute_user",
            )
        if request.action == "unban":
            return (
                BanUserAction(
                    kind="unban_user",
                    group_id=request.group_id,
                    actor_user_id=request.actor_user_id,
                    target_user_id=request.user_id,
                    reason=request.reason,
                    metadata=dict(request.metadata),
                ),
                audit_action or "unban_user",
            )
        return (
            BanUserAction(
                kind="ban_user",
                group_id=request.group_id,
                actor_user_id=request.actor_user_id,
                target_user_id=request.user_id,
                reason=request.reason,
                metadata=dict(request.metadata),
            ),
            audit_action or "ban_user",
        )
