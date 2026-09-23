# Claude 생산성 대시보드 — 운영·현황 가이드

> 이 문서는 지금까지 구축한 시스템의 **전체 구조·배포·자동화·운영 방법**을 정리한 핸드오프 문서입니다.
> 세부 변경 이력과 제안 커밋 메시지는 [CHANGES-ai-flag-detection.md](CHANGES-ai-flag-detection.md), 설계 결정은 [ADR-001-claude-productivity-dashboard.md](ADR-001-claude-productivity-dashboard.md) 참고.

- **최종 갱신**: 2026-09-23
- **상태**: 라이브 배포 완료 + 시간당 자동 갱신 정상 동작 (Lead time·PR 사이클 소표본 가드 적용)

---

## 1. 개요

AI 어시스턴트(Claude Code) 도입이 팀 개발 흐름에 주는 효과를 **Jira + Bitbucket 데이터로 팀 단위로 진단**하는 Streamlit 대시보드입니다. 개인 평가가 아닌 팀·저장소 단위 진단 도구입니다.

- **라이브 대시보드(Streamlit Cloud)**: `https://chriskim-0009-k6vetyecjymgwffpnwanvj.streamlit.app`
- **팀 공유용 요약 페이지(Artifact, KR/EN)**: `https://claude.ai/code/artifact/3d78a28e-5c2a-46b8-a316-e48042672eb3`
- **소스(로컬)**: `~/Desktop/Automation/ai_productivity/`
- **배포 저장소(로컬)**: `~/Desktop/ai_productivity_streamlit_deploy/`
- **GitHub(비공개)**: `chriskim-0009/productivity-improvement`

---

## 2. 데이터 흐름

```
[Jira: AS, AR]  [Bitbucket: appsealing 워크스페이스]
        \               /
         v             v
        etl.py  ──►  data.sqlite (로컬 SQLite)
         │              │
         │              └─► dashboard.py (로컬 Streamlit)  ← 개발/확인용
         │
   refresh_and_publish.sh (cron, 매시)
         │  etl → data.sqlite 복사 → 커밋 → push
         v
   GitHub 비공개 저장소 (data.sqlite 스냅샷)
         v
   Streamlit Community Cloud (자동 재배포) ── 팀이 보는 라이브 대시보드
```

핵심: **클라우드 대시보드는 GitHub에 push된 `data.sqlite` 스냅샷을 읽습니다.** 로컬 ETL만으로는 반영되지 않으며, 스냅샷 push가 있어야 갱신됩니다(이 push를 cron이 자동화).

---

## 3. 주요 파일

| 파일 | 역할 |
|---|---|
| `etl.py` | Jira·Bitbucket 수집 → `data.sqlite` 적재 |
| `dashboard.py` | Streamlit 대시보드 (독립 실행, `data.sqlite`만 읽음) |
| `schema.sql` | DB 스키마 |
| `refresh_and_publish.sh` | 자동화: ETL → 스냅샷 복사 → 커밋 → push |
| `.env` | 접속 정보·설정 (토큰 포함, 커밋 금지) |
| `refresh_publish.log` | 자동화 실행 로그 |
| `etl.log` | ETL 실행 로그 |
| `data.sqlite` | 로컬 데이터 |
| `~/Desktop/ai_productivity_streamlit_deploy/` | 배포 저장소(클라우드가 읽는 스냅샷) |

---

## 4. 이번 작업에서 한 것

### 4-1. 수집·감지 로직 (`etl.py`)
- **AI 커밋 2중 감지**: `Assisted-By: claude` + Claude Code가 자동으로 남기는 `Co-authored-by: Claude` 트레일러 모두 인식(훅 미설치여도 잡힘).
- **develop 브랜치 수집 + 폴백**: 팀 컨벤션(develop)을 따르되, develop이 없는 저장소는 기본 브랜치(master)로 자동 폴백(`BRANCH_FALLBACK`).
- **저장소 자동 탐색**: `BITBUCKET_WORKSPACE`+`BITBUCKET_PROJECTS`(AS,AR)의 활성 저장소를 매 실행마다 자동 포함(신규 저장소 자동 편입).
- **Jira 타임스탬프 정규화**: `+0900`→`+09:00`으로 저장해 SQLite `date()` 파싱 가능하게(대시보드 집계 정상화).
- **Jira 키 정규식 제한**: `JIRA_PROJECTS` 접두사만 인식 → `SHA-256`·`CWE-*` 등 오탐 제거.
- **`daily_quality` 전체 재생성**: 매 실행마다 commits 전체에서 재집계 → ETL 공백에 따른 빈 구간 원천 차단.

### 4-2. 대시보드 UX (`dashboard.py`)
- **팀 미지정 `(미지정)` 버킷**: component 없는 이슈(다수)도 표시되도록 필터 보정.
- **AI/Human 색상 구분**: AI-assisted=teal, Human only=charcoal.
- **"참조된 저장소" 섹션**: 저장소별 커밋·AI·PR 표(사이드바 필터 연동).
- **결함률 제거**: 이슈 타입 비율일 뿐 AI 진단과 무관해 KPI·탭에서 삭제.
- **`?` 도움말 툴팁**: KPI·차트 탭에 지표 설명(마우스 오버, KR/EN).
- **탭 가독성 수정**: 선택 탭의 "검정 위 검정" 문제 해결.
- **소표본 가드(Lead time · PR 사이클)**: AI-연결 표본이 적어 소수 이슈/이상치(예: `AS-23469` 1,086h)로 주간 중앙값이 급등하던 문제 방지. **주별 표본 3건 미만인 점은 생략**하고 각 점에 표본 수(n)를 hover로 노출. 임계값은 각 탭의 `min_sample`(기본 3)로 조정.

### 4-3. 일회성 데이터 마이그레이션
- 타임스탬프 정규화 백필(issues 1508, transitions 2531).
- `jira_keys` 재파싱(오탐 47건 제거).
- `daily_quality` 전체 재생성.
> 신규 환경에선 수정된 `etl.py`가 처음부터 올바르게 적재하므로 백필 불필요.

### 4-4. 배포 & 자동화
- Streamlit Community Cloud 배포(비공개 GitHub 저장소 연동).
- cron + `refresh_and_publish.sh`로 시간당 자동 갱신.

---

## 5. 배포 구조 (Streamlit Cloud)

- 배포 폴더(`ai_productivity_streamlit_deploy`)에는 클라우드 구동에 필요한 것만: `dashboard.py`, `data.sqlite`, `requirements.txt`(슬림), `.streamlit/config.toml`, `.gitignore`, `DEPLOY.md`.
- **토큰 불필요**: 대시보드는 `data.sqlite`만 읽으므로 클라우드에 secrets 설정이 없습니다.
- **비공개 유지 필수**: `data.sqlite`에 내부 데이터(이슈 제목·커밋 메시지·저장소명)가 포함 → 저장소는 private, 앱은 **뷰어 인증**으로 팀 제한 권장.
- 최초 배포 절차 상세는 [DEPLOY.md](../ai_productivity_streamlit_deploy/DEPLOY.md).

---

## 6. 자동화 (cron)

```
0 * * * * /Users/kor-sel-ck-mac/Desktop/Automation/ai_productivity/refresh_and_publish.sh
```
스크립트 동작: `etl.py` 실행 → `data.sqlite`를 배포 폴더로 복사 → **데이터 변경 시에만** 커밋·`git push` → Streamlit Cloud 자동 재배포. 로그는 `refresh_publish.log`.

- push 자격증명은 macOS **osxkeychain 캐시**를 사용(과거 수동 push 시 저장됨).
- 데이터 무변경 시 push 생략, ETL 실패 시 이후 단계 중단 및 로그 기록.
- **중요(경로)**: `.env`의 `DB_PATH`는 반드시 **절대경로**여야 합니다. 상대경로(`./data.sqlite`)면 cron(홈)·다른 위치에서 실행할 때 엉뚱한 빈 DB를 열어 `no such table: sync_state` 오류로 실패합니다. 스크립트도 실행 위치와 무관하도록 시작 시 `cd "$PROJ"`로 프로젝트 폴더로 이동합니다. (2026-09-22 수정 완료)

---

## 7. 운영 가이드

**지금 즉시 수동 갱신(로컬+클라우드):**
```bash
~/Desktop/Automation/ai_productivity/refresh_and_publish.sh
```

**ETL만 수동 실행(로컬 DB만):**
```bash
cd ~/Desktop/Automation/ai_productivity && ./.venv/bin/python etl.py >> etl.log 2>&1
```

**로컬 대시보드 확인:**
```bash
cd ~/Desktop/Automation/ai_productivity && ./.venv/bin/streamlit run dashboard.py
```

**로그 보기:**
```bash
tail -n 30 ~/Desktop/Automation/ai_productivity/refresh_publish.log   # 자동화
tail -n 30 ~/Desktop/Automation/ai_productivity/etl.log               # ETL
```

**갱신 주기 변경:** `crontab -e`에서 `0 * * * *` 수정 (예: 6시간마다 `0 */6 * * *`).

### 트러블슈팅
| 증상 | 원인 / 조치 |
|---|---|
| 클라우드가 최신이 아님 | `refresh_publish.log`에서 push 성공 여부 확인. 실패면 아래 참고. |
| `no such table: sync_state` | `.env`의 `DB_PATH`가 상대경로여서 빈 DB를 열었음 → **절대경로로 수정**, 잘못 생긴 `~/data.sqlite`·`~/Desktop/Automation/data.sqlite` 삭제. (2026-09-22 조치 완료) |
| 로그에 "push 실패" 반복 | cron이 로그인 keychain 접근 불가(맥OS 제약). 맥 로그인 유지, 또는 **launchd LaunchAgent**로 전환(세션에서 실행). |
| 로그 자체가 안 남음 | cron에 **전체 디스크 접근 권한** 필요(시스템 설정 → 개인정보 보호). |
| 특정 저장소 커밋 0 | 90일 내 활동 없음이거나 대상 브랜치 없음(정상). |
| 대시보드 특정 탭 비어있음 | 해당 지표 기간 내 데이터 없음. 기간 필터 확장. |

---

## 8. 알려진 한계 & 다음 단계

- **과소집계**: Claude Code 밖에서 도움받아 손으로 커밋하면 감지 불가.
- **이슈↔커밋 연결 부족**: 커밋이 Jira 키를 잘 참조하지 않아 Lead time·PR 사이클의 AI/Human 비교 신뢰도가 낮음. → **소표본 가드**(표본 3건 미만 주 생략)로 왜곡된 급등 표시는 막았으나, 근본 해결은 커밋의 Jira 키 참조 정착으로 연결 표본을 늘리는 것.
- **스냅샷 방식**: 클라우드는 push 시점 스냅샷. 저장소가 시간당 커밋으로 누적되어 커질 수 있음 → 커지면 주기 하향 또는 아래 전환.
- **근본 개선(권장)**: **PostgreSQL 호스팅 + ETL 스케줄** 전환 시, 스냅샷 push 없이 클라우드가 항상 실시간 최신을 반영. GitHub·용량 부담도 해소.
- **결함/품질 지표**: ADR-002에서 AI vs Human 결함·재작업(rework) 형태로 재도입 예정.

---

## 9. 보안 주의

- `.env`(토큰)·`data.sqlite`(내부 데이터)는 **공개 배포 금지**. 배포 저장소는 반드시 private, 앱은 뷰어 인증.
- 팀 공유 시 **Artifact 요약 페이지**나 **Streamlit 앱(뷰어 인증)** 을 사용하고, 원시 데이터 파일은 공유하지 않기.
