"""이미지 OCR — 선택적 기능.

easyocr(옵션 [ocr])이 설치되어 있으면 한국어+영어 OCR을 수행하고,
없으면 명확한 오류로 건너뛰어 status()에 사유가 남게 한다.
모델 로딩 비용이 크므로 리더는 프로세스당 1회만 생성한다.
"""
from __future__ import annotations

from pathlib import Path

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "OCR 미설치 — `pip install 'localdocs-mcp[ocr]'` 후 재인덱싱"
            ) from e
        _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    return _reader


def extract(path: Path) -> list[tuple[str, dict]]:
    reader = _get_reader()
    results = reader.readtext(str(path), detail=0, paragraph=True)
    text = "\n".join(r.strip() for r in results if r.strip())
    if not text:
        raise ValueError("이미지에서 텍스트를 찾지 못함")
    return [(text, {"ocr": "easyocr"})]
