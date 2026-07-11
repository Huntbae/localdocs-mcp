"""임베딩 제공자 — Ollama HTTP API (선택적 구성요소).

Ollama가 없거나 죽어 있어도 시스템 전체가 멈추지 않는 것이 설계 원칙이다.
available()이 False면 인덱서는 임베딩을 건너뛰고, 검색은 BM25 단독으로
동작한다. 이후 Ollama를 켜고 `localdocs-mcp embed`를 실행하면 누락분만
채워진다.
"""
from __future__ import annotations

import httpx

from . import config


class OllamaEmbedder:
    def __init__(self, host: str | None = None, model: str | None = None):
        self.host = (host or config.OLLAMA_HOST).rstrip("/")
        self.model = model or config.EMBED_MODEL

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """빈 리스트 입력은 빈 리스트를 반환. 모델 미설치 등은 예외로 전파."""
        if not texts:
            return []
        r = httpx.post(
            f"{self.host}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=config.EMBED_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        embeddings = data.get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise RuntimeError(f"임베딩 응답 형식 오류: {list(data.keys())}")
        return embeddings

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
