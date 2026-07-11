"""전역 설정 — 환경변수로 재정의 가능."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALDOCS_HOME", Path.home() / ".localdocs-mcp"))
DB_PATH = Path(os.environ.get("LOCALDOCS_DB", APP_DIR / "index.db"))

# 임베딩 (Ollama). 미설치/미기동이어도 키워드(BM25) 검색은 동작한다.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("LOCALDOCS_EMBED_MODEL", "bge-m3")
EMBED_BATCH = int(os.environ.get("LOCALDOCS_EMBED_BATCH", "16"))
EMBED_TIMEOUT = float(os.environ.get("LOCALDOCS_EMBED_TIMEOUT", "120"))

# 청킹
CHUNK_MAX_CHARS = int(os.environ.get("LOCALDOCS_CHUNK_MAX_CHARS", "1200"))
CHUNK_OVERLAP_CHARS = int(os.environ.get("LOCALDOCS_CHUNK_OVERLAP", "150"))

# 이미지(OCR 대상) 확장자 — 문서와 분리해 별도 단계로 인덱싱할 수 있게 한다
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

# 인덱싱 대상 확장자
INDEXABLE_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".log", ".json", ".rtf",
    ".pdf",
    ".docx", ".pptx", ".xlsx", ".doc",
    ".hwp", ".hwpx",
} | IMAGE_SUFFIXES

# 인덱싱에서 제외할 디렉토리 이름
SKIP_DIR_NAMES = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".Trash", "Library", ".cache",
}

MAX_FILE_MB = float(os.environ.get("LOCALDOCS_MAX_FILE_MB", "100"))


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
