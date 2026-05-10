from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class AdsClassification:
    label: str
    ad_score: float


class AdsClassifierService:
    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def classify(self, text: str) -> AdsClassification | None:
        if not text.strip():
            return None
        payload = {"text": text}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/classify", json=payload)
            if response.status_code >= 400:
                return None
            data = response.json()
            label = str(data.get("label", "not_ad"))
            score = float(data.get("ad_score", 0.0))
            return AdsClassification(label=label, ad_score=score)
        except Exception:
            return None
