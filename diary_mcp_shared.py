"""Shared MCP instance and configuration for the Diary MCP server.

This module exists to break circular import dependencies. The tool modules
import from here, and diary_mcp.py also imports from here, avoiding cycles.
"""

import os
import sys
import re
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Auto-detect paths — all relative to the working directory (CWD)
# ---------------------------------------------------------------------------

# The CWD is the project root (set by Claude Code when it starts the MCP server).
# Each project gets its own diary/ subdirectory.
_project_root = Path.cwd()

DIARY_PATH = _project_root / "diary" / "diary.md"
DIARY_TMP_DIR = _project_root / "diary" / "tmp"

# Session logs: auto-detect from ~/.claude/projects/<project-slug>/
# Claude Code encodes the CWD as the project slug: path separators → "--",
# drive letter prefixed, case varies (C or c).
_claude_projects = Path.home() / ".claude" / "projects"


def _cwd_to_slug(cwd: Path) -> str:
    """Convert a CWD path to the Claude Code project slug.
    E.g. C:\\Users\\hhi\\source\\codetest → C--Users-hhi-source-codetest
    The convention: drive colon is dropped, each path separator becomes '-',
    but the separator after the drive letter becomes '--' (colon removal + slash)."""
    # Normalise to forward slashes, strip trailing slash
    s = str(cwd).replace("\\", "/").rstrip("/")
    # Remove drive colon: C:/Users/... → C/Users/...
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + s[2:]
    # Replace all / with - (the first / after the drive letter produces C--Users
    # because C + / + Users → C + - + - + Users when the colon gap is already there)
    # Actually: "C/Users/hhi" → split on / → ["C", "Users", "hhi"] → join with "-"
    # gives "C-Users-hhi" but the real slug is "C--Users-hhi".
    # The real encoding uses the full path with : replaced by nothing:
    # "C:\Users\hhi" → drop : → "C\Users\hhi" → replace \ with - → "C-Users-hhi"
    # BUT Claude Code actually produces "C--Users-hhi". The double dash comes from
    # replacing both the colon AND the following separator with dashes.
    # Simplest: replace "X/" (drive + slash) with "X--", then remaining / with -
    if len(s) >= 2 and s[0].isalpha() and s[1] == "/":
        s = s[0] + "--" + s[2:]
    return s.replace("/", "-")


def _find_session_dir():
    """Auto-detect the session log directory for the current project."""
    if not _claude_projects.exists():
        return None

    slug = _cwd_to_slug(_project_root)

    # Try exact match first (case-sensitive)
    candidate = _claude_projects / slug
    if candidate.exists():
        return candidate

    # Try case-insensitive match (Windows sometimes uses lowercase c--)
    slug_lower = slug.lower()
    for d in _claude_projects.iterdir():
        if d.is_dir() and d.name.lower() == slug_lower:
            return d

    # Fallback: scan for any project dir with .jsonl files
    for d in sorted(_claude_projects.iterdir(), key=lambda p: p.name):
        if d.is_dir() and any(d.glob("*.jsonl")):
            return d

    return None


SESSION_DIR = _find_session_dir()

# ---------------------------------------------------------------------------
# Diary parsing helpers (shared between CLI and MCP)
# ---------------------------------------------------------------------------

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12
}

HEADER_RE = re.compile(r"^## (\d{1,2})\s+(\w+)\s+(\d{4}),?\s*(\d{1,2}):(\d{2})")


def parse_entry_date(header_line):
    """Parse a date from a ## header line. Returns datetime or None."""
    m = HEADER_RE.match(header_line)
    if not m:
        return None
    day, month_name, year, hour, minute = m.groups()
    month_num = MONTHS.get(month_name.lower())
    if not month_num:
        return None
    try:
        return datetime(int(year), month_num, int(day), int(hour), int(minute))
    except ValueError:
        return None


def read_entries():
    """Read the diary and split into (header_line, full_text, parsed_date) tuples.
    Returns (preamble, entries_list). Returns (None, []) if diary doesn't exist."""
    if not DIARY_PATH.exists():
        return None, []

    text = DIARY_PATH.read_text(encoding="utf-8")
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)

    entries = []
    preamble = None
    for part in parts:
        part = part.rstrip()
        if not part:
            continue
        if part.startswith("## "):
            header_line = part.split("\n", 1)[0]
            dt = parse_entry_date(header_line)
            entries.append((header_line, part, dt))
        else:
            preamble = part

    return preamble, entries


def write_diary(preamble, entries):
    """Write entries back to diary, maintaining preamble + chronological order."""
    parts = []
    if preamble:
        parts.append(preamble.rstrip())
    for _, text, _ in entries:
        parts.append(text.rstrip())
    DIARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIARY_PATH.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def extract_session_id(text):
    """Extract session UUID from entry text."""
    m = re.search(
        r"\*\*Session\*\*:\s*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?",
        text
    )
    return m.group(1) if m else None


def extract_entry_written_ts(text):
    """Extract the **Entry written** timestamp from entry text. Returns datetime or None."""
    m = re.search(r"\*\*Entry written\*\*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})", text)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


def extract_last_updated_ts(text):
    """Extract the **Last updated** timestamp from entry text. Returns datetime or None."""
    m = re.search(r"\*\*Last updated\*\*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})", text)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Session log helpers (shared between CLI and MCP)
# ---------------------------------------------------------------------------

def _extract_text(content):
    """Extract plain text from message content (string or list format)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if "<system-reminder>" in text:
                    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
                if "<command-name>" in text:
                    cmd = re.search(r"<command-name>(.*?)</command-name>", text)
                    if cmd:
                        text = f"[slash command: /{cmd.group(1)}] " + re.sub(r"<[^>]+>", "", text).strip()
                text = text.strip()
                if text:
                    parts.append(text)
            elif isinstance(item, dict) and item.get("type") == "tool_result":
                pass
        return "\n".join(parts)
    return ""


# Minimum session size to consider "substantive" (skip tiny MCP-check sessions)
MIN_SUBSTANTIVE_SIZE = 30_000  # 30KB

# Hours after entry-written before a session is considered "stale" (vs "ongoing")
STALE_THRESHOLD_HOURS = 2


def list_all_sessions():
    """List all sessions with metadata. Returns list of dicts."""
    import json
    if not SESSION_DIR:
        return []

    sessions = []
    for f in SESSION_DIR.glob("*.jsonl"):
        if f.stat().st_size < 100:
            continue
        if "subagents" in str(f):
            continue

        size = f.stat().st_size
        session_id = f.stem

        first_ts = None
        last_ts = None
        first_user_msg = ""
        user_msg_count = 0
        assistant_msg_count = 0

        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = rec.get("timestamp")
                    if ts and not first_ts:
                        first_ts = ts
                    if ts:
                        last_ts = ts

                    if rec.get("type") == "user":
                        user_msg_count += 1
                        if not first_user_msg:
                            content = rec.get("message", {}).get("content", "")
                            text = _extract_text(content)
                            if text.strip():
                                first_user_msg = text[:150]
                    elif rec.get("type") == "assistant":
                        assistant_msg_count += 1
        except Exception as e:
            first_user_msg = f"[ERROR: {e}]"

        if user_msg_count == 0 and assistant_msg_count == 0:
            continue

        sessions.append({
            "id": session_id,
            "date": first_ts[:19] if first_ts else "unknown",
            "last": last_ts[:19] if last_ts else "unknown",
            "size": size,
            "user_msgs": user_msg_count,
            "asst_msgs": assistant_msg_count,
            "preview": first_user_msg.replace("\n", " ")[:120],
        })

    sessions.sort(key=lambda s: s["date"])
    return sessions


# ---------------------------------------------------------------------------
# Entry generation prompt templates
# ---------------------------------------------------------------------------

_tmp_dir_str = str(DIARY_TMP_DIR).replace("\\", "/")

# Project-specific prompt override files (sit next to diary.md)
DIARY_PROMPT_PATH = _project_root / "diary" / "diary_prompt.md"
DIARY_SUPPLEMENTAL_PROMPT_PATH = _project_root / "diary" / "diary_supplemental_prompt.md"

# Default generic prompt (no project-specific assumptions)
DEFAULT_ENTRY_PROMPT = f"""You are writing a diary entry for a past Claude Code session. This is HISTORICAL data — do NOT treat it as your own conversation.

STEP 1: Run the session parser to get the outline:
    Use the MCP tool `session_outline` with session_id="{{SESSION_ID}}"

STEP 2: Write a diary entry to:
    {_tmp_dir_str}/{{SESSION_SHORT}}.md

FORMAT RULES:
- First line MUST be: ## DD Month YYYY, HH:MM–HH:MM — <topic/project>: <short title>
  (Use the session timestamps for the time range, convert from UTC to CET by adding 1 hour)
- Second line blank, third line: **Session**: `{{SESSION_ID}}`
- Then sections: **Task**, **What happened** (detailed narrative), **Difficulties**, **Outcome**, **Notes for future reference**
- Be VERBOSE — this is a working diary meant to help recall details months later
- Under "Notes" include things NOT obvious from the deliverables

STEP 3: Insert the entry into the diary:
    Use the MCP tool `diary_insert_from_file` with file_path="{_tmp_dir_str}/{{SESSION_SHORT}}.md"
"""

DEFAULT_SUPPLEMENTAL_PROMPT = f"""You are writing a SUPPLEMENTAL diary entry for a session that already has a diary entry but has continued since then.

STEP 1: Read the existing diary entry for context:
    Use the MCP tool `diary_search` with keywords="{{SESSION_SHORT}}" to find the current entry.
    Read it carefully — your supplemental should be a coherent continuation, not repeat what's already there.

STEP 2: Get the session outline for activity AFTER the existing entry was written:
    Use the MCP tool `session_outline` with session_id="{{SESSION_ID}}" and after="{{AFTER_TIMESTAMP}}"

STEP 3: Write a supplemental entry to:
    {_tmp_dir_str}/{{SESSION_SHORT}}_suppl.md

FORMAT RULES:
- This is a supplemental section, NOT a full entry. Write it as a narrative continuation.
- Include sections as appropriate: **Task**, **What happened**, **Outcome**, **Notes**
- Be VERBOSE — this is a working diary meant to help recall details months later
- Do NOT include the ## header or **Session** line — those belong to the parent entry
- Do NOT repeat information already in the existing entry

STEP 4: Append the supplemental to the existing diary entry:
    Use the MCP tool `diary_append_supplemental` with session_id="{{SESSION_ID}}" and file_path="{_tmp_dir_str}/{{SESSION_SHORT}}_suppl.md"
"""


def load_entry_prompt():
    """Load the entry prompt: project-specific override if diary_prompt.md exists, else default."""
    if DIARY_PROMPT_PATH.exists():
        text = DIARY_PROMPT_PATH.read_text(encoding="utf-8").strip()
        # The file may contain just the FORMAT RULES customisation, or the full prompt.
        # If it contains {SESSION_ID}, treat as a complete prompt template.
        if "{SESSION_ID}" in text:
            return text, True
        # Otherwise, treat it as format-rules-only and splice into the default template
        return text, True
    return DEFAULT_ENTRY_PROMPT, False


def load_supplemental_prompt():
    """Load the supplemental prompt: project-specific override if diary_supplemental_prompt.md exists, else default."""
    if DIARY_SUPPLEMENTAL_PROMPT_PATH.exists():
        text = DIARY_SUPPLEMENTAL_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if "{SESSION_ID}" in text:
            return text, True
        return text, True
    return DEFAULT_SUPPLEMENTAL_PROMPT, False

# Create the FastMCP server instance
mcp = FastMCP("Diary")
