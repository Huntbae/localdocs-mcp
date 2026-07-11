"""문단 경계를 존중하는 청킹.

세그먼트(페이지/슬라이드/섹션) 안에서 문단 단위로 묶어 max_chars를 넘지 않는
청크를 만들고, 검색 문맥 연속성을 위해 청크 간 오버랩을 둔다. 하나의 문단이
max_chars를 넘으면 문장/고정폭으로 강제 분할한다.
"""
from __future__ import annotations

import re

from . import config


def _split_long(text: str, max_chars: int) -> list[str]:
    # 고정 길이 lookbehind만 사용(Python re 제약). 한국어 '다.' 종결은 마침표가
    # 이미 아래 문자 클래스에 포함되므로 별도 처리가 필요 없다.
    sentences = re.split(r"(?<=[.!?。…])\s+", text)
    parts: list[str] = []
    buf = ""
    for s in sentences:
        if len(s) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            parts.extend(s[i:i + max_chars] for i in range(0, len(s), max_chars))
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            parts.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        parts.append(buf)
    return parts


def chunk_segments(
    segments: list[tuple[str, dict]],
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[tuple[str, dict]]:
    max_chars = max_chars or config.CHUNK_MAX_CHARS
    overlap = overlap if overlap is not None else config.CHUNK_OVERLAP_CHARS
    chunks: list[tuple[str, dict]] = []
    for text, meta in segments:
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
        buf = ""
        for p in paras:
            if len(p) > max_chars:
                if buf:
                    chunks.append((buf, dict(meta)))
                    buf = ""
                for part in _split_long(p, max_chars):
                    chunks.append((part, dict(meta)))
                continue
            if len(buf) + len(p) + 1 > max_chars and buf:
                chunks.append((buf, dict(meta)))
                buf = (buf[-overlap:] + "\n" + p) if overlap else p
            else:
                buf = f"{buf}\n{p}".strip()
        if buf:
            chunks.append((buf, dict(meta)))
    return chunks
