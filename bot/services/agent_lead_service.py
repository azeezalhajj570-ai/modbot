"""Agent lead CRM service for managing captured leads with full lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AgentLead


class AgentLeadService:

    VALID_STATUSES = ("new", "contacted", "interested", "converted", "junk", "dismissed")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def capture_lead(
        self,
        *,
        agent_id: int,
        group_id: int,
        tg_user_id: int | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        source_group_tg_id: int | None = None,
        source_group_title: str | None = None,
        source_message_id: int | None = None,
        message_text: str | None = None,
        lead_label: str | None = None,
        contact_info: str | None = None,
        confidence: float = 0.5,
    ) -> AgentLead:
        existing = (
            await self.session.execute(
                select(AgentLead).where(
                    AgentLead.agent_id == agent_id,
                    AgentLead.tg_user_id == tg_user_id,
                    AgentLead.source_group_tg_id == source_group_tg_id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            if message_text:
                existing.message_text = message_text
            if source_message_id is not None:
                existing.source_message_id = source_message_id
            if username:
                existing.username = username
            if first_name:
                existing.first_name = first_name
            if last_name:
                existing.last_name = last_name
            if source_group_title:
                existing.source_group_title = source_group_title
            if lead_label:
                existing.lead_label = lead_label
            await self.session.commit()
            return existing

        lead = AgentLead(
            agent_id=agent_id,
            group_id=group_id,
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            source_group_tg_id=source_group_tg_id,
            source_group_title=source_group_title,
            source_message_id=source_message_id,
            message_text=message_text,
            lead_label=lead_label,
            contact_info=contact_info,
            confidence=confidence,
        )
        self.session.add(lead)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            dup = (
                await self.session.execute(
                    select(AgentLead).where(
                        AgentLead.agent_id == agent_id,
                        AgentLead.tg_user_id == tg_user_id,
                        AgentLead.source_group_tg_id == source_group_tg_id,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                if message_text:
                    dup.message_text = message_text
                await self.session.commit()
                return dup
            raise
        return lead

    async def list_leads(
        self,
        *,
        agent_id: int | None = None,
        group_id: int | None = None,
        status: str | None = None,
        assigned_to: int | None = None,
        lead_label: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        stmt = select(AgentLead)
        count_stmt = select(func.count(AgentLead.id))

        if agent_id is not None:
            stmt = stmt.where(AgentLead.agent_id == agent_id)
            count_stmt = count_stmt.where(AgentLead.agent_id == agent_id)
        if group_id is not None:
            stmt = stmt.where(AgentLead.group_id == group_id)
            count_stmt = count_stmt.where(AgentLead.group_id == group_id)
        if status is not None:
            stmt = stmt.where(AgentLead.status == status)
            count_stmt = count_stmt.where(AgentLead.status == status)
        if assigned_to is not None:
            stmt = stmt.where(AgentLead.assigned_to == assigned_to)
            count_stmt = count_stmt.where(AgentLead.assigned_to == assigned_to)
        if lead_label is not None:
            stmt = stmt.where(AgentLead.lead_label == lead_label)
            count_stmt = count_stmt.where(AgentLead.lead_label == lead_label)

        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(AgentLead.created_at)).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).scalars().all()

        return {
            "items": [self._serialize(lead) for lead in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    async def get_lead(self, *, lead_id: int) -> AgentLead:
        lead = (await self.session.execute(select(AgentLead).where(AgentLead.id == lead_id))).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
        return lead

    async def update_lead(
        self,
        *,
        lead_id: int,
        status: str | None = None,
        assigned_to: int | None = None,
        contact_info: str | None = None,
        notes: str | None = None,
        lead_label: str | None = None,
        confidence: float | None = None,
    ) -> AgentLead:
        lead = await self.get_lead(lead_id=lead_id)

        if status is not None:
            if status not in self.VALID_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid status: {status}. Valid: {', '.join(self.VALID_STATUSES)}",
                )
            lead.status = status
            if status == "contacted":
                lead.last_contacted_at = datetime.now(timezone.utc)
            elif status == "converted":
                lead.converted_at = datetime.now(timezone.utc)
        if assigned_to is not None:
            lead.assigned_to = assigned_to
        if contact_info is not None:
            lead.contact_info = contact_info
        if notes is not None:
            lead.notes = notes
        if lead_label is not None:
            lead.lead_label = lead_label
        if confidence is not None:
            lead.confidence = confidence

        await self.session.commit()
        return lead

    async def delete_lead(self, *, lead_id: int) -> bool:
        lead = await self.get_lead(lead_id=lead_id)
        await self.session.delete(lead)
        await self.session.commit()
        return True

    async def lead_stats(
        self,
        *,
        agent_id: int | None = None,
        group_id: int | None = None,
    ) -> dict[str, Any]:
        base = select(AgentLead)
        if agent_id is not None:
            base = base.where(AgentLead.agent_id == agent_id)
        if group_id is not None:
            base = base.where(AgentLead.group_id == group_id)

        total = (await self.session.execute(select(func.count(AgentLead.id)).where(base.whereclause))).scalar_one()

        status_counts: dict[str, int] = {}
        for s in self.VALID_STATUSES:
            count = (await self.session.execute(
                select(func.count(AgentLead.id)).where(base.whereclause, AgentLead.status == s)
            )).scalar_one()
            status_counts[s] = count

        return {
            "total": total,
            "by_status": status_counts,
        }

    @staticmethod
    def _serialize(lead: AgentLead) -> dict[str, Any]:
        return {
            "id": lead.id,
            "agent_id": lead.agent_id,
            "group_id": lead.group_id,
            "tg_user_id": lead.tg_user_id,
            "username": lead.username,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "source_group_tg_id": lead.source_group_tg_id,
            "source_group_title": lead.source_group_title,
            "source_message_id": lead.source_message_id,
            "message_text": lead.message_text,
            "lead_label": lead.lead_label,
            "status": lead.status,
            "assigned_to": lead.assigned_to,
            "contact_info": lead.contact_info,
            "notes": lead.notes,
            "confidence": lead.confidence,
            "last_contacted_at": lead.last_contacted_at.isoformat() if lead.last_contacted_at else None,
            "converted_at": lead.converted_at.isoformat() if lead.converted_at else None,
            "captured_at": lead.captured_at.isoformat() if lead.captured_at else None,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }
