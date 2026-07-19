import struct
import zlib

from localdocs_mcp.extractors import get_extractor, hwp, hwpx, office
from tests.conftest import make_docx, make_hwpx, make_pptx


def test_docx(tmp_path):
    p = make_docx(tmp_path / "a.docx", ["첫 문단", "둘째 문단"])
    segs = office.extract_docx(p)
    assert len(segs) == 1
    assert "첫 문단" in segs[0][0] and "둘째 문단" in segs[0][0]


def test_pptx_slide_meta(tmp_path):
    p = make_pptx(tmp_path / "a.pptx", [["슬라이드1"], ["슬라이드2 내용"]])
    segs = office.extract_pptx(p)
    assert len(segs) == 2
    assert segs[0][1] == {"slide": 1}
    assert "슬라이드2 내용" in segs[1][0]


def test_hwpx(tmp_path):
    p = make_hwpx(tmp_path / "a.hwpx", [["안녕하세요", "한글 문서입니다"]])
    segs = hwpx.extract(p)
    assert len(segs) == 1
    assert "한글 문서입니다" in segs[0][0]
    assert segs[0][1] == {"section": 0}


def test_registry_dispatch(tmp_path):
    assert get_extractor(tmp_path / "x.hwp")[0] == "hwp5-ole"
    assert get_extractor(tmp_path / "x.HWPX")[0] == "hwpx-xml"
    assert get_extractor(tmp_path / "x.unknown") is None


# ---------- HWP 5.0 바이너리 레코드 파서 단위 테스트 ----------

def _record(tag: int, payload: bytes) -> bytes:
    header = (tag & 0x3FF) | ((len(payload) & 0xFFF) << 20)
    return struct.pack("<I", header) + payload


def test_hwp_decode_para_text_skips_controls():
    # 확장 컨트롤(코드 3)은 8 WCHAR를 차지한다
    payload = "가나".encode("utf-16-le")
    payload += struct.pack("<H", 3) + b"\x00" * 14  # 컨트롤 + 7 WCHAR
    payload += "다".encode("utf-16-le")
    assert hwp._decode_para_text(payload) == "가나다"


def test_hwp_iter_records_roundtrip():
    text = "테스트 문단".encode("utf-16-le")
    data = _record(66, b"\x01\x02") + _record(hwp.HWPTAG_PARA_TEXT, text)
    records = list(hwp._iter_records(data))
    assert [t for t, _ in records] == [66, hwp.HWPTAG_PARA_TEXT]
    assert hwp._decode_para_text(records[1][1]) == "테스트 문단"


def test_hwp_compressed_stream_decodes():
    raw = _record(hwp.HWPTAG_PARA_TEXT, "압축 본문".encode("utf-16-le"))
    compressed = zlib.compress(raw)[2:-4]  # raw deflate
    restored = zlib.decompress(compressed, -15)
    records = list(hwp._iter_records(restored))
    assert hwp._decode_para_text(records[0][1]) == "압축 본문"


def test_hwp_surrogate_pair_combines():
    import struct
    from localdocs_mcp.extractors import hwp
    # BMP 밖 문자(U+1F600)를 UTF-16LE 서로게이트 쌍으로
    emoji = "가😀나"
    payload = emoji.encode("utf-16-le")
    out = hwp._decode_para_text(payload)
    assert out == "가😀나"
    out.encode("utf-8")  # 인코딩 가능해야 함(예외 없음)


def test_hwp_lone_surrogate_dropped():
    import struct
    from localdocs_mcp.extractors import hwp
    # 짝 없는 상위 서로게이트(0xD83D) → 폐기되어야 함
    payload = "가".encode("utf-16-le") + struct.pack("<H", 0xD83D) + "나".encode("utf-16-le")
    out = hwp._decode_para_text(payload)
    assert out == "가나"
    out.encode("utf-8")
