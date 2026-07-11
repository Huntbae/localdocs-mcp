"""증분 인덱서.

mtime+size가 바뀐 파일만 다시 처리하고, 추출 실패는 files.status='error'로
기록해 status()에서 확인할 수 있게 한다(침묵 실패 금지). 임베딩은 인덱싱과
분리된 단계라 Ollama가 없어도 인덱싱 자체는 완료된다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .chunker import chunk_segments
from .embeddings import OllamaEmbedder
from .extractors import get_extractor
from .store import Store

log = logging.getLogger("localdocs.indexer")


@dataclass
class IndexReport:
    indexed: int = 0
    unchanged: int = 0
    errors: int = 0
    skipped: int = 0
    error_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "skipped": self.skipped,
            "error_files": self.error_files[:50],
        }


def iter_indexable(root: Path):
    if root.is_file():
        if root.suffix.lower() in config.INDEXABLE_SUFFIXES:
            yield root
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in config.SKIP_DIR_NAMES or part.startswith(".")
               for part in p.relative_to(root).parts[:-1]):
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() in config.INDEXABLE_SUFFIXES:
            yield p


def index_file(store: Store, path: Path, force: bool = False) -> str:
    """단일 파일 인덱싱. 반환: indexed | unchanged | error | skipped."""
    stat = path.stat()
    if stat.st_size > config.MAX_FILE_MB * 1024 * 1024:
        store.replace_file(str(path), stat.st_mtime, stat.st_size, [],
                           extractor="none", status="skipped",
                           error=f"파일이 {config.MAX_FILE_MB}MB 제한을 초과")
        return "skipped"
    if not force and not store.file_needs_update(str(path), stat.st_mtime, stat.st_size):
        return "unchanged"
    ext = get_extractor(path)
    if ext is None:
        return "skipped"
    name, fn = ext
    try:
        segments = fn(path)
        chunks = chunk_segments(segments)
        store.replace_file(str(path), stat.st_mtime, stat.st_size, chunks,
                           extractor=name)
        return "indexed"
    except Exception as e:  # 실패를 기록하고 다음 파일로 진행
        log.warning("추출 실패 %s: %s", path, e)
        store.replace_file(str(path), stat.st_mtime, stat.st_size, [],
                           extractor=name, status="error", error=str(e)[:500])
        return "error"


def index_paths(store: Store, roots: list[Path], force: bool = False) -> IndexReport:
    report = IndexReport()
    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            report.errors += 1
            report.error_files.append(f"{root} (존재하지 않음)")
            continue
        for path in iter_indexable(root):
            result = index_file(store, path, force=force)
            if result == "indexed":
                report.indexed += 1
            elif result == "unchanged":
                report.unchanged += 1
            elif result == "error":
                report.errors += 1
                report.error_files.append(str(path))
            else:
                report.skipped += 1
    prune_deleted(store)
    return report


def prune_deleted(store: Store) -> int:
    """디스크에서 사라진 파일을 인덱스에서 제거."""
    removed = 0
    for row in store.list_files(limit=1_000_000):
        if not Path(row["path"]).exists():
            store.delete_file(row["path"])
            removed += 1
    return removed


def embed_pending(store: Store, embedder: OllamaEmbedder | None = None,
                  batch: int | None = None) -> dict:
    """임베딩이 없는 청크를 배치로 채운다. Ollama 미가용 시 명확히 보고."""
    embedder = embedder or OllamaEmbedder()
    batch = batch or config.EMBED_BATCH
    if not embedder.available():
        return {"embedded": 0, "pending": len(store.chunks_without_embedding(10**9)),
                "error": f"Ollama({embedder.host}) 미가용 — BM25 검색만 동작"}
    done = 0
    while True:
        rows = store.chunks_without_embedding(limit=batch)
        if not rows:
            break
        ids = [cid for cid, _ in rows]
        texts = [t[:8000] for _, t in rows]
        vectors = embedder.embed(texts)
        store.add_embeddings(zip(ids, vectors))
        done += len(ids)
    store.set_meta("embed_model", embedder.model)
    return {"embedded": done, "pending": 0, "model": embedder.model}
