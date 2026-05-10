from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.account_group_membership_service import AccountGroupMembershipService
from bot.agents.exceptions import AgentBannedError, AgentFloodWaitError, AgentSessionError


class AdminGroupMemberSearchRateLimitedError(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Linked account is rate limited. Retry after {retry_after}s.")


class AdminGroupMemberSearchUnavailableError(RuntimeError):
    pass


class AdminGroupMemberSearchConflictError(RuntimeError):
    pass


class AdminGroupMemberService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memberships = AccountGroupMembershipService(session)

    async def search_group_members(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        try:
            return await self.memberships.search_group_members(
                actor_user_id=actor_user_id,
                group_id=group_id,
                query=query,
                limit=limit,
            )
        except AgentFloodWaitError as exc:
            raise AdminGroupMemberSearchRateLimitedError(exc.retry_after) from exc
        except AgentBannedError as exc:
            raise AdminGroupMemberSearchConflictError("Linked account is banned.") from exc
        except AgentSessionError as exc:
            raise AdminGroupMemberSearchUnavailableError(str(exc)) from exc
