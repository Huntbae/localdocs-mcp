from pathlib import Path

from localdocs_mcp.chunker import chunk_segments
from localdocs_mcp.indexer import index_paths, prune_deleted
from localdocs_mcp.search import hybrid_search
from localdocs_mcp.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "index.db")


def test_chunker_respects_max_and_overlap():
    text = "\n".join(f"문단 {i} " + "내용" * 30 for i in range(20))
    chunks = chunk_segments([(text, {"page": 1})], max_chars=300, overlap=50)
    assert all(len(c) <= 300 + 60 for c, _ in chunks)
    assert all(m == {"page": 1} for _, m in chunks)
    assert len(chunks) > 3


def test_chunker_splits_long_single_paragraph():
    # 문단 하나가 max_chars를 크게 초과하는 경우 _split_long 경로를 탄다.
    # (가변 길이 lookbehind 정규식 회귀 방지 — 실제 한국어 문장 종결 포함)
    long_para = " ".join(f"이것은 {i}번째 문장입니다. 내용을 채운다." for i in range(200))
    chunks = chunk_segments([(long_para, {})], max_chars=400, overlap=50)
    assert len(chunks) > 5
    assert all(len(c) <= 400 + 60 for c, _ in chunks)

    # 문장 부호도 공백도 없는 초장문(CJK 연속)도 강제 분할된다.
    no_break = "가" * 5000
    chunks2 = chunk_segments([(no_break, {})], max_chars=400, overlap=0)
    assert all(len(c) <= 400 for c, _ in chunks2)
    assert sum(len(c) for c, _ in chunks2) == 5000


def test_fts_search_korean(tmp_path):
    store = _store(tmp_path)
    store.replace_file("/a.txt", 1.0, 10,
                       [("마실카트 배터리 사양서", {}), ("무관한 내용", {})],
                       extractor="text")
    hits = store.search_fts("배터리")
    assert len(hits) == 1
    assert hits[0].text == "마실카트 배터리 사양서"


def test_replace_file_updates_fts(tmp_path):
    store = _store(tmp_path)
    store.replace_file("/a.txt", 1.0, 10, [("옛날 키워드", {})], extractor="text")
    store.replace_file("/a.txt", 2.0, 12, [("새로운 키워드", {})], extractor="text")
    assert store.search_fts("옛날") == []
    assert len(store.search_fts("새로운")) == 1


def test_vector_search_and_hybrid(tmp_path):
    store = _store(tmp_path)
    ids = store.replace_file(
        "/a.txt", 1.0, 10,
        [("전기 카트 판매 전략", {}), ("김치찌개 레시피", {})],
        extractor="text",
    )
    store.add_embeddings([(ids[0], [1.0, 0.0, 0.0]), (ids[1], [0.0, 1.0, 0.0])])

    hits = store.search_vector([0.9, 0.1, 0.0], limit=2)
    assert hits[0].text == "전기 카트 판매 전략"

    class FakeEmbedder:
        model = "fake"
        def available(self):
            return True
        def embed_one(self, text):
            return [1.0, 0.0, 0.0]

    out = hybrid_search(store, "판매 전략", embedder=FakeEmbedder())
    assert out["mode"] == "hybrid"
    assert out["results"][0]["file_path"] == "/a.txt"
    assert "bm25" in out["results"][0]["matched_by"]


def test_hybrid_falls_back_without_ollama(tmp_path):
    store = _store(tmp_path)
    store.replace_file("/a.txt", 1.0, 10, [("계약서 초안", {})], extractor="text")

    class DownEmbedder:
        def available(self):
            return False

    out = hybrid_search(store, "계약서", embedder=DownEmbedder())
    assert out["mode"] == "bm25-only"
    assert len(out["results"]) == 1


def test_indexer_end_to_end(sample_dir, tmp_path):
    store = _store(tmp_path)
    report = index_paths(store, [sample_dir])
    assert report.errors == 0
    assert report.indexed == 5  # txt, md, docx, pptx, hwpx

    # 재실행 시 변경 없으면 건너뜀 (증분 인덱싱)
    report2 = index_paths(store, [sample_dir])
    assert report2.indexed == 0 and report2.unchanged == 5

    # 포맷별 검색 확인
    for query, filename in [
        ("배터리", "메모.txt"),
        ("커리큘럼", "notes.md"),
        ("할인", "제안서.docx"),
        ("보조금", "발표.pptx"),
        ("시범사업", "공문.hwpx"),
    ]:
        hits = store.search_fts(query)
        assert hits, f"'{query}' 검색 실패"
        assert hits[0].file_path.endswith(filename)

    # 파일 삭제 → prune 반영
    (sample_dir / "메모.txt").unlink()
    removed = prune_deleted(store)
    assert removed == 1
    assert store.search_fts("배터리") == []


def test_retry_errors_recovers_fixed_files(sample_dir, tmp_path):
    from localdocs_mcp.indexer import retry_errors
    store = _store(tmp_path)
    bad = sample_dir / "깨진문서.hwpx"
    bad.write_bytes(b"not a zip")
    index_paths(store, [sample_dir])
    assert len(store.list_files(status="error")) == 1

    # 내용을 정상 hwpx로 교체 후 retry-errors 하면 복구된다
    from tests.conftest import make_hwpx
    make_hwpx(bad, [["복구된 본문입니다"]])
    report = retry_errors(store)
    assert report.indexed == 1
    assert store.list_files(status="error") == []
    assert store.search_fts("복구된")


def test_error_files_are_recorded(sample_dir, tmp_path):
    bad = sample_dir / "깨진문서.hwpx"
    bad.write_bytes(b"this is not a zip file")
    store = _store(tmp_path)
    report = index_paths(store, [sample_dir])
    assert report.errors == 1
    errs = store.list_files(status="error")
    assert len(errs) == 1
    assert errs[0]["path"].endswith("깨진문서.hwpx")
    assert errs[0]["error"]


def test_index_skip_and_only_filters(sample_dir, tmp_path):
    # 이미지 없는 샘플이므로 확장자 필터 동작만 검증
    store = _store(tmp_path / "a")
    r = index_paths(store, [sample_dir], skip={".hwpx"})
    assert store.list_files(prefix=str(sample_dir))
    assert not any(f["path"].endswith(".hwpx") for f in store.list_files())
    assert r.indexed == 4  # hwpx 제외

    store2 = _store(tmp_path / "b")
    index_paths(store2, [sample_dir], only={".pdf", ".hwpx"})
    files = store2.list_files()
    assert len(files) == 1 and files[0]["path"].endswith(".hwpx")


def test_iter_indexable_exclude_paths(tmp_path):
    from localdocs_mcp.indexer import iter_indexable
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "bigdata").mkdir()
    (tmp_path / "bigdata" / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "bigdata" / "sub").mkdir()
    (tmp_path / "bigdata" / "sub" / "c.txt").write_text("x", encoding="utf-8")
    found = {p.name for p in iter_indexable(tmp_path, exclude=["bigdata"])}
    assert found == {"a.txt"}


def test_iter_indexable_prunes_hidden_and_skip_dirs(tmp_path):
    from localdocs_mcp.indexer import iter_indexable
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".secret.txt").write_text("x", encoding="utf-8")
    (tmp_path / "~$lock.docx").write_text("x", encoding="utf-8")  # 오피스 임시파일
    found = {p.name for p in iter_indexable(tmp_path)}
    assert found == {"a.txt"}


def test_get_chunk_context(tmp_path):
    store = _store(tmp_path)
    ids = store.replace_file(
        "/a.txt", 1.0, 10,
        [(f"청크 {i}", {}) for i in range(5)],
        extractor="text",
    )
    ctx = store.get_chunk_with_neighbors(ids[2], neighbors=1)
    assert [c["seq"] for c in ctx["chunks"]] == [1, 2, 3]
