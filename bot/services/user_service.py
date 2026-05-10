from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import User


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tg_id(self, tg_user_id: int) -> User | None:
        return (
            await self.session.execute(select(User).where(User.tg_user_id == tg_user_id))
        ).scalar_one_or_none()

    async def get_language(self, tg_user_id: int) -> str | None:
        user = await self.get_by_tg_id(tg_user_id)
        return user.language_code if user else None

    async def set_language(
        self,
        tg_user_id: int,
        language_code: str,
        username: str | None = None,
        full_name: str | None = None,
    ) -> None:
        values = {
            "tg_user_id": tg_user_id,
            "username": username,
            "full_name": full_name,
            "language_code": language_code,
        }
        update_values = {"language_code": language_code}
        if username is not None:
            update_values["username"] = username
        if full_name is not None:
            update_values["full_name"] = full_name

        statement = insert(User).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[User.tg_user_id],
            set_=update_values,
        )
        await self.session.execute(statement)
        await self.session.commit()

    async def resolve_language(self, tg_user_id: int, fallback: str | None = None) -> str:
        lang = await self.get_language(tg_user_id)
        return lang or fallback or get_settings().default_language
