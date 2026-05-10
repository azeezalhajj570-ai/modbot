from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import String, and_, cast, desc, func, inspect, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.contracts import AccountGroupVisibility
from bot.agents.session import SessionManager
from bot.db.models import Agent, Group, GroupAdminRole, ScrapedGroup, ScrapedMember, ScrapedMessage, User
from bot.services.group_service import canonical_tg_group_id
from bot.services.scraper_service import ScraperService

from .agent_notification_service import AgentNotificationService
from .service_support import AgentServiceSupport

logger = structlog.get_logger(__name__)


def _is_missing_scraper_table_error(exc: Exception) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "undefinedtableerror" in message or 'relation "scraped_' in message


class AccountGroupMembershipService(AgentServiceSupport):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._scraper_tables_available: bool | None = None

    async def _has_scraper_tables(self) -> bool:
        if self._scraper_tables_available is not None:
            return self._scraper_tables_available
        connection = await self.session.connection()

        def check_tables(sync_connection) -> bool:
            inspector = inspect(sync_connection)
            return bool(inspector.has_table("scraped_groups") and inspector.has_table("scraped_members"))

        if hasattr(connection, "run_sync"):
            self._scraper_tables_available = await connection.run_sync(check_tables)
        else:
            self._scraper_tables_available = check_tables(connection)
        return self._scraper_tables_available

    async def list_managed_member_groups(self, *, actor_user_id: int, agent_id: int, query: str | None = None) -> list[dict[str, Any]]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return []
        await self.ensure_agent_owner(agent, actor_user_id)
        if agent.auth_state != "active" or not agent.session_string:
            return []

        if not await self._has_scraper_tables():
            return []

        try:
            normalized_query = str(query or "").strip()
            word_conditions = []

            # Multi-word "AND" search
            query_words = [w.strip() for w in normalized_query.split() if len(w.strip()) >= 1]
            for word in query_words:
                # Ignore very short special chars if there are better words
                if word in {"-", "_", ".", ","} and len(query_words) > 1:
                    continue

                pattern = f"%{word}%"
                word_conditions.append(
                    or_(
                        ScrapedGroup.title.ilike(pattern),
                        ScrapedGroup.username.ilike(pattern),
                        cast(ScrapedGroup.tg_group_id, String).like(pattern),
                    )
                )

            if normalized_query and not word_conditions:
                return []

            filters = [ScrapedGroup.last_agent_id == agent_id]
            filters.extend(word_conditions)
            stmt = (
                select(ScrapedGroup)
                .where(and_(*filters))
                .order_by(ScrapedGroup.title, ScrapedGroup.id)
                .limit(100 if normalized_query else 500)
            )

            scraped_rows = (await self.session.execute(stmt)).scalars().all()
            if not scraped_rows:
                return []

            member_counts = {
                int(row.scraped_group_id): int(row.member_count)
                for row in (
                    await self.session.execute(
                        select(
                            ScrapedMember.scraped_group_id,
                            func.count(ScrapedMember.id).label("member_count"),
                        )
                        .where(ScrapedMember.scraped_group_id.in_([int(r.id) for r in scraped_rows]))
                        .group_by(ScrapedMember.scraped_group_id)
                    )
                ).all()
            }
            message_counts = {
                int(row.scraped_group_id): int(row.message_count)
                for row in (
                    await self.session.execute(
                        select(
                            ScrapedMessage.scraped_group_id,
                            func.count(ScrapedMessage.id).label("message_count"),
                        )
                        .where(ScrapedMessage.scraped_group_id.in_([int(r.id) for r in scraped_rows]))
                        .group_by(ScrapedMessage.scraped_group_id)
                    )
                ).all()
            }

            results = []
            for row in scraped_rows:
                results.append({
                    "id": row.id,
                    "tg_group_id": int(row.tg_group_id),
                    "title": row.title or str(row.tg_group_id),
                    "username": row.username,
                    "group_type": row.group_type,
                    "member_count": member_counts.get(int(row.id), int(row.member_count or 0)),
                    "messages_count": message_counts.get(int(row.id), 0),
                })
            return results

        except ProgrammingError as exc:
            if not _is_missing_scraper_table_error(exc):
                raise
            return []

    async def list_account_group_visibility(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
    ) -> list[AccountGroupVisibility]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return []
        groups = await self.list_managed_member_groups(actor_user_id=actor_user_id, agent_id=agent_id)
        return [
            AccountGroupVisibility(
                agent_id=agent.id,
                group_id=agent.group_id,
                tg_group_id=int(group["tg_group_id"]),
                title=str(group["title"]),
            )
            for group in groups
        ]

    async def search_agent_member_group_members(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        if agent.auth_state != "active" or not agent.session_string:
            raise ValueError("Link an active agent first to browse group members")

        normalized_query = str(query or "").strip()
        normalized_limit = max(1, min(int(limit), 50))
        client = await SessionManager().get_client(agent.id)
        try:
            members: list[dict[str, Any]] = []
            async for participant in client.iter_participants(entity=int(tg_group_id), search=normalized_query, limit=normalized_limit):
                user_id = getattr(participant, "id", None)
                if user_id is None or bool(getattr(participant, "bot", False)) or bool(getattr(participant, "deleted", False)):
                    continue
                first_name = str(getattr(participant, "first_name", None) or "").strip()
                last_name = str(getattr(participant, "last_name", None) or "").strip()
                full_name = " ".join(part for part in [first_name, last_name] if part).strip() or None
                members.append({"user_id": int(user_id), "username": getattr(participant, "username", None), "full_name": full_name})
        finally:
            await client.disconnect()

        await self._sync_users(members)
        for member in members:
            member["role"] = "member"
        logger.info("agent_member_lookup_completed", actor_user_id=actor_user_id, group_id=agent.group_id, tg_group_id=int(tg_group_id), agent_id=agent.id, query=normalized_query, count=len(members))
        return members

    async def search_group_members(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        await self.ensure_group_admin(group_id, actor_user_id)
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            raise ValueError("Group not found")

        agent = (
            await self.session.execute(
                select(Agent)
                .where(Agent.group_id == group_id, Agent.auth_state == "active", Agent.session_string.is_not(None))
                .order_by(desc(Agent.updated_at), desc(Agent.id))
            )
        ).scalar_one_or_none()
        if agent is None:
            raise ValueError("Link an active agent first to browse group members")

        normalized_query = str(query or "").strip()
        normalized_limit = max(1, min(int(limit), 50))
        client = await SessionManager().get_client(agent.id)
        try:
            members: list[dict[str, Any]] = []
            async for participant in client.iter_participants(entity=group.tg_group_id, search=normalized_query, limit=normalized_limit):
                user_id = getattr(participant, "id", None)
                if user_id is None or bool(getattr(participant, "bot", False)) or bool(getattr(participant, "deleted", False)):
                    continue
                first_name = str(getattr(participant, "first_name", None) or "").strip()
                last_name = str(getattr(participant, "last_name", None) or "").strip()
                full_name = " ".join(part for part in [first_name, last_name] if part).strip() or None
                members.append({"user_id": int(user_id), "username": getattr(participant, "username", None), "full_name": full_name})
        finally:
            await client.disconnect()

        user_ids = [int(member["user_id"]) for member in members]
        role_map: dict[int, str] = {}
        if user_ids:
            role_rows = (
                await self.session.execute(
                    select(GroupAdminRole.user_id, GroupAdminRole.role).where(GroupAdminRole.group_id == group_id, GroupAdminRole.user_id.in_(user_ids))
                )
            ).all()
            role_map = {int(row.user_id): str(row.role) for row in role_rows}

        await self._sync_users(members)
        for member in members:
            member["role"] = role_map.get(int(member["user_id"]), "member")
        logger.info("agent_member_lookup_completed", actor_user_id=actor_user_id, group_id=group_id, agent_id=agent.id, query=normalized_query, count=len(members))
        return members

    async def list_scraped_agent_group_members(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        query: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)

        canonical_id = canonical_tg_group_id(int(tg_group_id))
        normalized_query = str(query or "").strip()
        normalized_page = max(1, int(page))
        normalized_page_size = max(1, min(int(page_size), 50))

        if not await self._has_scraper_tables():
            return {
                "members": [],
                "total": 0,
                "page": normalized_page,
                "page_size": normalized_page_size,
            }

        scraped_group = await self._get_scraped_group(canonical_id)
        if scraped_group is None:
            await self._ensure_agent_group_visible(agent=agent, tg_group_id=tg_group_id)
        filters = [
            (ScrapedMember.scraped_group_id == scraped_group.id)
            if scraped_group is not None
            else (ScrapedMember.tg_group_id == canonical_id)
        ]
        if normalized_query:
            pattern = f"%{normalized_query.lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(ScrapedMember.username, "")).like(pattern),
                    func.lower(func.coalesce(ScrapedMember.full_name, "")).like(pattern),
                    func.lower(func.coalesce(ScrapedMember.first_name, "")).like(pattern),
                    func.lower(func.coalesce(ScrapedMember.last_name, "")).like(pattern),
                    cast(ScrapedMember.tg_user_id, String).like(f"%{normalized_query}%"),
                )
            )

        try:
            total = (
                int(scraped_group.member_count or 0)
                if scraped_group is not None and not normalized_query and scraped_group.member_count is not None
                else int((await self.session.execute(select(func.count(ScrapedMember.id)).where(*filters))).scalar_one() or 0)
            )
            rows = (
                await self.session.execute(
                    select(
                        ScrapedMember.tg_user_id,
                        ScrapedMember.username,
                        ScrapedMember.full_name,
                        ScrapedMember.role,
                    )
                    .where(*filters)
                    .order_by(desc(ScrapedMember.scraped_at), desc(ScrapedMember.id))
                    .offset((normalized_page - 1) * normalized_page_size)
                    .limit(normalized_page_size)
                )
            ).all()
        except ProgrammingError as exc:
            if not _is_missing_scraper_table_error(exc):
                raise
            logger.warning(
                "scraper_tables_missing_for_scraped_agent_group_members",
                agent_id=agent.id,
                tg_group_id=canonical_id,
            )
            total = 0
            rows = []

        user_ids = [int(member.tg_user_id) for member in rows if member.tg_user_id is not None]
        message_counts: dict[int, int] = {}
        if user_ids:
            message_counts = {
                int(row.sender_user_id): int(row.message_count)
                for row in (
                    await self.session.execute(
                        select(
                            ScrapedMessage.sender_user_id,
                            func.count(ScrapedMessage.id).label("message_count"),
                        )
                        .where(
                            ScrapedMessage.tg_group_id == canonical_id,
                            ScrapedMessage.sender_user_id.in_(user_ids),
                        )
                        .group_by(ScrapedMessage.sender_user_id)
                    )
                ).all()
                if row.sender_user_id is not None
            }

        return {
            "members": [
                {
                    "user_id": int(member.tg_user_id),
                    "username": member.username,
                    "full_name": member.full_name,
                    "role": member.role or "member",
                    "message_count": message_counts.get(int(member.tg_user_id), 0),
                }
                for member in rows
            ],
            "total": total,
            "page": normalized_page,
            "page_size": normalized_page_size,
        }

    async def list_scraped_agent_group_member_messages(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)

        canonical_id = canonical_tg_group_id(int(tg_group_id))
        normalized_page = max(1, int(page))
        normalized_page_size = max(1, min(int(page_size), 100))

        if not await self._has_scraper_tables():
            return {
                "messages": [],
                "total": 0,
                "page": normalized_page,
                "page_size": normalized_page_size,
            }

        scraped_group = await self._get_scraped_group(canonical_id)
        if scraped_group is None:
            await self._ensure_agent_group_visible(agent=agent, tg_group_id=tg_group_id)

        filters = [
            (ScrapedMessage.scraped_group_id == scraped_group.id)
            if scraped_group is not None
            else (ScrapedMessage.tg_group_id == canonical_id),
            ScrapedMessage.sender_user_id == int(user_id),
        ]

        try:
            total = int((await self.session.execute(select(func.count(ScrapedMessage.id)).where(*filters))).scalar_one() or 0)
            rows = (
                await self.session.execute(
                    select(
                        ScrapedMessage.message_id,
                        ScrapedMessage.message_text,
                        ScrapedMessage.message_date,
                        ScrapedMessage.message_type,
                        ScrapedMessage.sender_username,
                        ScrapedMessage.sender_first_name,
                        ScrapedMessage.sender_last_name,
                    )
                    .where(*filters)
                    .order_by(desc(ScrapedMessage.message_date), desc(ScrapedMessage.id))
                    .offset((normalized_page - 1) * normalized_page_size)
                    .limit(normalized_page_size)
                )
            ).all()
        except ProgrammingError as exc:
            if not _is_missing_scraper_table_error(exc):
                raise
            logger.warning(
                "scraper_tables_missing_for_scraped_agent_group_member_messages",
                agent_id=agent.id,
                tg_group_id=canonical_id,
                user_id=int(user_id),
            )
            total = 0
            rows = []

        return {
            "messages": [
                {
                    "message_id": int(row.message_id),
                    "text": row.message_text,
                    "date": row.message_date.isoformat() if row.message_date else None,
                    "message_type": row.message_type,
                    "username": row.sender_username,
                    "full_name": " ".join(
                        part for part in [str(row.sender_first_name or "").strip(), str(row.sender_last_name or "").strip()] if part
                    ).strip() or None,
                }
                for row in rows
            ],
            "total": total,
            "page": normalized_page,
            "page_size": normalized_page_size,
        }

    async def scrape_agent_member_group(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        limit: int = 500,
        message_limit: int | None = None,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        await self._ensure_agent_group_visible(agent=agent, tg_group_id=tg_group_id)
        if agent.auth_state != "active" or not agent.session_string:
            raise ValueError("Link an active agent first to scrape group members")
        results = await ScraperService(self.session).scrape_full_group(
            agent_id=agent.id,
            tg_group_id=tg_group_id,
            scrape_members=True,
            scrape_messages=True,
            member_limit=limit,
            message_limit=max(1, min(int(message_limit or limit), 50000)),
            max_age_days=max_age_days,
        )
        response = {
            **results["members"],
            "messages_count": int(results["messages"].get("success_count") or 0),
            "messages_total_scraped": int(results["messages"].get("total_scraped") or 0),
            "members_from_messages": int(results["messages"].get("member_success_count") or 0),
        }
        visible_groups = await self._list_agent_member_groups(agent)
        group_title = next(
            (str(group.get("title") or "") for group in visible_groups if int(group.get("tg_group_id") or 0) == canonical_tg_group_id(int(tg_group_id))),
            str(tg_group_id),
        )
        
        # Combine unique counts if possible, but for notification, simple sum is better than just "2"
        total_members_synced = int(response["success_count"]) + int(response["members_from_messages"])
        
        await AgentNotificationService(self.session).create_notification(
            actor_user_id=actor_user_id,
            agent=agent,
            kind="scrape_completed",
            title="Scrape finished",
            body=(
                f"{group_title}: {total_members_synced} members synced, "
                f"{int(response['messages_count'])} messages scraped."
            ),
            payload={
                "tg_group_id": canonical_tg_group_id(int(tg_group_id)),
                "group_title": group_title,
                "success_count": total_members_synced,
                "messages_count": int(response["messages_count"]),
                "total_scraped": int(response["total_scraped"]),
                "messages_total_scraped": int(response["messages_total_scraped"]),
                "members_direct": int(response["success_count"]),
                "members_from_messages": int(response["members_from_messages"]),
            },
        )
        return response

    async def _list_agent_member_groups(self, agent: Agent) -> list[dict[str, Any]]:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.utils import get_peer_id

        from bot.config import get_settings

        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return []

        client = TelegramClient(StringSession(agent.session_string), settings.telegram_api_id, settings.telegram_api_hash)
        await client.connect()
        try:
            groups: list[dict[str, Any]] = []
            async for dialog in client.iter_dialogs():
                if not (dialog.is_group or getattr(dialog.entity, "megagroup", False)):
                    continue
                tg_group_id = canonical_tg_group_id(int(get_peer_id(dialog.entity)))
                title = str(getattr(dialog, "title", None) or getattr(dialog.entity, "title", None) or tg_group_id)
                groups.append({"tg_group_id": tg_group_id, "title": title})
            deduped: dict[int, dict[str, Any]] = {}
            for group in groups:
                deduped[int(group["tg_group_id"])] = group
            return list(deduped.values())
        finally:
            await client.disconnect()

    async def _ensure_agent_group_visible(self, *, agent: Agent, tg_group_id: int) -> None:
        visible_groups = await self._list_agent_member_groups(agent)
        normalized_tg_group_id = canonical_tg_group_id(int(tg_group_id))
        if not any(int(group["tg_group_id"]) == normalized_tg_group_id for group in visible_groups):
            raise ValueError("Group is not visible to this linked account")

    async def _get_scraped_group(self, tg_group_id: int) -> ScrapedGroup | None:
        return (
            await self.session.execute(
                select(ScrapedGroup).where(ScrapedGroup.tg_group_id == canonical_tg_group_id(int(tg_group_id)))
            )
        ).scalar_one_or_none()

    async def _sync_users(self, members: list[dict[str, Any]]) -> None:
        user_ids = [int(member["user_id"]) for member in members]
        if not user_ids:
            return
        existing_users = (await self.session.execute(select(User).where(User.tg_user_id.in_(user_ids)))).scalars().all()
        existing_by_tg_id = {int(user.tg_user_id): user for user in existing_users}
        for member in members:
            user_id = int(member["user_id"])
            existing_user = existing_by_tg_id.get(user_id)
            if existing_user is None:
                self.session.add(User(tg_user_id=user_id, username=member["username"], full_name=member["full_name"]))
            else:
                existing_user.username = member["username"]
                existing_user.full_name = member["full_name"]
        await self.session.commit()
