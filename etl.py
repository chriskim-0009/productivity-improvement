"""
etl.py
======
Jira와 Bitbucket Cloud에서 데이터를 가져와 SQLite에 적재하는 ETL 스크립트.
1시간 주기로 실행되는 것을 가정 — 매번 마지막 sync 시각 이후 변경된 것만 가져온다.

실행
----
    python etl.py                # 한 번만 실행
    python etl.py --schedule     # APScheduler로 1시간마다 실행 (서버에 상주)

환경변수는 .env 파일에서 자동 로드되며, .env.example을 참고하세요.

설계 메모
---------
- Jira와 Bitbucket 모두 Atlassian이라 동일한 (email, api_token) Basic Auth를 쓴다.
- Bitbucket pagination은 응답 본문의 `next` URL을 따라간다.
- Bitbucket commit endpoint에는 line stats가 포함되지 않는다 — PR diffstat에서만.
- PR의 ai_flag는 "PR 내 커밋 중 하나라도 Assisted-By trailer가 있으면 True".
- MERGED PR의 merge 시각은 list 응답의 updated_on을 근사값으로 사용.
- DB_PATH가 env에 없으면 스크립트와 같은 폴더의 data.sqlite를 사용 (cwd 비독립적).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import requests

# ─────────────────────────────────────────────────────────────────────────────
# 환경/로깅
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger("etl")


def _load_env() -> None:
    """
    `.env` 파일을 명시적으로 로드한다.
    - 스크립트와 같은 디렉터리의 .env 를 1순위로 본다.
    - python-dotenv 가 없으면 친절한 안내와 함께 즉시 종료.
    - .env 파일이 없으면 경고만 띄우고 진행 (system env로 셋업된 환경 대응).
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        sys.stderr.write(
            "[etl] python-dotenv 가 설치되지 않았습니다.\n"
            "      pip install -r requirements.txt 로 의존성을 먼저 설치하세요.\n"
        )
        sys.exit(2)

    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        log.info(".env 로드 완료: %s", env_path)
    else:
        log.warning(".env 파일이 없습니다 (%s). 시스템 환경변수로 진행합니다. "
                    "샘플은 .env.example 을 참고하세요.", env_path)


_load_env()

# DB_PATH 환경변수가 설정되어 있으면 그것을, 아니면 스크립트와 같은 폴더의 data.sqlite를 사용.
# (어느 cwd에서 실행해도 동일한 DB를 가리키게 하기 위함)
_SCRIPT_DIR = Path(__file__).resolve().parent
_env_db = os.environ.get("DB_PATH", "").strip()
DB_PATH = Path(_env_db) if _env_db else (_SCRIPT_DIR / "data.sqlite")

SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK", "").strip()
BITBUCKET_API = "https://api.bitbucket.org/2.0"


REQUIRED_ENV = {
    "Jira": ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECTS"],
    "Bitbucket": ["BITBUCKET_TOKEN", "BITBUCKET_REPOS"],
}


def validate_env() -> None:
    """필수 환경변수가 비어 있으면 친절한 에러로 즉시 중단."""
    missing: list[str] = []
    for group, keys in REQUIRED_ENV.items():
        for k in keys:
            if not os.environ.get(k, "").strip():
                missing.append(f"  - {k}  ({group})")

    if not (os.environ.get("BITBUCKET_EMAIL") or os.environ.get("BITBUCKET_USERNAME")):
        missing.append("  - BITBUCKET_EMAIL 또는 BITBUCKET_USERNAME  (Bitbucket)")

    if missing:
        sys.stderr.write(
            "\n[etl] 다음 환경변수가 비어 있습니다 — .env 파일을 확인하세요:\n"
            + "\n".join(missing)
            + "\n\n샘플 파일: .env.example  →  `cp .env.example .env` 후 값 입력\n\n"
        )
        sys.exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# DB 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_db() -> None:
    """
    DB 파일이 없으면 자동으로 schema.sql 을 적용해 만든다.
    schema.sql 은 스크립트와 같은 폴더에서 찾는다.
    """
    if DB_PATH.exists():
        return
    schema = _SCRIPT_DIR / "schema.sql"
    if not schema.exists():
        log.error("DB 파일도, schema.sql도 없습니다 (%s). PoC 가이드의 1) 단계를 따라주세요.", _SCRIPT_DIR)
        sys.exit(1)
    log.info("DB 파일이 없어 schema.sql 로 자동 생성합니다 → %s", DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))


def get_last_synced(source: str, default_days: int = 90) -> datetime:
    with db() as conn:
        row = conn.execute(
            "SELECT last_synced FROM sync_state WHERE source = ?", (source,)
        ).fetchone()
        if row:
            return datetime.fromisoformat(row["last_synced"])
    return datetime.now(timezone.utc) - timedelta(days=default_days)


def set_last_synced(source: str, ts: datetime) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (source, last_synced) VALUES (?, ?)",
            (source, ts.isoformat()),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 커밋 메시지 trailer 파서
# ─────────────────────────────────────────────────────────────────────────────

ASSISTED_BY_RE = re.compile(r"^Assisted-By:\s*(\S+)", re.MULTILINE | re.IGNORECASE)
ASSISTED_LEVEL_RE = re.compile(
    r"^Assisted-By-Level:\s*(heavy|light)", re.MULTILINE | re.IGNORECASE
)
JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


@dataclass
class CommitFlags:
    ai_flag: bool
    ai_level: str | None
    jira_keys: list[str]


def parse_commit_flags(message: str) -> CommitFlags:
    if not message:
        return CommitFlags(False, None, [])
    ai_flag = bool(ASSISTED_BY_RE.search(message))
    lvl_match = ASSISTED_LEVEL_RE.search(message)
    ai_level = lvl_match.group(1).lower() if lvl_match else None
    jira_keys = sorted(set(JIRA_KEY_RE.findall(message)))
    return CommitFlags(ai_flag, ai_level, jira_keys)


# ─────────────────────────────────────────────────────────────────────────────
# Jira fetch
# ─────────────────────────────────────────────────────────────────────────────

def _jira_session() -> requests.Session:
    s = requests.Session()
    s.auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_TOKEN"])
    s.headers.update({"Accept": "application/json"})
    return s


def fetch_jira_issues() -> int:
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    projects = [p.strip() for p in os.environ["JIRA_PROJECTS"].split(",") if p.strip()]
    team_field = os.environ.get("JIRA_TEAM_FIELD", "")

    source = "jira"
    since = get_last_synced(source)
    quoted_projects = ",".join(f'"{p}"' for p in projects)   # ← 각 프로젝트 키를 큰따옴표로
    jql = (
        f"project in ({quoted_projects}) "
        f"AND updated >= \"{since.strftime('%Y-%m-%d %H:%M')}\" "
        f"ORDER BY updated ASC"
    )
    log.info("Jira JQL: %s", jql)

    sess = _jira_session()
    page_size = 100
    inserted = 0
    next_page_token: str | None = None

    fields = ["summary", "status", "issuetype", "created", "resolutiondate",
              "assignee", "components", "customfield_10016"]
    if team_field:
        fields.append(team_field)
    fields_param = ",".join(fields)   # ★ 콤마 구분 문자열

    while True:
        params: dict = {
            "jql": jql,
            "maxResults": page_size,
            "fields": fields_param,
            "expand": "changelog",     # ★ 문자열
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        resp = sess.get(
            f"{base}/rest/api/3/search/jql",
            params=params,
            timeout=30,
        )
        if not resp.ok:                                    # ← 추가
            log.error("Jira API %s: %s", resp.status_code, resp.text)  # ← 추가
        resp.raise_for_status()
        data = resp.json()

        for issue in data.get("issues", []):
            _upsert_jira_issue(issue, team_field)
            inserted += 1

        next_page_token = data.get("nextPageToken")
        if not next_page_token or data.get("isLast"):
            break
        time.sleep(0.2)

    set_last_synced(source, datetime.now(timezone.utc))
    log.info("Jira: upserted %d issues", inserted)
    return inserted

def _upsert_jira_issue(issue: dict, team_field: str) -> None:
    key = issue["key"]
    f = issue["fields"]
    project = key.split("-")[0]
    status = (f.get("status") or {}).get("name")
    itype = (f.get("issuetype") or {}).get("name")
    summary = f.get("summary")
    created = f.get("created")
    resolved = f.get("resolutiondate")
    assignee = (f.get("assignee") or {}).get("displayName")
    sp = f.get("customfield_10016")

    team = None
    if team_field and f.get(team_field):
        v = f[team_field]
        team = v if isinstance(v, str) else (v.get("value") if isinstance(v, dict) else None)
    if not team and f.get("components"):
        team = f["components"][0].get("name")

    first_in_progress = None
    transitions: list[tuple[str | None, str, str]] = []
    for entry in (issue.get("changelog") or {}).get("histories", []):
        at = entry.get("created")
        for item in entry.get("items", []):
            if item.get("field") == "status":
                from_s = item.get("fromString")
                to_s = item.get("toString")
                transitions.append((from_s, to_s, at))
                if to_s and to_s.lower() in {"in progress", "doing"} and first_in_progress is None:
                    first_in_progress = at

    updated = f.get("updated") or created

    with db() as conn:
        conn.execute(
            """
            INSERT INTO issues (
                key, project, type, status, summary, created_at, resolved_at,
                first_in_progress_at, story_points, assignee, team, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                status=excluded.status, summary=excluded.summary,
                resolved_at=excluded.resolved_at,
                first_in_progress_at=COALESCE(issues.first_in_progress_at, excluded.first_in_progress_at),
                story_points=excluded.story_points,
                assignee=excluded.assignee, team=excluded.team,
                updated_at=excluded.updated_at
            """,
            (key, project, itype, status, summary, created, resolved,
             first_in_progress, sp, assignee, team, updated),
        )
        for from_s, to_s, at in transitions:
            conn.execute(
                """
                INSERT OR IGNORE INTO issue_transitions(issue_key, from_status, to_status, at)
                VALUES (?,?,?,?)
                """,
                (key, from_s, to_s, at),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Bitbucket Cloud fetch
# ─────────────────────────────────────────────────────────────────────────────

def _bitbucket_session() -> requests.Session:
    s = requests.Session()
    user = os.environ.get("BITBUCKET_EMAIL") or os.environ.get("BITBUCKET_USERNAME")
    if not user:
        raise RuntimeError("BITBUCKET_EMAIL 또는 BITBUCKET_USERNAME 환경변수가 필요합니다.")
    s.auth = (user, os.environ["BITBUCKET_TOKEN"])
    s.headers.update({"Accept": "application/json"})
    return s


def _list_repos() -> list[str]:
    raw = os.environ.get("BITBUCKET_REPOS") or os.environ.get("GIT_REPOS", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def fetch_bitbucket_repo(repo: str) -> tuple[int, int]:
    if "/" not in repo:
        raise ValueError(f"BITBUCKET_REPOS 항목은 'workspace/slug' 형식이어야 합니다: {repo!r}")

    sess = _bitbucket_session()
    source = f"bitbucket:{repo}"
    since = get_last_synced(source)

    n_commits = _fetch_bb_commits(sess, repo, since)
    n_prs = _fetch_bb_pulls(sess, repo, since)

    set_last_synced(source, datetime.now(timezone.utc))
    log.info("Bitbucket[%s]: commits=%d, prs=%d", repo, n_commits, n_prs)
    return n_commits, n_prs


def _paged(sess: requests.Session, url: str, params: dict | None = None,
           timeout: int = 30) -> Iterator[dict]:
    while url:
        r = sess.get(url, params=params, timeout=timeout)
        if r.status_code == 404:
            log.warning("404 from %s", url)
            return
        r.raise_for_status()
        data = r.json()
        for item in data.get("values", []):
            yield item
        url = data.get("next")
        params = None
        time.sleep(0.1)


def _fetch_bb_commits(sess: requests.Session, repo: str, since: datetime) -> int:
    workspace, slug = repo.split("/", 1)
    url = f"{BITBUCKET_API}/repositories/{workspace}/{slug}/commits"
    n = 0
    for c in _paged(sess, url, {"pagelen": 100}):
        try:
            committed = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if committed < since:
            break
        _upsert_bb_commit(repo, c)
        n += 1
    return n


def _upsert_bb_commit(repo: str, c: dict) -> None:
    sha = c["hash"]
    message = c.get("message", "")
    flags = parse_commit_flags(message)
    committed_at = c.get("date")
    author = c.get("author") or {}
    user = author.get("user") or {}
    author_login = (
        user.get("nickname")
        or user.get("display_name")
        or author.get("raw")
    )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO commits(sha, repo, author_login, author_team, committed_at,
                                additions, deletions, message, ai_flag, ai_level, jira_keys)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sha) DO UPDATE SET
                ai_flag=excluded.ai_flag, ai_level=excluded.ai_level,
                jira_keys=excluded.jira_keys, message=excluded.message
            """,
            (sha, repo, author_login, None, committed_at,
             0, 0, message,
             1 if flags.ai_flag else 0, flags.ai_level,
             ",".join(flags.jira_keys) if flags.jira_keys else None),
        )


def _fetch_bb_pulls(sess: requests.Session, repo: str, since: datetime) -> int:
    workspace, slug = repo.split("/", 1)
    url = f"{BITBUCKET_API}/repositories/{workspace}/{slug}/pullrequests"
    since_iso = since.isoformat(timespec="seconds")
    params = {
        "pagelen": 50,
        "sort": "-updated_on",
        "state": ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"],
        "q": f'updated_on>="{since_iso}"',
    }
    n = 0
    for pr in _paged(sess, url, params):
        _upsert_bb_pull(repo, pr, sess)
        n += 1
    return n


def _upsert_bb_pull(repo: str, pr: dict, sess: requests.Session) -> None:
    workspace, slug = repo.split("/", 1)
    number = pr["id"]
    title = pr.get("title")
    state = pr.get("state")
    opened = pr.get("created_on")
    merged_at = pr.get("updated_on") if state == "MERGED" else None
    author_obj = pr.get("author") or {}
    author = author_obj.get("nickname") or author_obj.get("display_name")

    additions, deletions = _sum_pr_diffstat(sess, workspace, slug, number)
    ai_flag, first_sha = _scan_pr_commits(sess, workspace, slug, number)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO pull_requests(repo, number, title, author, team,
                                      opened_at, merged_at, additions, deletions,
                                      first_commit_sha, ai_flag)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(repo, number) DO UPDATE SET
                title=excluded.title, merged_at=excluded.merged_at,
                additions=excluded.additions, deletions=excluded.deletions,
                first_commit_sha=excluded.first_commit_sha,
                ai_flag=excluded.ai_flag
            """,
            (repo, number, title, author, None, opened, merged_at,
             additions, deletions, first_sha, ai_flag),
        )


def _sum_pr_diffstat(sess: requests.Session, workspace: str, slug: str,
                     number: int) -> tuple[int, int]:
    additions = deletions = 0
    try:
        url = f"{BITBUCKET_API}/repositories/{workspace}/{slug}/pullrequests/{number}/diffstat"
        for f in _paged(sess, url, {"pagelen": 100}, timeout=20):
            additions += int(f.get("lines_added") or 0)
            deletions += int(f.get("lines_removed") or 0)
    except requests.RequestException as e:
        log.debug("diffstat 실패 PR#%s: %s", number, e)
    return additions, deletions


def _scan_pr_commits(sess: requests.Session, workspace: str, slug: str,
                     number: int) -> tuple[int, str | None]:
    ai_flag = 0
    earliest_sha = None
    earliest_at: datetime | None = None
    try:
        url = f"{BITBUCKET_API}/repositories/{workspace}/{slug}/pullrequests/{number}/commits"
        for c in _paged(sess, url, {"pagelen": 50}, timeout=20):
            msg = c.get("message", "")
            if parse_commit_flags(msg).ai_flag:
                ai_flag = 1
            try:
                at = datetime.fromisoformat((c.get("date") or "").replace("Z", "+00:00"))
            except ValueError:
                at = None
            if at and (earliest_at is None or at < earliest_at):
                earliest_at = at
                earliest_sha = c.get("hash")
    except requests.RequestException as e:
        log.debug("PR commits 실패 PR#%s: %s", number, e)
    return ai_flag, earliest_sha


# ─────────────────────────────────────────────────────────────────────────────
# 일별 품질 스냅샷
# ─────────────────────────────────────────────────────────────────────────────

def refresh_daily_quality() -> None:
    with db() as conn:
        conn.executescript(
            """
            DELETE FROM daily_quality WHERE day >= date('now', '-7 day');
            INSERT INTO daily_quality(day, total_commits, ai_commits)
            SELECT date(committed_at) AS day,
                   COUNT(*),
                   SUM(ai_flag)
            FROM commits
            WHERE committed_at >= datetime('now', '-7 day')
            GROUP BY date(committed_at);
            """
        )


# ─────────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────────

def run_once() -> None:
    started = datetime.now(timezone.utc)
    try:
        fetch_jira_issues()
        for repo in _list_repos():
            fetch_bitbucket_repo(repo)
        refresh_daily_quality()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info("ETL 완료 — %.1fs", elapsed)
    except Exception:
        log.exception("ETL 실패")
        _notify_failure()
        raise


def _notify_failure() -> None:
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": ":warning: Productivity ETL 실패"}, timeout=5)
    except requests.RequestException:
        pass


def run_scheduled() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", hours=1, next_run_time=datetime.now(timezone.utc))
    log.info("APScheduler 시작 — 1시간 주기")
    sched.start()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude productivity ETL (Jira + Bitbucket)")
    parser.add_argument("--schedule", action="store_true", help="1시간 주기로 계속 실행")
    args = parser.parse_args(argv)

    ensure_db()       # DB가 없으면 schema.sql 로 자동 생성
    validate_env()

    if args.schedule:
        run_scheduled()
    else:
        run_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
