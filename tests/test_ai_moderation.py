from __future__ import annotations

import pytest

from bot.ai.moderation import AIClassifier, ModerationDecision, ModerationPipeline, RuleEngine
from bot.ai.providers import AIProviderError, ClassificationResult


class FailingProvider:
    async def classify(self, _text: str) -> ClassificationResult:
        raise AIProviderError("provider_down")


class StaticProvider:
    def __init__(self, result: ClassificationResult) -> None:
        self.result = result

    async def classify(self, _text: str) -> ClassificationResult:
        return self.result


@pytest.mark.asyncio
async def test_pipeline_deletes_clear_spam_pattern() -> None:
    pipeline = ModerationPipeline(rule_engine=RuleEngine(), classifier=AIClassifier(provider_name="heuristic"))
    result = await pipeline.process("free money airdrop now")
    assert result.decision == ModerationDecision.DELETE


@pytest.mark.asyncio
async def test_pipeline_warns_on_link_with_heuristic() -> None:
    pipeline = ModerationPipeline(rule_engine=RuleEngine(), classifier=AIClassifier(provider_name="heuristic"))
    result = await pipeline.process("check https://site.example")
    assert result.decision == ModerationDecision.WARN


@pytest.mark.asyncio
async def test_pipeline_allows_normal_message() -> None:
    pipeline = ModerationPipeline(rule_engine=RuleEngine(), classifier=AIClassifier(provider_name="heuristic"))
    result = await pipeline.process("hello team, this is normal")
    assert result.decision == ModerationDecision.ALLOW


@pytest.mark.asyncio
async def test_ai_provider_failure_falls_back_to_heuristic() -> None:
    classifier = AIClassifier(openai_provider=FailingProvider(), provider_name="openai")
    result = await classifier.classify("promo offer")
    assert result.decision == ModerationDecision.WARN


@pytest.mark.asyncio
async def test_ai_provider_response_mapping() -> None:
    classifier = AIClassifier(
        openai_provider=StaticProvider(ClassificationResult(label="spam", score=0.91, reason="model_spam")),
        provider_name="openai",
    )
    result = await classifier.classify("random")
    assert result.decision == ModerationDecision.DELETE
    assert result.score == 0.91
