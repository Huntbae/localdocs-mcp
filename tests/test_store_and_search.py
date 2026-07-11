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


def test_get_chunk_context(tmp_path):
    store = _store(tmp_path)
    ids = store.replace_file(
        "/a.txt", 1.0, 10,
        [(f"청크 {i}", {}) for i in range(5)],
        extractor="text",
    )
    ctx = store.get_chunk_with_neighbors(ids[2], neighbors=1)
    assert [c["seq"] for c in ctx["chunks"]] == [1, 2, 3]
