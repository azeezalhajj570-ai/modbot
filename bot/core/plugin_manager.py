from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType
from typing import Protocol

from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.event_bus import EventBus
from bot.schemas.settings import PluginManifest, SettingSchema
from bot.services.plugin_service import PluginService


class PluginProtocol(Protocol):
    manifest: PluginManifest
    settings_schema: list[SettingSchema]

    async def setup(self, dispatcher: Dispatcher, event_bus: EventBus) -> None: ...
    async def teardown(self, dispatcher: Dispatcher, event_bus: EventBus) -> None: ...


@dataclass
class LoadedPlugin:
    name: str
    module: ModuleType
    instance: PluginProtocol


class PluginManager:
    def __init__(self, plugins_package: str = "bot.plugins") -> None:
        self.plugins_package = plugins_package
        self._loaded: dict[str, LoadedPlugin] = {}

    def discover(self) -> list[str]:
        package = importlib.import_module(self.plugins_package)
        return [
            f"{self.plugins_package}.{name}.plugin"
            for _, name, ispkg in pkgutil.iter_modules(package.__path__)
            if ispkg
        ]

    async def load_all(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        for module_name in self.discover():
            await self.load_plugin(module_name, dispatcher, event_bus)

    async def load_plugin(self, module_name: str, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        if module_name in self._loaded:
            return
        module = importlib.import_module(module_name)
        plugin: PluginProtocol = getattr(module, "plugin")
        await plugin.setup(dispatcher, event_bus)
        self._loaded[module_name] = LoadedPlugin(
            name=plugin.manifest.name,
            module=module,
            instance=plugin,
        )

    async def unload_plugin(self, module_name: str, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        loaded = self._loaded.get(module_name)
        if not loaded:
            return
        await loaded.instance.teardown(dispatcher, event_bus)
        self._loaded.pop(module_name, None)

    async def reload_plugin(self, module_name: str, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        loaded = self._loaded.get(module_name)
        if loaded:
            await loaded.instance.teardown(dispatcher, event_bus)
            reloaded_module = importlib.reload(loaded.module)
            plugin: PluginProtocol = getattr(reloaded_module, "plugin")
            await plugin.setup(dispatcher, event_bus)
            self._loaded[module_name] = LoadedPlugin(
                name=plugin.manifest.name,
                module=reloaded_module,
                instance=plugin,
            )
            return
        await self.load_plugin(module_name, dispatcher, event_bus)

    def get_settings_schema(self) -> dict[str, SettingSchema]:
        merged: dict[str, SettingSchema] = {}
        for loaded in self._loaded.values():
            for setting in loaded.instance.settings_schema:
                merged[setting.key] = setting
        return merged

    def loaded_plugins(self) -> list[LoadedPlugin]:
        return list(self._loaded.values())

    async def enable_for_group(self, session: AsyncSession, group_id: int, plugin_name: str) -> None:
        await PluginService(session).set_enabled(group_id, plugin_name, True)

    async def disable_for_group(self, session: AsyncSession, group_id: int, plugin_name: str) -> None:
        await PluginService(session).set_enabled(group_id, plugin_name, False)

    def discover_schema_catalog(self) -> dict[str, list[SettingSchema]]:
        catalog: dict[str, list[SettingSchema]] = {}
        for module_name in self.discover():
            module = importlib.import_module(module_name)
            plugin: PluginProtocol = getattr(module, "plugin")
            catalog[plugin.manifest.name] = list(plugin.settings_schema)
        return catalog
