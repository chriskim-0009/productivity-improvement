-- schema.sql
-- SQLite 스키마 (PoC). 팀이 50명을 넘으면 PostgreSQL로 옮기되 동일 구조를 유지.
-- 실행:  sqlite3 data.sqlite < schema.sql

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ── 이슈 ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS issues (
    key             TEXT PRIMARY KEY,           -- 예: BILL-142
    project         TEXT NOT NULL,
    type            TEXT,                       -- Story / Bug / Task ...
    status          TEXT,                       -- 현재 상태
    summary         TEXT,
    created_at      TIMESTAMP NOT NULL,
    resolved_at     TIMESTAMP,
    first_in_progress_at TIMESTAMP,             -- "처음 In Progress 진입" 시각 (lead time 계산용)
    story_points    REAL,
    assignee        TEXT,
    team            TEXT,                       -- 매니저 필터용 (Jira component or custom field로 채움)
    updated_at      TIMESTAMP NOT NULL          -- 증분 sync용 (마지막으로 본 updated_at 이후만 가져옴)
);

CREATE INDEX IF NOT EXISTS idx_issues_team    ON issues(team);
CREATE INDEX IF NOT EXISTS idx_issues_updated ON issues(updated_at);

-- ── 이슈 상태 변경 이력 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS issue_transitions (
    issue_key   TEXT NOT NULL REFERENCES issues(key) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    at          TIMESTAMP NOT NULL,
    PRIMARY KEY (issue_key, at, to_status)
);

CREATE INDEX IF NOT EXISTS idx_transitions_issue ON issue_transitions(issue_key);

-- ── 커밋 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS commits (
    sha          TEXT PRIMARY KEY,
    repo         TEXT NOT NULL,
    author_login TEXT,                          -- GitHub/GitLab 로그인 (가능하면 익명화/매핑)
    author_team  TEXT,                          -- 사람→팀 매핑 (people 테이블 또는 외부 매핑 사용)
    committed_at TIMESTAMP NOT NULL,
    additions    INTEGER DEFAULT 0,
    deletions    INTEGER DEFAULT 0,
    message      TEXT,
    ai_flag      INTEGER NOT NULL DEFAULT 0,    -- 0/1 (Assisted-By trailer 유무)
    ai_level     TEXT,                          -- 'heavy' / 'light' / NULL
    jira_keys    TEXT                           -- 'BILL-142,BILL-150' 처럼 콤마 구분
);

CREATE INDEX IF NOT EXISTS idx_commits_repo      ON commits(repo);
CREATE INDEX IF NOT EXISTS idx_commits_committed ON commits(committed_at);
CREATE INDEX IF NOT EXISTS idx_commits_team      ON commits(author_team);
CREATE INDEX IF NOT EXISTS idx_commits_ai        ON commits(ai_flag);

-- ── 풀 리퀘스트 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pull_requests (
    repo        TEXT NOT NULL,
    number      INTEGER NOT NULL,
    title       TEXT,
    author      TEXT,
    team        TEXT,
    opened_at   TIMESTAMP NOT NULL,
    merged_at   TIMESTAMP,
    additions   INTEGER DEFAULT 0,
    deletions   INTEGER DEFAULT 0,
    first_commit_sha TEXT,                      -- ai_flag 결정에 사용
    ai_flag     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (repo, number)
);

CREATE INDEX IF NOT EXISTS idx_pr_opened ON pull_requests(opened_at);
CREATE INDEX IF NOT EXISTS idx_pr_merged ON pull_requests(merged_at);

-- ── 동기화 상태(마지막으로 본 updated_at 등) ────────────────────────────
CREATE TABLE IF NOT EXISTS sync_state (
    source       TEXT PRIMARY KEY,              -- 'jira' / 'git:<repo>'
    last_synced  TIMESTAMP NOT NULL,
    note         TEXT
);

-- ── 데이터 품질: trailer 누락률 등을 보기 위한 일별 스냅샷 ───────────────
CREATE TABLE IF NOT EXISTS daily_quality (
    day               DATE PRIMARY KEY,
    total_commits     INTEGER NOT NULL,
    ai_commits        INTEGER NOT NULL,
    missing_trailer_estimated INTEGER DEFAULT 0
);
