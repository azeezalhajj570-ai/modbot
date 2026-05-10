from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, GroupSetting, PluginEnabled, User, Warning


@pytest.mark.asyncio
async def test_user_group_and_role_relationship_persistence(db_session) -> None:
    user = User(tg_user_id=501, username="alice", full_name="Alice", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-100501, title="DB Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    row = (
        await db_session.execute(
            select(GroupAdminRole).where(GroupAdminRole.group_id == group.id, GroupAdminRole.user_id == user.tg_user_id)
        )
    ).scalar_one()
    assert row.role == "owner"


@pytest.mark.asyncio
async def test_unique_constraint_group_settings(db_session) -> None:
    group = Group(tg_group_id=-100502, title="Unique Group", is_active=True)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupSetting(group_id=group.id, key="anti_links", value={"value": True}))
    await db_session.commit()

    db_session.add(GroupSetting(group_id=group.id, key="anti_links", value={"value": False}))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_group_tg_id_is_unique_per_owner_scope(db_session) -> None:
    owner_one = User(tg_user_id=1501, username="owner1", full_name="Owner One", language_code="en")
    owner_two = User(tg_user_id=1502, username="owner2", full_name="Owner Two", language_code="en")
    db_session.add_all([owner_one, owner_two])
    await db_session.flush()

    db_session.add_all(
        [
            Group(tg_group_id=-100777001, title="Owner One Group", owner_user_id=owner_one.id, is_active=True),
            Group(tg_group_id=-100777001, title="Owner Two Group", owner_user_id=owner_two.id, is_active=True),
        ]
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(Group).where(Group.tg_group_id == -100777001).order_by(Group.owner_user_id.asc()))
    ).scalars().all()
    assert [row.owner_user_id for row in rows] == [owner_one.id, owner_two.id]


@pytest.mark.asyncio
async def test_group_tg_id_cannot_repeat_for_same_owner_scope(db_session) -> None:
    owner = User(tg_user_id=1503, username="owner3", full_name="Owner Three", language_code="en")
    db_session.add(owner)
    await db_session.flush()

    db_session.add(Group(tg_group_id=-100777002, title="Scoped Group", owner_user_id=owner.id, is_active=True))
    await db_session.commit()

    db_session.add(Group(tg_group_id=-100777002, title="Scoped Group Duplicate", owner_user_id=owner.id, is_active=True))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_plugin_enabled_and_warnings_rows(db_session) -> None:
    group = Group(tg_group_id=-100503, title="Feature Group", is_active=True)
    db_session.add(group)
    await db_session.flush()

    db_session.add(PluginEnabled(group_id=group.id, plugin_name="anti_links", enabled=True, config={}))
    db_session.add(Warning(group_id=group.id, user_id=777, issued_by=1, reason="link", count=1))
    await db_session.commit()

    plugin = (
        await db_session.execute(
            select(PluginEnabled).where(PluginEnabled.group_id == group.id, PluginEnabled.plugin_name == "anti_links")
        )
    ).scalar_one()
    assert plugin.enabled is True

    warning = (
        await db_session.execute(select(Warning).where(Warning.group_id == group.id, Warning.user_id == 777))
    ).scalar_one()
    assert warning.reason == "link"


@pytest.mark.asyncio
async def test_agent_and_agent_job_relationship(db_session) -> None:
    group = Group(tg_group_id=-100504, title="Agent Group", is_active=True)
    db_session.add(group)
    await db_session.flush()

    agent = Agent(group_id=group.id, telegram_user_id=1234, external_account_id="support-bot", status="active", details={})
    db_session.add(agent)
    await db_session.flush()
    db_session.add(AgentJob(agent_id=agent.id, job_type="sync", job_payload={"scope": "full"}, status="pending"))
    await db_session.commit()

    row = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    assert row.external_account_id == "support-bot"
    job = (await db_session.execute(select(AgentJob).where(AgentJob.agent_id == agent.id))).scalar_one()
    assert job.job_payload["scope"] == "full"
