from __future__ import annotations

import httpx

import pytest

from bot.services.semantic_search_service import SemanticSearchService


@pytest.mark.asyncio
async def test_semantic_search_service_parses_nested_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "answer": "اهلا بك",
                        "score": 0.91,
                        "metadata": {"url": "https://example.com/faq"},
                    }
                ]
            },
        )

    service = SemanticSearchService(
        "https://semantic.example.com",
        transport=httpx.MockTransport(handler),
    )

    result = await service.search("مرحبا")

    assert result is not None
    assert result.text == "اهلا بك"
    assert result.score == 0.91
    assert result.url == "https://example.com/faq"


@pytest.mark.asyncio
async def test_semantic_search_service_returns_none_on_http_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    service = SemanticSearchService(
        "https://semantic.example.com",
        transport=httpx.MockTransport(handler),
    )

    result = await service.search("مرحبا")

    assert result is None
