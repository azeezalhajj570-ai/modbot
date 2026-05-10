from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.agents.auth import AgentTelegramAuthResult, AgentTelegramAuthSession, AgentTelegramTwoFactorRequired
from bot.agents.contracts import AccountGroupVisibility, AccountSessionState, AgentJobOwnership, LinkedAccountIdentity
from bot.agents.linked_account_service import LinkedAccountService
from bot.agents.account_session_service import AccountSessionService
from bot.agents.account_group_membership_service import AccountGroupMembershipService
from bot.agents.agent_job_service import AgentJobService
from bot.agents.runtime import GROUP_MEMBER_BROADCAST_JOB_TYPE
from bot.agents.service import AgentService
from bot.db.models import Agent, AgentJob, AgentNotification, Group, GroupAdminRole, ScrapedGroup, ScrapedMember, ScrapedMessage, User


class FakeTelegramAuthService:
    async def start_login(self, *, phone_number: str) -> AgentTelegramAuthSession:
        return AgentTelegramAuthSession(phone_number=phone_number, session_string="session:pending", phone_code_hash="hash-1")

    async def verify_code(
        self,
        *,
        phone_number: str,
        code: str,
        phone_code_hash: str,
        session_string: str,
    ) -> AgentTelegramAuthResult:
        assert phone_number == "+15550000001"
        assert code == "12345"
        assert phone_code_hash == "hash-1"
        assert session_string == "session:pending"
        return AgentTelegramAuthResult(
            telegram_user_id=9101,
            phone_number=phone_number,
            username="salesbot",
            full_name="Sales Bot",
            session_string="session:active",
        )

    async def verify_password(self, *, password: str, session_string: str) -> AgentTelegramAuthResult:
        raise AssertionError("2FA should not be required in this test")


class CountingTelegramAuthService(FakeTelegramAuthService):
    def __init__(self) -> None:
        self.start_login_calls = 0

    async def start_login(self, *, phone_number: str) -> AgentTelegramAuthSession:
        self.start_login_calls += 1
        return AgentTelegramAuthSession(
            phone_number=phone_number,
            session_string=f"session:pending:{self.start_login_calls}",
            phone_code_hash=f"hash-{self.start_login_calls}",
        )


class FakeTelegramAuth2FAService(FakeTelegramAuthService):
    async def verify_code(
        self,
        *,
        phone_number: str,
        code: str,
        phone_code_hash: str,
        session_string: str,
    ) -> AgentTelegramAuthResult:
        raise AgentTelegramTwoFactorRequired("2FA required")

    async def verify_password(self, *, password: str, session_string: str) -> AgentTelegramAuthResult:
        assert password == "secret-password"
        assert session_string == "session:pending"
        return AgentTelegramAuthResult(
            telegram_user_id=9102,
            phone_number="+15550000002",
            username="opsbot",
            full_name="Ops Bot",
            session_string="session:active-2fa",
        )


@pytest.mark.asyncio
async def test_agent_service_authenticates_agent_and_creates_job(db_session) -> None:
    user = User(tg_user_id=8101, username="owner", full_name="Owner", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008101, title="Agents Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    service = AgentService(db_session)
    agent = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+15550000001",
        auth_service=FakeTelegramAuthService(),
    )
    assert agent.auth_state == "pending_code"

    agent = await service.complete_agent_code(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        code="12345",
        auth_service=FakeTelegramAuthService(),
    )
    job = await service.create_job(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        job_type="sync",
        job_payload={"priority": "high"},
    )

    stored_agent = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    stored_job = (await db_session.execute(select(AgentJob).where(AgentJob.id == job.id))).scalar_one()
    assert stored_agent.external_account_id == "salesbot"
    assert stored_agent.phone_number == "+15550000001"
    assert stored_agent.auth_state == "active"
    assert stored_agent.session_string == "session:active"
    assert stored_job.job_type == "sync"
    assert stored_job.status == "pending"


@pytest.mark.asyncio
async def test_linked_account_service_validates_and_deduplicates_phone_numbers(db_session) -> None:
    user = User(tg_user_id=8120, username="owner20", full_name="Owner 20", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008120, title="Phone Link Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    service = LinkedAccountService(db_session)
    with pytest.raises(ValueError, match="international format"):
        await service.create_agent(
            actor_user_id=user.tg_user_id,
            group_id=group.id,
            external_account_id="bad-phone-agent",
            phone_number="555",
        )

    agent = await service.create_agent(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        external_account_id="phone-agent-a",
        phone_number="+1 (555) 000-0300",
    )

    assert agent.phone_number == "+15550000300"
    assert agent.linked_by_user_id == user.tg_user_id
    assert agent.auth_state == "pending_auth"

    with pytest.raises(ValueError, match="already linked"):
        await service.create_agent(
            actor_user_id=user.tg_user_id,
            group_id=group.id,
            external_account_id="phone-agent-b",
            phone_number="+15550000300",
        )


@pytest.mark.asyncio
async def test_account_session_start_reuses_pending_login_without_resending_code(db_session) -> None:
    user = User(tg_user_id=8121, username="owner21", full_name="Owner 21", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008121, title="Login Reuse Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    auth_service = CountingTelegramAuthService()
    service = AccountSessionService(db_session)
    agent = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+1 (555) 000-0400",
        auth_service=auth_service,
    )
    repeated = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+15550000400",
        auth_service=auth_service,
    )

    assert repeated.id == agent.id
    assert repeated.phone_number == "+15550000400"
    assert auth_service.start_login_calls == 1


@pytest.mark.asyncio
async def test_account_session_start_handles_duplicate_phone_rows(db_session) -> None:
    user = User(tg_user_id=8122, username="owner22", full_name="Owner 22", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008122, title="Duplicate Phone Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    db_session.add_all(
        [
            Agent(
                linked_by_user_id=user.tg_user_id,
                group_id=group.id,
                phone_number="+15550000401",
                external_account_id="duplicate-phone-a",
                status="pending",
                auth_state="pending_auth",
                details={},
            ),
            Agent(
                linked_by_user_id=user.tg_user_id,
                group_id=group.id,
                phone_number="+15550000401",
                external_account_id="duplicate-phone-b",
                status="pending",
                auth_state="pending_auth",
                details={},
            ),
        ]
    )
    await db_session.commit()

    auth_service = CountingTelegramAuthService()
    service = AccountSessionService(db_session)
    agent = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+15550000401",
        auth_service=auth_service,
    )
    repeated = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+15550000401",
        auth_service=auth_service,
    )

    assert agent.external_account_id == "+15550000401"
    assert agent.auth_state == "pending_code"
    assert repeated.id == agent.id
    assert auth_service.start_login_calls == 1


@pytest.mark.asyncio
async def test_agent_service_validates_group_member_broadcast_job_payload(db_session) -> None:
    user = User(tg_user_id=8103, username="owner3", full_name="Owner 3", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008104, title="Broadcast Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9103,
        external_account_id="broadcast-agent",
        status="active",
        auth_state="active",
        session_string="session:broadcast",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    service = AgentService(db_session)
    job = await service.create_job(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        job_type=GROUP_MEMBER_BROADCAST_JOB_TYPE,
        job_payload={
            "source_group_id": str(group.tg_group_id),
            "message": "Hello from the team",
            "threshold": "25",
            "interval_seconds": "1.5",
        },
    )

    stored_job = (await db_session.execute(select(AgentJob).where(AgentJob.id == job.id))).scalar_one()
    assert stored_job.job_payload["source_group_id"] == group.tg_group_id
    assert stored_job.job_payload["message"] == "Hello from the team"
    assert stored_job.job_payload["threshold"] == 25
    assert stored_job.job_payload["interval_seconds"] == 1.5
    assert stored_job.job_payload["skip_bots"] is True
    queued_notification = (
        await db_session.execute(select(AgentNotification).where(AgentNotification.agent_id == agent.id))
    ).scalars().all()
    assert len(queued_notification) == 1
    assert queued_notification[0].kind == "job_queued"
    assert queued_notification[0].payload["job_type"] == GROUP_MEMBER_BROADCAST_JOB_TYPE
    assert queued_notification[0].payload["job_id"] == job.id
    assert queued_notification[0].payload["job_payload"]["message"] == "Hello from the team"


@pytest.mark.asyncio
async def test_agent_service_rejects_invalid_group_member_broadcast_job_payload(db_session) -> None:
    user = User(tg_user_id=8104, username="owner4", full_name="Owner 4", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008105, title="Broadcast Reject Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9104,
        external_account_id="reject-agent",
        status="active",
        auth_state="active",
        session_string="session:reject",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    service = AgentService(db_session)
    with pytest.raises(ValueError, match="threshold"):
        await service.create_job(
            actor_user_id=user.tg_user_id,
            agent_id=agent.id,
            job_type=GROUP_MEMBER_BROADCAST_JOB_TYPE,
            job_payload={"source_group_id": group.tg_group_id, "message": "Hello", "threshold": 0},
        )


@pytest.mark.asyncio
async def test_agent_service_rejects_non_admin(db_session) -> None:
    group = Group(tg_group_id=-1008102, title="Restricted Agents Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    service = AgentService(db_session)
    with pytest.raises(PermissionError):
        await service.start_agent_login(
            actor_user_id=99999,
            group_id=group.id,
            phone_number="+15550000009",
            auth_service=FakeTelegramAuthService(),
        )


@pytest.mark.asyncio
async def test_scrape_agent_member_group_creates_notification(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(tg_user_id=8105, username="owner5", full_name="Owner 5", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008106, title="Scrape Notify Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9105,
        external_account_id="notify-agent",
        status="active",
        auth_state="active",
        session_string="session:notify",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    async def fake_ensure_visible(self, *, agent, tg_group_id: int) -> None:
        _ = (self, agent, tg_group_id)

    async def fake_list_groups(self, agent):
        _ = self
        return [{"tg_group_id": group.tg_group_id, "title": group.title}]

    async def fake_scrape_full_group(self, **kwargs):
        _ = kwargs
        return {
            "group_info": None,
            "members": {"success_count": 31, "error_count": 0, "total_scraped": 31},
            "messages": {"success_count": 12, "error_count": 0, "total_scraped": 12},
        }

    monkeypatch.setattr(AccountGroupMembershipService, "_ensure_agent_group_visible", fake_ensure_visible)
    monkeypatch.setattr(AccountGroupMembershipService, "_list_agent_member_groups", fake_list_groups)
    monkeypatch.setattr("bot.agents.account_group_membership_service.ScraperService.scrape_full_group", fake_scrape_full_group)

    payload = await AccountGroupMembershipService(db_session).scrape_agent_member_group(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        tg_group_id=group.tg_group_id,
        limit=500,
        message_limit=500,
        max_age_days=30,
    )

    assert payload["success_count"] == 31
    notifications = (
        await db_session.execute(select(AgentNotification).where(AgentNotification.agent_id == agent.id))
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].title == "Scrape finished"
    assert notifications[0].is_seen is False
    assert notifications[0].payload["messages_count"] == 12


@pytest.mark.asyncio
async def test_agent_service_handles_2fa_login(db_session) -> None:
    user = User(tg_user_id=8102, username="owner2", full_name="Owner 2", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008103, title="Agents 2FA Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    service = AgentService(db_session)
    agent = await service.start_agent_login(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        phone_number="+15550000002",
        auth_service=FakeTelegramAuth2FAService(),
    )
    agent = await service.complete_agent_code(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        code="22222",
        auth_service=FakeTelegramAuth2FAService(),
    )
    assert agent.auth_state == "pending_2fa"

    agent = await service.complete_agent_password(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        password="secret-password",
        auth_service=FakeTelegramAuth2FAService(),
    )
    assert agent.auth_state == "active"
    assert agent.external_account_id == "opsbot"


@pytest.mark.asyncio
async def test_extracted_agent_services_expose_group_owned_account_contracts(db_session) -> None:
    user = User(tg_user_id=8110, username="owner10", full_name="Owner 10", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008110, title="Contracts Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9110,
        external_account_id="contracts-agent",
        phone_number="+15550000110",
        status="active",
        auth_state="active",
        session_string="session:contracts",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    linked_identity = await LinkedAccountService(db_session).describe_linked_account(agent_id=agent.id)
    session_state = await AccountSessionService(db_session).get_account_session_state(agent_id=agent.id)

    assert linked_identity == LinkedAccountIdentity(
        agent_id=agent.id,
        group_id=group.id,
        external_account_id="contracts-agent",
        telegram_user_id=9110,
        ownership_scope="group",
    )
    assert session_state == AccountSessionState(
        agent_id=agent.id,
        group_id=group.id,
        auth_state="active",
        status="active",
        phone_number="+15550000110",
        session_available=True,
        ownership_scope="group",
    )


@pytest.mark.asyncio
async def test_account_group_membership_service_exposes_group_visibility_contract(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(tg_user_id=8112, username="owner12", full_name="Owner 12", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008112, title="Visibility Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9112,
        external_account_id="visibility-agent",
        status="active",
        auth_state="active",
        session_string="session:visibility",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    async def fake_list_managed_member_groups(self, *, actor_user_id: int, agent_id: int):
        assert actor_user_id == user.tg_user_id
        assert agent_id == agent.id
        return [{"tg_group_id": -1009555, "title": "Remote Visibility Group"}]

    monkeypatch.setattr(
        AccountGroupMembershipService,
        "list_managed_member_groups",
        fake_list_managed_member_groups,
    )

    visibility = await AccountGroupMembershipService(db_session).list_account_group_visibility(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
    )

    assert visibility == [
        AccountGroupVisibility(
            agent_id=agent.id,
            group_id=group.id,
            tg_group_id=-1009555,
            title="Remote Visibility Group",
            visibility_scope="group",
        )
    ]


@pytest.mark.asyncio
async def test_account_group_membership_service_returns_member_message_counts_and_history(db_session) -> None:
    user = User(tg_user_id=8113, username="owner13", full_name="Owner 13", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008113, title="Member History Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9113,
        external_account_id="history-agent",
        status="active",
        auth_state="active",
        session_string="session:history",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()

    scraped_group = ScrapedGroup(
        tg_group_id=group.tg_group_id,
        title=group.title,
        group_type="supergroup",
        last_agent_id=agent.id,
        member_count=2,
    )
    db_session.add(scraped_group)
    await db_session.flush()

    db_session.add_all(
        [
            ScrapedMember(
                scraped_group_id=scraped_group.id,
                tg_group_id=group.tg_group_id,
                tg_user_id=7001,
                username="member_one",
                full_name="Member One",
                role="member",
            ),
            ScrapedMember(
                scraped_group_id=scraped_group.id,
                tg_group_id=group.tg_group_id,
                tg_user_id=7002,
                username="member_two",
                full_name="Member Two",
                role="member",
            ),
        ]
    )
    db_session.add_all(
        [
            ScrapedMessage(
                scraped_group_id=scraped_group.id,
                tg_group_id=group.tg_group_id,
                message_id=101,
                sender_user_id=7001,
                sender_username="member_one",
                sender_first_name="Member",
                sender_last_name="One",
                message_text="first message",
            ),
            ScrapedMessage(
                scraped_group_id=scraped_group.id,
                tg_group_id=group.tg_group_id,
                message_id=102,
                sender_user_id=7001,
                sender_username="member_one",
                sender_first_name="Member",
                sender_last_name="One",
                message_text="second message",
            ),
            ScrapedMessage(
                scraped_group_id=scraped_group.id,
                tg_group_id=group.tg_group_id,
                message_id=103,
                sender_user_id=7002,
                sender_username="member_two",
                sender_first_name="Member",
                sender_last_name="Two",
                message_text="other member message",
            ),
        ]
    )
    await db_session.commit()

    service = AccountGroupMembershipService(db_session)
    members_payload = await service.list_scraped_agent_group_members(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        tg_group_id=group.tg_group_id,
        page=1,
        page_size=10,
    )
    messages_payload = await service.list_scraped_agent_group_member_messages(
        actor_user_id=user.tg_user_id,
        agent_id=agent.id,
        tg_group_id=group.tg_group_id,
        user_id=7001,
        page=1,
        page_size=10,
    )

    members_by_id = {member["user_id"]: member for member in members_payload["members"]}
    assert members_by_id[7001]["message_count"] == 2
    assert members_by_id[7002]["message_count"] == 1
    assert messages_payload["total"] == 2
    assert [message["message_id"] for message in messages_payload["messages"]] == [102, 101]
    assert messages_payload["messages"][0]["text"] == "second message"


@pytest.mark.asyncio
async def test_agent_job_service_queues_automation_jobs_without_agent_facade(db_session) -> None:
    user = User(tg_user_id=8111, username="owner11", full_name="Owner 11", language_code="en")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008111, title="Automation Job Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9111,
        external_account_id="auto-agent",
        status="active",
        auth_state="active",
        session_string="session:auto",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    job = await AgentJobService(db_session).queue_automation_task_job(
        group_id=group.id,
        agent_id=agent.id,
        task_key="notify_destination",
        assignment_id="assign-1",
        task_config={"destination": "@alerts"},
        conditions={"keywords": ["pricing"]},
        event={"name": "message.received", "group_id": group.id, "user_id": 123, "payload": {"text": "pricing"}},
    )

    assert job == AgentJobOwnership(
        job_id=job.job_id,
        agent_id=agent.id,
        group_id=group.id,
        job_type="automation_task",
        status="pending",
        ownership_scope="group",
    )
    stored_job = (await db_session.execute(select(AgentJob).where(AgentJob.id == job.job_id))).scalar_one()
    assert stored_job.job_payload["task_key"] == "notify_destination"
    assert stored_job.job_payload["assignment_id"] == "assign-1"
