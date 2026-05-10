from __future__ import annotations

import pytest

from bot.services.group_service import GroupService


class _Row:
    def __init__(self, group_id: int, title: str, tg_group_id: int = 0) -> None:
        self.id = group_id
        self.title = title
        self.tg_group_id = tg_group_id


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows) -> None:
        self._rows = rows

    async def execute(self, _stmt):
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_list_admin_groups_deduplicates_by_group_id() -> None:
    rows = [
        _Row(1, "Group A", -1001),
        _Row(1, "Group A", -1001),
        _Row(2, "Group B", -1002),
    ]
    service = GroupService(_Session(rows))

    page = await service.list_admin_groups(user_id=111, page=1, page_size=10)

    assert [item["id"] for item in page.items] == [1, 2]


@pytest.mark.asyncio
async def test_list_admin_groups_all_deduplicates_by_group_id() -> None:
    rows = [
        _Row(1, "Group A", -1001),
        _Row(1, "Group A", -1001),
        _Row(2, "Group B", -1002),
    ]
    service = GroupService(_Session(rows))

    items = await service.list_admin_groups_all(user_id=111)

    assert [item["id"] for item in items] == [1, 2]
    assert items[0]["tg_group_id"] == -1001


@pytest.mark.asyncio
async def test_list_admin_groups_prefers_supergroup_variant() -> None:
    rows = [
        _Row(3, "Gate Group", -3333),
        _Row(4, "Gate Group", -1003333),
    ]
    service = GroupService(_Session(rows))

    page = await service.list_admin_groups(user_id=111, page=1, page_size=10)

    assert page.items == [{"id": 4, "title": "Gate Group"}]


@pytest.mark.asyncio
async def test_list_admin_groups_all_prefers_supergroup_variant() -> None:
    rows = [
        _Row(3, "Gate Group", -3333),
        _Row(4, "Gate Group", -1003333),
    ]
    service = GroupService(_Session(rows))

    items = await service.list_admin_groups_all(user_id=111)

    assert items == [{"id": 4, "title": "Gate Group", "tg_group_id": -1003333}]
