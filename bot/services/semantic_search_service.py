from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class SemanticSearchResult:
    text: str
    title: str | None = None
    url: str | None = None
    score: float | None = None
    raw: dict[str, Any] | list[Any] | None = None


class SemanticSearchService:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        search_path: str = "/search",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.search_path = search_path if search_path.startswith("/") else f"/{search_path}"
        self.transport = transport

    async def search(
        self,
        query: str,
        *,
        service_name: str | None = None,
        resource_scope: str | None = None,
        top_k: int = 3,
    ) -> SemanticSearchResult | None:
        normalized_query = query.strip()
        if not normalized_query:
            return None

        payload: dict[str, Any] = {"query": normalized_query, "top_k": top_k}
        if service_name:
            payload["service"] = service_name
        if resource_scope:
            payload["resource_scope"] = resource_scope

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(f"{self.base_url}{self.search_path}", json=payload)
            if response.status_code >= 400:
                return None
            return self._parse_response(response.json())
        except Exception:
            return None

    def _parse_response(self, payload: Any) -> SemanticSearchResult | None:
        if isinstance(payload, dict):
            direct = self._result_from_mapping(payload, raw=payload)
            if direct is not None:
                return direct

            for key in ("result", "data"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    result = self._result_from_mapping(nested, raw=payload)
                    if result is not None:
                        return result

            for key in ("results", "matches", "items", "documents"):
                items = payload.get(key)
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        result = self._result_from_mapping(item, raw=payload)
                        if result is not None:
                            return result
        return None

    def _result_from_mapping(self, payload: dict[str, Any], *, raw: dict[str, Any]) -> SemanticSearchResult | None:
        text = self._first_string(
            payload,
            "answer",
            "response",
            "reply",
            "text",
            "content",
            "snippet",
            "summary",
            "description",
        )
        title = self._first_string(payload, "title", "name", "label")
        url = self._first_string(payload, "url", "link", "source_url", "href")
        metadata = payload.get("metadata")
        if url is None and isinstance(metadata, dict):
            url = self._first_string(metadata, "url", "link", "source_url", "href")
        if title is None and isinstance(metadata, dict):
            title = self._first_string(metadata, "title", "name", "label")
        score = self._first_float(payload, "score", "similarity", "distance")

        if not text:
            if title and url:
                text = f"{title}\n{url}"
            elif url:
                text = url
            else:
                return None

        return SemanticSearchResult(text=text, title=title, url=url, score=score, raw=raw)

    @staticmethod
    def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _first_float(payload: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None
