from __future__ import annotations

from math import ceil
from typing import Generic, TypeVar

T = TypeVar("T")


class Page(Generic[T]):
    def __init__(self, items: list[T], page: int, page_size: int, total: int) -> None:
        self.items = items
        self.page = page
        self.page_size = page_size
        self.total = total

    @property
    def pages(self) -> int:
        return max(1, ceil(self.total / self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def paginate(items: list[T], page: int, page_size: int) -> Page[T]:
    normalized = max(1, page)
    start = (normalized - 1) * page_size
    end = start + page_size
    return Page(items=items[start:end], page=normalized, page_size=page_size, total=len(items))
