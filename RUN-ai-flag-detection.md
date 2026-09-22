# 실행 가이드 — AI 커밋 감지 변경분 적용/검증

이 변경은 **판별 로직(`etl.py`)만** 바뀐 것이라 스키마 변경·마이그레이션이 없습니다.
아래 순서대로 하면 (1) 정상 동작 확인 → (2) 과거 커밋 재분류 → (3) 대시보드 확인 까지 됩니다.

전제: 이미 PoC 초기 세팅(가상환경·`.env`·DB)이 끝나 있어야 합니다. 아직이면 `README.md`의 "단계별 실행 순서"를 먼저 따르세요.

```bash
cd /Users/kor-sel-ck-mac/Desktop/Automation/ai_productivity
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

---

## 1) 문법·판별 규칙 빠른 검증 (API 호출 없음)

새 정규식이 진짜 케이스는 잡고 사람 이름은 거르는지 즉시 확인합니다.

```bash
python -c "
import etl
cases = {
  'Assisted-By':              'feat: x\n\nAssisted-By: claude',
  'Claude co-author':         'fix: y\n\nCo-authored-by: Claude <noreply@anthropic.com>',
  'Claude 모델명 co-author':  'fix: z\n\nCo-authored-by: Claude Opus 4.8 <noreply@anthropic.com>',
  'anthropic 이메일':          'chore\n\nCo-authored-by: Bot <noreply@anthropic.com>',
  'Claudia(사람) 오탐방지':   'docs\n\nCo-authored-by: Claudia Kim <claudia@corp.com>',
  '트레일러 없음':             'plain message',
}
for name, msg in cases.items():
    print(f'{etl.parse_commit_flags(msg).ai_flag!s:5}  {name}')
"
```

**기대 결과**: 앞 4개 `True`, `Claudia`·`트레일러 없음`은 `False`.

---

## 2) ETL 재실행 — 새 규칙으로 데이터 반영

### 2-a) 증분 실행 (신규/변경 커밋만)

```bash
python etl.py
```

`_upsert_bb_commit`의 `ON CONFLICT ... DO UPDATE ai_flag=excluded.ai_flag` 덕분에,
이번에 다시 가져오는 커밋은 새 규칙으로 재분류됩니다.

### 2-b) 과거 커밋까지 재분류 (백필) — 권장

`etl.py`는 `last_synced` 이후 커밋만 가져오므로, 이미 DB에 있는 과거 커밋은 그대로 남습니다.
과거분까지 새 규칙을 소급 적용하려면 Bitbucket 동기화 상태를 초기화해 최근 90일치를 다시 받습니다.

```bash
# Bitbucket sync 상태만 리셋 → 다음 실행 시 90일치 재수집·재분류
sqlite3 data.sqlite "DELETE FROM sync_state WHERE source LIKE 'bitbucket:%';"
python etl.py
```

> `data.sqlite` 대신 다른 경로를 `.env`의 `DB_PATH`로 지정했다면 그 경로를 사용하세요.
> 리셋 전 백업이 필요하면: `cp data.sqlite data.sqlite.bak`

### (선택) 재분류 결과 눈으로 확인

```bash
sqlite3 data.sqlite "
SELECT
  SUM(ai_flag)              AS ai_commits,
  COUNT(*)                  AS total_commits,
  ROUND(100.0*SUM(ai_flag)/COUNT(*), 1) AS ai_pct
FROM commits;"
```

---

## 3) 대시보드에서 확인

```bash
streamlit run dashboard.py
```

브라우저가 `http://localhost:8501`로 열립니다. 사이드바에서 기간/팀/저장소를 고르고
AI 지원 비율 차트가 갱신되는지 확인하세요.

---

## 롤백

이 변경은 코드 3곳(정규식 추가·`parse_commit_flags`의 OR·docstring)과 README 문구뿐입니다.

- 코드를 되돌리려면 `etl.py`의 `CO_AUTHORED_CLAUDE_RE` 관련 부분을 제거하고
  `ai_flag = bool(ASSISTED_BY_RE.search(message))` 로 되돌립니다.
- 그 뒤 위 **2-b) 백필**을 다시 실행하면 데이터도 이전 기준으로 재분류됩니다.
