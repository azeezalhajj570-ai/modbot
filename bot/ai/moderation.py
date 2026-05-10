from __future__ import annotations

from dataclasses import dataclass
from strenum import StrEnum

from bot.ai.providers import AIProviderError, ClassificationResult, GeminiProvider, OpenAIProvider
from bot.config import get_settings


class ModerationDecision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    DELETE = "delete"


@dataclass
class ModerationResult:
    decision: ModerationDecision
    score: float
    reason: str


class RuleEngine:
    def evaluate(self, text: str) -> ModerationResult | None:
        lowered = text.lower()
        if "free money" in lowered or "airdrop" in lowered:
            return ModerationResult(ModerationDecision.DELETE, 0.95, "scam_pattern")
        if "http://" in lowered or "https://" in lowered:
            return ModerationResult(ModerationDecision.WARN, 0.7, "link_detected")
        return None


class AIClassifier:
    def __init__(
        self,
        openai_provider: OpenAIProvider | None = None,
        gemini_provider: GeminiProvider | None = None,
        provider_name: str = "heuristic",
    ) -> None:
        self.openai_provider = openai_provider
        self.gemini_provider = gemini_provider
        self.provider_name = provider_name

    def _heuristic(self, text: str) -> ModerationResult:
        lowered = text.lower()
        if any(term in lowered for term in ("guaranteed profit", "x100", "dm for signals")):
            return ModerationResult(ModerationDecision.DELETE, 0.9, "promotional_spam")
        if "promo" in lowered:
            return ModerationResult(ModerationDecision.WARN, 0.6, "promotional_content")
        return ModerationResult(ModerationDecision.ALLOW, 0.1, "clean")

    @staticmethod
    def _to_result(result: ClassificationResult) -> ModerationResult:
        label = result.label.lower()
        if label in {"scam", "spam"} and result.score >= 0.8:
            return ModerationResult(ModerationDecision.DELETE, result.score, result.reason)
        if label in {"promotional", "spam"} and result.score >= 0.5:
            return ModerationResult(ModerationDecision.WARN, result.score, result.reason)
        return ModerationResult(ModerationDecision.ALLOW, result.score, result.reason)

    async def classify(self, text: str) -> ModerationResult:
        try:
            if self.provider_name == "openai" and self.openai_provider:
                return self._to_result(await self.openai_provider.classify(text))
            if self.provider_name == "gemini" and self.gemini_provider:
                return self._to_result(await self.gemini_provider.classify(text))
        except AIProviderError:
            return self._heuristic(text)
        return self._heuristic(text)


class ModerationPipeline:
    def __init__(self, rule_engine: RuleEngine, classifier: AIClassifier) -> None:
        self.rule_engine = rule_engine
        self.classifier = classifier

    async def process(self, text: str) -> ModerationResult:
        rule_result = self.rule_engine.evaluate(text)
        if rule_result and rule_result.score >= 0.85:
            return rule_result
        model_result = await self.classifier.classify(text)
        if rule_result and model_result.decision == ModerationDecision.ALLOW:
            return rule_result
        return model_result


def build_default_pipeline() -> ModerationPipeline:
    settings = get_settings()
    openai = (
        OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
        if settings.openai_api_key
        else None
    )
    gemini = (
        GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
        if settings.gemini_api_key
        else None
    )
    classifier = AIClassifier(openai_provider=openai, gemini_provider=gemini, provider_name=settings.ai_provider)
    return ModerationPipeline(rule_engine=RuleEngine(), classifier=classifier)
