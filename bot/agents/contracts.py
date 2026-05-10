from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LinkedAccountIdentity:
    agent_id: int
    group_id: int
    external_account_id: str
    telegram_user_id: int | None
    ownership_scope: str = "group"


@dataclass
class AccountSessionState:
    agent_id: int
    group_id: int
    auth_state: str
    status: str
    phone_number: str | None
    session_available: bool
    ownership_scope: str = "group"


@dataclass
class AccountGroupVisibility:
    agent_id: int
    group_id: int
    tg_group_id: int
    title: str
    visibility_scope: str = "group"


@dataclass
class AgentJobOwnership:
    job_id: int
    agent_id: int
    group_id: int
    job_type: str
    status: str
    ownership_scope: str = "group"
