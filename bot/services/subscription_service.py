from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import SubscriptionRequest, SubscriptionStatus


def build_owner_notification(
    request_id: int,
    actor_label: str,
    actor_id: int,
    message_text: str | None,
    review_url: str | None,
) -> str:
    lines = [
        f"Subscription request #{request_id}",
        f"From: {actor_label} (TG {actor_id})",
        f"Message: {message_text or 'No message provided.'}",
    ]
    if review_url:
        lines.append(f"Review: {review_url}")
    return "\n".join(lines)


def build_requester_status_notification(
    *,
    status: SubscriptionStatus,
    response: str | None,
) -> str:
    if status is SubscriptionStatus.APPROVED:
        lines = ["Your subscription request was approved."]
    elif status is SubscriptionStatus.DECLINED:
        lines = ["Your subscription request was declined."]
    elif status is SubscriptionStatus.CANCELLED:
        lines = ["Your subscription was cancelled."]
    elif status is SubscriptionStatus.SUPERSEDED:
        lines = ["Your earlier subscription approval was replaced by a newer request."]
    else:
        lines = [f"Your subscription request status was updated to {status.value}."]
    if response:
        lines.append(f"Note: {response}")
    return "\n".join(lines)


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_active_subscription(self, *, tg_user_id: int, bot_kind: str | None = None) -> bool:
        sub = await self.get_active_subscription(tg_user_id=tg_user_id, bot_kind=bot_kind)
        return sub is not None

    async def get_active_subscription(self, *, tg_user_id: int, bot_kind: str | None = None) -> SubscriptionRequest | None:
        now = datetime.now(timezone.utc)
        stmt = (
            select(SubscriptionRequest)
            .where(
                SubscriptionRequest.tg_user_id == tg_user_id,
                SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
                or_(
                    SubscriptionRequest.expires_at.is_(None),
                    SubscriptionRequest.expires_at > now,
                ),
            )
            .order_by(desc(SubscriptionRequest.id))
            .limit(1)
        )
        if bot_kind:
            stmt = stmt.where(
                or_(
                    SubscriptionRequest.bot_kind == bot_kind,
                    SubscriptionRequest.bot_kind.is_(None),
                )
            )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def ensure_free_plan(self, *, tg_user_id: int, username: str | None, full_name: str | None, language_code: str | None, bot_kind: str | None = None) -> SubscriptionRequest:
        existing = await self.get_active_subscription(tg_user_id=tg_user_id, bot_kind=bot_kind)
        if existing is not None:
            return existing

        request = SubscriptionRequest(
            tg_user_id=tg_user_id,
            username=username,
            full_name=full_name,
            language_code=language_code,
            status=SubscriptionStatus.APPROVED.value,
            plan="free",
            bot_kind=bot_kind,
        )
        self.session.add(request)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def create_request(
        self,
        *,
        tg_user_id: int,
        username: str | None,
        full_name: str | None,
        language_code: str | None,
        message: str | None,
    ) -> SubscriptionRequest:
        request = SubscriptionRequest(
            tg_user_id=tg_user_id,
            username=username,
            full_name=full_name,
            language_code=language_code,
            message=message,
            status=SubscriptionStatus.PENDING.value,
        )
        self.session.add(request)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def list_requests(self) -> list[SubscriptionRequest]:
        rows = (
            await self.session.execute(
                select(SubscriptionRequest).order_by(desc(SubscriptionRequest.created_at))
            )
        ).scalars().all()
        return rows

    async def get_latest_request(self, *, tg_user_id: int) -> SubscriptionRequest | None:
        return (
            await self.session.execute(
                select(SubscriptionRequest)
                .where(SubscriptionRequest.tg_user_id == tg_user_id)
                .order_by(desc(SubscriptionRequest.created_at), desc(SubscriptionRequest.id))
                .limit(1)
            )
        ).scalar_one_or_none()

    async def get_request(self, request_id: int) -> SubscriptionRequest | None:
        return (
            await self.session.execute(
                select(SubscriptionRequest).where(SubscriptionRequest.id == request_id)
            )
        ).scalar_one_or_none()

    async def set_user_plan(
        self,
        *,
        tg_user_id: int,
        plan: str,
        username: str | None = None,
        full_name: str | None = None,
        language_code: str | None = None,
        expires_at: datetime | None = None,
        responder_id: int | None = None,
        message: str | None = None,
        bot_kind: str | None = None,
    ) -> SubscriptionRequest:
        existing = await self.get_active_subscription(tg_user_id=tg_user_id, bot_kind=bot_kind)
        if existing is not None and existing.plan == plan and existing.expires_at == expires_at:
            return existing

        supersede_note = "Superseded by a newer plan assignment."
        if existing is not None:
            existing.status = SubscriptionStatus.SUPERSEDED.value
            existing.response = existing.response or supersede_note
            existing.response_by = responder_id
            await self.session.flush()

        request = SubscriptionRequest(
            tg_user_id=tg_user_id,
            username=username,
            full_name=full_name,
            language_code=language_code,
            message=message or f"Plan set to {plan} by admin",
            status=SubscriptionStatus.APPROVED.value,
            plan=plan,
            expires_at=expires_at,
            response_by=responder_id,
            bot_kind=bot_kind,
        )
        self.session.add(request)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def list_active_subscriptions(self, bot_kind: str | None = None) -> list[SubscriptionRequest]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(SubscriptionRequest)
            .where(
                SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
                or_(
                    SubscriptionRequest.expires_at.is_(None),
                    SubscriptionRequest.expires_at > now,
                ),
            )
            .order_by(desc(SubscriptionRequest.id))
        )
        if bot_kind:
            stmt = stmt.where(SubscriptionRequest.bot_kind == bot_kind)
        return (await self.session.execute(stmt)).scalars().all()

    async def update_request_status(
        self,
        *,
        request_id: int,
        status: SubscriptionStatus,
        response: str | None,
        responder_id: int | None,
    ) -> SubscriptionRequest | None:
        request = await self.get_request(request_id)
        if request is None:
            return None
        if status is SubscriptionStatus.APPROVED:
            supersede_note = "Superseded by a newer approved request."
            supersede_stmt = select(SubscriptionRequest).where(
                SubscriptionRequest.tg_user_id == request.tg_user_id,
                SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
                SubscriptionRequest.id != request_id,
            )
            if request.bot_kind:
                supersede_stmt = supersede_stmt.where(
                    or_(
                        SubscriptionRequest.bot_kind == request.bot_kind,
                        SubscriptionRequest.bot_kind.is_(None),
                    )
                )
            other_approved = (
                await self.session.execute(supersede_stmt)
            ).scalars().all()
            for row in other_approved:
                row.status = SubscriptionStatus.SUPERSEDED.value
                row.response = row.response or supersede_note
                row.response_by = responder_id
            if other_approved:
                await self.session.flush()
        request.status = status.value
        request.response = response
        request.response_by = responder_id
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def cancel_subscription(self, *, tg_user_id: int, responder_id: int | None = None, bot_kind: str | None = None) -> bool:
        active = await self.get_active_subscription(tg_user_id=tg_user_id, bot_kind=bot_kind)
        if active is None:
            return False
        active.status = SubscriptionStatus.CANCELLED.value
        active.response = "Cancelled by admin"
        active.response_by = responder_id
        await self.session.commit()
        return True
