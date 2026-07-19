"""단일 SQLite 저장소.

파일 메타데이터, 청크 본문, FTS5(BM25) 인덱스, 임베딩 벡터를 하나의 DB에
트랜잭션으로 함께 저장한다. 별도 벡터 DB를 두지 않아 두 저장소 간
동기화 불일치가 구조적으로 발생하지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',      -- ok | error | skipped
    error TEXT,
    extractor TEXT,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id, seq);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_text(text: str) -> str:
    """UTF-8로 인코딩 불가한 문자(짝 없는 서로게이트 등)를 제거해 저장 오류를 막는다."""
    return text.encode("utf-8", "ignore").decode("utf-8")


def vec_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_vec(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)


@dataclass
class ChunkHit:
    chunk_id: int
    file_path: str
    seq: int
    text: str
    meta: dict
    score: float


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------- 파일/청크 쓰기 ----------

    def file_needs_update(self, path: str, mtime: float, size: int) -> bool:
        row = self.conn.execute(
            "SELECT mtime, size, status FROM files WHERE path=?", (path,)
        ).fetchone()
        if row is None:
            return True
        old_mtime, old_size, status = row
        if status == "error":
            # 실패했던 파일은 내용이 바뀐 경우에만 재시도
            return abs(old_mtime - mtime) > 1e-6 or old_size != size
        return abs(old_mtime - mtime) > 1e-6 or old_size != size

    def replace_file(
        self,
        path: str,
        mtime: float,
        size: int,
        chunks: Iterable[tuple[str, dict]],
        extractor: str,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> list[int]:
        """파일 레코드와 그 청크 전체를 원자적으로 교체하고 청크 id 목록을 반환."""
        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN")
            cur.execute("SELECT id FROM files WHERE path=?", (path,))
            row = cur.fetchone()
            if row:
                file_id = row[0]
                for (cid,) in cur.execute(
                    "SELECT id FROM chunks WHERE file_id=?", (file_id,)
                ).fetchall():
                    cur.execute(
                        "INSERT INTO chunks_fts(chunks_fts, rowid, text) "
                        "VALUES('delete', ?, (SELECT text FROM chunks WHERE id=?))",
                        (cid, cid),
                    )
                cur.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                cur.execute(
                    "UPDATE files SET mtime=?, size=?, status=?, error=?, "
                    "extractor=?, indexed_at=? WHERE id=?",
                    (mtime, size, status, error, extractor, _now(), file_id),
                )
            else:
                cur.execute(
                    "INSERT INTO files(path, mtime, size, status, error, extractor, indexed_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (path, mtime, size, status, error, extractor, _now()),
                )
                file_id = cur.lastrowid
            chunk_ids: list[int] = []
            for seq, (text, meta) in enumerate(chunks):
                text = _safe_text(text)  # 낱개 서로게이트 등 UTF-8 불가 문자 제거
                cur.execute(
                    "INSERT INTO chunks(file_id, seq, text, meta) VALUES(?,?,?,?)",
                    (file_id, seq, text, json.dumps(meta, ensure_ascii=False)),
                )
                cid = cur.lastrowid
                cur.execute(
                    "INSERT INTO chunks_fts(rowid, text) VALUES(?,?)", (cid, text)
                )
                chunk_ids.append(cid)
            self.conn.commit()
            return chunk_ids
        except Exception:
            self.conn.rollback()
            raise

    def delete_file(self, path: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        row = cur.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        if not row:
            self.conn.rollback()
            return False
        file_id = row[0]
        for (cid,) in cur.execute(
            "SELECT id FROM chunks WHERE file_id=?", (file_id,)
        ).fetchall():
            cur.execute(
                "INSERT INTO chunks_fts(chunks_fts, rowid, text) "
                "VALUES('delete', ?, (SELECT text FROM chunks WHERE id=?))",
                (cid, cid),
            )
        cur.execute("DELETE FROM files WHERE id=?", (file_id,))
        self.conn.commit()
        return True

    def add_embeddings(self, items: Iterable[tuple[int, list[float]]]) -> None:
        cur = self.conn.cursor()
        cur.executemany(
            "INSERT OR REPLACE INTO embeddings(chunk_id, dim, vector) VALUES(?,?,?)",
            [(cid, len(vec), vec_to_blob(vec)) for cid, vec in items],
        )
        self.conn.commit()

    def chunks_without_embedding(self, limit: int = 1000) -> list[tuple[int, str]]:
        return self.conn.execute(
            "SELECT c.id, c.text FROM chunks c "
            "LEFT JOIN embeddings e ON e.chunk_id = c.id "
            "WHERE e.chunk_id IS NULL LIMIT ?",
            (limit,),
        ).fetchall()

    # ---------- 검색 ----------

    def search_fts(self, query: str, limit: int = 50) -> list[ChunkHit]:
        """BM25 키워드 검색. 사용자 질의는 따옴표로 감싸 FTS 문법 오류를 방지한다."""
        terms = [t.replace('"', '""') for t in query.split() if t.strip()]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self.conn.execute(
            "SELECT c.id, f.path, c.seq, c.text, c.meta, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "JOIN files f ON f.id = c.file_id "
            "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
        return [
            ChunkHit(cid, path, seq, text, json.loads(meta), -rank)
            for cid, path, seq, text, meta, rank in rows
        ]

    def search_vector(self, query_vec: list[float], limit: int = 50) -> list[ChunkHit]:
        """코사인 유사도 전수 검색. 개인 코퍼스(수십만 청크)까지는 충분히 빠르다."""
        rows = self.conn.execute(
            "SELECT chunk_id, dim, vector FROM embeddings"
        ).fetchall()
        if not rows:
            return []
        dim = rows[0][1]
        mat = np.vstack([blob_to_vec(blob, d) for _, d, blob in rows if d == dim])
        ids = [cid for cid, d, _ in rows if d == dim]
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        mn = np.linalg.norm(mat, axis=1)
        denom = np.maximum(mn * qn, 1e-9)
        sims = (mat @ q) / denom
        order = np.argsort(-sims)[:limit]
        top = {ids[i]: float(sims[i]) for i in order}
        placeholders = ",".join("?" * len(top))
        rows2 = self.conn.execute(
            f"SELECT c.id, f.path, c.seq, c.text, c.meta FROM chunks c "
            f"JOIN files f ON f.id = c.file_id WHERE c.id IN ({placeholders})",
            list(top.keys()),
        ).fetchall()
        hits = [
            ChunkHit(cid, path, seq, text, json.loads(meta), top[cid])
            for cid, path, seq, text, meta in rows2
        ]
        hits.sort(key=lambda h: -h.score)
        return hits

    # ---------- 조회 ----------

    def get_chunk_with_neighbors(self, chunk_id: int, neighbors: int = 1) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT c.file_id, c.seq, f.path FROM chunks c "
            "JOIN files f ON f.id = c.file_id WHERE c.id=?",
            (chunk_id,),
        ).fetchone()
        if not row:
            return None
        file_id, seq, path = row
        rows = self.conn.execute(
            "SELECT id, seq, text FROM chunks WHERE file_id=? AND seq BETWEEN ? AND ? "
            "ORDER BY seq",
            (file_id, seq - neighbors, seq + neighbors),
        ).fetchall()
        return {
            "file_path": path,
            "center_seq": seq,
            "chunks": [{"chunk_id": cid, "seq": s, "text": t} for cid, s, t in rows],
        }

    def get_file_text(self, path: str) -> Optional[str]:
        rows = self.conn.execute(
            "SELECT c.text FROM chunks c JOIN files f ON f.id=c.file_id "
            "WHERE f.path=? ORDER BY c.seq",
            (path,),
        ).fetchall()
        if not rows:
            return None
        return "\n\n".join(r[0] for r in rows)

    def list_files(self, prefix: Optional[str] = None, status: Optional[str] = None,
                   limit: int = 200) -> list[dict]:
        sql = ("SELECT f.path, f.status, f.error, f.extractor, f.indexed_at, "
               "(SELECT COUNT(*) FROM chunks c WHERE c.file_id=f.id) FROM files f")
        cond, params = [], []
        if prefix:
            cond.append("f.path LIKE ?")
            params.append(prefix + "%")
        if status:
            cond.append("f.status = ?")
            params.append(status)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY f.path LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"path": p, "status": s, "error": e, "extractor": x,
             "indexed_at": t, "chunks": n}
            for p, s, e, x, t, n in rows
        ]

    def stats(self) -> dict:
        c = self.conn
        files_total = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        files_err = c.execute("SELECT COUNT(*) FROM files WHERE status='error'").fetchone()[0]
        chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = c.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        last = c.execute("SELECT MAX(indexed_at) FROM files").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "files_indexed": files_total,
            "files_error": files_err,
            "chunks": chunks,
            "chunks_embedded": embedded,
            "last_indexed_at": last,
            "meta": dict(c.execute("SELECT key, value FROM meta").fetchall()),
        }

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value)
        )
        self.conn.commit()
