"""MCP 서버(stdio) — 검색·조회 중심의 얇은 계층.

대량 인덱싱은 CLI(`localdocs-mcp index`)로 분리했고, 서버에서는 소규모
경로 추가 인덱싱만 허용한다. stdio 전송만 사용하므로 네트워크에 노출되지
않는다(현행 MCP 스펙의 인증 공백 이슈 회피).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import config
from .embeddings import OllamaEmbedder
from .indexer import embed_pending, index_paths
from .search import hybrid_search
from .store import Store

mcp = FastMCP(
    "localdocs",
    instructions=(
        "사용자 로컬 문서(txt/pdf/docx/pptx/xlsx/hwp/hwpx/이미지) 검색 서버. "
        "내부 자료에 대한 질문을 받으면 먼저 search_documents로 근거 청크를 찾고, "
        "필요하면 get_chunk_context나 get_document로 문맥을 확장해 인용과 함께 "
        "답하라. 검색 결과의 file_path를 항상 출처로 명시할 것."
    ),
)

_store: Store | None = None


def _get_store() -> Store:
    global _store
    if _store is None:
        config.ensure_app_dir()
        _store = Store(config.DB_PATH)
    return _store


@mcp.tool()
def search_documents(
    query: str,
    top_k: int = 8,
    path_prefix: Optional[str] = None,
    file_suffix: Optional[str] = None,
) -> dict:
    """로컬 문서를 하이브리드(BM25+시맨틱) 검색한다.

    Args:
        query: 자연어 또는 키워드 질의 (한국어 지원)
        top_k: 반환할 청크 수 (기본 8)
        path_prefix: 이 경로로 시작하는 파일만 검색 (예: /Users/me/Documents)
        file_suffix: 파일 확장자 필터 (예: .hwp, .pdf)
    """
    result = hybrid_search(_get_store(), query, top_k=top_k,
                           path_prefix=path_prefix, file_suffix=file_suffix)
    stats = _get_store().stats()
    result["index_freshness"] = stats["last_indexed_at"]
    return result


@mcp.tool()
def get_chunk_context(chunk_id: int, neighbors: int = 1) -> dict:
    """검색으로 찾은 청크의 앞뒤 문맥(이웃 청크)을 함께 반환한다."""
    ctx = _get_store().get_chunk_with_neighbors(chunk_id, neighbors=neighbors)
    if ctx is None:
        return {"error": f"chunk_id {chunk_id} 없음"}
    return ctx


@mcp.tool()
def get_document(path: str, max_chars: int = 20000, offset: int = 0) -> dict:
    """인덱싱된 문서의 전체 텍스트를 반환한다(길면 offset으로 이어 읽기)."""
    text = _get_store().get_file_text(path)
    if text is None:
        return {"error": f"인덱스에 없는 파일: {path}. index_path로 먼저 인덱싱하세요."}
    total = len(text)
    piece = text[offset:offset + max_chars]
    return {
        "path": path,
        "total_chars": total,
        "offset": offset,
        "text": piece,
        "truncated": offset + max_chars < total,
    }


@mcp.tool()
def list_indexed_files(path_prefix: Optional[str] = None,
                       only_errors: bool = False, limit: int = 100) -> dict:
    """인덱싱된 파일 목록(실패 파일과 사유 포함)을 반환한다."""
    files = _get_store().list_files(
        prefix=path_prefix, status="error" if only_errors else None, limit=limit)
    return {"count": len(files), "files": files}


@mcp.tool()
def index_path(path: str) -> dict:
    """파일 또는 폴더를 (재)인덱싱한다. 대량 폴더는 CLI 사용을 권장."""
    store = _get_store()
    report = index_paths(store, [Path(path)])
    embed_result = embed_pending(store)
    return {"index": report.as_dict(), "embedding": embed_result}


@mcp.tool()
def index_status() -> dict:
    """인덱스 통계: 파일/청크/임베딩 수, 실패 파일 수, 마지막 인덱싱 시각, 검색 모드."""
    store = _get_store()
    stats = store.stats()
    embedder = OllamaEmbedder()
    stats["ollama_available"] = embedder.available()
    stats["embed_model"] = embedder.model
    stats["search_mode"] = "hybrid" if (
        stats["chunks_embedded"] > 0 and stats["ollama_available"]) else "bm25-only"
    return stats


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
