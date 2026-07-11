"""하이브리드 검색 — BM25(FTS5) + 벡터 코사인, RRF(Reciprocal Rank Fusion) 병합.

시맨틱 검색만으로는 고유명사/파일명/코드 검색이 약하고, 키워드만으로는
의미 질의가 약하다. 두 순위를 RRF로 합쳐 안정적인 상위권을 만든다.
임베딩이 없는 환경에서는 자동으로 BM25 단독 모드로 동작한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .embeddings import OllamaEmbedder
from .store import ChunkHit, Store

RRF_K = 60


@dataclass
class SearchResult:
    chunk_id: int
    file_path: str
    seq: int
    snippet: str
    meta: dict
    score: float
    matched_by: list[str] = field(default_factory=list)


def _rrf_merge(ranked_lists: dict[str, list[ChunkHit]], top_k: int) -> list[SearchResult]:
    scores: dict[int, float] = {}
    sources: dict[int, list[str]] = {}
    hits: dict[int, ChunkHit] = {}
    for source, ranked in ranked_lists.items():
        for rank, hit in enumerate(ranked):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            sources.setdefault(hit.chunk_id, []).append(source)
            hits.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
    results = []
    for cid, score in ordered:
        h = hits[cid]
        results.append(SearchResult(
            chunk_id=cid, file_path=h.file_path, seq=h.seq,
            snippet=h.text[:600], meta=h.meta, score=round(score, 5),
            matched_by=sources[cid],
        ))
    return results


def hybrid_search(
    store: Store,
    query: str,
    top_k: int = 8,
    path_prefix: Optional[str] = None,
    file_suffix: Optional[str] = None,
    embedder: Optional[OllamaEmbedder] = None,
    candidates: int = 50,
) -> dict:
    ranked: dict[str, list[ChunkHit]] = {}
    ranked["bm25"] = store.search_fts(query, limit=candidates)

    mode = "bm25-only"
    embedder = embedder or OllamaEmbedder()
    if embedder.available():
        try:
            qvec = embedder.embed_one(query)
            vec_hits = store.search_vector(qvec, limit=candidates)
            if vec_hits:
                ranked["vector"] = vec_hits
                mode = "hybrid"
        except Exception:
            mode = "bm25-only(vector-error)"

    def _keep(h: ChunkHit) -> bool:
        if path_prefix and not h.file_path.startswith(path_prefix):
            return False
        if file_suffix and not h.file_path.lower().endswith(file_suffix.lower()):
            return False
        return True

    ranked = {k: [h for h in v if _keep(h)] for k, v in ranked.items()}
    results = _rrf_merge(ranked, top_k)
    return {
        "mode": mode,
        "query": query,
        "results": [r.__dict__ for r in results],
    }
