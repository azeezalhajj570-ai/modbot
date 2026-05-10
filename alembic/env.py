from __future__ import annotations

import asyncio
from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from bot.config import get_settings
from bot.db.base import Base
from bot.db import models  # noqa: F401

config = context.config


def _resolve_sqlalchemy_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    env_database_url = os.getenv("DATABASE_URL")
    if env_database_url and configured_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/combot":
        return env_database_url
    return configured_url


sqlalchemy_url = _resolve_sqlalchemy_url()
config.set_main_option("sqlalchemy.url", sqlalchemy_url)
config.set_section_option(config.config_ini_section, "sqlalchemy.url", sqlalchemy_url)
settings = get_settings()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online_sync() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    url = config.get_main_option("sqlalchemy.url")
    if any(driver in url for driver in ("+asyncpg", "+aiosqlite")):
        asyncio.run(run_migrations_online())
    else:
        run_migrations_online_sync()
