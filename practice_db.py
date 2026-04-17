"""SQLite backend for the practice knowledge base.

Manages two tables:
  - work_log: structured record of what was done, when, on which case
  - practice_rules: accumulated operational rules, tagged by context

The database file lives at diary/practice.db alongside diary.md.
"""

import sqlite3
from pathlib import Path
from diary_mcp_shared import _project_root

DB_PATH = _project_root / "diary" / "practice.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    date        TEXT NOT NULL,
    matter_code TEXT,
    client      TEXT,
    action_type TEXT NOT NULL,
    outcome     TEXT,
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS practice_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    rule           TEXT NOT NULL,
    rationale      TEXT,
    contexts       TEXT NOT NULL,
    source_session TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')),
    updated_at     TEXT,
    active         INTEGER NOT NULL DEFAULT 1
);
"""


def get_db() -> sqlite3.Connection:
    """Open (and initialise if needed) the practice database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# work_log helpers
# ---------------------------------------------------------------------------

def insert_work_log(*, session_id: str = "", date: str, matter_code: str = "",
                    client: str = "", action_type: str, outcome: str = "",
                    summary: str = "") -> int:
    """Insert a work_log row. Returns the new row id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO work_log (session_id, date, matter_code, client, action_type, outcome, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, date, matter_code, client, action_type, outcome, summary),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def query_work_log(*, client: str = "", matter_code: str = "",
                   action_type: str = "", since: str = "", until: str = "",
                   limit: int = 50) -> list[dict]:
    """Query work_log with optional filters. Returns list of dicts."""
    clauses = []
    params = []
    if client:
        clauses.append("LOWER(client) = LOWER(?)")
        params.append(client)
    if matter_code:
        clauses.append("matter_code LIKE ?")
        params.append(f"%{matter_code}%")
    if action_type:
        clauses.append("LOWER(action_type) = LOWER(?)")
        params.append(action_type)
    if since:
        clauses.append("date >= ?")
        params.append(since)
    if until:
        clauses.append("date <= ?")
        params.append(until)

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"SELECT * FROM work_log WHERE {where} ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_work_log(*, since: str = "", group_by: str = "client") -> list[dict]:
    """Aggregate work_log counts. group_by can be 'client', 'action_type',
    or 'client,action_type'."""
    allowed = {"client", "action_type", "matter_code"}
    cols = [c.strip() for c in group_by.split(",") if c.strip() in allowed]
    if not cols:
        cols = ["client"]
    group_expr = ", ".join(cols)

    params = []
    where = "1=1"
    if since:
        where = "date >= ?"
        params.append(since)

    sql = (
        f"SELECT {group_expr}, COUNT(*) as count "
        f"FROM work_log WHERE {where} "
        f"GROUP BY {group_expr} ORDER BY count DESC"
    )

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# practice_rules helpers
# ---------------------------------------------------------------------------

def insert_rule(*, rule: str, rationale: str = "", contexts: str,
                source_session: str = "") -> int:
    """Insert a new practice rule. Returns the new row id."""
    # Normalise context tags: lowercase, strip whitespace, deduplicate
    tags = _normalise_contexts(contexts)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO practice_rules (rule, rationale, contexts, source_session) "
            "VALUES (?, ?, ?, ?)",
            (rule, rationale, tags, source_session),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def lookup_rules(contexts: str) -> list[dict]:
    """Find active rules matching ANY of the given context tags."""
    tags = [t.strip().lower() for t in contexts.split(",") if t.strip()]
    if not tags:
        return []

    # Build OR conditions: contexts LIKE '%tag%' for each tag
    clauses = ["contexts LIKE ?" for _ in tags]
    params = [f"%{t}%" for t in tags]

    where = "active = 1 AND (" + " OR ".join(clauses) + ")"
    sql = f"SELECT * FROM practice_rules WHERE {where} ORDER BY id"

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_rule(rule_id: int, *, rule: str = "", rationale: str = "",
                contexts: str = "", active: int = -1) -> bool:
    """Update fields on an existing rule. Only non-empty values are changed.
    Returns True if a row was updated."""
    sets = []
    params = []
    if rule:
        sets.append("rule = ?")
        params.append(rule)
    if rationale:
        sets.append("rationale = ?")
        params.append(rationale)
    if contexts:
        sets.append("contexts = ?")
        params.append(_normalise_contexts(contexts))
    if active >= 0:
        sets.append("active = ?")
        params.append(active)

    if not sets:
        return False

    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')")
    sql = f"UPDATE practice_rules SET {', '.join(sets)} WHERE id = ?"
    params.append(rule_id)

    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_rules(active_only: bool = True) -> list[dict]:
    """List all practice rules, optionally filtering to active only."""
    where = "active = 1" if active_only else "1=1"
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT * FROM practice_rules WHERE {where} ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_contexts() -> list[tuple[str, int]]:
    """Return all distinct context tags with their rule counts, sorted by count descending."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT contexts FROM practice_rules WHERE active = 1"
        ).fetchall()
    finally:
        conn.close()

    counts: dict[str, int] = {}
    for row in rows:
        for tag in row["contexts"].split(","):
            tag = tag.strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1

    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def find_similar_rules(contexts: str, keywords: list[str]) -> list[dict]:
    """Find active rules that share contexts AND contain any of the given keywords.
    Use this before inserting a new rule to check for near-duplicates.

    contexts: comma-separated tags (matches rules sharing ANY tag)
    keywords: list of distinctive words from the candidate rule

    Returns matching rules sorted by relevance (number of keyword hits)."""
    # First get rules with overlapping contexts
    candidates = lookup_rules(contexts)
    if not candidates or not keywords:
        return candidates  # return context matches even without keyword filtering

    # Score each candidate by keyword overlap
    kw_lower = [k.lower() for k in keywords if len(k) >= 4]  # skip short words
    if not kw_lower:
        return candidates

    scored = []
    for r in candidates:
        rule_lower = r["rule"].lower()
        hits = sum(1 for kw in kw_lower if kw in rule_lower)
        if hits > 0:
            scored.append((hits, r))

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored]


# ---------------------------------------------------------------------------
# Setup check
# ---------------------------------------------------------------------------

def check_setup() -> dict:
    """Check the state of the diary + practice system. Returns a dict with
    status of each component."""
    from diary_mcp_shared import (
        DIARY_PATH, SESSION_DIR, DIARY_PROMPT_PATH, DIARY_SUPPLEMENTAL_PROMPT_PATH,
        SUPPRESSED_PATH, _claude_projects, _cwd_to_slug, _project_root,
        read_entries,
    )

    result = {}

    # Diary file
    if DIARY_PATH.exists():
        _, entries = read_entries()
        result["diary_md"] = {"status": "ok", "entries": len(entries)}
    else:
        result["diary_md"] = {"status": "missing"}

    # Practice database
    if DB_PATH.exists():
        conn = get_db()
        try:
            rules_active = conn.execute(
                "SELECT COUNT(*) FROM practice_rules WHERE active = 1"
            ).fetchone()[0]
            rules_inactive = conn.execute(
                "SELECT COUNT(*) FROM practice_rules WHERE active = 0"
            ).fetchone()[0]
            wl_count = conn.execute("SELECT COUNT(*) FROM work_log").fetchone()[0]
            wl_range = conn.execute(
                "SELECT MIN(date), MAX(date) FROM work_log"
            ).fetchone()
            ctx_count = len(list_contexts())
        finally:
            conn.close()
        result["practice_db"] = {
            "status": "ok",
            "rules_active": rules_active,
            "rules_inactive": rules_inactive,
            "work_log_count": wl_count,
            "work_log_range": (wl_range[0] or "", wl_range[1] or ""),
            "context_tags": ctx_count,
        }
    else:
        result["practice_db"] = {"status": "missing"}

    # Session directory
    if SESSION_DIR and SESSION_DIR.exists():
        session_count = len(list(SESSION_DIR.glob("*.jsonl")))
        result["session_dir"] = {"status": "ok", "sessions": session_count,
                                 "path": str(SESSION_DIR)}
    else:
        result["session_dir"] = {"status": "missing"}

    # Optional files
    result["diary_prompt"] = "custom" if DIARY_PROMPT_PATH.exists() else "default"
    result["diary_supplemental_prompt"] = (
        "custom" if DIARY_SUPPLEMENTAL_PROMPT_PATH.exists() else "default"
    )
    result["suppressed_json"] = "ok" if SUPPRESSED_PATH.exists() else "missing"

    # MEMORY.md integration
    slug = _cwd_to_slug(_project_root)
    memory_dir = _claude_projects / slug / "memory"
    # Try case-insensitive match
    if not memory_dir.exists():
        slug_lower = slug.lower()
        for d in _claude_projects.iterdir():
            if d.is_dir() and d.name.lower() == slug_lower:
                memory_dir = d / "memory"
                break

    memory_md = memory_dir / "MEMORY.md"
    if memory_md.exists():
        text = memory_md.read_text(encoding="utf-8")
        result["memory_md"] = {
            "status": "ok",
            "path": str(memory_md),
            "has_practice_db_ref": "practice.db" in text or "practice_rules" in text,
            "has_lookup_rule": "practice_rules_lookup" in text,
            "has_correction_rule": "practice_rules_add" in text,
        }
    else:
        result["memory_md"] = {"status": "missing", "path": str(memory_md)}

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_contexts(raw: str) -> str:
    """Lowercase, strip, deduplicate, sort, comma-join."""
    tags = sorted(set(t.strip().lower() for t in raw.split(",") if t.strip()))
    return ",".join(tags)
