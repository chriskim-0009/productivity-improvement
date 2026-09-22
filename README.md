# Claude 생산성 대시보드 — PoC 시작 가이드

이 폴더 안에 있는 파일들로, 5분 만에 데모를 띄우고 1주일 안에 PoC를 완성할 수 있습니다. 개발자가 아닌 분도 따라올 수 있도록 단계별로 설명했습니다.

## 이 폴더에 들어 있는 것

| 파일 | 무엇인가요 |
|---|---|
| `ADR-001-claude-productivity-dashboard.md` | "왜 이렇게 만들었는가" 설계서 — 의사결정자/매니저에게 공유할 문서 |
| `schema.sql` | 데이터를 담아둘 표(테이블) 정의 |
| `prepare-commit-msg` | 커밋할 때 `Assisted-By: claude`를 자동으로 붙여주는 Git 훅 (Python 스크립트) |
| `etl.py` | Jira와 **Bitbucket Cloud**에서 데이터를 가져오는 수집 스크립트 |
| `dashboard.py` | 차트 6개와 필터가 있는 웹 대시보드 (Streamlit) |
| `requirements.txt` | 필요한 Python 패키지 목록 |

---

## 사전 준비

1. **Python 3.10 이상**이 설치되어 있어야 합니다. (터미널에서 `python3 --version`)
2. **Atlassian API 토큰** (Jira + Bitbucket을 같은 토큰 하나로 인증):
   - 접속: <https://id.atlassian.com/manage-profile/security/api-tokens>
   - **Create API token with scopes** 클릭
   - 필요한 scope (읽기 전용):
     - Jira: `read:jira-work`, `read:jira-user`
     - Bitbucket: `read:repository:bitbucket`, `read:pullrequest:bitbucket`, `read:account:bitbucket`
   - 발급된 문자열을 즉시 복사 (창을 닫으면 다시 못 봅니다)
3. (대안) Bitbucket **App password** — 곧 폐지 예정이지만 아직 동작합니다.
   - Bitbucket 우상단 아바타 → Personal settings → App passwords → Create
   - 권한: Repositories: Read, Pull requests: Read, Account: Read

---

## 단계별 실행 순서

### 1) 가상환경 만들고 패키지 설치

```bash
cd <이 폴더>
python3 -m venv .venv
source .venv/bin/activate          # Windows는: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) 환경변수 설정 — `.env` 파일을 새로 만듭니다

```env
# Jira (Atlassian Cloud)
JIRA_BASE_URL=https://doverunner.atlassian.net
JIRA_EMAIL=chris.kim@doverunner.com
JIRA_TOKEN=발급받은_API_토큰
JIRA_PROJECTS=BILL,WEB,APP
JIRA_TEAM_FIELD=                # 팀 정보가 들어있는 커스텀 필드 ID. 없으면 비워두세요(component를 대신 사용)

# Bitbucket Cloud
# API token이면 BITBUCKET_EMAIL을, App password면 BITBUCKET_USERNAME을 채우세요
BITBUCKET_EMAIL=chris.kim@doverunner.com
# BITBUCKET_USERNAME=          # App password 사용 시
BITBUCKET_TOKEN=발급받은_API_토큰_또는_App_password
# 저장소 지정 방식 2가지 — 하나만 있어도 되고, 둘을 함께 쓰면 합쳐집니다.
# (A) 자동 탐색: 아래 워크스페이스의 프로젝트(들)에서 활성 저장소를 매 실행마다 포함.
#     새 저장소가 생기면 자동 반영되므로 스케줄 실행과 궁합이 좋습니다.
BITBUCKET_WORKSPACE=appsealing   # 탐색할 워크스페이스
BITBUCKET_PROJECTS=AS,AR         # 탐색할 프로젝트 키(콤마 구분). 비우면 자동 탐색 안 함
BITBUCKET_ACTIVE_DAYS=90         # 최근 N일 내 업데이트된 저장소만 (기본 90)
# (B) 수동 지정: workspace/repo_slug 콤마 구분. 자동 탐색을 안 쓰면 이것만으로 동작.
BITBUCKET_REPOS=
BITBUCKET_BRANCH=develop        # 커밋을 수집할 브랜치 (PoC 기본값: develop). 해당 브랜치가 없는 저장소는 건너뜁니다.

DB_PATH=./data.sqlite
SLACK_WEBHOOK=                  # 실패 알림이 필요하면 채우세요
```

> Jira와 Bitbucket이 같은 Atlassian 계정이라면 **하나의 API token을 두 변수(`JIRA_TOKEN`, `BITBUCKET_TOKEN`)에 동일하게 넣어도 됩니다** — 단, 발급 시 두 서비스의 scope를 모두 부여해야 합니다.

### 3) 데이터베이스 만들기

```bash
sqlite3 data.sqlite < schema.sql
```

> Windows에서 `sqlite3` 명령이 없으면 https://www.sqlite.org/download.html 에서 받거나, 잠시 Python으로 만들어도 됩니다:
> ```bash
> python -c "import sqlite3; sqlite3.connect('data.sqlite').executescript(open('schema.sql').read())"
> ```

### 4) 데이터 한 번 채워보기

```bash
python etl.py
```

처음 실행 시 최근 90일치 이슈/커밋/PR을 가져옵니다. 팀/저장소가 크면 몇 분 걸릴 수 있습니다.

### 5) 대시보드 띄우기

```bash
streamlit run dashboard.py
```

브라우저가 `http://localhost:8501`로 열립니다. 사이드바에서 기간/팀/저장소를 선택하면 차트 6개가 갱신됩니다.

### 6) 1시간마다 자동 갱신되게 하기

세 가지 방법 중 편한 것을 고르세요.

**a. APScheduler로 직접 띄우기** (가장 단순)

```bash
python etl.py --schedule
```

터미널을 띄워둔 채로 두면 1시간마다 자동 실행됩니다. 서버에 올릴 때는 `nohup`이나 `systemd`로 띄워두세요.

**b. macOS / Linux의 cron 사용**

```bash
crontab -e
# 아래 한 줄 추가 (매시 정각)
0 * * * * cd /path/to/this/folder && /path/to/.venv/bin/python etl.py >> etl.log 2>&1
```

**c. Bitbucket Pipelines의 schedule 사용**

이미 화면에서 보이는 `bitbucket-pipelines.yml`에 schedule 단계를 추가합니다.

```yaml
# bitbucket-pipelines.yml
image: python:3.11

pipelines:
  custom:
    hourly-etl:
      - step:
          name: Run ETL
          script:
            - pip install -r requirements.txt
            - python etl.py

  # Bitbucket의 Repository settings → Pipelines → Schedules 에서
  # 'hourly-etl' 커스텀 파이프라인을 매시간 실행되도록 등록합니다.
```

Bitbucket Pipelines 변수에 `JIRA_TOKEN`, `BITBUCKET_TOKEN` 등을 **Secured**로 등록하세요.

---

## 개발자 머신에 Git 훅 설치하기

이 부분이 있어야 커밋 메시지에 `Assisted-By: claude`가 자동으로 붙습니다.

### 한 저장소에 적용

```bash
cp prepare-commit-msg /path/to/your/repo/.git/hooks/prepare-commit-msg
chmod +x /path/to/your/repo/.git/hooks/prepare-commit-msg
```

### 모든 저장소에 한 번에 적용

```bash
mkdir -p ~/.git-hooks
cp prepare-commit-msg ~/.git-hooks/
chmod +x ~/.git-hooks/prepare-commit-msg
git config --global core.hooksPath ~/.git-hooks
```

### 사용법

Claude를 쓰고 있을 때만 환경변수를 켜고 커밋합니다.

```bash
CLAUDE_ASSISTED=1 git commit -m "feat: 청구서 CSV 내보내기"
```

`.zshrc`나 `.bashrc`에 alias로 두면 편합니다.

```bash
alias gcai='CLAUDE_ASSISTED=1 git commit'
```

> Claude Code를 쓰고 있다면 IDE/CLI 통합으로 환경변수를 자동 셋업하는 것을 권합니다 — 사람이 매번 신경 쓰지 않게 하는 게 데이터 품질의 핵심입니다.

---

## 자주 묻는 질문

**Q0. Bitbucket 인증이 401로 실패해요.**
A. 세 가지를 확인하세요. (1) `BITBUCKET_EMAIL`이 Atlassian 계정의 정확한 이메일인지 (App password를 쓴다면 `BITBUCKET_USERNAME`에 Bitbucket 사용자명), (2) API token에 `read:repository:bitbucket` 등 Bitbucket scope가 포함되었는지, (3) `BITBUCKET_REPOS` 항목이 `workspace/repo_slug`(예: `DoveRunner/test1`) 형식인지.

**Q1. 데이터가 비어있어요.**
A. `etl.py`를 먼저 한 번 실행했는지 확인하세요. 환경변수가 비어 있으면 API 호출이 실패합니다. `etl.log`를 확인해보세요.

**Q2. 개인별 차트는 왜 없나요?**
A. 1차 PoC에서는 의도적으로 비활성화했습니다. "개인 줄세우기" 우려를 해소한 뒤(별도 ADR로 거버넌스 결정), 단계적으로 도입합니다.

**Q3. Trailer가 누락된 커밋이 너무 많아요.**
A. 두 종류의 신호가 함께 집계됩니다: (1) 훅이 붙이는 `Assisted-By: claude`, (2) **Claude Code가 커밋을 저작하면 자동으로 남기는 `Co-authored-by: Claude ...` 트레일러**. 즉 Claude Code로 커밋했다면 훅이 설치되어 있지 않아도 AI 커밋으로 잡힙니다. 그래도 누락이 많다면: 대시보드 하단 "데이터 품질 안내"에서 추정치를 확인하고, (a) Claude Code 밖에서 손으로 커밋하는 경우를 위해 `prepare-commit-msg` 훅이 설치/활성화되어 있는지, (b) IDE 통합이 환경변수를 잘 셋업하는지 점검하세요. (판별 규칙은 `etl.py`의 `parse_commit_flags`에 한곳으로 모여 있습니다.)

**Q4. 결함률(defect rate) 정의가 우리 팀과 맞지 않아요.**
A. 현재는 "이슈 type이 Bug/Defect인 비율"로 간단히 잡았습니다. 팀에서 `hotfix` 라벨이나 `linked issues` 기반으로 정의하고 싶다면 `etl.py`와 `dashboard.py` 둘 다에서 조정해야 합니다 — D6 매니저 리뷰 때 합의를 거쳐 PoC 마지막 날 반영하세요.

**Q5. PostgreSQL로 옮기려면?**
A. 코드에서 `sqlite3` → `psycopg2`/`sqlalchemy`로 바꾸면 됩니다. 스키마는 거의 그대로 옮길 수 있습니다. 팀이 50명 넘어가거나 한 달치 데이터가 백만 행을 넘기 시작하면 그 시점에 작업하세요.

---

## 다음 단계 (PoC 이후)

- ADR-002 (예정): 개인 차원 측정에 대한 거버넌스/프라이버시 결정
- 결함률 정의 정교화 (linked issues 추적, 같은 파일 재수정 패턴 분석)
- Cursor, Copilot 등 다른 AI 도구 라벨 통합 (`Assisted-By: cursor`, 등)
- 매니저 알림: 주간 변동률이 임계치를 넘으면 Slack DM
