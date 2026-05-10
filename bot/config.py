from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppKind = Literal["admin", "agents"]


class DashboardBrowserUser(BaseModel):
    email: str
    password: str
    user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token_raw: str | None = Field(default=None, alias="BOT_TOKEN")
    bot_app_kind: AppKind = Field(default="admin", alias="BOT_APP_KIND")
    admin_bot_token: str | None = Field(default=None, alias="ADMIN_BOT_TOKEN")
    agents_bot_token: str | None = Field(default=None, alias="AGENTS_BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_app_url: str | None = Field(default=None, alias="OPENROUTER_APP_URL")
    openrouter_app_title: str = Field(default="Combot", alias="OPENROUTER_APP_TITLE")
    ai_provider: str = Field(default="heuristic", alias="AI_PROVIDER")
    ai_spam_detection_enabled: bool = Field(default=False, alias="AI_SPAM_DETECTION_ENABLED")
    ai_receptionist_enabled: bool = Field(default=False, alias="AI_RECEPTIONIST_ENABLED")
    ai_model: str | None = Field(default=None, alias="AI_MODEL")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_model_premium: str = Field(default="gpt-4.1", alias="OPENAI_MODEL_PREMIUM")
    openai_model_bulk: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL_BULK")
    gemini_model: str = Field(default="gemini-1.5-flash", alias="GEMINI_MODEL")
    gemini_model_premium: str = Field(default="gemini-1.5-pro", alias="GEMINI_MODEL_PREMIUM")
    openrouter_model: str = Field(default="google/gemini-2.0-flash-001", alias="OPENROUTER_MODEL")
    openrouter_model_bulk: str = Field(default="google/gemini-2.0-flash-001", alias="OPENROUTER_MODEL_BULK")
    openrouter_model_premium: str = Field(default="openai/gpt-4.1", alias="OPENROUTER_MODEL_PREMIUM")
    knowledge_extraction_enabled: bool = Field(default=False, alias="KNOWLEDGE_EXTRACTION_ENABLED")
    daily_summary_enabled: bool = Field(default=False, alias="DAILY_SUMMARY_ENABLED")
    ai_extraction_chunk_size: int = Field(default=8000, alias="AI_EXTRACTION_CHUNK_SIZE")
    ai_extraction_stagger_seconds: float = Field(default=1.5, alias="AI_EXTRACTION_STAGGER_SECONDS")
    ai_auto_send_default: bool = Field(default=False, alias="AI_AUTO_SEND_DEFAULT")
    ai_request_timeout_seconds: float = Field(default=30.0, alias="AI_REQUEST_TIMEOUT_SECONDS")
    dashboard_url: str | None = Field(default=None, alias="DASHBOARD_URL")
    webapp_url: str | None = Field(default=None, alias="WEBAPP_URL")
    admin_webapp_url: str | None = Field(default=None, alias="ADMIN_WEBAPP_URL")
    agents_webapp_url: str | None = Field(default=None, alias="AGENTS_WEBAPP_URL")
    telegram_api_id: int | None = Field(default=None, alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, alias="TELEGRAM_API_HASH")
    telegram_webapp_auth_max_age_seconds: int = Field(default=86_400, alias="TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS")
    dashboard_jwt_secret: str | None = Field(default=None, alias="DASHBOARD_JWT_SECRET")
    dashboard_jwt_exp_seconds: int = Field(default=3600, alias="DASHBOARD_JWT_EXP_SECONDS")
    telegram_login_bot_username: str | None = Field(default=None, alias="TELEGRAM_LOGIN_BOT_USERNAME")
    dashboard_browser_users_raw: str = Field(default="", alias="DASHBOARD_BROWSER_USERS")
    ads_classifier_url: str | None = Field(default=None, alias="ADS_CLASSIFIER_URL")
    ads_classifier_timeout: float = Field(default=3.0, alias="ADS_CLASSIFIER_TIMEOUT")
    ads_classifier_threshold: float = Field(default=0.8, alias="ADS_CLASSIFIER_THRESHOLD")
    semantic_search_url: str | None = Field(default=None, alias="SEMANTIC_SEARCH_URL")
    semantic_search_path: str = Field(default="/search", alias="SEMANTIC_SEARCH_PATH")
    semantic_search_timeout: float = Field(default=5.0, alias="SEMANTIC_SEARCH_TIMEOUT")
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    default_language: str = Field(default="ar", alias="DEFAULT_LANGUAGE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    aiogram_log_level: str = Field(default="WARNING", alias="AIROGRAM_LOG_LEVEL")
    log_raw_updates: bool = Field(default=False, alias="LOG_RAW_UPDATES")
    log_agent_listener_messages: bool = Field(default=False, alias="LOG_AGENT_LISTENER_MESSAGES")
    faq_auto_answer_enabled: bool = Field(default=False, alias="FAQ_AUTO_ANSWER_ENABLED")
    telegram_polling_timeout: int = Field(default=30, alias="TELEGRAM_POLLING_TIMEOUT")
    telegram_request_timeout: float = Field(default=90.0, alias="TELEGRAM_REQUEST_TIMEOUT")
    run_schema_bootstrap: bool = Field(default=False, alias="RUN_SCHEMA_BOOTSTRAP")
    session_encryption_key: str | None = Field(default=None, alias="SESSION_ENCRYPTION_KEY")
    stripe_api_key: str | None = Field(default=None, alias="STRIPE_API_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: str | None = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    bot_owner_ids_raw: str = Field(default="", alias="BOT_OWNER_IDS")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_requests_per_minute: int = Field(default=100, alias="RATE_LIMIT_REQUESTS_PER_MINUTE")
    rate_limit_burst: int = Field(default=25, alias="RATE_LIMIT_BURST")
    automation_rate_limit_per_group_minute: int = Field(default=10, alias="AUTOMATION_RATE_LIMIT_PER_GROUP_MINUTE")

    FREE_PLAN_LIMITS: dict[str, int] = {
        "max_groups": 5,
        "max_scheduled_messages": 5,
        "max_automation_tasks": 5,
        "max_moderation_actions_per_day": 200,
    }

    @field_validator(
        "dashboard_url",
        "webapp_url",
        "admin_webapp_url",
        "agents_webapp_url",
        "ads_classifier_url",
        "semantic_search_url",
        mode="before",
    )
    @classmethod
    def _strip_url_prefix(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip().lstrip("=").strip()

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def _blank_telegram_api_id_to_none(cls, value):
        if value in {"", None}:
            return None
        return value

    @field_validator("bot_app_kind", mode="before")
    @classmethod
    def _normalize_bot_app_kind(cls, value):
        normalized = str(value or "admin").strip().lower()
        if normalized not in {"admin", "agents"}:
            raise ValueError("BOT_APP_KIND must be either 'admin' or 'agents'")
        return normalized

    @property
    def bot_token(self) -> str:
        return self.resolve_bot_token()

    def resolve_bot_token(self, app_kind: AppKind | None = None) -> str:
        target_kind = app_kind or self.bot_app_kind
        if target_kind == "admin":
            token = self.admin_bot_token or self.bot_token_raw
        else:
            token = self.agents_bot_token or self.bot_token_raw
        if not token:
            raise ValueError(f"Missing bot token for app kind '{target_kind}'")
        return token

    def resolve_webapp_url(self, app_kind: AppKind | None = None) -> str | None:
        target_kind = app_kind or self.bot_app_kind
        if target_kind == "admin":
            return self.admin_webapp_url or self.webapp_url or self.dashboard_url
        return self.agents_webapp_url or self.webapp_url or self.dashboard_url

    def all_bot_tokens(self) -> tuple[str, ...]:
        values = [self.admin_bot_token, self.agents_bot_token, self.bot_token_raw]
        unique: list[str] = []
        for value in values:
            token = str(value or "").strip()
            if token and token not in unique:
                unique.append(token)
        return tuple(unique)

    @property
    def bot_owner_ids(self) -> set[int]:
        values: set[int] = set()
        for chunk in self.bot_owner_ids_raw.split(","):
            value = chunk.strip()
            if not value:
                continue
            try:
                values.add(int(value))
            except ValueError:
                continue
        return values

    @property
    def dashboard_browser_users(self) -> list[DashboardBrowserUser]:
        raw = self.dashboard_browser_users_raw.strip()
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        users: list[DashboardBrowserUser] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                users.append(DashboardBrowserUser.model_validate(item))
            except Exception:
                continue
        return users


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
