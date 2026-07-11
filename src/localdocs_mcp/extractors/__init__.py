"""파일 → 텍스트 세그먼트 추출기 레지스트리.

모든 추출기는 (text, meta) 튜플의 리스트를 반환한다. meta에는 페이지/슬라이드
번호 등 출처 정보를 담아 검색 결과 인용에 사용한다. 지원하지 않거나 파싱에
실패한 파일은 예외를 올려 인덱서가 files.status='error'로 기록하게 한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

Segment = tuple[str, dict]
Extractor = Callable[[Path], list[Segment]]

from . import hwp, hwpx, image, office, pdf, text  # noqa: E402

_REGISTRY: dict[str, tuple[str, Extractor]] = {
    ".txt": ("text", text.extract),
    ".md": ("text", text.extract),
    ".markdown": ("text", text.extract),
    ".csv": ("text", text.extract),
    ".log": ("text", text.extract),
    ".json": ("text", text.extract),
    ".rtf": ("textutil", text.extract_with_textutil),
    ".doc": ("textutil", text.extract_with_textutil),
    ".pdf": ("pypdf", pdf.extract),
    ".docx": ("docx-xml", office.extract_docx),
    ".pptx": ("pptx-xml", office.extract_pptx),
    ".xlsx": ("xlsx-xml", office.extract_xlsx),
    ".hwpx": ("hwpx-xml", hwpx.extract),
    ".hwp": ("hwp5-ole", hwp.extract),
    ".png": ("ocr", image.extract),
    ".jpg": ("ocr", image.extract),
    ".jpeg": ("ocr", image.extract),
    ".webp": ("ocr", image.extract),
    ".bmp": ("ocr", image.extract),
    ".tiff": ("ocr", image.extract),
}


def get_extractor(path: Path) -> tuple[str, Extractor] | None:
    return _REGISTRY.get(path.suffix.lower())


def supported_suffixes() -> set[str]:
    return set(_REGISTRY.keys())
