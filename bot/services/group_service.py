from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import BigInteger, func, or_, select
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from bot.config import get_settings
from bot.db.models import Group, GroupAdminRole, GroupMember, User
from bot.utils.pagination import Page, paginate


def tg_group_id_candidates(tg_group_id: int) -> tuple[int, ...]:
    text = str(tg_group_id)
    if tg_group_id > 0 and text.startswith("100"):
        canonical_id = -int(text)
        legacy_id = -int(text[3:])
        return (canonical_id, tg_group_id, legacy_id)
    if text.startswith("-100"):
        legacy_id = -int(text[4:])
        raw_supergroup_id = int(text[1:])
        return (tg_group_id, legacy_id, raw_supergroup_id)
    if tg_group_id < 0:
        return (tg_group_id, int(f"-100{abs(tg_group_id)}"))
    return (tg_group_id,)


def canonical_tg_group_id(tg_group_id: int) -> int:
    text = str(tg_group_id)
    if tg_group_id > 0 and text.startswith("100"):
        return -int(text)
    candidates = tg_group_id_candidates(tg_group_id)
    return min(candidates, key=lambda value: (0 if str(value).startswith("-100") else 1, abs(value)))


def _match_tg_user_ids(column, tg_user_ids: Sequence[int], dialect_name: str):
    normalized_ids = [int(user_id) for user_id in tg_user_ids]
    if dialect_name == "postgresql":
        return column == pg_array(normalized_ids, type_=BigInteger).any_()
    return column.in_(normalized_ids)


def _build_insert(table, dialect_name: str):
    if dialect_name == "postgresql":
        return pg_insert(table)
    if dialect_name == "sqlite":
        return sqlite_insert(table)
    raise NotImplementedError(f"Unsupported database dialect for bulk upsert: {dialect_name}")


async def bulk_upsert_group_members(
    session: AsyncSession,
    *,
    group_id: int,
    members: Sequence[dict[str, Any]],
    commit: bool,
) -> None:
    if not members:
        if commit:
            await session.commit()
        return

    bind = getattr(session, "bind", None)
    if bind is None:
        sync_session = getattr(session, "_session", None)
        bind = getattr(sync_session, "bind", None)
    dialect_name = bind.dialect.name if bind is not None else "sqlite"

    normalized_members_by_tg_id: dict[int, dict[str, Any]] = {}
    for member in members:
        tg_user_id = int(member["tg_user_id"])
        normalized_members_by_tg_id[tg_user_id] = {
            **member,
            "tg_user_id": tg_user_id,
        }
    normalized_members = list(normalized_members_by_tg_id.values())
    unique_tg_user_ids = list(normalized_members_by_tg_id.keys())
    existing_users = (
        await session.execute(
            select(User).where(_match_tg_user_ids(User.tg_user_id, unique_tg_user_ids, dialect_name))
        )
    ).scalars().all()
    existing_group_members = (
        await session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                _match_tg_user_ids(GroupMember.tg_user_id, unique_tg_user_ids, dialect_name),
            )
        )
    ).scalars().all()

    existing_users_by_tg_id = {int(user.tg_user_id): user for user in existing_users}
    existing_members_by_tg_id = {int(member.tg_user_id): member for member in existing_group_members}
    default_language = get_settings().default_language

    user_rows: list[dict[str, Any]] = []
    group_member_rows: list[dict[str, Any]] = []
    for member in normalized_members:
        tg_user_id = int(member["tg_user_id"])
        username = member.get("username")
        full_name = member.get("full_name")
        language_code = member.get("language_code")
        normalized_role = str(member.get("role") or "member").strip() or "member"
        source = member.get("source")

        existing_user = existing_users_by_tg_id.get(tg_user_id)
        final_language_code = (
            str(language_code)
            if language_code
            else (existing_user.language_code if existing_user is not None else default_language)
        )
        if (
            existing_user is None
            or existing_user.username != username
            or existing_user.full_name != full_name
            or existing_user.language_code != final_language_code
        ):
            user_rows.append(
                {
                    "tg_user_id": tg_user_id,
                    "username": username,
                    "full_name": full_name,
                    "language_code": final_language_code,
                }
            )

        existing_group_member = existing_members_by_tg_id.get(tg_user_id)
        if existing_group_member is None:
            final_source = source
        else:
            final_source = source or existing_group_member.source
        if (
            existing_group_member is None
            or existing_group_member.username != username
            or existing_group_member.full_name != full_name
            or existing_group_member.role != normalized_role
            or existing_group_member.source != final_source
        ):
            group_member_rows.append(
                {
                    "group_id": group_id,
                    "tg_user_id": tg_user_id,
                    "username": username,
                    "full_name": full_name,
                    "role": normalized_role,
                    "source": final_source,
                }
            )

    if user_rows:
        user_insert = _build_insert(User.__table__, dialect_name).values(user_rows)
        await session.execute(
            user_insert.on_conflict_do_update(
                index_elements=[User.tg_user_id],
                set_={
                    "username": user_insert.excluded.username,
                    "full_name": user_insert.excluded.full_name,
                    "language_code": user_insert.excluded.language_code,
                },
            )
        )

    if group_member_rows:
        group_member_insert = _build_insert(GroupMember.__table__, dialect_name).values(group_member_rows)
        await session.execute(
            group_member_insert.on_conflict_do_update(
                index_elements=[GroupMember.group_id, GroupMember.tg_user_id],
                set_={
                    "username": group_member_insert.excluded.username,
                    "full_name": group_member_insert.excluded.full_name,
                    "role": group_member_insert.excluded.role,
                    "source": group_member_insert.excluded.source,
                    "updated_at": func.now(),
                },
            )
        )

    if commit:
        await session.commit()


async def _get_or_create_user(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    full_name: str | None,
    language_code: str | None,
) -> User:
    user = (await session.execute(select(User).where(User.tg_user_id == tg_user_id))).scalar_one_or_none()
    if user:
        user.username = username
        user.full_name = full_name
        if language_code:
            user.language_code = language_code
        return user

    user = User(
        tg_user_id=tg_user_id,
        username=username,
        full_name=full_name,
        language_code=language_code or get_settings().default_language,
    )
    session.add(user)
    await session.flush()
    return user


def _select_scoped_group(
    rows: Sequence[Group],
    *,
    tg_group_id: int,
    owner_db_user_id: int | None,
) -> Group | None:
    if owner_db_user_id is not None:
        owned_rows = [row for row in rows if row.owner_user_id == owner_db_user_id]
        if owned_rows:
            return next((row for row in owned_rows if row.tg_group_id == tg_group_id), owned_rows[0])

        # Allow a single legacy unowned row to be adopted into the caller's scope.
        unowned_rows = [row for row in rows if row.owner_user_id is None]
        if unowned_rows and len(unowned_rows) == len(rows):
            return next((row for row in unowned_rows if row.tg_group_id == tg_group_id), unowned_rows[0])
        return None

    unowned_rows = [row for row in rows if row.owner_user_id is None]
    if not unowned_rows:
        return None
    return next((row for row in unowned_rows if row.tg_group_id == tg_group_id), unowned_rows[0])


async def upsert_group_member(
    session: AsyncSession,
    *,
    group_id: int,
    tg_user_id: int,
    username: str | None,
    full_name: str | None,
    language_code: str | None = None,
    role: str = "member",
    source: str | None = None,
) -> GroupMember:
    await bulk_upsert_group_members(
        session,
        group_id=group_id,
        members=[
            {
                "tg_user_id": int(tg_user_id),
                "username": username,
                "full_name": full_name,
                "language_code": language_code,
                "role": role,
                "source": source,
            }
        ],
        commit=False,
    )
    membership = (
        await session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.tg_user_id == tg_user_id,
            )
        )
    ).scalar_one()
    return membership


async def upsert_group(
    session: AsyncSession,
    *,
    tg_group_id: int,
    title: str | None,
    is_active: bool = True,
    owner_user_id: int | None = None,
) -> Group:
    tg_group_id = canonical_tg_group_id(int(tg_group_id))
    candidates = tg_group_id_candidates(tg_group_id)
    rows = (await session.execute(select(Group).where(Group.tg_group_id.in_(candidates)))).scalars().all()
    group = _select_scoped_group(rows, tg_group_id=tg_group_id, owner_db_user_id=owner_user_id)

    if group:
        group.tg_group_id = tg_group_id
        group.title = title or group.title
        group.is_active = is_active
        if owner_user_id is not None and group.owner_user_id is None:
            group.owner_user_id = owner_user_id
        return group

    bind = getattr(session, "bind", None)
    if bind is None:
        sync_session = getattr(session, "_session", None)
        bind = getattr(sync_session, "bind", None)
    dialect_name = bind.dialect.name if bind is not None else "sqlite"

    if dialect_name == "postgresql":
        try:
            statement = (
                pg_insert(Group)
                .values(
                    tg_group_id=tg_group_id,
                    title=title or str(tg_group_id),
                    is_active=is_active,
                    owner_user_id=owner_user_id,
                )
                .on_conflict_do_update(
                    index_elements=[Group.tg_group_id],
                    set_={
                        "title": title or str(tg_group_id),
                        "is_active": is_active,
                    },
                )
                .returning(Group.id)
            )
            group_id = int((await session.execute(statement)).scalar_one())
            group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one()
            return group
        except IntegrityError:
            rows = (await session.execute(select(Group).where(Group.tg_group_id.in_(candidates)))).scalars().all()
            group = _select_scoped_group(rows, tg_group_id=tg_group_id, owner_db_user_id=owner_user_id)
            if group:
                return group
            raise

    group = Group(
        tg_group_id=tg_group_id,
        title=title or str(tg_group_id),
        owner_user_id=owner_user_id,
        is_active=is_active,
    )
    session.add(group)
    await session.flush()
    return group


async def sync_group_admin_roles(
    session: AsyncSession,
    *,
    bot,
    group: Group,
    fallback_actor=None,
) -> None:
    synced_user_ids: set[int] = set()

    try:
        admins = await bot.get_chat_administrators(group.tg_group_id)
    except Exception:
        admins = []

    for admin in admins:
        admin_user = getattr(admin, "user", None)
        if admin_user is None or getattr(admin_user, "is_bot", False):
            continue

        db_user = await _get_or_create_user(
            session,
            tg_user_id=admin_user.id,
            username=getattr(admin_user, "username", None),
            full_name=getattr(admin_user, "full_name", None),
            language_code=getattr(admin_user, "language_code", None),
        )
        role_name = "owner" if getattr(admin, "status", None) in {"creator", "owner"} else "admin"
        role = (
            await session.execute(
                select(GroupAdminRole).where(
                    GroupAdminRole.group_id == group.id,
                    GroupAdminRole.user_id == admin_user.id,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            session.add(GroupAdminRole(group_id=group.id, user_id=admin_user.id, role=role_name))
        else:
            role.role = role_name

        if role_name == "owner":
            group.owner_user_id = db_user.id

        synced_user_ids.add(admin_user.id)

    if fallback_actor is None or fallback_actor.id in synced_user_ids:
        return

    await _get_or_create_user(
        session,
        tg_user_id=fallback_actor.id,
        username=getattr(fallback_actor, "username", None),
        full_name=getattr(fallback_actor, "full_name", None),
        language_code=getattr(fallback_actor, "language_code", None),
    )
    role = (
        await session.execute(
            select(GroupAdminRole).where(
                GroupAdminRole.group_id == group.id,
                GroupAdminRole.user_id == fallback_actor.id,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        session.add(GroupAdminRole(group_id=group.id, user_id=fallback_actor.id, role="admin"))


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _prefer_row(current: dict | None, row) -> bool:
        if current is None:
            return True
        current_is_supergroup = str(current["tg_group_id"]).startswith("-100")
        row_is_supergroup = str(row.tg_group_id).startswith("-100")
        if row_is_supergroup and not current_is_supergroup:
            return True
        return False

    async def list_admin_groups(self, user_id: int, page: int, page_size: int = 10) -> Page[dict]:
        stmt = (
            select(Group.id, Group.title, Group.tg_group_id)
            .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
            .where(GroupAdminRole.user_id == user_id, Group.is_active.is_(True))
            .order_by(Group.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        canonical_items: dict[int, dict] = {}
        for row in rows:
            canonical_id = canonical_tg_group_id(int(row.tg_group_id))
            current = canonical_items.get(canonical_id)
            if self._prefer_row(current, row):
                canonical_items[canonical_id] = {"id": row.id, "title": row.title, "tg_group_id": row.tg_group_id}
        items = [{"id": item["id"], "title": item["title"]} for item in canonical_items.values()]
        items.sort(key=lambda item: str(item["title"]).lower())
        return paginate(items, page=page, page_size=page_size)
    
    async def list_admin_groups_all(self, user_id: int) -> list[dict]:
        stmt = (
            select(Group.id, Group.title, Group.tg_group_id, Group.created_at)
            .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
            .where(GroupAdminRole.user_id == user_id, Group.is_active.is_(True))
            .order_by(Group.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        canonical_items: dict[int, dict] = {}
        for row in rows:
            canonical_id = canonical_tg_group_id(int(row.tg_group_id))
            current = canonical_items.get(canonical_id)
            if self._prefer_row(current, row):
                canonical_items[canonical_id] = {"id": row.id, "title": row.title, "tg_group_id": row.tg_group_id}
        items = list(canonical_items.values())
        items.sort(key=lambda item: str(item["title"]).lower())
        return items

    async def refresh_admin_groups(self, *, user_id: int, bot, fallback_actor=None) -> int:
        stmt = (
            select(Group)
            .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
            .where(GroupAdminRole.user_id == user_id, Group.is_active.is_(True))
            .order_by(Group.id.asc())
        )
        groups = list((await self.session.execute(stmt)).scalars().unique())
        refreshed = 0

        for group in groups:
            try:
                chat = await bot.get_chat(group.tg_group_id)
            except Exception:
                continue

            group.title = getattr(chat, "title", None) or group.title
            group.is_active = True
            await sync_group_admin_roles(self.session, bot=bot, group=group, fallback_actor=fallback_actor)
            refreshed += 1

        await self.session.commit()
        return refreshed

    async def get_or_create_by_tg_id(
        self,
        *,
        tg_group_id: int,
        title: str | None = None,
        owner_tg_user_id: int | None = None,
        is_active: bool = False,
    ) -> Group:
        owner_db_user_id: int | None = None
        if owner_tg_user_id is not None:
            owner = await _get_or_create_user(
                self.session,
                tg_user_id=int(owner_tg_user_id),
                username=None,
                full_name=None,
                language_code=None,
            )
            owner_db_user_id = int(owner.id)
        group = await upsert_group(
            self.session,
            tg_group_id=tg_group_id,
            title=title,
            is_active=is_active,
            owner_user_id=owner_db_user_id,
        )
        if owner_tg_user_id:
            role = (
                await self.session.execute(
                    select(GroupAdminRole).where(
                        GroupAdminRole.group_id == group.id,
                        GroupAdminRole.user_id == owner_tg_user_id,
                    )
                )
            ).scalar_one_or_none()
            if role is None:
                self.session.add(GroupAdminRole(group_id=group.id, user_id=owner_tg_user_id, role="owner"))
        await self.session.flush()
        return group
