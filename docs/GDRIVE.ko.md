# Model B — 구글 드라이브 자립형 인덱싱 (rclone)

파일을 드라이브에 둔 채, **텍스트만 받아** 인덱싱하는 방식입니다. 어시스턴트(LLM)를 거치지 않고 `rclone`이 Drive API로 파일을 직접 받아(고장난 스트리밍 마운트 우회) 로컬 파서로 추출하므로:

- **세션/토큰 한도와 무관** — 수백~수천 개도 한 번에 처리
- **모든 형식** — pdf·docx·pptx·xlsx는 물론 **hwp/hwpx까지** 로컬 파서로 복구
- **파일은 드라이브에 그대로** — 임시로만 받아 추출 후 삭제
- **자동화 가능** — cron으로 주기 동기화

민감 파일(recovery-codes, private_key 등)은 여기서도 자동 제외됩니다.

---

## 1. rclone 설치 + Google Drive 원격 설정 (1회)

```bash
brew install rclone
rclone config
```

`rclone config` 대화형 진행(GCP 콘솔 설정 불필요 — rclone 기본 클라이언트 사용):

| 프롬프트 | 입력 |
|---|---|
| `n/s/q` | `n` (새 원격) |
| `name>` | `gdrive` |
| `Storage>` | `drive` 항목의 번호 (Google Drive) |
| `client_id>` | 빈칸 (Enter) |
| `client_secret>` | 빈칸 (Enter) |
| `scope>` | `drive.readonly` 항목 번호 (읽기 전용이면 충분·안전) |
| `root_folder_id>` | 빈칸 |
| `service_account_file>` | 빈칸 |
| `Edit advanced config?` | `n` |
| `Use auto config?` | `y` → 브라우저가 열림 → **huntbae@huntbae.com로 동의** |
| `Configure this as a Shared Drive?` | `n` (내 드라이브 대상) |
| 확인 | `y` → `q`로 종료 |

확인:
```bash
rclone lsd gdrive:            # 내 드라이브 최상위 폴더 목록이 나오면 성공
```

---

## 2. 실패 파일 복구 실행

`gdrive:`가 **내 드라이브 루트**를 가리키므로, 대응하는 로컬 마운트 경로를 `--local-root`로 줍니다.

```bash
BIN=~/Projects/localdocs-mcp/.venv/bin/localdocs-mcp
ROOT="$HOME/Library/CloudStorage/GoogleDrive-huntbae@huntbae.com/내 드라이브"

$BIN gdrive-recover --remote gdrive: --local-root "$ROOT"
```

- 현재 `error` 상태이고 `내 드라이브` 하위인 파일을 전부 rclone로 받아 재인덱싱하고, 끝나면 임베딩까지 수행합니다.
- 오래 걸리면 백그라운드로:
  ```bash
  nohup $BIN gdrive-recover --remote gdrive: --local-root "$ROOT" \
        >> ~/.localdocs-mcp/gdrive.log 2>&1 &
  tail -f ~/.localdocs-mcp/gdrive.log
  ```
- 진행/결과 확인: `$BIN status`

> **공유 드라이브(공유 드라이브)** 는 별도 원격이 필요합니다. `rclone config`에서 "Shared Drive"로 하나 더 만든 뒤(예: `gdriveshared:`), 해당 `--local-root`로 다시 실행하세요.

---

## 3. (선택) 주기 자동 동기화

```bash
crontab -e
# 매일 새벽 3시, 내 드라이브의 새로 실패/변경분 복구
0 3 * * * ~/Projects/localdocs-mcp/.venv/bin/localdocs-mcp gdrive-recover \
  --remote gdrive: --local-root "$HOME/Library/CloudStorage/GoogleDrive-huntbae@huntbae.com/내 드라이브" \
  >> ~/.localdocs-mcp/gdrive.log 2>&1
```

---

## 왜 이 방식인가 (배경)

Claude 커넥터로 문서 텍스트를 받는 방식(Model A)은 텍스트가 전부 어시스턴트의 컨텍스트를 거쳐, 수백 개를 처리하면 **세션 토큰 한도**에 걸립니다. Model B는 rclone이 텍스트를 **로컬로 직접** 가져와 SQLite에 넣으므로 이 병목이 없습니다.

| | Model A (커넥터) | Model B (rclone) |
|---|---|---|
| 규모 | 수십 개 한계(세션 한도) | 수천 개 OK |
| hwp/hwpx | ✗ (API 미지원) | ✓ (로컬 파서) |
| 설정 | 없음 | rclone 1회 인증 |
| 자동화 | 어려움 | cron 가능 |
