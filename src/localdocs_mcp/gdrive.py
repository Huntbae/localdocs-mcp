"""Model B — rclone 기반 Google Drive 인덱싱(자립형).

어시스턴트(LLM)를 거치지 않고 Drive API로 파일 바이트를 직접 받아(고장난
스트리밍 FUSE 마운트 우회) 로컬 추출기로 텍스트를 뽑아 인덱싱한다. 텍스트가
LLM 컨텍스트를 통과하지 않으므로 세션 토큰 한도와 무관하며, hwp/hwpx까지
로컬 파서로 처리된다.

전제: `rclone`이 설치되고 Google Drive 원격이 설정돼 있어야 한다.
  brew install rclone
  rclone config           # 원격 이름 예: gdrive, 타입 drive, 범위 drive.readonly

로컬 마운트 경로 ↔ rclone 경로 매핑:
  local_root = ".../GoogleDrive-<메일>/내 드라이브"  (rclone 'gdrive:' = 내 드라이브 루트)
  로컬 <local_root>/A/B.pdf  →  rclone 'gdrive:A/B.pdf'
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from . import config
from .chunker import chunk_segments
from .extractors import get_extractor
from .indexer import IndexReport
from .store import Store

log = logging.getLogger("localdocs.gdrive")


def rclone_available() -> bool:
    try:
        return subprocess.run(["rclone", "version"], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def remote_ok(remote: str) -> bool:
    """원격이 인증되어 접근 가능한지 얕게 확인."""
    try:
        r = subprocess.run(["rclone", "lsjson", "--max-depth", "1", remote],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def local_to_remote(local_path: str, local_root: str, remote: str) -> str:
    """로컬 마운트 경로를 rclone 원격 경로로 변환.

    macOS 파일시스템은 한글을 NFD(자모 분리)로 저장하지만 Google Drive는
    NFC(완성형)로 저장하므로, rclone이 파일을 찾도록 경로를 NFC로 정규화한다.
    (미정규화 시 한글 이름 파일에서 rclone이 'not found'로 실패한다.)
    """
    rel = os.path.relpath(local_path, local_root)
    joined = remote + rel if remote.endswith(":") else remote.rstrip("/") + "/" + rel
    return unicodedata.normalize("NFC", joined)


def _is_sensitive(name: str) -> bool:
    lname = name.lower()
    return any(pat in lname for pat in config.SENSITIVE_NAME_PATTERNS)


def _fetch_to_temp(remote_path: str, suffix: str, timeout: float) -> str:
    """rclone cat으로 파일 바이트를 임시 파일에 받아 그 경로를 반환."""
    fd, tmp = tempfile.mkstemp(suffix=suffix or ".bin")
    os.close(fd)
    try:
        with open(tmp, "wb") as out:
            r = subprocess.run(["rclone", "cat", remote_path], stdout=out,
                               stderr=subprocess.PIPE, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[:200] or
                               "rclone cat 실패")
        return tmp
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _index_one(store: Store, local_path: str, remote: str, local_root: str,
               timeout: float) -> str:
    """단일 파일: rclone로 바이트 받아 로컬 추출→인덱싱. 반환 상태 문자열."""
    p = Path(local_path)
    if _is_sensitive(p.name):
        return "skipped"
    ext = get_extractor(p)
    if ext is None:
        return "skipped"
    name, fn = ext
    remote_path = local_to_remote(local_path, local_root, remote)
    tmp = None
    try:
        tmp = _fetch_to_temp(remote_path, p.suffix.lower(), timeout)
        segments = fn(Path(tmp))
        chunks = chunk_segments(segments)
        try:
            st = os.stat(local_path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0.0, os.path.getsize(tmp)
        store.replace_file(local_path, mtime, size, chunks,
                           extractor=f"gdrive/{name}", status="ok")
        return "indexed"
    except Exception as e:
        log.warning("gdrive 복구 실패 %s: %s", p.name, e)
        try:
            st = os.stat(local_path); mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0.0, 0
        store.replace_file(local_path, mtime, size, [], extractor="gdrive",
                           status="error", error=str(e)[:500])
        return "error"
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def recover_errors(store: Store, remote: str, local_root: str,
                   timeout: float = 300.0, progress_every: int = 25) -> IndexReport:
    """현재 error 상태이고 local_root 하위인 파일을 rclone로 재복구한다."""
    report = IndexReport()
    local_root = str(Path(local_root).expanduser())
    root_nfd = unicodedata.normalize("NFD", local_root)
    targets = [
        f["path"] for f in store.list_files(status="error", limit=10**9)
        if unicodedata.normalize("NFD", f["path"]).startswith(root_nfd)
    ]
    log.info("gdrive 복구 대상: %d개 (root=%s)", len(targets), local_root)
    for i, path in enumerate(targets, 1):
        result = _index_one(store, path, remote, local_root, timeout)
        if result == "indexed":
            report.indexed += 1
        elif result == "error":
            report.errors += 1
            report.error_files.append(path)
        else:
            report.skipped += 1
        if progress_every and i % progress_every == 0:
            log.info("진행 %d/%d — 복구=%d 실패=%d 건너뜀=%d",
                     i, len(targets), report.indexed, report.errors, report.skipped)
    return report
