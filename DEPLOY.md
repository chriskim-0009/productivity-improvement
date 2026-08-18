# Streamlit Community Cloud 배포 가이드

이 폴더를 GitHub 저장소에 올리고 Streamlit Community Cloud에 연결하면, 필터가 살아있는
라이브 대시보드가 공개 URL로 배포됩니다. 최종 배포는 본인 GitHub/Streamlit 계정 로그인이
필요해 대신 해드릴 수 없어, 여기 단계대로 클릭만 하면 되도록 준비했습니다.

## 이 폴더에 든 것
- `dashboard.py` — 대시보드 (결함률 제거 + `?` 툴팁 등 최신 반영)
- `data.sqlite` — 데이터 **스냅샷** (클라우드가 읽을 데이터. 2MB)
- `requirements.txt` — 클라우드 설치용 (대시보드 전용, 슬림)
- `.streamlit/config.toml` — 라이트 테마
- `.gitignore` — `.env`는 제외, `data.sqlite`는 포함

## ⚠️ 먼저 알아둘 것
1. **Streamlit Community Cloud는 GitHub만 지원**합니다 (Bitbucket 불가). 새 GitHub 저장소가 필요합니다.
2. `data.sqlite`에는 **내부 Jira/Bitbucket 데이터**(이슈 제목·커밋 메시지·저장소명)가 들어 있습니다.
   → 반드시 **비공개(private) 저장소**를 쓰고, 아래 4단계에서 **뷰어 인증**으로 접근을 팀으로 제한하세요.
3. 토큰은 필요 없습니다 — 대시보드는 `data.sqlite`만 읽습니다. (`.env`/토큰은 올리지 않습니다.)

## 1) GitHub 비공개 저장소 만들기
GitHub에서 New repository → **Private** 선택 → 생성 (예: `productivity-dashboard`).

## 2) 이 폴더를 푸시
```bash
cd ~/Desktop/ai_productivity_streamlit_deploy
git init
git add .
git commit -m "Streamlit 생산성 대시보드 (스냅샷)"
git branch -M main
git remote add origin https://github.com/<본인계정>/<저장소>.git
git push -u origin main
```

## 3) Streamlit Community Cloud에 연결
1. https://share.streamlit.io 접속 → GitHub로 로그인 (첫 로그인 시 저장소 접근 권한 허용).
2. **Create app → Deploy a public app from GitHub** (저장소는 private여도 됩니다).
3. 설정:
   - Repository: 방금 만든 저장소
   - Branch: `main`
   - **Main file path: `dashboard.py`**
4. **Deploy** 클릭 → 1~2분 후 `https://<앱이름>.streamlit.app` URL 생성.

## 4) 접근 제한 (중요 — 내부 데이터)
Community Cloud 앱은 기본이 **공개**입니다. 팀만 보게 하려면:
- 앱 우하단 **Manage app → Settings → Sharing** → **viewer 인증** 활성화 후, 볼 수 있는 이메일(팀원)을 추가.

## 5) 데이터 갱신 (스냅샷 방식)
지금은 스냅샷이라 수치가 고정됩니다. 최신화하려면:
```bash
# 원본 프로젝트에서 ETL 재실행 후 새 data.sqlite를 이 폴더로 복사
cp ~/Desktop/Automation/ai_productivity/data.sqlite ~/Desktop/ai_productivity_streamlit_deploy/
cd ~/Desktop/ai_productivity_streamlit_deploy
git add data.sqlite && git commit -m "데이터 스냅샷 갱신" && git push
```
푸시하면 Streamlit Cloud가 자동으로 재배포합니다.

## 더 나아가려면 (선택)
매번 스냅샷을 올리는 게 번거로우면, 데이터를 **호스팅 PostgreSQL**로 옮기고 ETL을 별도 스케줄
(cron/Fargate)로 돌리면 클라우드 대시보드가 항상 최신을 보여줍니다. 이 전환이 필요하면 말씀해 주세요.
