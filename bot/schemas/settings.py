from __future__ import annotations

from strenum import StrEnum

from pydantic import BaseModel, Field


class SettingType(StrEnum):
    TOGGLE = "toggle"
    NUMBER = "number"
    TEXT = "text"


class SettingSchema(BaseModel):
    key: str
    type: SettingType
    category: str
    label_key: str
    min: int | None = None
    max: int | None = None
    default: bool | int | str | None = None


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    categories: list[str] = Field(default_factory=list)


class CategorySchema(BaseModel):
    key: str
    label_key: str
