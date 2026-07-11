"""테스트 픽스처 — 실제 포맷 규격대로 최소 문서를 생성한다."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc)
    return path


def make_pptx(path: Path, slides: list[list[str]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for i, texts in enumerate(slides, start=1):
            runs = "".join(
                f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts
            )
            slide = (
                '<?xml version="1.0"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<p:cSld><p:spTree><p:sp><p:txBody>{runs}</p:txBody></p:sp>"
                "</p:spTree></p:cSld></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{i}.xml", slide)
    return path


def make_hwpx(path: Path, sections: list[list[str]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        for i, paras in enumerate(sections):
            body = "".join(
                f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>" for t in paras
            )
            sec = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
                'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
                f"{body}</hs:sec>"
            )
            zf.writestr(f"Contents/section{i}.xml", sec)
    return path


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "메모.txt").write_text(
        "마실카트 2024년 계약서 초안.\n전기 카트 배터리 사양은 리튬인산철 48V.",
        encoding="utf-8",
    )
    (docs / "notes.md").write_text(
        "# eDu Kart\n교육용 카트 커리큘럼 개요와 안전 교육 지침.",
        encoding="utf-8",
    )
    make_docx(docs / "제안서.docx",
              ["뉴트로엠 전기 카트 제안서", "가격 조건: 대당 350만원, 10대 이상 5% 할인"])
    make_pptx(docs / "발표.pptx",
              [["이모빌리티 시장 개요"], ["마실카트 판매 전략", "지자체 보조금 활용"]])
    make_hwpx(docs / "공문.hwpx",
              [["수신: 서울특별시", "제목: 전기카트 시범사업 협조 요청"]])
    return docs
