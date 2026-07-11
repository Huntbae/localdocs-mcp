"""HWP 5.0(바이너리, OLE 복합문서) 텍스트 추출.

한컴오피스나 외부 파서 없이 동작하는 자체 구현:
  1) FileHeader 스트림에서 압축/암호화 플래그 확인
  2) BodyText/Section* 스트림을 (필요시 raw-deflate 해제 후) 레코드 단위로 순회
  3) HWPTAG_PARA_TEXT(67) 레코드의 UTF-16LE 본문에서 제어문자를 규칙대로 건너뜀
본문 파싱이 실패하면 PrvText(미리보기) 스트림으로 폴백한다.

레코드 헤더: uint32 = tag(10bit) | level(10bit) | size(12bit), size==0xFFF이면
다음 uint32가 실제 크기다. 제어문자 규칙: 인라인/확장 컨트롤(1~9,11,12,14~23)은
8 WCHAR를 차지하고, 문자 컨트롤(0,10,13,24~31)은 1 WCHAR다.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import olefile

HWPTAG_PARA_TEXT = 67  # HWPTAG_BEGIN(16) + 51

# 8 WCHAR를 차지하는 인라인/확장 컨트롤 문자 코드
_EXTENDED_CTRL = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17,
                  18, 19, 20, 21, 22, 23}


def _decode_para_text(payload: bytes) -> str:
    out: list[str] = []
    n = len(payload) // 2
    i = 0
    while i < n:
        (code,) = struct.unpack_from("<H", payload, i * 2)
        if code >= 32:
            out.append(chr(code))
            i += 1
        elif code in (10, 13):
            out.append("\n")
            i += 1
        elif code in _EXTENDED_CTRL:
            i += 8  # 컨트롤 본체 7 WCHAR 포함
        else:
            i += 1
    return "".join(out)


def _iter_records(data: bytes):
    pos = 0
    end = len(data)
    while pos + 4 <= end:
        (header,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 4 > end:
                break
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        if pos + size > end:
            break
        yield tag, data[pos:pos + size]
        pos += size


def extract(path: Path) -> list[tuple[str, dict]]:
    ole = olefile.OleFileIO(str(path))
    try:
        if not ole.exists("FileHeader"):
            raise ValueError("FileHeader 없음 — HWP 5.0 형식이 아님")
        header = ole.openstream("FileHeader").read()
        (flags,) = struct.unpack_from("<I", header, 36)
        compressed = bool(flags & 0x1)
        if flags & 0x2:
            raise ValueError("암호화된 문서 — 암호 해제 후 재인덱싱 필요")

        sections = sorted(
            (e for e in ole.listdir()
             if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][len("Section"):]),
        )
        segments: list[tuple[str, dict]] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            data = zlib.decompress(raw, -15) if compressed else raw
            paras: list[str] = []
            for tag, payload in _iter_records(data):
                if tag == HWPTAG_PARA_TEXT:
                    txt = _decode_para_text(payload).strip()
                    if txt:
                        paras.append(txt)
            if paras:
                sec_no = int(entry[1][len("Section"):])
                segments.append(("\n".join(paras), {"section": sec_no}))
        if segments:
            return segments

        # 폴백: 미리보기 텍스트(문서 앞부분만 담겨 있을 수 있음)
        if ole.exists("PrvText"):
            prv = ole.openstream("PrvText").read().decode(
                "utf-16-le", errors="replace").strip("\x00 \n")
            if prv:
                return [(prv, {"source": "PrvText", "partial": True})]
        raise ValueError("본문 텍스트 없음")
    finally:
        ole.close()
