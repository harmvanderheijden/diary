"""
Session Log Parser for Claude Code
===================================
Extracts structured summaries from Claude Code session JSONL logs.

Usage:
    python session_parser.py list                     # List all sessions with dates and sizes
    python session_parser.py summary <session_id>     # Extract a compact summary of a session
    python session_parser.py user_messages <session_id>  # Extract just user messages (what was asked)
    python session_parser.py outline <session_id>     # Outline: user messages + assistant text (no tool details)

All output goes to stdout. The summaries are designed to be compact enough
to be safely consumed by Claude Code without blowing up the context window.

For large sessions (>2MB), the outline mode truncates assistant messages
to keep output manageable.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Auto-detect session dir from CWD (same logic as diary_mcp_shared)
def _cwd_to_slug(cwd: Path) -> str:
    s = str(cwd).replace("\\", "/").rstrip("/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + s[2:]
    if len(s) >= 2 and s[0].isalpha() and s[1] == "/":
        s = s[0] + "--" + s[2:]
    return s.replace("/", "-")

def _find_session_dir():
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return None
    slug = _cwd_to_slug(Path.cwd())
    candidate = projects / slug
    if candidate.exists():
        return candidate
    slug_lower = slug.lower()
    for d in projects.iterdir():
        if d.is_dir() and d.name.lower() == slug_lower:
            return d
    return None

SESSION_DIR = _find_session_dir()


def list_sessions():
    """List all sessions with date, size, and first user message preview."""
    if not SESSION_DIR:
        print("ERROR: Could not find session log directory for CWD: %s" % Path.cwd())
        return
    sessions = []
    for f in SESSION_DIR.glob("*.jsonl"):
        if f.stat().st_size < 100:
            continue  # skip empty/trivial files
        # Don't recurse into subagent dirs
        if "subagents" in str(f):
            continue

        size = f.stat().st_size
        session_id = f.stem

        # Extract timestamp and first user message
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
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        text = item["text"]
                                        # Strip system reminders and command tags
                                        if "<system-reminder>" in text:
                                            # Find text after all system tags
                                            parts = text.split("</system-reminder>")
                                            text = parts[-1] if parts else text
                                        if "<command-name>" in text:
                                            # It's a slash command, skip
                                            continue
                                        text = text.strip()
                                        if text:
                                            first_user_msg = text[:150]
                                            break
                            elif isinstance(content, str):
                                first_user_msg = content[:150]

                    elif rec.get("type") == "assistant":
                        assistant_msg_count += 1
        except Exception as e:
            first_user_msg = f"[ERROR: {e}]"

        if user_msg_count == 0 and assistant_msg_count == 0:
            continue  # Skip sessions with no real conversation

        sessions.append({
            "id": session_id,
            "date": first_ts[:19] if first_ts else "unknown",
            "last": last_ts[:19] if last_ts else "unknown",
            "size": size,
            "user_msgs": user_msg_count,
            "asst_msgs": assistant_msg_count,
            "preview": first_user_msg.replace("\n", " ")[:120],
        })

    # Sort by date
    sessions.sort(key=lambda s: s["date"])

    print(f"{'Date':<22} {'Size':>8} {'U/A':>6} {'ID':<38} Preview")
    print("-" * 140)
    for s in sessions:
        size_str = f"{s['size']//1024}K"
        ua = f"{s['user_msgs']}/{s['asst_msgs']}"
        print(f"{s['date']:<22} {size_str:>8} {ua:>6} {s['id']:<38} {s['preview'][:60]}")


def extract_user_messages(session_id):
    """Extract just user messages from a session."""
    if not SESSION_DIR:
        print("ERROR: No session log directory found."); return
    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        print(f"Session not found: {session_id}")
        return

    with open(path, encoding="utf-8") as f:
        msg_num = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if rec.get("type") != "user":
                continue

            msg_num += 1
            ts = rec.get("timestamp", "?")[:19]
            content = rec.get("message", {}).get("content", "")
            text = _extract_text(content)

            if not text.strip():
                continue

            print(f"\n=== USER [{msg_num}] {ts} ===")
            # Truncate very long messages
            if len(text) > 2000:
                print(text[:2000])
                print(f"... [truncated, {len(text)} chars total]")
            else:
                print(text)


def extract_summary(session_id):
    """Extract a compact summary: tools used, matter codes, key topics."""
    if not SESSION_DIR:
        print("ERROR: No session log directory found."); return
    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        print(f"Session not found: {session_id}")
        return

    first_ts = None
    last_ts = None
    user_messages = []
    tools_used = set()
    matter_codes = set()
    files_mentioned = set()
    mcp_tools = set()

    with open(path, encoding="utf-8") as f:
        for line in f:
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
                content = rec.get("message", {}).get("content", "")
                text = _extract_text(content)
                if text.strip():
                    user_messages.append(text[:500])

            elif rec.get("type") == "assistant":
                content = rec.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            name = item.get("name", "")
                            tools_used.add(name)
                            if name.startswith("mcp__equinox__"):
                                mcp_tools.add(name.replace("mcp__equinox__", ""))
                            inp = item.get("input", {})
                            # Extract matter codes
                            for key in ["matter_code", "matter_id"]:
                                if key in inp:
                                    matter_codes.add(str(inp[key]))
                            # Extract file paths
                            for key in ["file_path", "save_path", "msg_path", "docx_path"]:
                                if key in inp and inp[key]:
                                    files_mentioned.add(str(inp[key]))

    print(f"Session: {session_id}")
    print(f"Period:  {first_ts[:19] if first_ts else '?'} -> {last_ts[:19] if last_ts else '?'}")
    print(f"User messages: {len(user_messages)}")
    print(f"Tools used: {', '.join(sorted(tools_used))}")
    if mcp_tools:
        print(f"Equinox tools: {', '.join(sorted(mcp_tools))}")
    if matter_codes:
        print(f"Matter codes: {', '.join(sorted(matter_codes))}")
    if files_mentioned:
        print(f"Files: {', '.join(sorted(files_mentioned))}")
    print()
    print("--- User messages ---")
    for i, msg in enumerate(user_messages, 1):
        # Clean up
        msg = msg.replace("\n", " ").strip()
        if len(msg) > 300:
            msg = msg[:300] + "..."
        print(f"  [{i}] {msg}")


def extract_outline(session_id):
    """Extract conversation outline: user messages + assistant text responses (no tool details).
    For large sessions, truncates to keep output manageable."""
    if not SESSION_DIR:
        print("ERROR: No session log directory found."); return
    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        print(f"Session not found: {session_id}")
        return

    size = path.stat().st_size
    # For very large sessions, be more aggressive with truncation
    max_assistant_text = 500 if size > 2_000_000 else 1500
    max_user_text = 1000 if size > 2_000_000 else 3000

    first_ts = None

    with open(path, encoding="utf-8") as f:
        msg_num = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = rec.get("timestamp", "")[:19]
            if ts and not first_ts:
                first_ts = ts

            if rec.get("type") == "user":
                msg_num += 1
                content = rec.get("message", {}).get("content", "")
                text = _extract_text(content)
                if not text.strip():
                    continue
                print(f"\n{'='*60}")
                print(f"USER [{msg_num}] {ts}")
                print(f"{'='*60}")
                if len(text) > max_user_text:
                    print(text[:max_user_text])
                    print(f"... [truncated from {len(text)} chars]")
                else:
                    print(text)

            elif rec.get("type") == "assistant":
                content = rec.get("message", {}).get("content", [])
                texts = []
                tools = []
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text" and item.get("text", "").strip():
                                texts.append(item["text"])
                            elif item.get("type") == "tool_use":
                                tool_name = item.get("name", "?")
                                inp = item.get("input", {})
                                # Compact tool summary
                                tool_summary = tool_name
                                for key in ["matter_code", "file_path", "msg_path", "pattern", "command", "query", "username", "prompt"]:
                                    if key in inp:
                                        val = str(inp[key])[:80]
                                        tool_summary += f" ({key}={val})"
                                        break
                                tools.append(tool_summary)
                elif isinstance(content, str) and content.strip():
                    texts.append(content)

                if texts or tools:
                    print(f"\n--- Assistant ---")
                    if tools:
                        print(f"  Tools: {'; '.join(tools)}")
                    for t in texts:
                        if len(t) > max_assistant_text:
                            print(t[:max_assistant_text])
                            print(f"  ... [truncated from {len(t)} chars]")
                        else:
                            print(t)


def _extract_text(content):
    """Extract plain text from message content (string or list format)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                # Strip system reminders
                if "<system-reminder>" in text:
                    import re
                    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
                # Strip command tags but keep command name
                if "<command-name>" in text:
                    import re
                    cmd = re.search(r"<command-name>(.*?)</command-name>", text)
                    if cmd:
                        text = f"[slash command: /{cmd.group(1)}] " + re.sub(r"<[^>]+>", "", text).strip()
                text = text.strip()
                if text:
                    parts.append(text)
            elif isinstance(item, dict) and item.get("type") == "tool_result":
                # Skip tool results in user messages (they're responses to tool calls)
                pass
        return "\n".join(parts)
    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        list_sessions()
    elif cmd == "summary" and len(sys.argv) > 2:
        extract_summary(sys.argv[2])
    elif cmd == "user_messages" and len(sys.argv) > 2:
        extract_user_messages(sys.argv[2])
    elif cmd == "outline" and len(sys.argv) > 2:
        extract_outline(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
