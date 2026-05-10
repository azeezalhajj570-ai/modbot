from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class ClassificationResult:
    label: str
    score: float
    reason: str


class AIProviderError(RuntimeError):
    pass


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini") -> None:
        self.api_key = api_key
        self.model = model

    async def classify(self, text: str) -> ClassificationResult:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Classify text as one of: spam, scam, promotional, clean. Return JSON keys:"
                        " label, score(0..1), reason."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "text": {"format": {"type": "json_object"}},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"openai_http_{response.status_code}")
        data = response.json()
        # API response shape may vary by model; this parses the common json-text output path.
        output = data.get("output", [])
        if not output:
            raise AIProviderError("openai_empty_output")
        content = output[0].get("content", [])
        if not content:
            raise AIProviderError("openai_missing_content")
        parsed = content[0].get("parsed") or content[0].get("text")
        if isinstance(parsed, str):
            import json

            parsed = json.loads(parsed)
        return ClassificationResult(
            label=parsed.get("label", "clean"),
            score=float(parsed.get("score", 0.1)),
            reason=parsed.get("reason", "model_response"),
        )


class GeminiProvider:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self.api_key = api_key
        self.model = model

    async def classify(self, text: str) -> ClassificationResult:
        prompt = (
            "Classify the message as spam, scam, promotional, or clean. "
            "Return JSON with label, score(0..1), reason only.\n\n"
            f"message: {text}"
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"gemini_http_{response.status_code}")
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise AIProviderError("gemini_empty_output")
        text_out = candidates[0]["content"]["parts"][0].get("text", "{}")
        import json

        parsed = json.loads(text_out)
        return ClassificationResult(
            label=parsed.get("label", "clean"),
            score=float(parsed.get("score", 0.1)),
            reason=parsed.get("reason", "model_response"),
        )
