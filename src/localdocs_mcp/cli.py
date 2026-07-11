"""CLI — 인덱싱/임베딩/검색/상태/서버 실행.

무거운 작업(대량 인덱싱, 임베딩 백필)은 MCP 서버가 아닌 CLI에서 수행하는
것이 기본 운영 방식이다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import config
from .embeddings import OllamaEmbedder
from .indexer import embed_pending, index_paths, prune_deleted
from .search import hybrid_search
from .store import Store


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="localdocs-mcp",
        description="로컬 문서 검색 MCP — 인덱서 및 서버",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="파일/폴더를 인덱싱하고 임베딩까지 수행")
    p_index.add_argument("paths", nargs="+", help="인덱싱할 파일 또는 폴더")
    p_index.add_argument("--force", action="store_true", help="변경 여부와 무관하게 재인덱싱")
    p_index.add_argument("--no-embed", action="store_true", help="임베딩 단계 생략(BM25만)")

    p_embed = sub.add_parser("embed", help="임베딩 누락 청크 백필(Ollama 필요)")

    p_search = sub.add_parser("search", help="인덱스 검색(동작 확인용)")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=8)
    p_search.add_argument("--path-prefix")
    p_search.add_argument("--suffix")

    sub.add_parser("status", help="인덱스 통계 출력")
    sub.add_parser("prune", help="삭제된 파일을 인덱스에서 제거")
    sub.add_parser("serve", help="MCP 서버 실행(stdio)")

    args = parser.parse_args(argv)
    config.ensure_app_dir()

    if args.command == "serve":
        from .server import run
        run()
        return 0

    store = Store(config.DB_PATH)
    try:
        if args.command == "index":
            report = index_paths(store, [Path(p) for p in args.paths],
                                 force=args.force)
            out = {"index": report.as_dict()}
            if not args.no_embed:
                out["embedding"] = embed_pending(store)
            _print(out)
            return 1 if report.errors and not report.indexed else 0
        if args.command == "embed":
            _print(embed_pending(store))
            return 0
        if args.command == "search":
            _print(hybrid_search(store, args.query, top_k=args.top_k,
                                 path_prefix=args.path_prefix,
                                 file_suffix=args.suffix))
            return 0
        if args.command == "status":
            stats = store.stats()
            stats["ollama_available"] = OllamaEmbedder().available()
            _print(stats)
            return 0
        if args.command == "prune":
            _print({"removed": prune_deleted(store)})
            return 0
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
