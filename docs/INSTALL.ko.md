# 로컬 Data MCP (localdocs-mcp) — 설치·사용 가이드 (macOS)

내 컴퓨터의 문서(txt·pdf·docx·pptx·xlsx·hwp·hwpx·이미지)를 인덱싱해서, Claude(또는 임의의 MCP 클라이언트)가 **하이브리드(키워드 BM25 + 의미 시맨틱) 검색**으로 내부 자료를 찾아 인용하게 하는 100% 로컬 시스템입니다. 파일은 제자리에 두고, 데이터는 기기 밖으로 나가지 않습니다.

이 문서는 **새 맥(예: 맥북프로)에 처음부터 설치**하는 전체 과정을 담습니다.

---

## 0. 한눈에 (원커맨드 설치)

```bash
git clone https://github.com/Huntbae/localdocs-mcp.git
cd localdocs-mcp
./install.sh                 # 표준 설치 (문서 + 시맨틱 검색)
# ./install.sh --with-ocr    # 이미지 OCR 포함(용량 큼)
# ./install.sh --no-ollama   # 키워드(BM25) 검색만
```

스크립트가 uv·의존성·가상환경·Ollama·임베딩 모델·Claude Code 등록·스모크 테스트까지 자동으로 처리합니다. 여러 번 실행해도 안전합니다.

설치가 끝나면 [2. 인덱싱](#2-인덱싱)으로.

---

## 1. 수동 설치 (스크립트 대신 단계별로)

### 1-1. 사전 준비
- **Homebrew** — 없으면 https://brew.sh
- **uv** — `brew install uv`

### 1-2. 패키지 설치
```bash
git clone https://github.com/Huntbae/localdocs-mcp.git
cd localdocs-mcp
uv venv --python 3.11 .venv
uv pip install -p .venv/bin/python -e .          # 기본
# uv pip install -p .venv/bin/python -e ".[ocr]" # 이미지 OCR 포함
```
설치 위치: `.venv/bin/localdocs-mcp` (이하 편의상 `ldocs`로 표기)
```bash
alias ldocs="$PWD/.venv/bin/localdocs-mcp"
```

### 1-3. 시맨틱 검색용 Ollama (선택이지만 권장)
```bash
brew install ollama
brew services start ollama     # 재부팅 후에도 자동 실행
ollama pull bge-m3             # 한국어 강한 다국어 임베딩(최초 1회 ~1.2GB)
```
Ollama가 없어도 **키워드(BM25) 검색은 완전히 동작**합니다. 나중에 켜고 `ldocs embed`만 하면 시맨틱까지 활성화됩니다.

---

## 2. 인덱싱

### 2-1. 로컬 폴더
```bash
ldocs index ~/Documents ~/Desktop --no-images    # 증분(바뀐 파일만 재처리)
ldocs status                                      # 파일/청크/임베딩/검색모드
ldocs search "검색어"                              # 동작 확인
```

### 2-2. 구글 드라이브 (스트리밍 마운트)
드라이브 데스크톱 앱을 쓰면 파일이 `~/Library/CloudStorage/GoogleDrive-<메일>/` 아래에 있습니다.
```bash
ROOT=~/Library/CloudStorage/GoogleDrive-<메일>
ldocs index "$ROOT/내 드라이브" "$ROOT/공유 드라이브" --no-images --exclude legalize-data
```
- `--no-images` : 이미지 OCR 제외(문서 먼저 빠르게). 이미지는 나중에 `--only-images`로.
- `--exclude <문자열>` : 경로에 해당 문자열이 든 폴더 통째 제외(대형 데이터셋 분리용).
- 대량 인덱싱은 오래 걸리므로 백그라운드 권장:
  ```bash
  nohup ldocs index "$ROOT/내 드라이브" --no-images >> ~/.localdocs-mcp/index.log 2>&1 &
  ```

> **주의 — 스트리밍(온라인 전용) 파일**: 드라이브 파일이 로컬에 내려받아져 있지 않으면 읽을 때 다운로드가 발생하며, 앱 상태에 따라 타임아웃될 수 있습니다. 안 되는 파일이 많으면 대상 폴더를 드라이브 앱에서 **"오프라인 사용 설정"** 후 재인덱싱하거나, [부록 A의 Drive API 방식](#부록-a--구글-드라이브-api로-텍스트만-받아-인덱싱)을 쓰세요.

### 2-3. 실패 파일 다루기
```bash
ldocs status                        # files_error 개수
ldocs retry-errors                  # 일시적 실패(타임아웃 등) 재시도
```
`hwp/hwpx`는 자체 파서로 처리하지만 구버전·암호화 문서는 실패할 수 있습니다. 실패는 사유와 함께 기록되며 검색에는 영향 없습니다.

---

## 3. Claude에 연결

### Claude Code (터미널)
```bash
claude mcp add localdocs -- "$PWD/.venv/bin/localdocs-mcp" serve
```

### Claude Desktop
`~/Library/Application Support/Claude/claude_desktop_config.json` 에 추가 후 앱 재시작:
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

이제 자연어로 물어보면 됩니다: *"작년 사업계획서에서 가격 조건 찾아줘"* → Claude가 `search_documents`로 근거를 찾아 **파일 경로를 출처로** 답합니다.

---

## 4. 맥북프로 등 두 번째 기기에 설치할 때

이 도구의 인덱스(`~/.localdocs-mcp/index.db`)는 **로컬 파일 경로 기준**이라 기기마다 다릅니다. 그래서 각 기기에서 따로 인덱싱하는 것이 정석입니다.

1. 맥북프로에서 `git clone … && ./install.sh` (위 0번).
2. 그 기기의 폴더/드라이브 마운트를 `ldocs index …`로 인덱싱.
3. Claude Code/Desktop 등록.

> 인덱스 DB를 그대로 복사해 오면 경로가 안 맞아 동작하지 않습니다. 코드/설정만 공유하고 인덱싱은 기기별로 하세요. (드라이브를 두 기기에서 같은 경로로 마운트한다면 재사용 가능하지만 일반적으로 권장하지 않습니다.)

---

## 5. 유지보수

```bash
ldocs status            # 통계·검색 모드
ldocs prune             # 삭제된 파일 인덱스에서 제거
ldocs embed             # 임베딩 누락분 채우기(Ollama 필요)
git pull && ./install.sh   # 업데이트
```

주기적 자동 인덱싱(예: 매시간):
```bash
crontab -e
0 * * * * /절대경로/.venv/bin/localdocs-mcp index ~/Documents --no-images >> ~/.localdocs-mcp/cron.log 2>&1
```

---

## 6. MCP 도구 목록

| 도구 | 설명 |
|---|---|
| `search_documents(query, top_k, path_prefix, file_suffix)` | 하이브리드 검색(경로·확장자 필터 지원) |
| `get_chunk_context(chunk_id, neighbors)` | 검색된 청크의 앞뒤 문맥 |
| `get_document(path, max_chars, offset)` | 문서 전문 읽기 |
| `list_indexed_files(path_prefix, only_errors, limit)` | 인덱스 목록·실패 사유 |
| `index_path(path)` | 파일/소규모 폴더 즉시 인덱싱 |
| `index_status()` | 통계·Ollama 가용성·검색 모드 |

---

## 7. 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LOCALDOCS_DB` | `~/.localdocs-mcp/index.db` | 인덱스 DB 경로(여러 인덱스 분리 시 지정) |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 주소 |
| `LOCALDOCS_EMBED_MODEL` | `bge-m3` | 임베딩 모델 |
| `LOCALDOCS_CHUNK_MAX_CHARS` | `1200` | 청크 최대 길이 |
| `LOCALDOCS_MAX_FILE_MB` | `100` | 이 크기 초과 파일은 건너뜀 |

여러 인덱스 분리 예(개인 문서 vs 대형 데이터셋):
```bash
LOCALDOCS_DB=~/.localdocs-mcp/legalize.db ldocs search "…"   # 별도 인덱스 조회
```

---

## 8. 보안·프라이버시

- **100% 로컬 · stdio 전용** — 서버가 네트워크 포트를 열지 않습니다.
- **민감 파일 자동 제외** — `recovery-codes`, `private_key`, `id_rsa`, `mnemonic`, `credentials.json` 등 자격증명 패턴 파일은 인덱싱하지 않습니다(`config.SENSITIVE_NAME_PATTERNS`).
- 이미 인덱싱된 민감 파일을 빼려면: `ldocs` 로 검색해 경로 확인 후 재인덱싱 전 해당 파일 삭제, 또는 `--exclude` 사용.

---

## 9. 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| `search_mode: bm25-only` | Ollama 미실행 → `brew services start ollama`, 모델 없으면 `ollama pull bge-m3`, 그 후 `ldocs embed` |
| 드라이브 파일 다수 타임아웃 | 스트리밍 온라인 전용 상태. 드라이브 앱 재시작 또는 대상 폴더 "오프라인 사용 설정" 후 `ldocs retry-errors`. 근본 우회는 [부록 A](#부록-a--구글-드라이브-api로-텍스트만-받아-인덱싱) |
| hwp 인덱싱 실패 | 구버전(HWP3)·암호화 문서는 미지원. 한컴오피스에서 hwpx로 저장 후 재인덱싱 |
| 첫 인덱싱이 오래 걸림 | OCR·대형 폴더 제외(`--no-images`, `--exclude`)하고 백그라운드 실행 |

---

## 부록 A — 구글 드라이브 API로 텍스트만 받아 인덱싱

드라이브 앱의 온디맨드 다운로드가 불안정하거나, **파일을 로컬에 내려받지 않고** 필요한 텍스트만 받고 싶을 때의 방식입니다. Google이 서버측에서 PDF·Office·Google문서(Docs/Sheets/Slides)·이미지(OCR) 텍스트를 추출해 주므로 로컬 다운로드가 필요 없습니다. (hwp/한글은 API 미지원 → 로컬 파서 또는 pdf/docx로 export)

- **방법 1 (설정 0)**: Claude 세션에 연결된 **Google Drive 커넥터**로 텍스트를 받아 인덱스에 넣습니다. 소량엔 편하지만, 텍스트가 어시스턴트 컨텍스트를 거쳐 **대량 처리 시 세션 토큰 한도**에 걸립니다.
- **방법 2 (권장·구현됨) — rclone 자립형**: `localdocs-mcp gdrive-recover`. rclone이 Drive API로 파일을 로컬로 직접 받아 추출→인덱싱하므로 세션 한도 무관, **hwp까지 전부** 복구, cron 자동화 가능. 설정·사용법은 **[docs/GDRIVE.ko.md](GDRIVE.ko.md)**.

> 이 방식은 파일 내용을 Google 서버가 처리하므로(본인 소유 드라이브 범위) "완전 로컬" 원칙에서는 벗어납니다. 민감 파일은 위 8번대로 계속 자동 제외됩니다.
