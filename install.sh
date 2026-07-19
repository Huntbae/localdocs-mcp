#!/usr/bin/env bash
#
# localdocs-mcp — macOS 원커맨드 설치 스크립트
#
#   git clone https://github.com/Huntbae/localdocs-mcp.git
#   cd localdocs-mcp
#   ./install.sh                # 문서 검색(BM25+시맨틱) 설치
#   ./install.sh --with-ocr     # 이미지 OCR까지 (easyocr, 용량 큼)
#   ./install.sh --no-ollama    # 시맨틱 검색 없이 키워드(BM25)만
#
# 하는 일: uv/의존성 설치 → 가상환경 구성 → (선택) Ollama 설치·모델 다운로드·서비스 등록
#          → Claude Code에 MCP 등록(가능 시) → 스모크 테스트.
# 여러 번 실행해도 안전(idempotent).
set -euo pipefail

WITH_OCR=0
USE_OLLAMA=1
for arg in "$@"; do
  case "$arg" in
    --with-ocr) WITH_OCR=1 ;;
    --no-ollama) USE_OLLAMA=0 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "알 수 없는 옵션: $arg"; exit 1 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EMBED_MODEL="${LOCALDOCS_EMBED_MODEL:-bge-m3}"
say() { printf "\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()  { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }
warn(){ printf "\033[1;33m! %s\033[0m\n" "$1"; }

[ "$(uname)" = "Darwin" ] || { warn "이 스크립트는 macOS 전용입니다. 리눅스는 README 수동 설치 참고."; }

# 1) Homebrew --------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew가 없습니다. https://brew.sh 에서 먼저 설치한 뒤 다시 실행하세요."
  exit 1
fi
BREW_PREFIX="$(brew --prefix)"
export PATH="$BREW_PREFIX/bin:$PATH"
ok "Homebrew: $(brew --version | head -1)"

# 2) uv (파이썬 패키지·가상환경 관리자) -------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "uv 설치 중…"
  brew install uv
fi
ok "uv: $(uv --version)"

# 3) 가상환경 + 패키지 -----------------------------------------------------
say "가상환경(.venv) 및 패키지 설치…"
cd "$REPO_DIR"
uv venv --python 3.11 .venv >/dev/null
if [ "$WITH_OCR" = "1" ]; then
  uv pip install -p .venv/bin/python -e ".[ocr]"
else
  uv pip install -p .venv/bin/python -e "."
fi
BIN="$REPO_DIR/.venv/bin/localdocs-mcp"
ok "localdocs-mcp 설치됨: $BIN"

# 4) Ollama + 임베딩 모델 (시맨틱 검색) ------------------------------------
if [ "$USE_OLLAMA" = "1" ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    say "Ollama 설치 중…"
    brew install ollama
  fi
  ok "Ollama: $(ollama --version 2>/dev/null | head -1 || echo installed)"
  say "Ollama 서비스 등록/시작…"
  brew services start ollama >/dev/null 2>&1 || nohup ollama serve >/dev/null 2>&1 &
  # 서버 응답 대기(최대 30초)
  for _ in $(seq 1 30); do
    curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break || sleep 1
  done
  say "임베딩 모델 '$EMBED_MODEL' 다운로드(최초 1회, ~1.2GB)…"
  ollama pull "$EMBED_MODEL"
  ok "시맨틱 검색 준비 완료 (hybrid 모드)"
else
  warn "Ollama 생략 — 키워드(BM25) 검색만 동작합니다. 나중에 'brew install ollama && ollama pull $EMBED_MODEL' 후 '$BIN embed' 실행."
fi

# 5) Claude Code MCP 등록 (있으면 자동) ------------------------------------
if command -v claude >/dev/null 2>&1; then
  say "Claude Code에 MCP 등록…"
  claude mcp remove localdocs >/dev/null 2>&1 || true
  claude mcp add localdocs -- "$BIN" serve && ok "Claude Code 등록 완료 (localdocs)"
else
  warn "Claude Code CLI(claude) 미발견 — 수동 등록 안내는 아래 참고."
fi

# 6) 스모크 테스트 ---------------------------------------------------------
say "스모크 테스트…"
"$BIN" status >/dev/null && ok "정상 동작 확인"

cat <<EOF

──────────────────────────────────────────────
 설치 완료 🎉   로컬 Data MCP (localdocs-mcp)
──────────────────────────────────────────────
1) 별칭 등록(선택):
     echo 'alias ldocs="$BIN"' >> ~/.zshrc && source ~/.zshrc

2) 문서 인덱싱(폴더 지정):
     $BIN index ~/Documents ~/Desktop --no-images
   구글 드라이브 스트리밍 폴더라면 대형 데이터셋 제외 예:
     $BIN index "~/Library/CloudStorage/GoogleDrive-<메일>/내 드라이브" --no-images --exclude legalize-data

3) Claude Desktop을 쓰면 아래를 설정에 추가:
   ~/Library/Application Support/Claude/claude_desktop_config.json
     { "mcpServers": { "localdocs": { "command": "$BIN", "args": ["serve"] } } }

4) 확인:
     $BIN status
     $BIN search "검색어"

자세한 사용법: docs/INSTALL.ko.md
EOF
