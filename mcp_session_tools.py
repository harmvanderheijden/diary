"""Session log parsing tools for the MCP server."""

import json
import re
from diary_mcp_shared import mcp, SESSION_DIR, _extract_text


@mcp.tool()
def session_list() -> str:
    """List all Claude Code sessions with dates, sizes, message counts, and previews.
    Sessions are sorted chronologically. Use this to find session IDs for further analysis."""
    if not SESSION_DIR:
        return "ERROR: No session log directory found."

    from diary_mcp_shared import list_all_sessions
    sessions = list_all_sessions()
    if not sessions:
        return "No sessions found."

    lines = [f"{'Date':<22} {'Size':>8} {'U/A':>6} {'ID':<38} Preview"]
    lines.append("-" * 140)
    for s in sessions:
        size_str = f"{s['size'] // 1024}K"
        ua = f"{s['user_msgs']}/{s['asst_msgs']}"
        lines.append(f"{s['date']:<22} {size_str:>8} {ua:>6} {s['id']:<38} {s['preview'][:60]}")
    return "\n".join(lines)


@mcp.tool()
def session_summary(session_id: str) -> str:
    """Extract a compact summary of a session: period, tools used, matter codes, files, user message previews.
    Provide the full session UUID."""
    if not SESSION_DIR:
        return "ERROR: No session log directory found."

    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return f"Session not found: {session_id}"

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
                            for key in ["matter_code", "matter_id"]:
                                if key in inp:
                                    matter_codes.add(str(inp[key]))
                            for key in ["file_path", "save_path", "msg_path", "docx_path"]:
                                if key in inp and inp[key]:
                                    files_mentioned.add(str(inp[key]))

    lines = [
        f"Session: {session_id}",
        f"Period:  {first_ts[:19] if first_ts else '?'} -> {last_ts[:19] if last_ts else '?'}",
        f"User messages: {len(user_messages)}",
        f"Tools used: {', '.join(sorted(tools_used))}",
    ]
    if mcp_tools:
        lines.append(f"Equinox tools: {', '.join(sorted(mcp_tools))}")
    if matter_codes:
        lines.append(f"Matter codes: {', '.join(sorted(matter_codes))}")
    if files_mentioned:
        lines.append(f"Files: {', '.join(sorted(files_mentioned))}")
    lines.append("")
    lines.append("--- User messages ---")
    for i, msg in enumerate(user_messages, 1):
        msg = msg.replace("\n", " ").strip()
        if len(msg) > 300:
            msg = msg[:300] + "..."
        lines.append(f"  [{i}] {msg}")
    return "\n".join(lines)


@mcp.tool()
def session_outline(session_id: str, after: str = "") -> str:
    """Extract conversation outline: user messages + assistant text responses + tool call summaries.
    Auto-truncates for large sessions (>2MB). This is the primary tool for diary entry generation.

    If `after` is provided (ISO timestamp like '2026-03-12T16:46'), only records with
    timestamps after that point are included. Use this for writing supplemental entries."""
    if not SESSION_DIR:
        return "ERROR: No session log directory found."

    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return f"Session not found: {session_id}"

    # Parse the after filter
    after_dt = None
    if after:
        from datetime import datetime as _dt
        try:
            after_dt = _dt.fromisoformat(after)
        except ValueError:
            return f"ERROR: Invalid 'after' timestamp: {after}. Use ISO format like '2026-03-12T16:46'."

    size = path.stat().st_size
    max_assistant_text = 500 if size > 2_000_000 else 1500
    max_user_text = 1000 if size > 2_000_000 else 3000

    lines = []
    first_ts = None
    skipped = 0

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

            # Apply after filter
            if after_dt and ts:
                from datetime import datetime as _dt
                try:
                    rec_dt = _dt.fromisoformat(ts)
                    if rec_dt <= after_dt:
                        if rec.get("type") == "user":
                            msg_num += 1
                        skipped += 1
                        continue
                except ValueError:
                    pass

            if rec.get("type") == "user":
                msg_num += 1
                content = rec.get("message", {}).get("content", "")
                text = _extract_text(content)
                if not text.strip():
                    continue
                lines.append(f"\n{'=' * 60}")
                lines.append(f"USER [{msg_num}] {ts}")
                lines.append(f"{'=' * 60}")
                if len(text) > max_user_text:
                    lines.append(text[:max_user_text])
                    lines.append(f"... [truncated from {len(text)} chars]")
                else:
                    lines.append(text)

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
                                tool_summary = tool_name
                                for key in ["matter_code", "file_path", "msg_path", "pattern",
                                             "command", "query", "username", "prompt"]:
                                    if key in inp:
                                        val = str(inp[key])[:80]
                                        tool_summary += f" ({key}={val})"
                                        break
                                tools.append(tool_summary)
                elif isinstance(content, str) and content.strip():
                    texts.append(content)

                if texts or tools:
                    lines.append(f"\n--- Assistant ---")
                    if tools:
                        lines.append(f"  Tools: {'; '.join(tools)}")
                    for t in texts:
                        if len(t) > max_assistant_text:
                            lines.append(t[:max_assistant_text])
                            lines.append(f"  ... [truncated from {len(t)} chars]")
                        else:
                            lines.append(t)

    if after_dt and skipped:
        header = f"[Showing records after {after}; skipped {skipped} earlier records]\n"
        lines.insert(0, header)

    return "\n".join(lines)


@mcp.tool()
def session_user_messages(session_id: str) -> str:
    """Extract just the user messages from a session (what was asked).
    Useful for quick triage of session content."""
    if not SESSION_DIR:
        return "ERROR: No session log directory found."

    path = SESSION_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return f"Session not found: {session_id}"

    lines = []
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

            lines.append(f"\n=== USER [{msg_num}] {ts} ===")
            if len(text) > 2000:
                lines.append(text[:2000])
                lines.append(f"... [truncated, {len(text)} chars total]")
            else:
                lines.append(text)

    return "\n".join(lines) if lines else "No user messages found."


# Tool registry for CLI testing
_tools = {
    "session_list": session_list,
    "session_summary": session_summary,
    "session_outline": session_outline,
    "session_user_messages": session_user_messages,
}
