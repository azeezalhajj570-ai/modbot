from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import delete, insert

from bot.db.models import Group, GroupAdminRole, GroupSetting, PluginEnabled, User
from bot.db.session import SessionLocal


async def seed() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(GroupSetting))
        await session.execute(delete(PluginEnabled))
        await session.execute(delete(GroupAdminRole))
        await session.execute(delete(Group))
        await session.execute(delete(User))

        await session.execute(
            insert(User),
            [
                {
                    "id": 1,
                    "tg_user_id": 111111,
                    "username": "owner_user",
                    "full_name": "Owner User",
                    "language_code": "en",
                    "created_at": datetime.utcnow(),
                },
                {
                    "id": 2,
                    "tg_user_id": 222222,
                    "username": "admin_ar",
                    "full_name": "Admin Arabic",
                    "language_code": "ar",
                    "created_at": datetime.utcnow(),
                },
            ],
        )

        await session.execute(
            insert(Group),
            [
                {
                    "id": 1,
                    "tg_group_id": -100123456789,
                    "title": "Community Alpha",
                    "owner_user_id": 1,
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                },
                {
                    "id": 2,
                    "tg_group_id": -100223456789,
                    "title": "Trading Hub",
                    "owner_user_id": 1,
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                },
            ],
        )

        await session.execute(
            insert(GroupAdminRole),
            [
                {
                    "group_id": 1,
                    "user_id": 111111,
                    "role": "owner",
                    "created_at": datetime.utcnow(),
                },
                {
                    "group_id": 1,
                    "user_id": 222222,
                    "role": "admin",
                    "created_at": datetime.utcnow(),
                },
            ],
        )

        await session.execute(
            insert(PluginEnabled),
            [
                {"group_id": 1, "plugin_name": "anti_links", "enabled": True, "config": {}},
                {"group_id": 1, "plugin_name": "welcome", "enabled": False, "config": {}},
            ],
        )

        await session.execute(
            insert(GroupSetting),
            [
                {"group_id": 1, "key": "anti_links", "value": {"value": True}, "updated_at": datetime.utcnow()},
                {"group_id": 1, "key": "warn_limit", "value": {"value": 3}, "updated_at": datetime.utcnow()},
            ],
        )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
