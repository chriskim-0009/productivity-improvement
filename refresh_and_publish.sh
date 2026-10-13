#!/bin/zsh
# =============================================================================
# refresh_and_publish.sh
# ETL 실행 → 최신 data.sqlite를 Streamlit 배포 저장소로 복사 → 변경 시 커밋·push.
# launchd LaunchAgent(com.doverunner.productivity-etl)가 매시간 호출한다.
# git push 자격증명은 osxkeychain 캐시 사용(사용자 세션에서 실행되어 접근 가능).
# 오프라인/절전 시엔 아래 네트워크 사전점검으로 빠르게 건너뛴다.
# =============================================================================

PROJ="/Users/kor-sel-ck-mac/ai_productivity"
DEPLOY="/Users/kor-sel-ck-mac/ai_productivity_streamlit_deploy"
LOG="$PROJ/refresh_publish.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $1" >> "$LOG"; }

log "===== 시작 ====="

# 실행 위치(cwd)에 무관하게 동작하도록 프로젝트 폴더로 이동
cd "$PROJ" || { log "프로젝트 폴더 접근 실패: $PROJ"; exit 1; }

# 0) 네트워크/DNS 사전 점검 — 오프라인·절전 시 길게 매달리지 않고 빠르게 건너뜀(정상 종료)
if ! nslookup doverunner.atlassian.net >/dev/null 2>&1; then
  log "네트워크/DNS 불가(doverunner.atlassian.net 해석 실패) — 이번 실행 건너뜀."
  log "===== 종료 ====="
  exit 0
fi

# 1) ETL — 로컬 data.sqlite 최신화
if "$PROJ/.venv/bin/python" "$PROJ/etl.py" >> "$PROJ/etl.log" 2>&1; then
  log "ETL 완료"
else
  log "ETL 실패 — etl.log 확인. 이후 단계 중단."
  log "===== 종료 ====="
  exit 1
fi

# 2) 스냅샷을 배포 저장소로 복사 (임시 파일 제외)
cp "$PROJ/data.sqlite" "$DEPLOY/data.sqlite"
rm -f "$DEPLOY"/data.sqlite-wal "$DEPLOY"/data.sqlite-shm "$DEPLOY"/data.sqlite-journal

# 3) 데이터가 바뀌었을 때만 커밋·push
cd "$DEPLOY" || { log "배포 폴더 접근 실패"; exit 1; }
if [ -n "$(git status --porcelain data.sqlite)" ]; then
  git add data.sqlite
  git commit -m "자동 데이터 스냅샷 갱신 $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1
  if GIT_TERMINAL_PROMPT=0 git push origin main >> "$LOG" 2>&1; then
    log "push 성공 — 클라우드 재배포됨"
  else
    log "push 실패(자격증명/네트워크). 로컬·GitHub 커밋은 됐으나 원격 반영 안 됨."
  fi
else
  log "데이터 변경 없음 — push 생략"
fi

log "===== 종료 ====="
