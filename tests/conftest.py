from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alembic import command
from alembic.config import Config
import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, MenuButtonCommands, Message, Update, User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bot.config import get_settings

# Deterministic env for tests.
os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["BOT_OWNER_IDS"] = "6666,1001,9903,8113,8103"
get_settings.cache_clear()
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-ci.sqlite3")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("AI_PROVIDER", "heuristic")
os.environ.setdefault("AI_RECEPTIONIST_ENABLED", "true")
os.environ.setdefault("ADS_CLASSIFIER_URL", "")
os.environ["DASHBOARD_URL"] = "https://dashboard.test"
os.environ["WEBAPP_URL"] = "https://app.test"
os.environ["DEFAULT_LANGUAGE"] = "ar"
os.environ["BOT_OWNER_IDS"] = "6666,1001,9903,8113,8103"

from bot.core.event_bus import EventBus
from bot.core.menu_engine import MenuEngine
from bot.core.plugin_manager import PluginManager
from bot.dashboard.api.main import app as dashboard_app
from bot.db.bootstrap import ensure_schema
from bot.db.models import Group, GroupAdminRole, User as UserModel
from bot.handlers import build_router


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, stmt):
        return self._session.execute(stmt)

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def add_all(self, instances: list[Any]) -> None:
        self._session.add_all(instances)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance: Any) -> None:
        self._session.refresh(instance)

    async def delete(self, instance: Any) -> None:
        self._session.delete(instance)

    async def close(self) -> None:
        self._session.close()

    async def connection(self) -> Any:
        return self._session.connection()


class SessionContextFactory:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def __call__(self):
        factory = self

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                self._session = factory._maker()
                return self._session

            async def __aexit__(self, _exc_type, _exc, _tb) -> None:
                await self._session.close()

        return _Ctx()


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def flushall(self) -> None:
        self._store.clear()


@dataclass
class BotCallLog:
    answers: list[dict[str, Any]] = field(default_factory=list)
    edits: list[dict[str, Any]] = field(default_factory=list)
    edit_markups: list[dict[str, Any]] = field(default_factory=list)
    callback_answers: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[dict[str, Any]] = field(default_factory=list)


class FakeTelegramBot:
    def __init__(self) -> None:
        self.deleted_messages: list[tuple[int, int]] = []
        self.sent_messages: list[tuple[int, str]] = []
        self.sent_message_payloads: list[dict[str, Any]] = []
        self.forwarded_messages: list[tuple[int | str, int | str, int]] = []
        self.copied_messages: list[tuple[int | str, int | str, int]] = []
        self._next_message_id = 1000
        self.banned_members: list[tuple[int, int]] = []
        self.unbanned_members: list[tuple[int, int]] = []
        self.muted_members: list[tuple[int, int]] = []
        self.unmuted_members: list[tuple[int, int, Any]] = []
        self.promoted_members: list[tuple[int, int, dict[str, Any]]] = []
        self.demoted_members: list[tuple[int, int, dict[str, Any]]] = []
        self.left_chats: list[int] = []
        self.member_counts: dict[int, int] = {}
        self.chat_administrators: dict[int, list[SimpleNamespace]] = {}
        self.chats: dict[int, SimpleNamespace] = {}
        self.invite_links: dict[int, str] = {}
        self.session = SimpleNamespace(close=self._close_session)
        self.chat_members: dict[tuple[int, int], SimpleNamespace] = {}
        self.chat_menu_buttons: list[dict[str, Any]] = []
        self.my_commands: list[Any] = []
        self.approved_join_requests: list[tuple[int, int]] = []
        self.declined_join_requests: list[tuple[int, int]] = []

    async def get_me(self) -> SimpleNamespace:
        return SimpleNamespace(username="combot_test_bot")

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append((chat_id, message_id))

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        self.sent_messages.append((chat_id, text))
        self.sent_message_payloads.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                **kwargs,
            }
        )
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id)

    async def forward_message(
        self,
        chat_id: int | str,
        from_chat_id: int | str,
        message_id: int,
        **_kwargs: Any,
    ) -> SimpleNamespace:
        self.forwarded_messages.append((chat_id, from_chat_id, message_id))
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id)

    async def copy_message(
        self,
        chat_id: int | str,
        from_chat_id: int | str,
        message_id: int,
        **_kwargs: Any,
    ) -> SimpleNamespace:
        self.copied_messages.append((chat_id, from_chat_id, message_id))
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id)

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.banned_members.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.unbanned_members.append((chat_id, user_id))

    async def restrict_chat_member(self, chat_id: int, user_id: int, permissions: Any) -> None:
        if getattr(permissions, "can_send_messages", None) is False:
            self.muted_members.append((chat_id, user_id))
        else:
            self.unmuted_members.append((chat_id, user_id, permissions))

    async def promote_chat_member(self, chat_id: int, user_id: int, **kwargs: Any) -> None:
        if any(bool(value) for value in kwargs.values()):
            self.promoted_members.append((chat_id, user_id, kwargs))
        else:
            self.demoted_members.append((chat_id, user_id, kwargs))

    async def get_chat_member(self, chat_id: int, user_id: int) -> SimpleNamespace:
        if (chat_id, user_id) in self.chat_members:
            return self.chat_members[(chat_id, user_id)]
        return SimpleNamespace(status="member")

    async def get_chat_administrators(self, chat_id: int) -> list[SimpleNamespace]:
        return self.chat_administrators.get(chat_id, [])

    async def get_chat_member_count(self, chat_id: int) -> int:
        return self.member_counts.get(chat_id, 0)

    async def get_chat(self, chat_id: int) -> SimpleNamespace:
        if chat_id in self.chats:
            return self.chats[chat_id]
        raise RuntimeError("chat not found")

    async def export_chat_invite_link(self, chat_id: int) -> str:
        if chat_id in self.invite_links:
            return self.invite_links[chat_id]
        raise RuntimeError("invite link unavailable")

    async def leave_chat(self, chat_id: int) -> None:
        self.left_chats.append(chat_id)

    async def set_chat_menu_button(self, *, chat_id: int | None = None, menu_button: Any | None = None) -> bool:
        self.chat_menu_buttons.append({"chat_id": chat_id, "menu_button": menu_button or MenuButtonCommands()})
        return True

    async def set_my_commands(self, commands: list[Any], **_kwargs: Any) -> bool:
        self.my_commands = list(commands)
        return True

    async def approve_chat_join_request(self, chat_id: int, user_id: int) -> bool:
        self.approved_join_requests.append((chat_id, user_id))
        return True

    async def decline_chat_join_request(self, chat_id: int, user_id: int) -> bool:
        self.declined_join_requests.append((chat_id, user_id))
        return True

    async def __call__(self, method: Any) -> Any:
        """Handle aiogram method objects dispatched through bot(method) call pattern."""
        from aiogram.methods import ApproveChatJoinRequest, DeclineChatJoinRequest

        if isinstance(method, ApproveChatJoinRequest):
            return await self.approve_chat_join_request(method.chat_id, method.user_id)
        if isinstance(method, DeclineChatJoinRequest):
            return await self.decline_chat_join_request(method.chat_id, method.user_id)
        raise NotImplementedError(
            f"FakeTelegramBot does not support method type: {type(method).__name__}"
        )

    async def _close_session(self) -> None:
        return None


class FakeMessage:
    def __init__(
        self,
        *,
        chat_id: int,
        chat_type: str,
        user_id: int,
        text: str,
        message_id: int = 1,
        language_code: str = "en",
        username: str = "tester",
        full_name: str = "Test User",
        bot: FakeTelegramBot | None = None,
        caption: str | None = None,
        entities: list[Any] | None = None,
        caption_entities: list[Any] | None = None,
        new_chat_members: list[Any] | None = None,
    ) -> None:
        self.chat = SimpleNamespace(id=chat_id, type=chat_type, title=f"Chat-{chat_id}")
        self.from_user = SimpleNamespace(
            id=user_id,
            language_code=language_code,
            username=username,
            full_name=full_name,
        )
        self.text = text
        self.caption = caption
        self.entities = entities or []
        self.caption_entities = caption_entities or []
        self.new_chat_members = new_chat_members or []
        self.message_id = message_id
        self.bot = bot or FakeTelegramBot()
        self.log = BotCallLog()

    async def answer(self, text: str, reply_markup: Any | None = None) -> None:
        self.log.answers.append({"text": text, "reply_markup": reply_markup})

    async def edit_text(self, text: str, reply_markup: Any | None = None) -> None:
        self.log.edits.append({"text": text, "reply_markup": reply_markup})

    async def edit_reply_markup(self, reply_markup: Any | None = None) -> None:
        self.log.edit_markups.append({"reply_markup": reply_markup})

    async def delete(self) -> None:
        self.log.deletes.append({"chat_id": self.chat.id, "message_id": self.message_id})


class FakeCallbackQuery:
    def __init__(
        self,
        *,
        data: str,
        from_user_id: int,
        message: FakeMessage,
        language_code: str = "en",
    ) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=from_user_id, language_code=language_code)
        self.message = message
        self.bot = message.bot
        self.log = message.log

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.log.callback_answers.append({"text": text, "show_alert": show_alert})


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
def apply_migrations() -> Callable[[], None]:
    def _apply() -> None:
        cfg = Config("alembic.ini")
        database_url = os.environ["DATABASE_URL"].replace("+aiosqlite", "")
        cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(cfg, "head")

    return _apply


@pytest_asyncio.fixture
async def sync_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    await ensure_schema(engine)
    
    try:
        yield engine
    finally:
        await engine.dispose()
        if db_path.exists():
            db_path.unlink()


@pytest.fixture
def sync_session_maker(sync_engine) -> async_sessionmaker[AsyncSession]:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    return async_sessionmaker(bind=sync_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db_session(sync_session_maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sync_session_maker() as session:
        yield session


@pytest.fixture
def session_factory(sync_session_maker: sessionmaker[Session]) -> SessionContextFactory:
    return SessionContextFactory(sync_session_maker)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_bot() -> FakeTelegramBot:
    return FakeTelegramBot()


@pytest.fixture
def plugin_manager() -> PluginManager:
    return PluginManager()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def menu_engine() -> MenuEngine:
    return MenuEngine()


@pytest.fixture
def dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router())
    return dp


@pytest.fixture
def telegram_update_factory() -> Callable[..., Update]:
    def factory(
        *,
        text: str,
        user_id: int = 1001,
        chat_id: int = 9001,
        chat_type: str = "private",
        message_id: int = 1,
        language_code: str = "en",
    ) -> Update:
        return Update(
            update_id=message_id,
            message=Message(
                message_id=message_id,
                date=0,
                chat=Chat(id=chat_id, type=chat_type),
                from_user=User(
                    id=user_id,
                    is_bot=False,
                    first_name="Tester",
                    language_code=language_code,
                ),
                text=text,
            ),
        )

    return factory


@pytest.fixture
def callback_update_factory() -> Callable[..., Update]:
    def factory(
        *,
        data: str,
        user_id: int = 1001,
        chat_id: int = 9001,
        message_id: int = 1,
        language_code: str = "en",
    ) -> Update:
        msg = Message(
            message_id=message_id,
            date=0,
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Tester", language_code=language_code),
            text="inline",
        )
        return Update(
            update_id=message_id,
            callback_query=CallbackQuery(
                id=str(message_id),
                from_user=User(id=user_id, is_bot=False, first_name="Tester", language_code=language_code),
                chat_instance="ci",
                message=msg,
                data=data,
            ),
        )

    return factory


@pytest.fixture
def fsm_context_factory() -> Callable[..., FSMContext]:
    storage = MemoryStorage()

    def factory(bot_id: int = 42, chat_id: int = 9001, user_id: int = 1001) -> FSMContext:
        key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
        return FSMContext(storage=storage, key=key)

    return factory


@pytest_asyncio.fixture
async def patch_db_dependencies(monkeypatch: pytest.MonkeyPatch, session_factory: SessionContextFactory) -> None:
    from bot.dashboard.api import main as api_main
    from bot.dashboard.api import owner as owner_api
    from bot.handlers.commands import dashboard, moderation, register_group, start, subscribe
    from bot.handlers import fallback
    from bot.handlers.menu import reply_settings, settings
    from bot.plugins.anti_links import plugin as anti_links_plugin
    from bot.services import private_access_gate_service
    semantic_assistant_plugin = importlib.import_module("bot.plugins.semantic_assistant.plugin")

    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    monkeypatch.setattr(start, "SessionLocal", session_factory)
    monkeypatch.setattr(dashboard, "SessionLocal", session_factory)
    monkeypatch.setattr(subscribe, "SessionLocal", session_factory)
    monkeypatch.setattr(fallback, "SessionLocal", session_factory)
    monkeypatch.setattr(moderation, "SessionLocal", session_factory)
    monkeypatch.setattr(register_group, "SessionLocal", session_factory)
    monkeypatch.setattr(settings, "SessionLocal", session_factory)
    monkeypatch.setattr(reply_settings, "SessionLocal", session_factory)
    monkeypatch.setattr(anti_links_plugin, "SessionLocal", session_factory)
    monkeypatch.setattr(semantic_assistant_plugin, "SessionLocal", session_factory)
    monkeypatch.setattr(private_access_gate_service, "SessionLocal", session_factory)

    async def _override_get_session() -> AsyncIterator[AsyncSessionAdapter]:
        async with session_factory() as session:
            yield session

    dashboard_app.dependency_overrides[api_main.get_session] = _override_get_session
    dashboard_app.dependency_overrides[owner_api.get_session] = _override_get_session
    yield
    dashboard_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def patch_moderation_events_session(monkeypatch: pytest.MonkeyPatch, session_factory: SessionContextFactory) -> None:
    from bot.handlers.moderation import events
    from bot.services import private_access_gate_service

    monkeypatch.setattr(events, "SessionLocal", session_factory)
    monkeypatch.setattr(private_access_gate_service, "SessionLocal", session_factory)
    yield


@pytest_asyncio.fixture
async def seeded_group(db_session: AsyncSessionAdapter) -> dict[str, int]:
    user = UserModel(tg_user_id=1001, username="owner", full_name="Owner", language_code="ar")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10012345, title="QA Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupAdminRole(group_id=group.id, user_id=1001, role="owner"))
    await db_session.commit()
    return {"user_id": 1001, "group_id": group.id, "tg_group_id": group.tg_group_id}


@pytest.fixture
def fake_message_factory(fake_bot: FakeTelegramBot) -> Callable[..., FakeMessage]:
    def factory(**kwargs: Any) -> FakeMessage:
        bot = kwargs.pop("bot", fake_bot)
        return FakeMessage(bot=bot, **kwargs)

    return factory


@pytest.fixture
def fake_callback_factory() -> Callable[..., FakeCallbackQuery]:
    def factory(**kwargs: Any) -> FakeCallbackQuery:
        return FakeCallbackQuery(**kwargs)

    return factory


@pytest.fixture
def testcontainers_available() -> bool:
    try:
        import testcontainers  # noqa: F401

        return True
    except Exception:
        return False
