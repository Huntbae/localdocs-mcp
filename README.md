# localdocs-mcp

**100% 로컬 문서 검색 MCP 서버** — 내 컴퓨터의 txt / pdf / docx / pptx / xlsx / hwp / hwpx / 이미지를 인덱싱하고, Claude(또는 임의의 MCP 클라이언트)가 하이브리드(BM25 + 시맨틱) 검색으로 내부 자료를 찾아 인용하게 합니다.

파일은 제자리에 둡니다. 데이터는 기기 밖으로 나가지 않습니다.

```
"작년 전기카트 제안서에서 가격 조건 찾아줘"
  → Claude가 search_documents 호출
  → ~/Documents/제안서.docx 3번 청크 인용과 함께 답변
```

## 특징

- **한국 문서 네이티브**: HWP 5.0(바이너리)과 HWPX를 외부 프로그램 없이 자체 파서로 추출 (macOS에선 레거시 .doc/.rtf도 textutil로 지원)
- **하이브리드 검색**: SQLite FTS5(BM25) + bge-m3 임베딩 코사인 유사도를 RRF로 병합 — 고유명사·파일명 검색과 의미 검색을 모두 잡음
- **단일 저장소**: 파일 메타·청크·FTS·벡터를 SQLite 한 개 DB에 트랜잭션으로 저장 — 벡터DB/검색인덱스 이중화로 인한 동기화 불일치가 구조적으로 없음
- **우아한 성능 저하(graceful degradation)**: Ollama가 없거나 꺼져 있어도 BM25 검색으로 정상 동작. 임베딩은 나중에 `embed`로 백필
- **침묵 실패 금지**: 파싱 실패 파일은 사유와 함께 기록되고 `index_status` / `list_indexed_files(only_errors=true)`로 확인 가능
- **최소 의존성**: docx/pptx/xlsx/hwpx는 표준 라이브러리(zip+XML)로 직접 파싱. 필수 의존성은 `mcp`, `pypdf`, `olefile`, `numpy`, `httpx` 뿐
- **stdio 전용**: 네트워크 포트를 열지 않아 MCP 스펙의 인증 공백 이슈를 원천 회피

## 설치

**원커맨드(macOS)** — uv·의존성·Ollama·모델·Claude 등록까지 자동:

```bash
git clone https://github.com/Huntbae/localdocs-mcp.git
cd localdocs-mcp
./install.sh                 # 표준(문서 + 시맨틱 검색)
# ./install.sh --with-ocr    # 이미지 OCR 포함
# ./install.sh --no-ollama   # 키워드(BM25)만
```

전체 설치·사용·두 번째 기기(맥북프로) 설치·트러블슈팅은 **[docs/INSTALL.ko.md](docs/INSTALL.ko.md)** 참고.

수동 설치:

```bash
uv venv --python 3.11 && uv pip install -e .

# 선택: 이미지 OCR (easyocr, 용량 큼)
uv pip install -e ".[ocr]"
```

시맨틱 검색을 쓰려면 [Ollama](https://ollama.com) 설치 후:

```bash
ollama pull bge-m3
```

Ollama 없이도 키워드(BM25) 검색은 완전히 동작합니다.

## 사용법

### 1. 인덱싱 (CLI)

```bash
# 폴더 인덱싱 (증분 — 변경된 파일만 다시 처리)
localdocs-mcp index ~/Documents ~/Desktop/자료

# 상태 확인 (실패 파일 수, 임베딩 진행률, 검색 모드)
localdocs-mcp status

# 검색 동작 확인
localdocs-mcp search "전기카트 보조금"

# 삭제된 파일 정리 / 임베딩 백필
localdocs-mcp prune
localdocs-mcp embed
```

### 2. Claude Desktop 등록

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "localdocs": {
      "command": "/절대경로/localdocs-mcp/.venv/bin/localdocs-mcp",
      "args": ["serve"]
    }
  }
}
```

### 3. Claude Code 등록

```bash
claude mcp add localdocs -- /절대경로/localdocs-mcp/.venv/bin/localdocs-mcp serve
```

## MCP 툴

| 툴 | 설명 |
|---|---|
| `search_documents(query, top_k, path_prefix, file_suffix)` | 하이브리드 검색. 결과에 파일 경로·청크·점수·인덱스 신선도 포함 |
| `get_chunk_context(chunk_id, neighbors)` | 검색된 청크의 앞뒤 문맥 확장 |
| `get_document(path, max_chars, offset)` | 문서 전문 읽기(긴 문서는 이어 읽기) |
| `list_indexed_files(path_prefix, only_errors, limit)` | 인덱스 목록·실패 파일 사유 조회 |
| `index_path(path)` | 파일/소규모 폴더 즉시 (재)인덱싱 |
| `index_status()` | 파일/청크/임베딩 통계, Ollama 가용성, 검색 모드 |

## 아키텍처

```
파일 (txt/pdf/docx/pptx/xlsx/hwp/hwpx/이미지)
  → 추출기 (stdlib zip+XML, pypdf, 자체 HWP5 파서, textutil, easyocr*)
  → 청킹 (문단 경계 존중, 1200자, 150자 오버랩, 페이지/슬라이드 메타)
  → SQLite 단일 DB
      ├ files / chunks        (원문·출처·실패 기록)
      ├ chunks_fts (FTS5)     (BM25 키워드 검색)
      └ embeddings (BLOB)     (bge-m3 벡터, 없어도 동작)
  → MCP 서버 (FastMCP, stdio) — 검색·조회 전용 얇은 계층
                                 * = 선택 설치
```

운영 원칙: **무거운 인덱싱은 CLI(또는 cron/launchd), MCP 서버는 검색만.**

주기적 자동 인덱싱 예시 (macOS launchd 대신 crontab):

```bash
# 매시간 증분 인덱싱
0 * * * * /절대경로/.venv/bin/localdocs-mcp index ~/Documents >> ~/.localdocs-mcp/cron.log 2>&1
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LOCALDOCS_DB` | `~/.localdocs-mcp/index.db` | 인덱스 DB 경로 |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 주소 |
| `LOCALDOCS_EMBED_MODEL` | `bge-m3` | 임베딩 모델 (`bona/bge-m3-korean` 등으로 교체 가능) |
| `LOCALDOCS_CHUNK_MAX_CHARS` | `1200` | 청크 최대 길이 |
| `LOCALDOCS_MAX_FILE_MB` | `100` | 이 크기 초과 파일은 건너뜀 |

## 설계 결정 (방법론 재검토 반영)

초기 설계안 대비 다음 문제를 식별하고 수정했습니다:

1. **ChromaDB + SQLite 이중 저장소 → SQLite 단일화.** 두 저장소는 재인덱싱·삭제 시 동기화 드리프트가 필연적. 개인 코퍼스 규모(수십만 청크)에서는 numpy 전수 코사인이 충분히 빠르므로 벡터DB 자체를 제거.
2. **Ollama 하드 의존 → 선택적 구성요소.** 임베딩 불가 시 BM25 단독 모드로 자동 전환하고 `status`에 모드를 명시.
3. **markitdown/kordoc 등 무거운 변환기 의존 → stdlib 우선.** docx/pptx/xlsx/hwpx는 ZIP+XML이므로 직접 파싱. HWP 5.0도 olefile+zlib로 자체 구현(PrvText 폴백 포함). 외부 도구는 선택 설치로 강등.
4. **인덱서와 서버 결합 → 분리.** 첫 인덱싱은 수 시간이 걸릴 수 있어 MCP 요청 경로에서 제거.
5. **실패 침묵 → 실패 기록 의무화.** HWP 구버전 등 파싱 실패는 반드시 발생하므로 파일 단위로 사유를 남기고 조회 툴을 제공.
6. **인덱스 신선도 미표기 → 검색 응답에 `index_freshness` 포함.** LLM이 오래된 결과임을 인지하고 답변에 반영 가능.

## 로드맵

- [ ] 스캔 PDF OCR 파이프라인 (텍스트 레이어 없는 PDF 자동 감지 → OCR)
- [ ] 이미지 캡셔닝 (로컬 비전 LLM로 사진류 인덱싱)
- [ ] 재랭킹 (bge-reranker) 옵션
- [ ] watchdog 기반 실시간 폴더 감시 데몬
- [ ] 검색 품질 평가 하네스 (질의-정답 셋 회귀 테스트)

## 개발

```bash
uv pip install -e ".[dev]"
.venv/bin/pytest
```

## 라이선스

MIT
