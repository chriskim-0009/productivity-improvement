# Claude Productivity Dashboard — PoC Getting-Started Guide

With the files in this folder you can spin up a demo in 5 minutes and finish a PoC within a week. Steps are written so that non-developers can follow along too.

## What's in this folder

| File | What it is |
|---|---|
| `ADR-001-claude-productivity-dashboard.md` | The "why we built it this way" design record — a doc to share with decision-makers/managers |
| `schema.sql` | Table definitions for the stored data |
| `prepare-commit-msg` | A Git hook (Python script) that auto-appends `Assisted-By: claude` to commits |
| `etl.py` | Ingestion script that pulls data from Jira and **Bitbucket Cloud** |
| `dashboard.py` | Web dashboard (Streamlit) with 5 charts and filters |
| `requirements.txt` | Required Python packages |
| `OPERATIONS.md` | Operations/handoff guide (architecture, deploy, automation, troubleshooting) |

---

## Prerequisites

1. **Python 3.10+** installed (`python3 --version` in a terminal).
2. **Atlassian API token** (one token authenticates both Jira and Bitbucket):
   - Go to <https://id.atlassian.com/manage-profile/security/api-tokens>
   - Click **Create API token with scopes**
   - Required scopes (read-only):
     - Jira: `read:jira-work`, `read:jira-user`
     - Bitbucket: `read:repository:bitbucket`, `read:pullrequest:bitbucket`, `read:account:bitbucket`
   - Copy the generated string immediately (you can't see it again once the window closes)
3. (Alternative) Bitbucket **App password** — being deprecated soon but still works.
   - Bitbucket top-right avatar → Personal settings → App passwords → Create
   - Permissions: Repositories: Read, Pull requests: Read, Account: Read

---

## Step-by-step

### 1) Create a virtual environment and install packages

```bash
cd <this folder>
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure environment variables — create a new `.env` file

```env
# Jira (Atlassian Cloud)
JIRA_BASE_URL=https://doverunner.atlassian.net
JIRA_EMAIL=you@doverunner.com
JIRA_TOKEN=your_atlassian_api_token
JIRA_PROJECTS=AS,AR
JIRA_TEAM_FIELD=                # Custom field ID holding team info. Leave empty to use the first component instead.

# Bitbucket Cloud
# With an API token fill BITBUCKET_EMAIL; with an App password fill BITBUCKET_USERNAME
BITBUCKET_EMAIL=you@doverunner.com
# BITBUCKET_USERNAME=          # only when using an App password
BITBUCKET_TOKEN=your_atlassian_api_token_or_app_password
# Two ways to specify repositories — either alone works; using both merges them.
# (A) Auto-discovery: include active repos from the project(s) below on every run.
#     New repos are picked up automatically, so it pairs well with scheduled runs.
BITBUCKET_WORKSPACE=appsealing   # workspace to scan
BITBUCKET_PROJECTS=AS,AR         # project keys to scan (comma-separated). Empty = no auto-discovery
BITBUCKET_ACTIVE_DAYS=90         # only repos updated within the last N days (default 90)
# (B) Manual list: workspace/repo_slug, comma-separated. Works on its own without auto-discovery.
BITBUCKET_REPOS=
BITBUCKET_BRANCH=develop        # branch to collect commits from (PoC default: develop). Repos without it fall back to the default branch.

# IMPORTANT: use an ABSOLUTE path. A relative path (./data.sqlite) breaks when run
# from cron or another directory (it opens an empty DB → "no such table" errors).
DB_PATH=/Users/<you>/Desktop/Automation/ai_productivity/data.sqlite
SLACK_WEBHOOK=                  # fill in if you want failure alerts
```

> If Jira and Bitbucket share the same Atlassian account, you **can put one API token into both variables (`JIRA_TOKEN`, `BITBUCKET_TOKEN`)** — just grant both services' scopes when creating it.

### 3) Create the database

```bash
sqlite3 data.sqlite < schema.sql
```

> On Windows without the `sqlite3` command, download it from https://www.sqlite.org/download.html, or create it with Python:
> ```bash
> python -c "import sqlite3; sqlite3.connect('data.sqlite').executescript(open('schema.sql').read())"
> ```

### 4) Populate the data once

```bash
python etl.py
```

The first run pulls the last 90 days of issues/commits/PRs. It can take a few minutes for large teams/repos.

### 5) Launch the dashboard

```bash
streamlit run dashboard.py
```

Your browser opens at `http://localhost:8501`. Pick the date range / team / repository in the sidebar and the 5 charts refresh.

### 6) Auto-refresh every hour

Pick whichever of the three is convenient.

**a. Run it directly with APScheduler** (simplest)

```bash
python etl.py --schedule
```

Leave the terminal open and it runs every hour. On a server, keep it alive with `nohup` or `systemd`.

**b. Use cron on macOS / Linux**

```bash
crontab -e
# Add this one line (top of every hour)
0 * * * * cd /path/to/this/folder && /path/to/.venv/bin/python etl.py >> etl.log 2>&1
```

**c. Use Bitbucket Pipelines schedules**

Add a schedule step to `bitbucket-pipelines.yml`.

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

  # In Bitbucket: Repository settings → Pipelines → Schedules,
  # register the 'hourly-etl' custom pipeline to run hourly.
```

Register `JIRA_TOKEN`, `BITBUCKET_TOKEN`, etc. as **Secured** Bitbucket Pipelines variables.

> Tip: to keep a **hosted (e.g., Streamlit Cloud) dashboard** fresh too, the scheduled job must also publish the refreshed `data.sqlite` snapshot (commit & push). See `OPERATIONS.md` for the end-to-end automation.

---

## Install the Git hook on developer machines

This is what auto-appends `Assisted-By: claude` to commit messages.

### Apply to one repository

```bash
cp prepare-commit-msg /path/to/your/repo/.git/hooks/prepare-commit-msg
chmod +x /path/to/your/repo/.git/hooks/prepare-commit-msg
```

### Apply to all repositories at once

```bash
mkdir -p ~/.git-hooks
cp prepare-commit-msg ~/.git-hooks/
chmod +x ~/.git-hooks/prepare-commit-msg
git config --global core.hooksPath ~/.git-hooks
```

### Usage

Turn the env var on only when you're using Claude, then commit.

```bash
CLAUDE_ASSISTED=1 git commit -m "feat: export billing CSV"
```

An alias in `.zshrc` or `.bashrc` is handy.

```bash
alias gcai='CLAUDE_ASSISTED=1 git commit'
```

> If you use Claude Code, prefer wiring the env var automatically via IDE/CLI integration — not relying on people to remember is the key to data quality.

---

## FAQ

**Q0. Bitbucket auth fails with 401.**
A. Check three things. (1) `BITBUCKET_EMAIL` is the exact email of your Atlassian account (if using an App password, put your Bitbucket username in `BITBUCKET_USERNAME`); (2) the API token includes Bitbucket scopes such as `read:repository:bitbucket`; (3) each `BITBUCKET_REPOS` entry is in `workspace/repo_slug` form (e.g., `appsealing/owl-app`).

**Q1. The data is empty.**
A. Make sure you ran `etl.py` at least once. API calls fail if env vars are empty. Check `etl.log`. Also confirm `DB_PATH` is an absolute path (a relative path can open the wrong/empty DB when run from cron).

**Q2. Why are there no per-person charts?**
A. Deliberately disabled in the first PoC. We'll introduce them in stages after resolving "ranking individuals" concerns (a governance decision via a separate ADR).

**Q3. Too many commits are missing the trailer.**
A. Two signals are counted together: (1) the hook's `Assisted-By: claude`, and (2) the **`Co-authored-by: Claude ...` trailer that Claude Code adds automatically when it authors a commit**. So commits made with Claude Code are caught even without the hook installed. If misses are still high: check the "Data quality" note at the bottom of the dashboard, and verify (a) the `prepare-commit-msg` hook is installed/active for commits made by hand outside Claude Code, and (b) your IDE integration sets the env var. (Detection rules live in one place: `parse_commit_flags` in `etl.py`.)

**Q4. What happened to the defect-rate chart?**
A. It was removed from the current dashboard. As implemented it was just "share of issues whose type is Bug/Defect" — not split by AI/Human, so it didn't serve this dashboard's purpose and risked misreading. A proper AI-vs-Human defect/rework metric is planned for ADR-002.

**Q5. Why do Lead time / PR cycle exclude some points?**
A. Those charts exclude abnormally long **outliers** (above the Tukey upper fence, Q3 + 1.5·IQR) before computing the weekly median, so one unusually long-running issue/PR (e.g., one open ~45 days) doesn't distort the trend. AI-linked samples are small because few commits reference Jira keys, so the comparison should still be read with care.

**Q6. How do we move to PostgreSQL?**
A. Swap `sqlite3` → `psycopg2`/`sqlalchemy` in the code; the schema ports almost as-is. Do this when the team grows past ~50 people or a month of data exceeds ~1M rows. This also removes the need to publish SQLite snapshots to keep a hosted dashboard fresh.

---

## Next steps (after the PoC)

- ADR-002 (planned): governance/privacy decisions for individual-level measurement
- Refine the quality metric (track linked issues, detect re-edits of the same file; reintroduce defect/rework split by AI/Human)
- Integrate other AI-tool labels such as Cursor, Copilot (`Assisted-By: cursor`, etc.)
- Manager alerts: Slack DM when the weekly change rate crosses a threshold
