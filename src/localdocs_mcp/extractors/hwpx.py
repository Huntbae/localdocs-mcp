"""HWPX(OWPML) 추출 — HWPX는 ZIP + XML이므로 표준 라이브러리로 파싱 가능.

본문은 Contents/section*.xml 안의 <hp:p> 문단, 텍스트는 <hp:t> 요소에 있다.
네임스페이스 버전 차이에 대비해 로컬 태그 이름으로 매칭한다.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def extract(path: Path) -> list[tuple[str, dict]]:
    segments: list[tuple[str, dict]] = []
    with zipfile.ZipFile(path) as zf:
        section_names = sorted(
            (n for n in zf.namelist()
             if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        if not section_names:
            raise ValueError("Contents/section*.xml 없음 — HWPX 형식이 아님")
        for name in section_names:
            sec_no = int(re.search(r"(\d+)", name).group(1))
            root = ET.fromstring(zf.read(name))
            paras: list[str] = []
            for elem in root.iter():
                if _local(elem.tag) == "p":
                    texts = [
                        t.text or ""
                        for t in elem.iter()
                        if _local(t.tag) == "t"
                    ]
                    line = "".join(texts).strip()
                    if line:
                        paras.append(line)
            if paras:
                segments.append(("\n".join(paras), {"section": sec_no}))
    if not segments:
        raise ValueError("본문 텍스트 없음")
    return segments
