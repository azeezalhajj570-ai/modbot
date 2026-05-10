from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.exceptions import AgentSessionError
from bot.agents.session import SessionManager
from bot.db.models import Agent, ScrapedConversation, ScrapedGroup, ScrapedMember, ScrapedMessage
from bot.db.models.scraper import ScrapedLead
from bot.services.group_service import canonical_tg_group_id
from bot.services.scrapers import bulk_upsert, entity_resolver, serializers
from bot.services.scrapers.conversation_builder import build_conversations_from_scrape

logger = structlog.get_logger(__name__)


class ScraperService:
    _MEMBER_BATCH_SIZE = 500
    _MESSAGE_BATCH_SIZE = 500

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._dialect_name = None

    async def get_dialect_name(self) -> str:
        if self._dialect_name is None:
            bind = getattr(self.session, "bind", None)
            if bind is None:
                sync_session = getattr(self.session, "_session", None)
                bind = getattr(sync_session, "bind", None)
            self._dialect_name = bind.dialect.name if bind is not None else "postgresql"
        return self._dialect_name

    async def sync_agent_groups(self, *, agent_id: int, client: Any | None = None) -> list[Any]:
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return []

        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return []

        try:
            results = []
            async for dialog in managed_client.iter_dialogs():
                if not dialog.is_group and not dialog.is_channel:
                    continue

                entity = dialog.entity
                title = getattr(entity, "title", None)
                username = getattr(entity, "username", None)
                group_type = "channel" if getattr(entity, "broadcast", False) else "supergroup" if getattr(entity, "megagroup", False) else "group"
                member_count = getattr(entity, "participants_count", None) or getattr(entity, "user_count", None)

                raw_data = {
                    "id": getattr(entity, "id", None),
                    "access_hash": getattr(entity, "access_hash", None),
                }

                group = await entity_resolver.get_or_create_scraped_group(
                    tg_group_id=int(dialog.id),
                    last_agent_id=agent_id,
                    title=str(title) if title else None,
                    username=str(username) if username else None,
                    group_type=group_type,
                    member_count=int(member_count) if member_count else None,
                    raw_data=raw_data,
                    commit=False,
                    session=self.session,
                )
                results.append(group)

            await self.session.commit()
            logger.info("agent_groups_synced", agent_id=agent_id, count=len(results))
            return results
        except Exception as exc:
            await self.session.rollback()
            logger.exception("sync_agent_groups_failed", agent_id=agent_id, error=str(exc))
            return []
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    async def scrape_group_info(self, *, agent_id: int, tg_group_id: int, client: Any | None = None) -> Any | None:
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return None

        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return None

        try:
            entity = await entity_resolver.resolve_group_entity(managed_client, int(tg_group_id), self.session)
            title = getattr(entity, "title", None)
            username = getattr(entity, "username", None)
            group_type = "channel" if getattr(entity, "broadcast", False) else "supergroup" if getattr(entity, "megagroup", False) else "group"
            member_count = getattr(entity, "participants_count", None) or getattr(entity, "user_count", None)
            description = getattr(entity, "about", None) if hasattr(entity, "about") else None

            raw_data = {
                "id": getattr(entity, "id", None),
                "access_hash": getattr(entity, "access_hash", None),
            }

            return await entity_resolver.get_or_create_scraped_group(
                tg_group_id=int(tg_group_id),
                last_agent_id=agent_id,
                title=str(title) if title else None,
                username=str(username) if username else None,
                group_type=group_type,
                member_count=int(member_count) if member_count else None,
                description=str(description) if description else None,
                raw_data=raw_data,
                session=self.session,
            )
        except Exception as exc:
            logger.exception("scrape_group_info_failed", agent_id=agent_id, tg_group_id=tg_group_id, error=str(exc))
            return None
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    async def _scrape_group_info_dict(self, *, agent_id: int, tg_group_id: int, client: Any | None = None) -> dict | None:
        group = await self.scrape_group_info(agent_id=agent_id, tg_group_id=tg_group_id, client=client)
        if group is None:
            return None
        return {
            "id": group.id,
            "title": group.title,
            "username": group.username,
            "group_type": group.group_type,
            "member_count": group.member_count,
        }

    async def scrape_members(
        self,
        *,
        agent_id: int,
        tg_group_id: int,
        limit: int = 1000,
        offset: int = 0,
        client: Any | None = None,
    ) -> dict[str, Any]:
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return {"success_count": 0, "error_count": 0, "total_scraped": 0}

        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return {"success_count": 0, "error_count": 0, "total_scraped": 0}

        try:
            scraped_group = await entity_resolver.get_or_create_group_from_client(
                client=managed_client, agent_id=agent_id, tg_group_id=tg_group_id, session=self.session,
            )
            entity = await entity_resolver.resolve_group_entity(managed_client, int(tg_group_id), self.session)
            success_count = 0
            error_count = 0
            total_scraped = 0
            member_batch: list[dict[str, Any]] = []
            canonical_group_id = canonical_tg_group_id(int(tg_group_id))

            seen = 0
            async for participant in managed_client.iter_participants(entity=entity, limit=limit + max(0, offset)):
                if seen < max(0, offset):
                    seen += 1
                    continue
                seen += 1
                total_scraped += 1
                try:
                    user_id = getattr(participant, "id", None)
                    if user_id is None:
                        continue

                    row = serializers.build_member_row_from_participant(
                        participant, scraped_group.id, canonical_group_id, int(user_id)
                    )
                    member_batch.append(row)

                    if len(member_batch) >= self._MEMBER_BATCH_SIZE:
                        await bulk_upsert.bulk_upsert_scraped_members(member_batch, self.session)
                        member_batch = []
                    success_count += 1
                except Exception as exc:
                    error_count += 1
                    logger.warning("scrape_member_failed", agent_id=agent_id, tg_group_id=tg_group_id, error=str(exc))

            if member_batch:
                await bulk_upsert.bulk_upsert_scraped_members(member_batch, self.session)

            if success_count > (scraped_group.member_count or 0):
                scraped_group.member_count = success_count
            scraped_group.updated_at = datetime.utcnow()
            await self.session.commit()
            return {"success_count": success_count, "error_count": error_count, "total_scraped": total_scraped}
        except Exception as exc:
            await self.session.rollback()
            logger.exception("scrape_members_failed", agent_id=agent_id, tg_group_id=tg_group_id, error=str(exc))
            return {"success_count": 0, "error_count": 0, "total_scraped": 0}
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    def _build_member_row_from_participant(self, participant: Any, scraped_group_id: int, canonical_group_id: int, user_id: int) -> dict[str, Any]:
        return serializers.build_member_row_from_participant(participant, scraped_group_id, canonical_group_id, user_id)

    async def scrape_messages(
        self,
        *,
        agent_id: int,
        tg_group_id: int,
        limit: int = 100,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        max_age_days: int | None = None,
        client: Any | None = None,
    ) -> dict[str, Any]:
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return {"success_count": 0, "error_count": 0, "total_scraped": 0}

        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return {"success_count": 0, "error_count": 0, "total_scraped": 0}

        try:
            scraped_group = await entity_resolver.get_or_create_group_from_client(
                client=managed_client, agent_id=agent_id, tg_group_id=tg_group_id, session=self.session,
            )
            entity = await entity_resolver.resolve_group_entity(managed_client, int(tg_group_id), self.session)
            success_count = 0
            error_count = 0
            total_scraped = 0
            member_processed_count = 0
            message_batch: list[dict[str, Any]] = []
            member_batch: list[dict[str, Any]] = []
            canonical_group_id = canonical_tg_group_id(int(tg_group_id))
            min_message_date = (
                datetime.utcnow() - timedelta(days=max(1, int(max_age_days)))
                if max_age_days is not None
                else None
            )

            async for message in managed_client.iter_messages(entity=entity, limit=limit, offset_id=offset_id, min_id=min_id, max_id=max_id):
                message_date = getattr(message, "date", None)
                if isinstance(message_date, datetime) and min_message_date is not None and message_date.replace(tzinfo=None) < min_message_date:
                    break
                total_scraped += 1
                try:
                    message_id = getattr(message, "id", None)
                    if message_id is None:
                        continue

                    sender_user_id, sender_username, sender_first_name, sender_last_name, sender_raw_data = (
                        await entity_resolver.extract_message_sender_data(message)
                    )

                    msg_row = serializers.build_message_row_from_msg(
                        message, scraped_group.id, canonical_group_id, int(message_id),
                        sender_user_id, sender_username, sender_first_name, sender_last_name,
                    )
                    message_batch.append(msg_row)

                    if sender_user_id is not None and int(sender_user_id) > 0:
                        member_row = serializers.build_member_row_from_sender(
                            scraped_group.id, canonical_group_id, sender_user_id,
                            sender_username, sender_first_name, sender_last_name, sender_raw_data,
                        )
                        member_batch.append(member_row)
                        member_processed_count += 1

                    if len(message_batch) >= self._MESSAGE_BATCH_SIZE:
                        await bulk_upsert.bulk_upsert_scraped_messages(message_batch, self.session)
                        await build_conversations_from_scrape(
                            self.session,
                            scraped_group_id=scraped_group.id,
                            tg_group_id=tg_group_id,
                            message_rows=message_batch,
                        )
                        message_batch = []
                    if len(member_batch) >= self._MEMBER_BATCH_SIZE:
                        await bulk_upsert.bulk_upsert_scraped_members(member_batch, self.session)
                        member_batch = []
                    success_count += 1
                except Exception as exc:
                    error_count += 1
                    logger.warning("scrape_message_failed", agent_id=agent_id, tg_group_id=tg_group_id, message_id=getattr(message, "id", "unknown"), error=str(exc))

            if message_batch:
                await bulk_upsert.bulk_upsert_scraped_messages(message_batch, self.session)
                await build_conversations_from_scrape(
                    self.session,
                    scraped_group_id=scraped_group.id,
                    tg_group_id=tg_group_id,
                    message_rows=message_batch,
                )
            if member_batch:
                await bulk_upsert.bulk_upsert_scraped_members(member_batch, self.session)

            await self.session.commit()
            return {
                "success_count": success_count,
                "error_count": error_count,
                "total_scraped": total_scraped,
                "member_success_count": member_processed_count,
            }
        except Exception as exc:
            await self.session.rollback()
            logger.exception("scrape_messages_failed", agent_id=agent_id, tg_group_id=tg_group_id, error=str(exc))
            return {"success_count": 0, "error_count": 0, "total_scraped": 0, "member_success_count": 0}
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    def _build_message_row_from_msg(self, message, scraped_group_id, canonical_group_id, message_id, sender_user_id, sender_username, sender_first_name, sender_last_name):
        return serializers.build_message_row_from_msg(
            message, scraped_group_id, canonical_group_id, message_id,
            sender_user_id, sender_username, sender_first_name, sender_last_name,
        )

    def _build_member_row_from_sender(self, scraped_group_id, canonical_group_id, sender_user_id, sender_username, sender_first_name, sender_last_name, sender_raw_data):
        return serializers.build_member_row_from_sender(
            scraped_group_id, canonical_group_id, sender_user_id,
            sender_username, sender_first_name, sender_last_name, sender_raw_data,
        )

    async def scrape_messages_checkpointed(
        self,
        *,
        agent_id: int,
        tg_group_id: int,
        limit: int = 100,
        max_age_days: int | None = None,
        checkpoint_batch_size: int = 200,
        client: Any | None = None,
    ) -> dict[str, Any]:
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return {"success_count": 0, "error_count": 0, "total_scraped": 0, "batches": 0, "completed": False}

        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return {"success_count": 0, "error_count": 0, "total_scraped": 0, "batches": 0, "completed": False}

        try:
            scraped_group = await entity_resolver.get_or_create_group_from_client(
                client=managed_client, agent_id=agent_id, tg_group_id=tg_group_id, session=self.session,
            )
            entity = await entity_resolver.resolve_group_entity(managed_client, int(tg_group_id), self.session)

            checkpoint = (scraped_group.scrape_state or {}).get("messages", {})
            last_offset_id = checkpoint.get("last_scraped_message_id", 0)
            total_success = checkpoint.get("total_success", 0)
            total_errors = checkpoint.get("total_errors", 0)
            batches_completed = checkpoint.get("batches_completed", 0)

            success_count = 0
            error_count = 0
            batch_count = 0
            reached_end = False

            while limit <= 0 or (success_count < limit):
                batch_success = 0
                batch_errors = 0
                batch_scraped = 0
                message_batch: list[dict[str, Any]] = []
                member_batch: list[dict[str, Any]] = []
                canonical_group_id = canonical_tg_group_id(int(tg_group_id))
                min_date = (
                    datetime.utcnow() - timedelta(days=max(1, int(max_age_days)))
                    if max_age_days is not None
                    else None
                )
                lowest_id = None

                iterator_args = {"entity": entity, "limit": checkpoint_batch_size}
                if last_offset_id > 0:
                    iterator_args["offset_id"] = last_offset_id

                async for message in managed_client.iter_messages(**iterator_args):
                    msg_date = getattr(message, "date", None)
                    if isinstance(msg_date, datetime) and min_date is not None and msg_date.replace(tzinfo=None) < min_date:
                        reached_end = True
                        break
                    batch_scraped += 1
                    msg_id = getattr(message, "id", None)
                    if msg_id is not None:
                        lowest_id = min(lowest_id or msg_id, msg_id) if lowest_id is not None else msg_id
                    try:
                        if msg_id is None:
                            continue

                        sender_data = await entity_resolver.extract_message_sender_data(message)
                        sender_user_id, sender_username, sender_first_name, sender_last_name, sender_raw_data = sender_data

                        msg_row = serializers.build_message_row_from_msg(
                            message, scraped_group.id, canonical_group_id, int(msg_id),
                            sender_user_id, sender_username, sender_first_name, sender_last_name,
                        )
                        message_batch.append(msg_row)

                        if sender_user_id is not None and int(sender_user_id) > 0:
                            member_row = serializers.build_member_row_from_sender(
                                scraped_group.id, canonical_group_id, sender_user_id,
                                sender_username, sender_first_name, sender_last_name, sender_raw_data,
                            )
                            member_batch.append(member_row)

                        batch_success += 1
                    except Exception as exc:
                        batch_errors += 1
                        logger.warning("checkpoint_message_failed", agent_id=agent_id, tg_group_id=tg_group_id, message_id=msg_id, error=str(exc))

                if not batch_scraped:
                    reached_end = True
                    break

                if message_batch:
                    await bulk_upsert.bulk_upsert_scraped_messages(message_batch, self.session)
                    await build_conversations_from_scrape(
                        self.session,
                        scraped_group_id=scraped_group.id,
                        tg_group_id=tg_group_id,
                        message_rows=message_batch,
                    )
                if member_batch:
                    await bulk_upsert.bulk_upsert_scraped_members(member_batch, self.session)

                success_count += batch_success
                error_count += batch_errors
                batch_count += 1

                if lowest_id is not None:
                    last_offset_id = lowest_id

                checkpoint_state: dict[str, Any] = scraped_group.scrape_state or {}
                checkpoint_state["messages"] = {
                    "last_scraped_message_id": last_offset_id,
                    "total_success": total_success + success_count,
                    "total_errors": total_errors + error_count,
                    "batches_completed": batches_completed + batch_count,
                    "last_batch_at": datetime.utcnow().isoformat(),
                }
                scraped_group.scrape_state = checkpoint_state

                scraped_group.updated_at = datetime.utcnow()
                await self.session.commit()

                if reached_end:
                    break

            return {
                "success_count": success_count,
                "error_count": error_count,
                "total_scraped": success_count + error_count,
                "batches": batch_count,
                "completed": reached_end,
                "last_offset_id": last_offset_id,
            }
        except Exception as exc:
            await self.session.rollback()
            logger.exception("checkpoint_scrape_failed", agent_id=agent_id, tg_group_id=tg_group_id, error=str(exc))
            return {"success_count": 0, "error_count": 0, "total_scraped": 0, "batches": 0, "completed": False}
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    async def scrape_messages_two_period(
        self,
        *,
        agent_id: int,
        tg_group_id: int,
        recent_days: int = 30,
        archive_days: int = 365,
        client: Any | None = None,
    ) -> dict[str, Any]:
        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return {"recent": {"success_count": 0}, "archive": {"success_count": 0}}

        try:
            recent_result = await self.scrape_messages_checkpointed(
                agent_id=agent_id,
                tg_group_id=tg_group_id,
                limit=500,
                max_age_days=recent_days,
                checkpoint_batch_size=200,
                client=managed_client,
            )

            archive_result = {"success_count": 0, "error_count": 0}
            if archive_days > recent_days:
                archive_result = await self.scrape_messages_checkpointed(
                    agent_id=agent_id,
                    tg_group_id=tg_group_id,
                    limit=0,
                    max_age_days=archive_days,
                    checkpoint_batch_size=500,
                    client=managed_client,
                )

            return {
                "recent": recent_result,
                "archive": archive_result,
            }
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    async def scrape_full_group(
        self,
        *,
        agent_id: int,
        tg_group_id: int,
        scrape_members: bool = True,
        scrape_messages: bool = True,
        member_limit: int = 1000,
        message_limit: int = 100,
        max_age_days: int | None = None,
        scan_strategy: str = "auto",
        client: Any | None = None,
    ) -> dict[str, Any]:
        managed_client = client
        should_disconnect = False
        if managed_client is None:
            try:
                managed_client = await SessionManager().get_client(agent_id)
                should_disconnect = True
            except AgentSessionError:
                logger.warning("scraper_session_failed", agent_id=agent_id)
                return {
                    "group_info": None,
                    "members": {"success_count": 0, "error_count": 0, "total_scraped": 0},
                    "messages": {"success_count": 0, "error_count": 0, "total_scraped": 0},
                }

        try:
            group_info = await self._scrape_group_info_dict(agent_id=agent_id, tg_group_id=tg_group_id, client=managed_client)
            results = {
                "group_info": group_info,
                "members": {"success_count": 0, "error_count": 0, "total_scraped": 0},
                "messages": {"success_count": 0, "error_count": 0, "total_scraped": 0, "member_success_count": 0},
            }
            if scrape_members:
                results["members"] = await self.scrape_members(agent_id=agent_id, tg_group_id=tg_group_id, limit=member_limit, client=managed_client)
            if scrape_messages:
                if scan_strategy == "checkpoint":
                    results["messages"] = await self.scrape_messages_checkpointed(
                        agent_id=agent_id,
                        tg_group_id=tg_group_id,
                        limit=message_limit,
                        max_age_days=max_age_days,
                        client=managed_client,
                    )
                elif scan_strategy == "two_period":
                    results["messages"] = await self.scrape_messages_two_period(
                        agent_id=agent_id,
                        tg_group_id=tg_group_id,
                        recent_days=30,
                        archive_days=max_age_days or 365,
                        client=managed_client,
                    )
                else:
                    results["messages"] = await self.scrape_messages(
                        agent_id=agent_id,
                        tg_group_id=tg_group_id,
                        limit=message_limit,
                        max_age_days=max_age_days,
                        client=managed_client,
                    )
            return results
        finally:
            if should_disconnect:
                with suppress(Exception):
                    await managed_client.disconnect()

    async def _get_active_agent(self, agent_id: int) -> Agent | None:
        return await entity_resolver.get_active_agent(agent_id, self.session)

    async def _get_or_create_group_from_client(self, *, client, agent_id: int, tg_group_id: int) -> Any:
        return await entity_resolver.get_or_create_group_from_client(
            client=client, agent_id=agent_id, tg_group_id=tg_group_id, session=self.session,
        )

    async def _resolve_group_entity(self, client: Any, tg_group_id: int) -> Any:
        return await entity_resolver.resolve_group_entity(client, tg_group_id, self.session)

    async def _get_or_create_scraped_group(self, *, tg_group_id: int, last_agent_id: int | None = None, title: str | None = None, username: str | None = None, group_type: str = "group", member_count: int | None = None, description: str | None = None, raw_data: dict | None = None, commit: bool = True) -> Any:
        return await entity_resolver.get_or_create_scraped_group(
            tg_group_id=tg_group_id,
            last_agent_id=last_agent_id,
            title=title,
            username=username,
            group_type=group_type,
            member_count=member_count,
            description=description,
            raw_data=raw_data,
            commit=commit,
            session=self.session,
        )

    @staticmethod
    def _build_scraped_member_row(
        *,
        scraped_group_id: int,
        tg_group_id: int,
        tg_user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        full_name: str | None = None,
        phone: str | None = None,
        is_bot: bool = False,
        is_premium: bool = False,
        role: str | None = None,
        joined_date: datetime | None = None,
        raw_data: dict | None = None,
    ) -> dict[str, Any]:
        return serializers.build_scraped_member_row(
            scraped_group_id=scraped_group_id,
            tg_group_id=tg_group_id,
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            phone=phone,
            is_bot=is_bot,
            is_premium=is_premium,
            role=role,
            joined_date=joined_date,
            raw_data=raw_data,
        )

    @staticmethod
    def _build_scraped_message_row(
        *,
        scraped_group_id: int,
        tg_group_id: int,
        message_id: int,
        sender_user_id: int | None = None,
        sender_username: str | None = None,
        sender_first_name: str | None = None,
        sender_last_name: str | None = None,
        message_text: str | None = None,
        message_date: datetime | None = None,
        message_type: str = "text",
        media_file_id: str | None = None,
        media_url: str | None = None,
        reply_to_message_id: int | None = None,
        reply_to_top_id: int | None = None,
        forward_from_user_id: int | None = None,
        raw_data: dict | None = None,
    ) -> dict[str, Any]:
        return serializers.build_scraped_message_row(
            scraped_group_id=scraped_group_id,
            tg_group_id=tg_group_id,
            message_id=message_id,
            sender_user_id=sender_user_id,
            sender_username=sender_username,
            sender_first_name=sender_first_name,
            sender_last_name=sender_last_name,
            message_text=message_text,
            message_date=message_date,
            message_type=message_type,
            media_file_id=media_file_id,
            media_url=media_url,
            reply_to_message_id=reply_to_message_id,
            reply_to_top_id=reply_to_top_id,
            forward_from_user_id=forward_from_user_id,
            raw_data=raw_data,
        )

    async def _bulk_upsert_scraped_members(self, rows: list[dict[str, Any]]) -> None:
        await bulk_upsert.bulk_upsert_scraped_members(rows, self.session)

    async def _bulk_upsert_scraped_messages(self, rows: list[dict[str, Any]]) -> None:
        await bulk_upsert.bulk_upsert_scraped_messages(rows, self.session)

    async def _build_upsert_statement(self, *, model, rows: list[dict[str, Any]], index_elements: list[str], update_columns: list[str]):
        return await bulk_upsert.build_upsert_statement(
            model=model,
            rows=rows,
            index_elements=index_elements,
            update_columns=update_columns,
            session=self.session,
        )

    @staticmethod
    def _serialize_participant_data(participant: Any) -> dict:
        return serializers.serialize_participant_data(participant)

    @staticmethod
    def _serialize_message_data(message: Any) -> dict:
        return serializers.serialize_message_data(message)

    @staticmethod
    def _extract_peer_id(peer: Any) -> int | None:
        return entity_resolver.extract_peer_id(peer)

    async def _extract_message_sender_data(self, message: Any) -> tuple[int | None, str | None, str | None, str | None, dict[str, Any]]:
        return await entity_resolver.extract_message_sender_data(message)

    def _is_missing_scraper_table_error(self, exc: Exception) -> bool:
        return entity_resolver.is_missing_scraper_table_error(exc)

    async def search_messages(
        self,
        *,
        tg_group_id: int,
        query: str,
        sender_user_id: int | None = None,
        message_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))
        stmt = select(ScrapedMessage).where(
            ScrapedMessage.tg_group_id == canonical_group_id,
        )
        if query:
            stmt = stmt.where(ScrapedMessage.message_text.ilike(f"%{query}%"))
        if sender_user_id is not None:
            stmt = stmt.where(ScrapedMessage.sender_user_id == sender_user_id)
        if message_type:
            stmt = stmt.where(ScrapedMessage.message_type == message_type)
        if date_from:
            stmt = stmt.where(ScrapedMessage.message_date >= date_from)
        if date_to:
            stmt = stmt.where(ScrapedMessage.message_date <= date_to)

        count_stmt = select(func.count(ScrapedMessage.id)).where(
            ScrapedMessage.tg_group_id == canonical_group_id,
        )
        if query:
            count_stmt = count_stmt.where(ScrapedMessage.message_text.ilike(f"%{query}%"))
        if sender_user_id is not None:
            count_stmt = count_stmt.where(ScrapedMessage.sender_user_id == sender_user_id)
        if message_type:
            count_stmt = count_stmt.where(ScrapedMessage.message_type == message_type)
        if date_from:
            count_stmt = count_stmt.where(ScrapedMessage.message_date >= date_from)
        if date_to:
            count_stmt = count_stmt.where(ScrapedMessage.message_date <= date_to)

        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)

        stmt = stmt.order_by(desc(ScrapedMessage.message_date))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "messages": [{
                "id": m.id,
                "message_id": m.message_id,
                "sender_user_id": m.sender_user_id,
                "sender_username": m.sender_username,
                "sender_first_name": m.sender_first_name,
                "sender_last_name": m.sender_last_name,
                "message_text": m.message_text,
                "message_date": m.message_date.isoformat() if m.message_date else None,
                "message_type": m.message_type,
                "reply_to_message_id": m.reply_to_message_id,
            } for m in rows],
        }

    async def export_group_data(
        self,
        *,
        tg_group_id: int,
        format: str = "json",
        data_type: str = "messages",
        limit: int = 10000,
    ) -> str:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))

        if data_type == "members":
            stmt = select(ScrapedMember).where(
                ScrapedMember.tg_group_id == canonical_group_id,
            ).limit(limit)
            rows = (await self.session.execute(stmt)).scalars().all()
            records = [{
                "tg_user_id": m.tg_user_id,
                "username": m.username,
                "first_name": m.first_name,
                "last_name": m.last_name,
                "full_name": m.full_name,
                "phone": m.phone,
                "is_bot": m.is_bot,
                "is_premium": m.is_premium,
                "role": m.role,
                "joined_date": m.joined_date.isoformat() if m.joined_date else None,
            } for m in rows]
        elif data_type == "conversations":
            stmt = select(ScrapedConversation).where(
                ScrapedConversation.tg_group_id == canonical_group_id,
            ).order_by(desc(ScrapedConversation.last_message_at)).limit(limit)
            rows = (await self.session.execute(stmt)).scalars().all()
            records = [{
                "id": c.id,
                "title": c.title,
                "root_sender_name": c.root_sender_name,
                "participant_count": c.participant_count,
                "message_count": c.message_count,
                "first_message_at": c.first_message_at.isoformat() if c.first_message_at else None,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                "is_topic": c.is_topic,
            } for c in rows]
        else:
            stmt = select(ScrapedMessage).where(
                ScrapedMessage.tg_group_id == canonical_group_id,
            ).order_by(desc(ScrapedMessage.message_date)).limit(limit)
            rows = (await self.session.execute(stmt)).scalars().all()
            records = [{
                "message_id": m.message_id,
                "sender_username": m.sender_username,
                "sender_first_name": m.sender_first_name,
                "message_text": m.message_text,
                "message_date": m.message_date.isoformat() if m.message_date else None,
                "message_type": m.message_type,
                "reply_to_message_id": m.reply_to_message_id,
            } for m in rows]

        if format == "csv":
            import csv
            import io
            output = io.StringIO()
            if records:
                writer = csv.DictWriter(output, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
            return output.getvalue()
        else:
            import json
            return json.dumps(records, ensure_ascii=False, indent=2)

    async def get_member_leaderboard(
        self,
        *,
        tg_group_id: int,
        limit: int = 50,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))
        since = datetime.utcnow() - timedelta(days=max(1, int(days)))

        rows = (await self.session.execute(
            select(
                ScrapedMessage.sender_user_id,
                func.count(ScrapedMessage.id).label("message_count"),
                func.max(ScrapedMessage.message_date).label("last_active"),
            )
            .where(
                ScrapedMessage.tg_group_id == canonical_group_id,
                ScrapedMessage.sender_user_id.is_not(None),
                ScrapedMessage.message_date >= since,
            )
            .group_by(ScrapedMessage.sender_user_id)
            .order_by(desc("message_count"))
            .limit(limit)
        )).all()

        user_ids = [int(row[0]) for row in rows if row[0] is not None]

        member_info: dict[int, dict[str, Any]] = {}
        if user_ids:
            member_rows = (await self.session.execute(
                select(ScrapedMember).where(
                    ScrapedMember.tg_group_id == canonical_group_id,
                    ScrapedMember.tg_user_id.in_(user_ids),
                )
            )).scalars().all()
            for m in member_rows:
                member_info[int(m.tg_user_id)] = {
                    "username": m.username,
                    "first_name": m.first_name,
                    "last_name": m.last_name,
                    "full_name": m.full_name,
                    "is_bot": m.is_bot,
                    "role": m.role,
                }

        leaderboard = []
        for row in rows:
            if row[0] is None:
                continue
            uid = int(row[0])
            info = member_info.get(uid, {})
            leaderboard.append({
                "user_id": uid,
                "username": info.get("username"),
                "first_name": info.get("first_name"),
                "last_name": info.get("last_name"),
                "full_name": info.get("full_name"),
                "is_bot": info.get("is_bot", False),
                "role": info.get("role"),
                "message_count": int(row[1] or 0),
                "last_active": row[2].isoformat() if row[2] else None,
                "score": min(100, int(row[1] or 0)),
            })

        total_messages = sum(item["message_count"] for item in leaderboard)
        for item in leaderboard:
            item["share_pct"] = round(item["message_count"] / max(1, total_messages) * 100, 1)

        return leaderboard

    async def extract_leads(
        self,
        *,
        tg_group_id: int,
        limit: int = 500,
    ) -> dict[str, Any]:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))

        patterns = [
            ("buying_intent", [r"buy\b|purchase\b|how much|price|cost|offer|discount", r"interested|want|looking for|need"]),
            ("contact_request", [r"contact me|DM me|PM me|whatsapp|email|call me|phone number"]),
            ("support_need", [r"help|not working|broken|issue|error|bug|can't|won't"]),
            ("hiring", [r"hiring|looking for.*developer|looking for.*designer|job|freelance|recruit"]),
            ("partnership", [r"partnership|collab|sponsor|partner|work together|affiliate"]),
        ]

        import re
        messages = (await self.session.execute(
            select(ScrapedMessage).where(
                ScrapedMessage.tg_group_id == canonical_group_id,
                ScrapedMessage.message_text.is_not(None),
                ScrapedMessage.sender_user_id.is_not(None),
            ).order_by(desc(ScrapedMessage.message_date)).limit(limit)
        )).scalars().all()

        leads_found = 0
        for m in messages:
            text = (m.message_text or "").lower()
            for signal, regexes in patterns:
                matched = all(re.search(r, text) for r in regexes)
                if not matched:
                    continue

                existing = (await self.session.execute(
                    select(ScrapedLead).where(
                        ScrapedLead.source_message_id == m.message_id,
                        ScrapedLead.scraped_group_id == m.scraped_group_id,
                    )
                )).scalar_one_or_none()
                if existing:
                    continue

                contact_match = re.search(r"(@\w+|[\w\.-]+@[\w\.-]+|\+?\d{7,15})", (m.message_text or ""))
                lead = ScrapedLead(
                    scraped_group_id=m.scraped_group_id,
                    source_message_id=m.message_id,
                    sender_user_id=m.sender_user_id,
                    sender_name=(m.sender_first_name or m.sender_username or f"User {m.sender_user_id}"),
                    signal=signal,
                    excerpt=(m.message_text or "")[:500],
                    contact_info=contact_match.group(1) if contact_match else None,
                    confidence=0.7,
                )
                self.session.add(lead)
                leads_found += 1

        if leads_found:
            await self.session.commit()

        total = (await self.session.execute(
            select(func.count(ScrapedLead.id)).where(
                ScrapedLead.scraped_group_id.in_(
                    select(ScrapedGroup.id).where(ScrapedGroup.tg_group_id == canonical_group_id)
                )
            )
        )).scalar_one()

        return {"leads_found": leads_found, "total_leads": int(total or 0)}

    async def list_leads(
        self,
        *,
        tg_group_id: int,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))
        scraped_group = (await self.session.execute(
            select(ScrapedGroup).where(ScrapedGroup.tg_group_id == canonical_group_id)
        )).scalar_one_or_none()

        if scraped_group is None:
            return {"total": 0, "page": page, "page_size": page_size, "leads": []}

        stmt = select(ScrapedLead).where(ScrapedLead.scraped_group_id == scraped_group.id)
        if status:
            stmt = stmt.where(ScrapedLead.status == status)
        stmt = stmt.order_by(desc(ScrapedLead.detected_at)).offset((page - 1) * page_size).limit(page_size)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(
            select(func.count(ScrapedLead.id)).where(ScrapedLead.scraped_group_id == scraped_group.id)
        )).scalar_one()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "leads": [{
                "id": l.id,
                "source_message_id": l.source_message_id,
                "sender_user_id": l.sender_user_id,
                "sender_name": l.sender_name,
                "signal": l.signal,
                "excerpt": l.excerpt,
                "contact_info": l.contact_info,
                "status": l.status,
                "confidence": l.confidence,
                "detected_at": l.detected_at.isoformat() if l.detected_at else None,
            } for l in rows],
        }

    async def get_nudge_suggestions(
        self,
        *,
        tg_group_id: int,
    ) -> dict[str, Any]:
        canonical_group_id = canonical_tg_group_id(int(tg_group_id))
        now = datetime.utcnow()

        latest_msg = (await self.session.execute(
            select(ScrapedMessage.message_date).where(
                ScrapedMessage.tg_group_id == canonical_group_id,
            ).order_by(desc(ScrapedMessage.message_date)).limit(1)
        )).scalar_one_or_none()

        last_message_days = None
        if latest_msg:
            delta = now - latest_msg.replace(tzinfo=None)
            last_message_days = delta.days

        last_24h = now - timedelta(days=1)
        msgs_24h = (await self.session.execute(
            select(func.count(ScrapedMessage.id)).where(
                ScrapedMessage.tg_group_id == canonical_group_id,
                ScrapedMessage.message_date >= last_24h,
            )
        )).scalar_one() or 0

        last_7d = now - timedelta(days=7)
        msgs_7d = (await self.session.execute(
            select(func.count(ScrapedMessage.id)).where(
                ScrapedMessage.tg_group_id == canonical_group_id,
                ScrapedMessage.message_date >= last_7d,
            )
        )).scalar_one() or 0

        suggestions = []

        if last_message_days is not None and last_message_days >= 3:
            suggestions.append({
                "type": "inactivity_warning",
                "severity": "high" if last_message_days >= 7 else "medium",
                "message": f"Group has been inactive for {last_message_days} days. Consider sending a poll or discussion prompt.",
                "action": "send_poll",
            })

        if msgs_24h == 0 and msgs_7d > 0:
            suggestions.append({
                "type": "quiet_today",
                "severity": "low",
                "message": "No messages in the last 24 hours. Group may need re-engagement.",
                "action": "engagement_prompt",
            })

        if last_message_days is None:
            suggestions.append({
                "type": "no_data",
                "severity": "info",
                "message": "No scraped messages found. Trigger a scrape to get activity insights.",
                "action": "scrape_now",
            })

        peak_hours = await self._get_peak_activity_hours(canonical_group_id)
        if peak_hours:
            suggestions.append({
                "type": "peak_activity",
                "severity": "info",
                "message": f"Peak activity: {', '.join(f'{h}:00 ({c} msgs)' for h, c in peak_hours[:3])}",
                "action": "none",
            })

        return {
            "last_message_days": last_message_days,
            "messages_24h": msgs_24h,
            "messages_7d": msgs_7d,
            "peak_hours": peak_hours,
            "suggestions": suggestions,
        }

    async def _get_peak_activity_hours(self, canonical_group_id: int) -> list[tuple[int, int]]:
        from sqlalchemy import extract, literal_column
        rows = (await self.session.execute(
            select(
                extract("hour", ScrapedMessage.message_date).label("hour"),
                func.count(ScrapedMessage.id).label("cnt"),
            )
            .where(
                ScrapedMessage.tg_group_id == canonical_group_id,
                ScrapedMessage.message_date >= datetime.utcnow() - timedelta(days=30),
            )
            .group_by("hour")
            .order_by(desc("cnt"))
            .limit(5)
        )).all()
        return [(int(row[0]), int(row[1])) for row in rows]

    async def get_scraped_member_activity(
        self,
        *,
        tg_group_id: int,
        user_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        deduped_user_ids = list(dict.fromkeys(int(user_id) for user_id in user_ids if int(user_id) > 0))
        if not deduped_user_ids:
            return {}

        canonical_group_id = canonical_tg_group_id(int(tg_group_id))
        try:
            count_rows = (
                await self.session.execute(
                    select(ScrapedMessage.sender_user_id, func.count(ScrapedMessage.id))
                    .where(
                        ScrapedMessage.tg_group_id == canonical_group_id,
                        ScrapedMessage.sender_user_id.is_not(None),
                        ScrapedMessage.sender_user_id.in_(deduped_user_ids),
                    )
                    .group_by(ScrapedMessage.sender_user_id)
                )
            ).all()
            preview_rows = (
                await self.session.execute(
                    select(
                        ScrapedMessage.sender_user_id,
                        ScrapedMessage.message_id,
                        ScrapedMessage.message_text,
                        ScrapedMessage.message_date,
                        ScrapedMessage.message_type,
                    )
                    .where(
                        ScrapedMessage.tg_group_id == canonical_group_id,
                        ScrapedMessage.sender_user_id.is_not(None),
                        ScrapedMessage.sender_user_id.in_(deduped_user_ids),
                    )
                    .order_by(desc(ScrapedMessage.message_date), desc(ScrapedMessage.id))
                    .limit(300)
                )
            ).all()
        except ProgrammingError as exc:
            if not self._is_missing_scraper_table_error(exc):
                raise
            return {}

        scraped_data: dict[int, dict[str, Any]] = {
            int(row[0]): {
                "scraped_message_count": int(row[1] or 0),
                "scraped_messages_preview": [],
            }
            for row in count_rows
            if row[0] is not None
        }
        for row in preview_rows:
            if row.sender_user_id is None:
                continue
            sender_user_id = int(row.sender_user_id)
            entry = scraped_data.setdefault(
                sender_user_id,
                {
                    "scraped_message_count": 0,
                    "scraped_messages_preview": [],
                },
            )
            preview = entry["scraped_messages_preview"]
            if len(preview) >= 3:
                continue
            preview.append(
                {
                    "message_id": int(row.message_id),
                    "message_text": str(row.message_text or "").strip() or None,
                    "message_type": str(row.message_type or "text"),
                    "message_date": row.message_date.isoformat() if row.message_date is not None else None,
                }
            )
        return scraped_data
