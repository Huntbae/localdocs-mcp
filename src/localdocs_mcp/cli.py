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
from .indexer import embed_pending, index_paths, prune_deleted, retry_errors
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
    grp = p_index.add_mutually_exclusive_group()
    grp.add_argument("--no-images", action="store_true",
                     help="이미지(OCR) 제외, 문서만 인덱싱 — 빠름")
    grp.add_argument("--only-images", action="store_true",
                     help="이미지(OCR)만 인덱싱 — 문서 인덱싱 후 별도 실행용")
    grp.add_argument("--only-ext", nargs="+", metavar="EXT",
                     help="지정 확장자만 인덱싱 (예: --only-ext .hwp .pdf)")
    p_index.add_argument("--skip-ext", nargs="+", metavar="EXT",
                         help="지정 확장자 제외 (예: --skip-ext .xlsx)")
    p_index.add_argument("--exclude", nargs="+", metavar="STR",
                         help="경로에 이 문자열이 포함된 파일/폴더 제외 "
                              "(예: --exclude legalize-data node_modules)")

    p_embed = sub.add_parser("embed", help="임베딩 누락 청크 백필(Ollama 필요)")

    p_search = sub.add_parser("search", help="인덱스 검색(동작 확인용)")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=8)
    p_search.add_argument("--path-prefix")
    p_search.add_argument("--suffix")

    p_gd = sub.add_parser("gdrive-recover",
                          help="rclone로 Google Drive에서 실패 파일을 자립형 복구(세션 한도 무관)")
    p_gd.add_argument("--remote", required=True,
                      help="rclone 원격 (예: gdrive:) — '내 드라이브' 루트를 가리켜야 함")
    p_gd.add_argument("--local-root", required=True,
                      help="원격 루트에 대응하는 로컬 마운트 경로 (예: '.../GoogleDrive-<메일>/내 드라이브')")
    p_gd.add_argument("--timeout", type=float, default=300.0, help="파일당 다운로드 제한(초)")
    p_gd.add_argument("--no-embed", action="store_true", help="임베딩 단계 생략")

    sub.add_parser("status", help="인덱스 통계 출력")
    sub.add_parser("prune", help="삭제된 파일을 인덱스에서 제거")
    sub.add_parser("retry-errors", help="실패(error) 파일만 재인덱싱")
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
            only = skip = None
            if args.only_images:
                only = set(config.IMAGE_SUFFIXES)
            elif args.only_ext:
                only = {e if e.startswith(".") else f".{e}" for e in args.only_ext}
            if args.no_images:
                skip = set(config.IMAGE_SUFFIXES)
            if args.skip_ext:
                s = {e if e.startswith(".") else f".{e}" for e in args.skip_ext}
                skip = (skip or set()) | s
            report = index_paths(store, [Path(p) for p in args.paths],
                                 force=args.force, only=only, skip=skip,
                                 exclude=args.exclude)
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
        if args.command == "retry-errors":
            _print(retry_errors(store).as_dict())
            return 0
        if args.command == "gdrive-recover":
            from .gdrive import recover_errors, rclone_available, remote_ok
            if not rclone_available():
                _print({"error": "rclone 미설치 — 'brew install rclone' 후 'rclone config'로 "
                                  "Google Drive 원격을 설정하세요."})
                return 1
            if not remote_ok(args.remote):
                _print({"error": f"원격 '{args.remote}' 접근 불가 — 'rclone config'로 인증했는지, "
                                 f"원격 이름이 맞는지 확인하세요."})
                return 1
            report = recover_errors(store, args.remote, args.local_root, timeout=args.timeout)
            out = {"gdrive_recover": report.as_dict()}
            if not args.no_embed:
                out["embedding"] = embed_pending(store)
            _print(out)
            return 0
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
