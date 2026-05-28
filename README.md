# productivity-improvement

At a Glance
This document describes how to build a dashboard that answers the question: “Has our team actually gotten faster by using Claude?” — with data. The goal is to deliver a working proof-of-concept (PoC) within one week, and expand it further if results look promising.

Three core decisions:

How to mark AI-assisted work → Automatically append a single line Assisted-By: claude at the bottom of commit messages.
How to collect data → Fetch only new data from Jira and Git every hour, and store it in a lightweight DB.
Dashboard tool → Build with Python’s Streamlit. A full chart page can be written as a 5–10 line function, making it the fastest option for a one-week schedule.

| 파일 | 무엇인가요 |
|---|---|
| `ADR-001-claude-productivity-dashboard.md` | "왜 이렇게 만들었는가" 설계서 — 의사결정자/매니저에게 공유할 문서 |
| `schema.sql` | 데이터를 담아둘 표(테이블) 정의 |
| `prepare-commit-msg` | 커밋할 때 `Assisted-By: claude`를 자동으로 붙여주는 Git 훅 (Python 스크립트) |
| `etl.py` | Jira와 **Bitbucket Cloud**에서 데이터를 가져오는 수집 스크립트 |
| `dashboard.py` | 차트 6개와 필터가 있는 웹 대시보드 (Streamlit) |
| `requirements.txt` | 필요한 Python 패키지 목록 |
