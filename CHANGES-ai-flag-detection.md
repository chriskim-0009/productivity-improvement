# 변경 요약 — AI 지원 커밋 자동 감지 (Co-authored-by 인식)

- **날짜**: 2026-07-14 (develop 브랜치 및 대시보드 변경 2026-07-15 추가)
- **범위**: `etl.py` (판별 로직 + 수집 브랜치 + 타임스탬프 정규화 + Jira 키 정규식), `dashboard.py` (표시 수정·개선), `README.md` (문서)
- **한 줄 요약**: (1) `Assisted-By: claude`에 더해 **`Co-authored-by: Claude ...` 트레일러**도 AI 신호로 인식, (2) **커밋 수집 기준을 기본 브랜치에서 `develop`으로 변경**(PoC), (3) **Jira 기반 차트가 비던 문제를 수정**하고 저장소/색상 표시를 개선, (4) **Jira 키 정규식 오탐 제거**(`JIRA_PROJECTS` 접두사로 제한).

---

## 왜 바꿨나

기존 방식은 개발자 머신마다 `prepare-commit-msg` 훅을 설치하고 `CLAUDE_ASSISTED=1`을 켠 커밋에만 `Assisted-By: claude`를 붙이는 구조였다. 훅 미설치·환경변수 누락 시 AI 커밋이 통째로 누락된다(FAQ Q3의 실제 약점).

Claude Code는 커밋을 저작하면 **머신 설정과 무관하게** `Co-authored-by: Claude <noreply@anthropic.com>` 트레일러를 자동으로 남긴다. 이 트레일러는 이미 커밋 메시지에 들어가 Bitbucket 원격까지 그대로 도달하므로, `etl.py`가 이를 2차 신호로 인식하기만 하면 **별도 설치 없이** 누락을 크게 줄일 수 있다.

> 대안 비교(요지): "Claude Code settings.json 훅"은 머신마다 설정이 필요하고 Claude 주도 커밋만 잡아 기존 약점을 그대로 물려받음. "Co-authored-by 인식"은 머신 설치가 불필요해 마찰이 가장 적음 → **후자 채택.**

---

## 무엇을 바꿨나

### `etl.py`
1. **정규식 추가** — `CO_AUTHORED_CLAUDE_RE`
   - `^Co-authored-by:\s*.*(?:\bclaude\b|@anthropic\.com)` (MULTILINE·IGNORECASE)
   - `Claude`, `Claude Opus 4.8` 등 모델명 포함 케이스와 anthropic 이메일을 매치.
   - `\bclaude\b` 단어 경계로 `Claudia` 같은 사람 이름 오탐 방지.
2. **`parse_commit_flags` 확장** — `ai_flag = Assisted-By 매치 OR Co-authored-by(Claude) 매치`.
   - 커밋 수집(`_upsert_bb_commit`)과 PR 스캔(`_scan_pr_commits`)이 모두 이 함수를 재사용하므로 자동 반영됨.
3. **설계 메모(docstring) 갱신** — `ai_flag` 정의를 두 신호 기준으로 명시.

### `README.md`
- FAQ **Q3**(트레일러 누락)에 두 신호 병행 집계와 "Claude Code 커밋은 훅 없이도 잡힘"을 명시.

---

## 감지 규칙 (요약표)

| 커밋 메시지 트레일러 | ai_flag |
|---|---|
| `Assisted-By: claude` | ✅ True |
| `Co-authored-by: Claude <noreply@anthropic.com>` | ✅ True |
| `Co-authored-by: Claude Opus 4.8 <noreply@anthropic.com>` | ✅ True |
| `Co-authored-by: ... <noreply@anthropic.com>` (anthropic 이메일) | ✅ True |
| `Co-authored-by: Claudia Kim <claudia@corp.com>` (사람) | ❌ False |
| `Co-authored-by: Jane <jane@corp.com>` (다른 사람) | ❌ False |
| 트레일러 없음 | ❌ False |

---

## 남는 한계 (정직한 고지)

- 여전히 **과소집계**다. claude.ai 웹챗에서 도움받고 Claude Code 밖에서 손으로 커밋한 경우는 신호가 전혀 없어 감지 불가 → 이 용도로 기존 `prepare-commit-msg` 훅(`CLAUDE_ASSISTED=1`)을 수동 보완으로 유지.
- `Co-authored-by`는 Bitbucket/GitHub의 기여자(attribution) 통계에도 잡힌다. 팀이 이 표기를 원치 않으면 Co-author 인식을 끄는 토글이 필요할 수 있다.

---

## 추가 변경 — 커밋 수집 브랜치를 `develop`으로 (PoC, 2026-07-15)

### 왜 바꿨나
리비전 없는 Bitbucket `/commits`는 저장소 **기본 브랜치(master/main)** 만 따라간다. 그런데 이 조직은 팀 컨벤션상 실제 개발이 **`develop`** 에서 이뤄져, 기본 브랜치 수집으로는 실활동(그리고 그 안의 AI 커밋)을 거의 다 놓친다.

- 실측: `appsealing/doverunner-vapt`는 **master 기준 AI 0%(커밋 1개) → develop 기준 86.5%(347/401)**.

### 무엇을 바꿨나
**`etl.py`**
1. **`COMMIT_BRANCH` 상수 추가** — `os.environ.get("BITBUCKET_BRANCH", "develop")`. 기본값 `develop`, 코드 수정 없이 env로 변경 가능.
2. **`_fetch_bb_commits`** — 수집 URL을 `/commits`(기본 브랜치)에서 `/commits/{COMMIT_BRANCH}`로 변경. 해당 브랜치가 없는 저장소는 `_paged`가 404 경고만 남기고 건너뜀(커밋 0건).
3. **설계 메모(docstring)** 에 "커밋 수집은 develop 브랜치 기준" 명시.

**`README.md`**
- `.env` 예시에 `BITBUCKET_BRANCH=develop` 추가 (해당 브랜치 없는 저장소는 건너뜀을 주석으로 안내).

### 한계
- `develop`이 없는 저장소(master/main만 있는 곳)는 커밋이 0건으로 수집됨 — PoC에서 develop 중심으로 본다는 결정에 부합. 저장소별 브랜치를 달리하려면 추가 작업 필요.

---

## 추가 변경 — 대시보드 데이터 표시 수정 및 개선 (2026-07-15)

### 왜 바꿨나
차트는 뜨지만 **Throughput·Lead time 등 Jira 기반 뷰가 비어** 있었다. 원인 두 가지:
1. **타임스탬프 형식** — Jira `resolved_at`이 `...+0900`(오프셋에 콜론 없음)으로 저장돼 SQLite `date()`가 NULL 반환 → `GROUP BY date(...)`가 깨짐. (Bitbucket 커밋은 `+00:00` 콜론 형식이라 커밋 차트는 정상이었음.)
2. **팀 필터** — 이슈 89%가 `team` NULL(Jira component 미지정)인데 모든 Jira 쿼리가 `team IN (...)`로 걸러 NULL 팀 이슈가 항상 제외됨.

### 무엇을 바꿨나
**`etl.py`** — 타임스탬프 정규화
1. **`_norm_dt()` 추가** — Jira 타임스탬프의 `+0900` 오프셋을 `+09:00`으로 정규화(정규식). `created/resolved/updated` 및 상태전이 `at`에 적용.
2. (일회성) 기존 적재분 **백필** — issues 1508행, issue_transitions 2531행을 동일 규칙으로 교정. *(코드가 아닌 마이그레이션 작업)*

**`dashboard.py`** — 표시 수정 + 개선
3. **팀 미지정 `(미지정)` 버킷** — `load_filters()`가 NULL 팀 존재 시 `(미지정)` 옵션 추가, 5개 Jira 쿼리를 `COALESCE(team,'(미지정)') IN (...)`로 변경 → 미지정 이슈도 표시.
4. **AI/Human 색상 구분** — `LOVABLE_ACCENT`(teal) 추가, `COLOR_MAP`에서 AI-assisted→teal, Human only→charcoal로 매핑(색상+명도 대비).
5. **"참조된 저장소" 섹션 추가** — 저장소별 커밋·AI 커밋·AI 비율·PR·최근 커밋 표. commits/PR outer merge, i18n(KR/EN), **사이드바 repo 필터와 연동**.
6. **버그 픽스** — 참조 저장소 표의 `ai_share` 계산에서 `.replace(0, pd.NA)`가 object dtype→`.round()` TypeError. `.where(commits>0)`로 수정.

> 커밋 분리: **표시 복구(fix)** = 항목 1·2·3 → 커밋 3, **표시 개선(feat)** = 항목 4·5·6 → 커밋 4.

### 검증
- `date(resolved_at)` 510건 전부 파싱, Throughput/Lead time 데이터 반환.
- 대시보드 재실행 후 스크린샷으로 색상 구분·참조 저장소·Throughput 표시 확인.

---

## 추가 변경 — Jira 키 정규식 오탐 제거 (2026-07-15)

### 왜 바꿨나
기존 `JIRA_KEY_RE = \b([A-Z][A-Z0-9]+-\d+)\b` 가 이슈 키가 아닌 토큰을 키로 오탐했다: `SHA-256`, `CWE-922`, `OWASP-2024`, `BR-004`(타 프로젝트) 등. 이 값들이 `commits.jira_keys`에 저장돼 데이터를 오염시켰다.

### 무엇을 바꿨나
**`etl.py`**
1. **`_build_jira_key_re()` 추가** — 설정된 `JIRA_PROJECTS`(예: `AS`, `AR`) 접두사로만 매칭하는 패턴 생성(`\b((?:AS|AR)-\d+)\b`). `JIRA_PROJECTS` 미설정 시 기존 일반 패턴으로 폴백.
2. (일회성) 기존 적재분 **백필** — 커밋 448개 재파싱, 47개의 오탐 키 제거. 정리 후 남은 키는 전부 실제 AS 키(38건). *(코드가 아닌 마이그레이션 작업)*

### 한계
- 데이터 오염은 사라지지만 Lead time의 "AI 포함" 버킷은 여전히 안 채워진다 — 커밋이 참조하는 실제 키가 완료 대상 이슈와 거의 겹치지 않는다는 **연결 부족**은 별개 문제.

---

## 추가 변경 — Lead time·PR 사이클 극단 이상치 제외 (2026-09-23)

> 처음엔 "표본 3건 미만 주 생략(소표본 가드)"로 접근했으나, AI 선이 통째로 사라지는 부작용이 있어 **되돌리고**, 대신 **극단 이상치만 제외**하는 방식으로 변경했다.

### 왜 바꿨나
비정상적으로 오래 걸린 이슈 하나가 주간 중앙값을 급등시켰다. 예: Lead time에서 `AS-23469`(In Progress 약 45일, 1,086h)가 표본이 적은 주의 중앙값을 ~580h로 끌어올려 "AI가 느리다"는 오해를 유발.

### 무엇을 바꿨나
**`dashboard.py`** (Lead time · PR 사이클 탭)
1. `_drop_upper_outliers()` 헬퍼 추가 — **Tukey 상단 울타리(Q3 + 1.5·IQR)를 넘는 개별 값 제외**(표본 8건 미만이면 원본 유지).
2. 중앙값 계산 전 이 헬퍼를 적용 → 급등 제거. **모든 주는 그대로 표시**(소표본 주를 숨기지 않음).
3. 캡션에 이상치 제외 안내(`cap_lead`, `cap_pr_cycle`).

### 검증
- 상단 울타리 = 453h, 전체 233건 중 이상치 9건 제외, `AS-23469`(1,086h) 제외 확인 → Lead time 최대 ~580h → ~215h로 정상화.

### 한계
- 표시 왜곡은 막았으나 근본 원인(커밋의 Jira 키 참조 부족 → 연결 표본 부족)은 그대로. 처리량·커밋 볼륨·채택률은 전체 집계라 미적용.

---

## 제안 커밋 메시지

> 논리적으로 별개 변경이므로 **6개 커밋**으로 나누는 것을 권장.

### 커밋 1 — Co-authored-by 인식

```text
feat(etl): Claude Code의 Co-authored-by 트레일러를 AI 커밋 신호로 인식

prepare-commit-msg 훅과 CLAUDE_ASSISTED 플래그에만 의존하던 AI 커밋
판별을, Claude Code가 커밋 저작 시 자동으로 남기는 Co-authored-by: Claude
트레일러도 인식하도록 확장한다. 머신에 훅이 설치되어 있지 않아도 Claude Code로
저작한 커밋이 집계되어 누락(undercount)이 줄어든다.

- etl.py: CO_AUTHORED_CLAUDE_RE 추가, parse_commit_flags가 두 신호를 OR로 판별
  (Claudia 등 사람 이름 오탐은 단어 경계로 방지)
- README.md: FAQ Q3에 두 신호 병행 집계 명시

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

### 커밋 2 — 수집 브랜치를 develop으로

```text
feat(etl): 커밋 수집 기준을 저장소 기본 브랜치에서 develop으로 변경 (PoC)

팀 컨벤션상 실제 개발이 develop 브랜치에서 이뤄지는데, 리비전 없는
/commits는 저장소 기본 브랜치(master/main)만 따라가 실활동을 놓쳤다.
(예: doverunner-vapt는 master 기준 AI 0% → develop 기준 86.5%)

- etl.py: COMMIT_BRANCH 상수(env BITBUCKET_BRANCH, 기본 develop) 추가,
  _fetch_bb_commits가 /commits/{COMMIT_BRANCH} 수집.
  해당 브랜치가 없는 저장소는 404 경고 후 건너뜀.
- README.md: .env 예시에 BITBUCKET_BRANCH=develop 추가

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

### 커밋 3 — Jira 차트 데이터 표시 복구 (fix)

```text
fix: Jira 기반 차트가 비던 문제 수정 (타임스탬프/팀 필터)

차트는 뜨지만 Throughput·Lead time 등 Jira 기반 뷰가 비어 있던 문제를
수정한다. 원인은 (1) Jira 타임스탬프의 +0900 오프셋(콜론 없음)을 SQLite
date()가 파싱하지 못해 NULL이 된 것, (2) team NULL 이슈(89%)가 team IN
필터에서 제외된 것.

- etl.py: _norm_dt()로 Jira 타임스탬프 오프셋을 +09:00으로 정규화
  (created/resolved/updated/전이 at). 기존 적재분은 별도 백필로 교정.
- dashboard.py: team NULL을 '(미지정)' 버킷으로 노출(COALESCE),
  Jira 쿼리 5곳(lead/throughput/defect 등) 반영.

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

> 참고: 기존 적재분 백필은 커밋에 담기는 코드가 아니라 일회성 마이그레이션이다.
> 신규 환경에서는 `etl.py` 수정본으로 처음부터 정규화되어 적재되므로 백필이 불필요.

### 커밋 4 — 색상 구분 + 참조된 저장소 섹션 (feat)

```text
feat(dashboard): AI/Human 색상 구분 + '참조된 저장소' 섹션 추가

- AI-assisted=teal / Human only=charcoal 로 색상 구분(LOVABLE_ACCENT 추가,
  COLOR_MAP 매핑) — 기존 charcoal/muted 회색 조합보다 색상+명도 대비를 키워
  두 계열이 명확히 구분되도록 함.
- '참조된 저장소' 섹션 추가: 저장소별 커밋·AI 커밋·AI 비율·PR·최근 커밋 표.
  commits/PR outer merge, i18n(KR/EN), 사이드바 repo 필터와 연동.
  ai_share는 commits==0에서 .where로 NaN 처리해 object-dtype 오류 회피.

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

### 커밋 5 — Jira 키 정규식 오탐 제거 (fix)

```text
fix(etl): Jira 키 정규식을 JIRA_PROJECTS 접두사로 제한 (오탐 제거)

기존 \b([A-Z][A-Z0-9]+-\d+)\b 패턴이 SHA-256, CWE-922, OWASP-2024,
BR-004 등 이슈 키가 아닌 토큰을 jira_keys로 오탐해 데이터를 오염시켰다.
설정된 JIRA_PROJECTS(예: AS, AR) 접두사로만 매칭하도록 제한한다.

- etl.py: _build_jira_key_re()로 JIRA_PROJECTS 기반 패턴 생성
  (미설정 시 기존 일반 패턴 폴백). 기존 적재분은 별도 백필로 재파싱.

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

### 커밋 6 — Lead time·PR 사이클 극단 이상치 제외 (fix)

```text
fix(dashboard): Lead time·PR 사이클 극단 이상치 제외 (Q3+1.5·IQR)

비정상적으로 오래 걸린 이슈/PR 하나가 주간 중앙값을 급등시키던 문제를 방지한다.
(예: AS-23469 1,086h가 주간 중앙값을 ~580h로 왜곡)
표본 전체를 숨기던 소표본 가드는 되돌리고, Tukey 상단 울타리(Q3+1.5·IQR)를
넘는 개별 값만 제외해 모든 주를 그대로 표시한다.

- dashboard.py: _drop_upper_outliers() 추가, Lead time·PR 사이클에서
  중앙값 계산 전 적용. 캡션 안내(cap_lead / cap_pr_cycle)

Assisted-By: claude
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
