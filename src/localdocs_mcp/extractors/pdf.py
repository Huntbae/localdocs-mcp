"""PDF 텍스트 추출 (pypdf). 텍스트 레이어가 없으면 OCR로 폴백한다."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pypdf import PdfReader

# OCR 폴백 시 렌더링 해상도와 최대 페이지 수(초대형 스캔본 방지)
OCR_DPI = int(os.environ.get("LOCALDOCS_OCR_DPI", "200"))
OCR_MAX_PAGES = int(os.environ.get("LOCALDOCS_OCR_MAX_PAGES", "50"))


def extract(path: Path) -> list[tuple[str, dict]]:
    reader = PdfReader(str(path))
    segments: list[tuple[str, dict]] = []
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if txt:
            segments.append((txt, {"page": i}))
    if segments:
        return segments
    # 텍스트 레이어 없음 → 스캔 PDF로 보고 OCR 시도
    return _extract_via_ocr(path)


def _extract_via_ocr(path: Path) -> list[tuple[str, dict]]:
    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise ValueError(
            "텍스트 레이어 없음 — 스캔 PDF OCR엔 `pip install 'localdocs-mcp[ocr]'` 필요"
        ) from e
    from .image import _get_reader  # easyocr 리더 재사용(모델 1회 로드)

    reader = _get_reader()
    doc = fitz.open(str(path))
    segments: list[tuple[str, dict]] = []
    try:
        for i in range(min(len(doc), OCR_MAX_PAGES)):
            pix = doc[i].get_pixmap(dpi=OCR_DPI)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(pix.tobytes("png"))
                img_path = tmp.name
            try:
                results = reader.readtext(img_path, detail=0, paragraph=True)
            finally:
                Path(img_path).unlink(missing_ok=True)
            txt = "\n".join(r.strip() for r in results if r.strip())
            if txt:
                segments.append((txt, {"page": i + 1, "ocr": "easyocr"}))
    finally:
        doc.close()
    if not segments:
        raise ValueError("스캔 PDF OCR 결과 텍스트 없음")
    return segments
