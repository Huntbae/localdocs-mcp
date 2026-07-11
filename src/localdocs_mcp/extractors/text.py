"""일반 텍스트 및 macOS textutil 기반 추출(.rtf, 레거시 .doc)."""
from __future__ import annotations

import platform
import subprocess
import tempfile
from pathlib import Path

_ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "euc-kr", "utf-16")


def extract(path: Path) -> list[tuple[str, dict]]:
    data = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return [(data.decode(enc), {})]
        except (UnicodeDecodeError, UnicodeError):
            continue
    return [(data.decode("utf-8", errors="replace"), {"encoding": "lossy"})]


def extract_with_textutil(path: Path) -> list[tuple[str, dict]]:
    """macOS 내장 textutil로 .doc/.rtf를 txt로 변환. 다른 OS에서는 실패 처리."""
    if platform.system() != "Darwin":
        raise RuntimeError(f"{path.suffix} 추출은 macOS(textutil)에서만 지원됩니다")
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        subprocess.run(
            ["textutil", "-convert", "txt", "-output", str(out), str(path)],
            check=True, capture_output=True, timeout=120,
        )
        return [(out.read_text(encoding="utf-8", errors="replace"), {})]
    finally:
        out.unlink(missing_ok=True)
