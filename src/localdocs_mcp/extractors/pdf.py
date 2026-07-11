"""PDF 텍스트 추출 (pypdf). 페이지 번호를 메타데이터로 남긴다."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract(path: Path) -> list[tuple[str, dict]]:
    reader = PdfReader(str(path))
    segments: list[tuple[str, dict]] = []
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if txt:
            segments.append((txt, {"page": i}))
    if not segments:
        raise ValueError("텍스트 레이어 없음 — 스캔 PDF는 OCR 필요")
    return segments
