"""증분 인덱서.

mtime+size가 바뀐 파일만 다시 처리하고, 추출 실패는 files.status='error'로
기록해 status()에서 확인할 수 있게 한다(침묵 실패 금지). 임베딩은 인덱싱과
분리된 단계라 Ollama가 없어도 인덱싱 자체는 완료된다.
"""
from __future__ import annotations

import logging
import os
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


def _allowed_suffixes(only: set[str] | None, skip: set[str] | None) -> set[str]:
    suffixes = set(config.INDEXABLE_SUFFIXES)
    if only:
        suffixes &= {s.lower() for s in only}
    if skip:
        suffixes -= {s.lower() for s in skip}
    return suffixes


def iter_indexable(root: Path, only: set[str] | None = None,
                   skip: set[str] | None = None,
                   exclude: list[str] | None = None):
    """인덱싱 대상 파일을 디렉터리 단위로 점진적으로 내보낸다.

    os.walk로 순회하며 제외 대상 폴더는 진입 전에 가지치기한다. 전체 목록을
    한 번에 만들지 않으므로(rglob+sort 회피) 대용량 트리·네트워크 마운트(예:
    구글 드라이브 스트리밍)에서도 첫 디렉터리부터 즉시 인덱싱이 시작되고
    메모리 사용이 일정하게 유지된다. only/skip으로 확장자를 제한해 문서와
    이미지(OCR)를 분리된 단계로 인덱싱할 수 있다. exclude는 경로에 해당
    문자열이 포함된 파일/폴더를 통째로 건너뛴다(예: 별도로 관리하는 대형
    데이터셋 폴더를 개인 인덱스에서 제외).
    """
    allowed = _allowed_suffixes(only, skip)
    exclude = exclude or []

    def is_excluded(p: str) -> bool:
        return any(x in p for x in exclude)

    if root.is_file():
        if root.suffix.lower() in allowed and not is_excluded(str(root)):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        if is_excluded(dirpath):
            dirnames[:] = []  # 제외 폴더는 하위로 진입하지 않음
            continue
        # 하위 순회 전에 제외 폴더를 가지치기(dotdir, node_modules, exclude 등)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in config.SKIP_DIR_NAMES and not d.startswith(".")
            and not is_excluded(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            # dotfile 및 오피스 임시/잠금 파일(~$...) 제외
            if name.startswith(".") or name.startswith("~$"):
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() in allowed and not is_excluded(str(p)):
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


def index_paths(store: Store, roots: list[Path], force: bool = False,
                progress_every: int = 25, only: set[str] | None = None,
                skip: set[str] | None = None,
                exclude: list[str] | None = None) -> IndexReport:
    report = IndexReport()
    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            report.errors += 1
            report.error_files.append(f"{root} (존재하지 않음)")
            continue
        for path in iter_indexable(root, only=only, skip=skip, exclude=exclude):
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
            seen = report.indexed + report.unchanged + report.errors + report.skipped
            if progress_every and seen % progress_every == 0:
                log.info("진행: %d개 처리 (indexed=%d unchanged=%d error=%d skipped=%d) 최근=%s",
                         seen, report.indexed, report.unchanged, report.errors,
                         report.skipped, path.name)
    prune_deleted(store)
    return report


def retry_errors(store: Store, progress_every: int = 25) -> IndexReport:
    """현재 error 상태인 파일만 강제로 재인덱싱한다.

    추출기/청커 버그 수정 후, 전체 코퍼스를 --force로 재처리하지 않고
    실패분만 효율적으로 되살리기 위한 경로. 디스크에서 사라진 파일은 정리한다.
    """
    report = IndexReport()
    error_paths = [f["path"] for f in store.list_files(status="error", limit=10**9)]
    for i, p in enumerate(error_paths, start=1):
        path = Path(p)
        if not path.exists():
            store.delete_file(p)
            report.skipped += 1
            continue
        result = index_file(store, path, force=True)
        if result == "indexed":
            report.indexed += 1
        elif result == "error":
            report.errors += 1
            report.error_files.append(p)
        else:
            report.skipped += 1
        if progress_every and i % progress_every == 0:
            log.info("실패 재시도: %d/%d (복구=%d 여전히실패=%d)",
                     i, len(error_paths), report.indexed, report.errors)
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
