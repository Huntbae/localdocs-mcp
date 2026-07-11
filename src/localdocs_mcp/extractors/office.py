"""OOXML(docx/pptx/xlsx) 추출 — 표준 라이브러리(zipfile + ElementTree)만 사용.

python-docx/python-pptx 없이 XML을 직접 읽어 의존성을 최소화한다.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def extract_docx(path: Path) -> list[tuple[str, dict]]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    paras: list[str] = []
    for p in root.iter(f"{_W}p"):
        runs = [t.text or "" for t in p.iter(f"{_W}t")]
        line = "".join(runs).strip()
        if line:
            paras.append(line)
    if not paras:
        raise ValueError("본문 텍스트 없음")
    return [("\n".join(paras), {})]


def extract_pptx(path: Path) -> list[tuple[str, dict]]:
    segments: list[tuple[str, dict]] = []
    with zipfile.ZipFile(path) as zf:
        slide_names = sorted(
            (n for n in zf.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        for name in slide_names:
            slide_no = int(re.search(r"(\d+)", name).group(1))
            root = ET.fromstring(zf.read(name))
            texts = [t.text or "" for t in root.iter(f"{_A}t")]
            body = "\n".join(x.strip() for x in texts if x.strip())
            if body:
                segments.append((body, {"slide": slide_no}))
    if not segments:
        raise ValueError("슬라이드 텍스트 없음")
    return segments


def extract_xlsx(path: Path) -> list[tuple[str, dict]]:
    """공유 문자열 + 각 시트의 인라인 문자열을 시트 단위로 추출한다."""
    segments: list[tuple[str, dict]] = []
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter(f"{_S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
        sheet_names = sorted(
            n for n in zf.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
        )
        for name in sheet_names:
            sheet_no = int(re.search(r"(\d+)", name).group(1))
            root = ET.fromstring(zf.read(name))
            cells: list[str] = []
            for c in root.iter(f"{_S}c"):
                v = c.find(f"{_S}v")
                if v is None or v.text is None:
                    continue
                if c.get("t") == "s":
                    idx = int(v.text)
                    if 0 <= idx < len(shared) and shared[idx].strip():
                        cells.append(shared[idx].strip())
                else:
                    cells.append(v.text)
            if cells:
                segments.append(("\n".join(cells), {"sheet": sheet_no}))
    if not segments:
        raise ValueError("시트 텍스트 없음")
    return segments
