"""
dashboard.py
============
Claude 생산성 대시보드 (Claude Productivity Dashboard) — PoC.

실행 / Run:
    streamlit run dashboard.py

- 사이드바 상단의 KR/EN 토글로 언어를 전환할 수 있습니다.
- 디자인은 Lovable design system (cream / charcoal / warm borders) 을 적용했습니다.
- 1차 PoC는 *팀/저장소 단위 집계만* 보여줍니다 (개인 줄세우기 방지).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# .env 로드
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv  # type: ignore

    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_env_db = os.environ.get("DB_PATH", "").strip()
DB_PATH = Path(_env_db) if _env_db else (_SCRIPT_DIR / "data.sqlite")


# ─────────────────────────────────────────────────────────────────────────────
# 페이지 설정 (set_page_config 는 가장 먼저)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claude Productivity Dashboard",
    page_icon="📊",
    layout="wide",
)


# ─────────────────────────────────────────────────────────────────────────────
# i18n 사전
# ─────────────────────────────────────────────────────────────────────────────
T: dict[str, dict[str, str]] = {
    # Sidebar
    "language": {"KR": "언어", "EN": "Language"},
    "filters": {"KR": "필터", "EN": "Filters"},
    "date_range": {"KR": "기간", "EN": "Date range"},
    "teams": {"KR": "팀", "EN": "Teams"},
    "repos": {"KR": "저장소", "EN": "Repositories"},
    "sidebar_footer": {
        "KR": "PoC 버전 — 개인별 비교는 의도적으로 비활성화되어 있습니다.",
        "EN": "PoC build — individual-level comparison is intentionally disabled.",
    },
    # Header
    "title": {
        "KR": "Claude 생산성 대시보드",
        "EN": "Claude Productivity Dashboard",
    },
    "subtitle": {
        "KR": "AI 어시스턴트 도입의 효과를 팀 단위로 진단합니다.",
        "EN": "Measure the impact of AI assistant adoption at the team level.",
    },
    "caption": {
        "KR": "이 대시보드는 **진단 도구**입니다. 특정 개인을 평가하기 위한 것이 아니며, 단일 지표만으로 결론을 내리지 마세요.",
        "EN": "This dashboard is a **diagnostic tool**. It is not for evaluating individuals — do not draw conclusions from any single metric.",
    },
    # Empty / data states
    "no_db_warning": {
        "KR": "데이터베이스 파일이 없습니다. 먼저 `python etl.py` 를 한 번 실행해 데이터를 적재하세요.",
        "EN": "Database file not found. Run `python etl.py` once to populate data.",
    },
    "no_data_info": {
        "KR": "아직 적재된 데이터가 없습니다. `python etl.py` 를 실행해 첫 동기화를 마치면 여기에 차트가 채워집니다.",
        "EN": "No data has been loaded yet. After running `python etl.py` for the first sync, charts will appear here.",
    },
    "no_chart_data": {
        "KR": "표시할 데이터가 없습니다.",
        "EN": "No data to display.",
    },
    # KPI
    "kpi_adoption": {"KR": "AI 커밋 비율", "EN": "AI commit share"},
    "kpi_authors": {"KR": "활성 작성자", "EN": "Active authors"},
    "kpi_lead": {"KR": "평균 Lead time (시간)", "EN": "Median lead time (h)"},
    # Chart section
    "weekly_trends": {"KR": "주간 트렌드", "EN": "Weekly trends"},
    "tab_lead": {"KR": "1. Lead time", "EN": "1. Lead time"},
    "tab_throughput": {"KR": "2. 처리량", "EN": "2. Throughput"},
    "tab_commit_volume": {"KR": "3. 커밋 볼륨", "EN": "3. Commit volume"},
    "tab_pr_cycle": {"KR": "4. PR 사이클", "EN": "4. PR cycle"},
    "tab_adoption": {"KR": "5. Claude 채택률", "EN": "5. Claude adoption"},
    # Axis & legend labels
    "ax_week": {"KR": "주", "EN": "Week"},
    "ax_lead_hours": {"KR": "중앙값 (시간)", "EN": "Median (hours)"},
    "ax_done_count": {"KR": "완료 이슈 수", "EN": "Issues completed"},
    "ax_commit_count": {"KR": "커밋 수", "EN": "Commits"},
    "ax_pr_cycle": {
        "KR": "PR 머지까지 시간 중앙값(h)",
        "EN": "Median PR merge time (h)",
    },
    "ax_ai_share": {"KR": "AI 커밋 비율 (%)", "EN": "AI commit share (%)"},
    "bucket_ai": {"KR": "AI 포함", "EN": "AI-assisted"},
    "bucket_non_ai": {"KR": "비 AI", "EN": "Human only"},
    # Captions under charts
    "cap_lead": {
        "KR": "주별 Lead time 중앙값. 두 선 모두 떨어지면 좋은 신호.",
        "EN": "Weekly median lead time. Both lines trending down is a good signal.",
    },
    "cap_throughput_sp": {
        "KR": "이 기간 총 완료 스토리포인트: {sp}",
        "EN": "Total story points completed in range: {sp}",
    },
    # Help tooltips (라벨 옆 ? 에 마우스를 올리면 표시)
    "help_kpi_adoption": {
        "KR": "전체 커밋 중 AI 지원 트레일러(Assisted-By / Co-authored-by: Claude)가 붙은 커밋의 비율.",
        "EN": "Share of commits carrying an AI-assist trailer (Assisted-By / Co-authored-by: Claude).",
    },
    "help_kpi_authors": {
        "KR": "선택한 기간에 커밋을 1건 이상 남긴 고유 작성자 수.",
        "EN": "Distinct authors with at least one commit in the selected period.",
    },
    "help_kpi_lead": {
        "KR": "이슈가 'In Progress' 진입부터 완료까지 걸린 시간의 중앙값(시간).",
        "EN": "Median hours from an issue entering 'In Progress' to done.",
    },
    "help_lead": {
        "KR": "이슈별 In Progress→완료 시간의 주별 중앙값. AI 포함 / Human only로 비교합니다.",
        "EN": "Weekly median of per-issue In-Progress→done time, split AI-assisted vs. human-only.",
    },
    "help_throughput": {
        "KR": "주별 완료(resolved) 이슈 수. 팀이 얼마나 꾸준히 끝내는지 봅니다.",
        "EN": "Issues resolved per week—how steadily the team ships.",
    },
    "help_commit_volume": {
        "KR": "주별 커밋 수를 AI 포함 / Human only로 나눠 누적 막대로 표시합니다.",
        "EN": "Weekly commits stacked AI-assisted vs. human-only.",
    },
    "help_pr_cycle": {
        "KR": "PR 생성부터 머지까지 걸린 시간의 주별 중앙값.",
        "EN": "Weekly median time from PR opened to merged.",
    },
    "help_adoption": {
        "KR": "AI 지원 커밋 비율의 주별 추이. 도입이 실제로 퍼지는지 봅니다.",
        "EN": "Weekly trend of AI-assisted commit share—whether adoption is spreading.",
    },
    # Quality expander
    "quality_title": {
        "KR": "데이터 품질 / Trailer 누락 안내",
        "EN": "Data quality / trailer-miss alerts",
    },
    "quality_empty": {
        "KR": "아직 품질 스냅샷이 없습니다. `etl.py`가 한 번 이상 돌아야 채워집니다.",
        "EN": "No quality snapshots yet. `etl.py` must run at least once.",
    },
    "quality_caption": {
        "KR": "AI 커밋 비율이 갑자기 0으로 떨어지면 trailer 자동 삽입 훅이 깨졌을 가능성이 있습니다.",
        "EN": "If the AI commit ratio suddenly drops to 0, the auto-trailer Git hook may be broken.",
    },
    # Referenced-repositories expander
    "repos_title": {
        "KR": "참조된 저장소",
        "EN": "Referenced repositories",
    },
    "repos_empty": {
        "KR": "아직 커밋/PR 데이터가 있는 저장소가 없습니다. `etl.py`를 먼저 실행하세요.",
        "EN": "No repositories with commit/PR data yet. Run `etl.py` first.",
    },
    "repos_caption": {
        "KR": "현재 DB에 적재된 저장소별 커밋·AI 커밋·PR 수 (develop 브랜치 기준).",
        "EN": "Per-repository commits, AI commits, and PRs currently in the DB (develop branch).",
    },
    "repos_col_commits": {"KR": "커밋", "EN": "Commits"},
    "repos_col_ai": {"KR": "AI 커밋", "EN": "AI commits"},
    "repos_col_share": {"KR": "AI 비율(%)", "EN": "AI share (%)"},
    "repos_col_prs": {"KR": "PR", "EN": "PRs"},
    "repos_col_last": {"KR": "최근 커밋", "EN": "Last commit"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Lovable 디자인 시스템 CSS 주입
# (cream #f7f4ed background, charcoal #1c1c1c text, #eceae4 borders,
#  warm shadows, 6px / 12px radii, weight 400/600)
# ─────────────────────────────────────────────────────────────────────────────
LOVABLE_CSS = """
<style>
  :root {
    --bg-cream: #f7f4ed;
    --bg-cream-2: #fcfbf8;
    --text-charcoal: #1c1c1c;
    --text-muted: #5f5f5d;
    --border-soft: #eceae4;
    --border-strong: rgba(28, 28, 28, 0.4);
    --hover-tint: rgba(28, 28, 28, 0.04);
    --focus-shadow: rgba(0, 0, 0, 0.1) 0px 4px 12px;
    --inset-shadow:
        rgba(255, 255, 255, 0.2) 0px 0.5px 0px 0px inset,
        rgba(0, 0, 0, 0.2) 0px 0px 0px 0.5px inset,
        rgba(0, 0, 0, 0.05) 0px 1px 2px 0px;
    --font-stack:
        "Camera Plain Variable", "Pretendard Variable", "Pretendard",
        "Inter", ui-sans-serif, system-ui, -apple-system,
        "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
  }

  /* Page surface */
  .stApp, [data-testid="stAppViewContainer"] {
    background-color: var(--bg-cream) !important;
    color: var(--text-charcoal) !important;
    font-family: var(--font-stack) !important;
  }
  [data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stToolbar"] { background: transparent !important; }

  /* Headings: charcoal, tight tracking */
  h1, h2, h3, h4 {
    color: var(--text-charcoal) !important;
    font-family: var(--font-stack) !important;
    font-weight: 600 !important;
  }
  h1 { letter-spacing: -1.2px; }
  h2 { letter-spacing: -0.9px; }
  h3 { letter-spacing: -0.5px; }

  /* Body text */
  p, span, div, label, .stMarkdown { color: var(--text-charcoal); }
  .stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
    font-size: 14px;
  }

  /* Sidebar — slightly tinted cream */
  [data-testid="stSidebar"] {
    background-color: var(--bg-cream) !important;
    border-right: 1px solid var(--border-soft);
  }
  [data-testid="stSidebar"] * { color: var(--text-charcoal); }

  /* Metric cards (KPI) — bordered cream, no shadow */
  [data-testid="stMetric"] {
    background-color: var(--bg-cream) !important;
    border: 1px solid var(--border-soft);
    border-radius: 12px;
    padding: 16px 20px;
  }
  [data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-size: 14px;
    font-weight: 400;
  }
  [data-testid="stMetricValue"] {
    color: var(--text-charcoal) !important;
    font-weight: 600 !important;
    letter-spacing: -0.9px;
  }

  /* Tabs — pill-ish, charcoal selected */
  .stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid var(--border-soft);
  }
  .stTabs [data-baseweb="tab"] {
    background: transparent;
    color: var(--text-muted) !important;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 400;
  }
  .stTabs [aria-selected="true"] {
    background-color: var(--text-charcoal) !important;
    color: var(--bg-cream-2) !important;
    box-shadow: var(--inset-shadow);
  }

  /* Buttons & widgets — soft, bordered */
  .stButton > button,
  [data-baseweb="select"] > div,
  [data-testid="stDateInput"] input,
  [data-testid="stTextInput"] input {
    background-color: var(--bg-cream) !important;
    color: var(--text-charcoal) !important;
    border: 1px solid var(--border-soft) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
  }
  .stButton > button:hover {
    background-color: var(--hover-tint) !important;
  }
  .stButton > button:focus,
  .stButton > button:active {
    box-shadow: var(--focus-shadow) !important;
  }

  /* Radio (used for the language toggle) — segmented look */
  [data-testid="stSidebar"] [role="radiogroup"] {
    background-color: var(--bg-cream);
    border: 1px solid var(--border-soft);
    border-radius: 9999px;
    padding: 4px;
    gap: 4px;
    display: inline-flex;
  }
  [data-testid="stSidebar"] [role="radiogroup"] label {
    border-radius: 9999px !important;
    padding: 4px 14px !important;
    margin: 0 !important;
    cursor: pointer;
    font-weight: 400 !important;
  }
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background-color: var(--text-charcoal) !important;
    color: var(--bg-cream-2) !important;
    box-shadow: var(--inset-shadow);
  }
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) * {
    color: var(--bg-cream-2) !important;
  }
  /* Hide the native radio dot — segmented control look */
  [data-testid="stSidebar"] [role="radiogroup"] input + div:first-of-type {
    display: none !important;
  }

  /* Multiselect chips — soft cream pill with charcoal text + bordered outline.
     Avoids the dark-on-dark trap caused by the global sidebar color rule. */
  [data-baseweb="tag"] {
    background-color: var(--hover-tint) !important;   /* charcoal @ 4% */
    border: 1px solid var(--border-strong) !important;
    border-radius: 9999px !important;
  }
  [data-baseweb="tag"],
  [data-baseweb="tag"] span,
  [data-baseweb="tag"] div {
    color: var(--text-charcoal) !important;
  }
  /* Close (×) icon */
  [data-baseweb="tag"] svg {
    fill: var(--text-charcoal) !important;
    opacity: 0.6;
  }
  [data-baseweb="tag"] svg:hover {
    opacity: 1;
  }

  /* Expander */
  [data-testid="stExpander"] {
    background-color: var(--bg-cream) !important;
    border: 1px solid var(--border-soft) !important;
    border-radius: 12px;
  }

  /* Alerts (warning / info) — keep them warm */
  [data-testid="stAlert"] {
    border-radius: 12px;
    border: 1px solid var(--border-soft);
  }

  /* Plotly chart wrapper — remove default white panel feel */
  .js-plotly-plot, .plotly { background: transparent !important; }
</style>
"""
st.markdown(LOVABLE_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 사이드바 — 가장 먼저 언어 토글을 그려야 t() 가 정상 동작
# ─────────────────────────────────────────────────────────────────────────────
if "lang" not in st.session_state:
    st.session_state.lang = "KR"

with st.sidebar:
    st.markdown("### 🌐 Language / 언어")
    lang = st.radio(
        label="language_toggle",
        options=["KR", "EN"],
        horizontal=True,
        key="lang",
        label_visibility="collapsed",
    )

def t(key: str, **fmt) -> str:
    """Translate a key using the currently selected language."""
    msg = T.get(key, {}).get(st.session_state.lang, key)
    return msg.format(**fmt) if fmt else msg


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 액세스
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_df(query: str, params: tuple = ()) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(query, conn, params=params)


# 팀(=Jira component) 정보가 없는 이슈를 묶는 버킷 라벨.
# 이 프로젝트는 다수 이슈에 component가 없어 team이 NULL이다 — 필터에서 통째로
# 사라지지 않도록 '(미지정)' 버킷으로 노출한다.
UNASSIGNED_TEAM = "(미지정)"


def load_filters():
    teams = load_df(
        "SELECT DISTINCT team FROM issues WHERE team IS NOT NULL ORDER BY team"
    )["team"].tolist()
    # team이 NULL인 이슈가 하나라도 있으면 '(미지정)' 옵션을 추가
    has_null = load_df("SELECT 1 FROM issues WHERE team IS NULL LIMIT 1")
    if not has_null.empty:
        teams.append(UNASSIGNED_TEAM)
    repos = load_df(
        "SELECT DISTINCT repo FROM commits ORDER BY repo"
    )["repo"].tolist()
    return teams, repos


def _in_clause(items: list[str]) -> tuple[str, tuple]:
    """SQL `IN ?` placeholder. Empty list => `(NULL)` (matches 0 rows)."""
    if not items:
        return "(NULL)", ()
    placeholders = ",".join(["?"] * len(items))
    return f"({placeholders})", tuple(items)


# Plotly 공통 레이아웃 (Lovable 톤)
LOVABLE_FONT = (
    'Camera Plain Variable, Pretendard Variable, Pretendard, Inter, '
    'ui-sans-serif, system-ui, -apple-system, "Apple SD Gothic Neo", '
    '"Noto Sans KR", sans-serif'
)
LOVABLE_CHARCOAL = "#1c1c1c"
LOVABLE_MUTED = "#5f5f5d"
LOVABLE_CREAM = "#f7f4ed"
LOVABLE_BORDER = "#eceae4"
# AI-assisted 계열 강조색 — Human only(charcoal)와 색상(hue)으로 뚜렷이 구분되도록
# 크림 배경에서 대비가 충분한 teal을 사용한다.
LOVABLE_ACCENT = "#1a8f7d"

PLOTLY_LAYOUT = dict(
    paper_bgcolor=LOVABLE_CREAM,
    plot_bgcolor=LOVABLE_CREAM,
    font=dict(family=LOVABLE_FONT, color=LOVABLE_CHARCOAL, size=13),
    xaxis=dict(gridcolor=LOVABLE_BORDER, zerolinecolor=LOVABLE_BORDER),
    yaxis=dict(gridcolor=LOVABLE_BORDER, zerolinecolor=LOVABLE_BORDER),
    margin=dict(l=40, r=20, t=20, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

# AI vs Human 색상 — 두 계열을 확실히 구분하기 위해 AI-assisted는 강조 teal,
# Human only는 charcoal로 매핑한다(색상+명도 모두 대비).
COLOR_MAP = {
    "AI 포함": LOVABLE_ACCENT,
    "AI-assisted": LOVABLE_ACCENT,
    "비 AI": LOVABLE_CHARCOAL,
    "Human only": LOVABLE_CHARCOAL,
    "AI": LOVABLE_ACCENT,
    "Non_AI": LOVABLE_CHARCOAL,
}


def _style(fig):
    """Apply the shared Lovable layout to a Plotly figure."""
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 사이드바 필터 (언어 토글 아래)
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.title(t("filters"))

default_end = date.today()
default_start = default_end - timedelta(weeks=12)

date_range = st.sidebar.date_input(
    t("date_range"),
    value=(default_start, default_end),
    max_value=default_end,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
else:
    start_d, end_d = default_start, default_end

teams_all, repos_all = load_filters()
selected_teams = st.sidebar.multiselect(t("teams"), teams_all, default=teams_all)
selected_repos = st.sidebar.multiselect(t("repos"), repos_all, default=repos_all)

start_ts = datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc).isoformat()
end_ts = datetime.combine(end_d, datetime.max.time(), tzinfo=timezone.utc).isoformat()

teams_sql, teams_params = _in_clause(selected_teams)
repos_sql, repos_params = _in_clause(selected_repos)


# ─────────────────────────────────────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────────────────────────────────────
st.title(t("title"))
st.markdown(
    f"<p style='color:{LOVABLE_MUTED}; font-size:18px; line-height:1.38; "
    f"margin-top:-8px;'>{t('subtitle')}</p>",
    unsafe_allow_html=True,
)
st.caption(t("caption"))

if not DB_PATH.exists():
    st.warning(t("no_db_warning"))
    st.stop()

_have_data = bool(repos_all) or bool(teams_all)
if not _have_data:
    st.info(t("no_data_info"))


# ─────────────────────────────────────────────────────────────────────────────
# KPI
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
      AND COALESCE(team, '(미지정)') IN {teams_sql}
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



def _safe_pct(v) -> str:
    return f"{v * 100:.1f}%" if pd.notna(v) else "—"


def _safe_int(v) -> int:
    return int(v) if pd.notna(v) else 0


adoption_v = kpi["adoption_rate"].iloc[0] if not kpi.empty else None
authors_v = kpi["active_authors"].iloc[0] if not kpi.empty else None

c1, c2, c3 = st.columns(3)
c1.metric(t("kpi_adoption"), _safe_pct(adoption_v), help=t("help_kpi_adoption"))
c2.metric(t("kpi_authors"), _safe_int(authors_v), help=t("help_kpi_authors"))
c3.metric(
    t("kpi_lead"),
    f"{median_lead:.1f}" if median_lead is not None else "—",
    help=t("help_kpi_lead"),
)


# ─────────────────────────────────────────────────────────────────────────────
# 차트
# ─────────────────────────────────────────────────────────────────────────────
st.subheader(t("weekly_trends"))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    t("tab_lead"),
    t("tab_throughput"),
    t("tab_commit_volume"),
    t("tab_pr_cycle"),
    t("tab_adoption"),
])

# ── 1. Lead time ─────────────────────────────────────────────────────────
with tab1:
    st.caption(t("tab_lead").split(". ", 1)[-1], help=t("help_lead"))
    df = load_df(
        f"""
        SELECT i.key, i.team, i.first_in_progress_at, i.resolved_at,
               (SELECT MAX(ai_flag) FROM commits c
                WHERE c.jira_keys LIKE '%' || i.key || '%') AS ai_flag
        FROM issues i
        WHERE i.resolved_at IS NOT NULL
          AND i.first_in_progress_at IS NOT NULL
          AND i.resolved_at BETWEEN ? AND ?
          AND COALESCE(i.team, '(미지정)') IN {teams_sql}
        """,
        (start_ts, end_ts, *teams_params),
    )
    if df.empty:
        st.info(t("no_chart_data"))
    else:
        df["lead_hours"] = (
            pd.to_datetime(df["resolved_at"]) - pd.to_datetime(df["first_in_progress_at"])
        ).dt.total_seconds() / 3600.0
        df["week"] = pd.to_datetime(df["resolved_at"]).dt.to_period("W").dt.to_timestamp()
        df["bucket"] = df["ai_flag"].fillna(0).map(
            {1: t("bucket_ai"), 0: t("bucket_non_ai")}
        )
        agg = df.groupby(["week", "bucket"])["lead_hours"].median().reset_index()
        fig = px.line(
            agg,
            x="week",
            y="lead_hours",
            color="bucket",
            markers=True,
            color_discrete_map=COLOR_MAP,
            labels={
                "lead_hours": t("ax_lead_hours"),
                "week": t("ax_week"),
                "bucket": "",
            },
        )
        st.plotly_chart(_style(fig), use_container_width=True)
        st.caption(t("cap_lead"))

# ── 2. Throughput ────────────────────────────────────────────────────────
with tab2:
    st.caption(t("tab_throughput").split(". ", 1)[-1], help=t("help_throughput"))
    df = load_df(
        f"""
        SELECT date(resolved_at) AS day, COUNT(*) AS done, COALESCE(SUM(story_points), 0) AS sp
        FROM issues
        WHERE resolved_at BETWEEN ? AND ?
          AND COALESCE(team, '(미지정)') IN {teams_sql}
        GROUP BY date(resolved_at)
        """,
        (start_ts, end_ts, *teams_params),
    )
    if df.empty:
        st.info(t("no_chart_data"))
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(done=("done", "sum"), sp=("sp", "sum")).reset_index()
        fig = px.bar(
            weekly,
            x="week",
            y="done",
            labels={"done": t("ax_done_count"), "week": t("ax_week")},
            color_discrete_sequence=[LOVABLE_CHARCOAL],
        )
        st.plotly_chart(_style(fig), use_container_width=True)
        st.caption(t("cap_throughput_sp", sp=f"{weekly['sp'].sum():.0f}"))

# ── 3. Commit volume ─────────────────────────────────────────────────────
with tab3:
    st.caption(t("tab_commit_volume").split(". ", 1)[-1], help=t("help_commit_volume"))
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
        st.info(t("no_chart_data"))
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        ai_label = t("bucket_ai")
        non_label = t("bucket_non_ai")
        weekly = (
            df.groupby("week")
            .agg(**{ai_label: ("ai_commits", "sum"), non_label: ("non_ai_commits", "sum")})
            .reset_index()
            .melt(id_vars="week", var_name="bucket", value_name="commits")
        )
        fig = px.bar(
            weekly,
            x="week",
            y="commits",
            color="bucket",
            barmode="stack",
            color_discrete_map=COLOR_MAP,
            labels={
                "commits": t("ax_commit_count"),
                "week": t("ax_week"),
                "bucket": "",
            },
        )
        st.plotly_chart(_style(fig), use_container_width=True)

# ── 4. PR cycle ──────────────────────────────────────────────────────────
with tab4:
    st.caption(t("tab_pr_cycle").split(". ", 1)[-1], help=t("help_pr_cycle"))
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
        st.info(t("no_chart_data"))
    else:
        df["cycle_hours"] = (
            pd.to_datetime(df["merged_at"]) - pd.to_datetime(df["opened_at"])
        ).dt.total_seconds() / 3600.0
        df["week"] = pd.to_datetime(df["merged_at"]).dt.to_period("W").dt.to_timestamp()
        df["bucket"] = df["ai_flag"].map({1: t("bucket_ai"), 0: t("bucket_non_ai")})
        agg = df.groupby(["week", "bucket"])["cycle_hours"].median().reset_index()
        fig = px.line(
            agg,
            x="week",
            y="cycle_hours",
            color="bucket",
            markers=True,
            color_discrete_map=COLOR_MAP,
            labels={
                "cycle_hours": t("ax_pr_cycle"),
                "week": t("ax_week"),
                "bucket": "",
            },
        )
        st.plotly_chart(_style(fig), use_container_width=True)

# ── 5. Claude adoption ───────────────────────────────────────────────────
with tab5:
    st.caption(t("tab_adoption").split(". ", 1)[-1], help=t("help_adoption"))
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
        st.info(t("no_chart_data"))
    else:
        df["week"] = pd.to_datetime(df["day"]).dt.to_period("W").dt.to_timestamp()
        weekly = df.groupby("week").agg(ai=("ai_commits", "sum"), total=("total", "sum")).reset_index()
        weekly["rate"] = weekly["ai"] / weekly["total"].replace(0, pd.NA) * 100
        fig = px.area(
            weekly,
            x="week",
            y="rate",
            labels={"rate": t("ax_ai_share"), "week": t("ax_week")},
            color_discrete_sequence=[LOVABLE_CHARCOAL],
        )
        fig.update_traces(fillcolor="rgba(28,28,28,0.12)")
        st.plotly_chart(_style(fig), use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 품질
# ─────────────────────────────────────────────────────────────────────────────
with st.expander(t("quality_title"), expanded=False):
    q = load_df("SELECT * FROM daily_quality ORDER BY day DESC LIMIT 14")
    if q.empty:
        st.info(t("quality_empty"))
    else:
        q["ai_share"] = q["ai_commits"] / q["total_commits"].replace(0, pd.NA)
        st.dataframe(q, use_container_width=True)
        st.caption(t("quality_caption"))


# ─────────────────────────────────────────────────────────────────────────────
# 참조된 저장소 (어떤 repo 데이터가 반영됐는지)
# ─────────────────────────────────────────────────────────────────────────────
with st.expander(t("repos_title"), expanded=False):
    rc = load_df(
        f"""
        SELECT repo,
               COUNT(*)               AS commits,
               COALESCE(SUM(ai_flag), 0) AS ai_commits,
               MAX(committed_at)      AS last_commit
        FROM commits
        WHERE repo IN {repos_sql}
        GROUP BY repo
        """,
        repos_params,
    )
    rp = load_df(
        f"SELECT repo, COUNT(*) AS prs FROM pull_requests WHERE repo IN {repos_sql} GROUP BY repo",
        repos_params,
    )
    if rc.empty and rp.empty:
        st.info(t("repos_empty"))
    else:
        # 커밋이 없어도 PR만 있는 저장소까지 포함(outer merge)
        m = rc.merge(rp, on="repo", how="outer")
        for col in ("commits", "ai_commits", "prs"):
            m[col] = m.get(col, 0)
            m[col] = pd.to_numeric(m[col], errors="coerce").fillna(0).astype(int)
        # commits==0(PR만 있는 repo)은 NaN으로 두어 0/0 계산·object dtype 문제를 피한다
        m["ai_share"] = (
            m["ai_commits"] / m["commits"].where(m["commits"] > 0) * 100
        ).round(1)
        m["last_commit"] = pd.to_datetime(
            m["last_commit"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        m = m.sort_values("commits", ascending=False).set_index("repo")
        m = m.rename(
            columns={
                "commits": t("repos_col_commits"),
                "ai_commits": t("repos_col_ai"),
                "ai_share": t("repos_col_share"),
                "prs": t("repos_col_prs"),
                "last_commit": t("repos_col_last"),
            }
        )[
            [
                t("repos_col_commits"),
                t("repos_col_ai"),
                t("repos_col_share"),
                t("repos_col_prs"),
                t("repos_col_last"),
            ]
        ]
        st.dataframe(m, use_container_width=True)
        st.caption(t("repos_caption"))


st.sidebar.markdown("---")
st.sidebar.caption(t("sidebar_footer"))
