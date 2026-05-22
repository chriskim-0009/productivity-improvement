"""
dashboard.py
============
Streamlit으로 만든 "Claude 생산성 대시보드" PoC.

실행:
    streamlit run dashboard.py

페이지 구성:
    1) 상단: 기간 / 팀 / 저장소 필터
    2) KPI 카드: AI 채택률, 활성 사용자, 평균 lead time, 결함률
    3) 차트 6개 (lead time / throughput / commit volume / PR cycle / defect rate / adoption)
    4) 데이터 품질 안내 (trailer 누락 추정)

설계 원칙:
    - 1차 PoC는 *팀/저장소 단위 집계만* 보여준다 (개인 줄세우기 방지)
    - 모든 차트 상단에 "진단 도구이며 평가가 아님" 안내 노출
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# .env 의 DB_PATH 등을 읽기 위해 streamlit 실행 시에도 명시적으로 로드
try:
    from dotenv import load_dotenv  # type: ignore

    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # dotenv 미설치라도 시스템 env로 동작은 가능

# DB_PATH 가 env 에 있으면 그것을, 아니면 스크립트와 같은 폴더의 data.sqlite 사용.
_SCRIPT_DIR = Path(__file__).resolve().parent
_env_db = os.environ.get("DB_PATH", "").strip()
DB_PATH = Path(_env_db) if _env_db else (_SCRIPT_DIR / "data.sqlite")

st.set_page_config(page_title="Claude 생산성 대시보드", layout="wide")


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 액세스
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_df(query: str, params: tuple = ()) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(query, conn, params=params)


def load_filters():
    teams = load_df(
        "SELECT DISTINCT team FROM issues WHERE team IS NOT NULL ORDER BY team"
    )["team"].tolist()
    repos = load_df(
        "SELECT DISTINCT repo FROM commits ORDER BY repo"
    )["repo"].tolist()
    return teams, repos


# ─────────────────────────────────────────────────────────────────────────────
# 사이드바 필터
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("필터")
default_end = date.today()
default_start = default_end - timedelta(weeks=12)

date_range = st.sidebar.date_input(
    "기간",
    value=(default_start, default_end),
    max_value=default_end,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
else:
    start_d, end_d = default_start, default_end

teams_all, repos_all = load_filters()
selected_teams = st.sidebar.multiselect("팀", teams_all, default=teams_all)
selected_repos = st.sidebar.multiselect("저장소", repos_all, default=repos_all)

start_ts = datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc).isoformat()
end_ts = datetime.combine(end_d, datetime.max.time(), tzinfo=timezone.utc).isoformat()


def _in_clause(items: list[str]) -> tuple[str, tuple]:
    """
    SQL의 `xxx IN {clause}` 슬롯에 넣을 표현식 생성.

    items 가 비어 있으면 `(NULL)` 을 반환한다 — SQLite에서 `repo IN (NULL)` 은
    어떤 값과도 같지 않으므로 결과가 0행이 된다. (이전 버전은 `1=1` 을 돌려줘
    `repo IN 1=1` 이라는 잘못된 SQL을 만들었음.)
    """
    if not items:
        return "(NULL)", ()
    placeholders = ",".join(["?"] * len(items))
    return f"({placeholders})", tuple(items)


teams_sql, teams_params = _in_clause(selected_teams)
repos_sql, repos_params = _in_clause(selected_repos)


# ─────────────────────────────────────────────────────────────────────────────
# 상단 헤더 & 안내
# ─────────────────────────────────────────────────────────────────────────────

st.title("Claude 생산성 대시보드")
st.caption(
    "이 대시보드는 **진단 도구**입니다. "
    "특정 개인을 평가하기 위한 것이 아니며, "
    "단일 지표만으로 결론을 내리지 마세요."
)

# 빈 DB 안내 — ETL 한 번도 안 돌았을 때
if not DB_PATH.exists():
    st.warning(
        f"데이터베이스 파일이 없습니다 (`{DB_PATH}`). "
        "먼저 `sqlite3 data.sqlite < schema.sql` 로 스키마를 만들고 "
        "`python etl.py` 를 한 번 실행하세요."
    )
    st.stop()

_have_data = bool(repos_all) or bool(teams_all)
if not _have_data:
    st.info(
        "아직 적재된 데이터가 없습니다. `python etl.py` 를 실행해 첫 동기화를 마치면 "
        "여기에 차트가 채워집니다."
    )


# ─────────────────────────────────────────────────────────────────────────────
# KPI 카드 4종
# ─────────────────────────────────────────────────────────────────────────────

kpi = load_df(
    f"""
    SELECT
        SUM(CASE WHEN ai_flag=1 THEN 1 ELSE 0 END) * 1.0
            / NULLIF(COUNT(*), 0)              AS adoption_rate,
        COUNT(DISTINCT author_login)            AS active_authors,
        COUNT(*)                                AS total_commits
    FROM commits
    WHERE committed_at BETWEEN ? AND ?
      AND repo IN {repos_sql}
    """,
    (start_ts, end_ts, *repos_params),
)

lead = load_df(
    f"""
    SELECT first_in_progress_at, resolved_at, team
    FROM issues
    WHERE resolved_at IS NOT NULL
      AND first_in_progress_at IS NOT NULL
      AND resolved_at BETWEEN ? AND ?
      AND team IN {teams_sql}
    """,
    (start_ts, end_ts, *teams_params),
)
if not lead.empty:
    lead["lead_hours"] = (
        pd.to_datetime(lead["resolved_at"]) - pd.to_datetime(lead["first_in_progress_at"])
    ).dt.total_seconds() / 3600.0
    median_lead = lead["lead_hours"].median()
else:
    median_lead = None

defect = load_df(
    f"""
    SELECT
        SUM(CASE WHEN type IN ('Bug', 'Defect') THEN 1 ELSE 0 END) * 1.0
            / NULLIF(COUNT(*), 0) AS bug_ratio
    FROM issues
    WHERE created_at BETWEEN ? AND ?
      AND team IN {teams_sql}
    """,
    (start_ts, end_ts, *teams_params),
)

def _safe_pct(series_val) -> str:
    """NaN/None 이면 '—', 아니면 퍼센트 문자열."""
    return f"{series_val * 100:.1f}%" if pd.notna(series_val) else "—"


def _safe_int(series_val) -> int:
    return int(series_val) if pd.notna(series_val) else 0


adoption_v = kpi["adoption_rate"].iloc[0] if not kpi.empty else None
authors_v  = kpi["active_authors"].iloc[0] if not kpi.empty else None
bug_v      = defect["bug_ratio"].iloc[0] if not defect.empty else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("AI 커밋 비율", _safe_pct(adoption_v))
c2.metric("활성 작성자", _safe_int(authors_v))
c3.metric("평균 Lead time (시간)", f"{median_lead:.1f}" if median_lead is not None else "—")
c4.metric("버그 이슈 비율", _safe_pct(bug_v))


# ─────────────────────────────────────────────────────────────────────────────
# 차트 6종
# ─────────────────────────────────────────────────────────────────────────────

st.subheader("주간 트렌드")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "1. Lead time", "2. Throughput", "3. Commit 볼륨",
    "4. PR cycle", "5. 결함률", "6. Claude 채택률",
])

# ── 1. Lead time (AI vs No-AI) ───────────────────────────────────────────
with tab1:
    df = load_df(
        f"""
        SELECT i.key, i.team, i.first_in_progress_at, i.resolved_at,
               (SELECT MAX(ai_flag) FROM commits c
                WHERE c.jira_keys LIKE '%' || i.key || '%') AS ai_flag
        FROM issues i
        WHERE i.resolved_at IS NOT NULL
          AND i.first_in_progress_at IS NOT NULL
          AND i.resolved_at BETWEEN ? AND ?
          AND i.team IN {teams_sql}
        """,
        (start_ts, end_ts, *teams_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["lead_hours"] = (
            pd.to_datetime(df["resolved_at"]) - pd.to_datetime(df["first_in_progress_at"])
        ).dt.total_seconds() / 3600.0
        df["week"] = pd.to_datetime(df["resolved_at"]).dt.to_period("W").dt.to_timestamp()
        df["bucket"] = df["ai_flag"].fillna(0).map({1: "AI 포함", 0: "비 AI"})
        agg = df.groupby(["week", "bucket"])["lead_hours"].median().reset_index()
        fig = px.line(agg, x="week", y="lead_hours", color="bucket",
                      markers=True, labels={"lead_hours": "중앙값 (시간)", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption("주별 Lead time 중앙값. 두 선 모두 떨어지면 좋은 신호.")

# ── 2. Throughput ────────────────────────────────────────────────────────
with tab2:
    df = load_df(
        f"""
        SELECT date(resolved_at) AS day, COUNT(*) AS done, COALESCE(SUM(story_points), 0) AS sp
        FROM issues
        WHERE resolved_at BETWEEN ? AND ?
          AND team IN {teams_sql}
        GROUP BY date(resolved_at)
        """,
        (start_ts, end_ts, *teams_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(done=("done", "sum"), sp=("sp", "sum")).reset_index()
        fig = px.bar(weekly, x="week", y="done",
                     labels={"done": "완료 이슈 수", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"이 기간 총 완료 스토리포인트: {weekly['sp'].sum():.0f}")

# ── 3. Commit 볼륨 (AI vs No-AI) ─────────────────────────────────────────
with tab3:
    df = load_df(
        f"""
        SELECT date(committed_at) AS day,
               SUM(CASE WHEN ai_flag=1 THEN 1 ELSE 0 END) AS ai_commits,
               SUM(CASE WHEN ai_flag=0 THEN 1 ELSE 0 END) AS non_ai_commits
        FROM commits
        WHERE committed_at BETWEEN ? AND ?
          AND repo IN {repos_sql}
        GROUP BY date(committed_at)
        """,
        (start_ts, end_ts, *repos_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(
            AI=("ai_commits", "sum"), Non_AI=("non_ai_commits", "sum")
        ).reset_index().melt(id_vars="week", var_name="bucket", value_name="commits")
        fig = px.bar(weekly, x="week", y="commits", color="bucket",
                     barmode="stack", labels={"commits": "커밋 수", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)

# ── 4. PR cycle time ─────────────────────────────────────────────────────
with tab4:
    df = load_df(
        f"""
        SELECT opened_at, merged_at, ai_flag
        FROM pull_requests
        WHERE merged_at IS NOT NULL
          AND merged_at BETWEEN ? AND ?
          AND repo IN {repos_sql}
        """,
        (start_ts, end_ts, *repos_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["cycle_hours"] = (
            pd.to_datetime(df["merged_at"]) - pd.to_datetime(df["opened_at"])
        ).dt.total_seconds() / 3600.0
        df["week"] = pd.to_datetime(df["merged_at"]).dt.to_period("W").dt.to_timestamp()
        df["bucket"] = df["ai_flag"].map({1: "AI 포함", 0: "비 AI"})
        agg = df.groupby(["week", "bucket"])["cycle_hours"].median().reset_index()
        fig = px.line(agg, x="week", y="cycle_hours", color="bucket",
                      markers=True, labels={"cycle_hours": "PR 머지까지 시간 중앙값(h)", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)

# ── 5. 결함률 ────────────────────────────────────────────────────────────
with tab5:
    df = load_df(
        f"""
        SELECT date(created_at) AS day,
               SUM(CASE WHEN type IN ('Bug', 'Defect') THEN 1 ELSE 0 END) AS bugs,
               COUNT(*) AS total
        FROM issues
        WHERE created_at BETWEEN ? AND ?
          AND team IN {teams_sql}
        GROUP BY date(created_at)
        """,
        (start_ts, end_ts, *teams_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(bugs=("bugs", "sum"), total=("total", "sum")).reset_index()
        weekly["bug_ratio"] = weekly["bugs"] / weekly["total"].replace(0, pd.NA) * 100
        fig = px.line(weekly, x="week", y="bug_ratio", markers=True,
                      labels={"bug_ratio": "버그 이슈 비율 (%)", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption("주별 신규 이슈 중 버그/결함 비율. AI/No-AI 분해는 다음 ADR에서 정교화 예정.")

# ── 6. Claude 채택률 ─────────────────────────────────────────────────────
with tab6:
    df = load_df(
        f"""
        SELECT date(committed_at) AS day,
               SUM(ai_flag) AS ai_commits,
               COUNT(*) AS total
        FROM commits
        WHERE committed_at BETWEEN ? AND ?
          AND repo IN {repos_sql}
        GROUP BY date(committed_at)
        """,
        (start_ts, end_ts, *repos_params),
    )
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(ai=("ai_commits", "sum"), total=("total", "sum")).reset_index()
        weekly["rate"] = weekly["ai"] / weekly["total"].replace(0, pd.NA) * 100
        fig = px.area(weekly, x="week", y="rate",
                      labels={"rate": "AI 커밋 비율 (%)", "week": "주"})
        st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 품질 안내
# ─────────────────────────────────────────────────────────────────────────────

with st.expander("데이터 품질 / Trailer 누락 안내", expanded=False):
    q = load_df("SELECT * FROM daily_quality ORDER BY day DESC LIMIT 14")
    if q.empty:
        st.info("아직 품질 스냅샷이 없습니다. `etl.py`가 한 번 이상 돌아야 채워집니다.")
    else:
        q["ai_share"] = q["ai_commits"] / q["total_commits"].replace(0, pd.NA)
        st.dataframe(q, use_container_width=True)
        st.caption(
            "AI 커밋 비율이 갑자기 0으로 떨어지면 trailer 자동 삽입 훅이 깨졌을 가능성이 있습니다."
        )

st.sidebar.markdown("---")
st.sidebar.caption("PoC 버전 — 개인별 비교는 의도적으로 비활성화되어 있습니다.")
