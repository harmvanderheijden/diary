"""Diary management tools for the MCP server."""

import json
import re
from datetime import datetime, timedelta
from diary_mcp_shared import (
    mcp, DIARY_PATH, DIARY_TMP_DIR, SESSION_DIR, DIARY_PROMPT_PATH,
    read_entries, write_diary, parse_entry_date, extract_session_id,
    extract_entry_written_ts, extract_last_updated_ts,
    list_all_sessions, load_entry_prompt, load_supplemental_prompt,
    MIN_SUBSTANTIVE_SIZE, STALE_THRESHOLD_HOURS,
    read_suppressed, write_suppressed, suppressed_set, auto_unsuppress,
)
from pathlib import Path


def _no_diary():
    return "No diary exists yet. Create diary/diary.md with a preamble to get started."


@mcp.tool()
def diary_list() -> str:
    """List all diary entries with date, session ID, and title. Returns a compact overview."""
    preamble, entries = read_entries()
    if not entries:
        return _no_diary() if preamble is None else "Diary exists but has no entries."

    lines = [f"Diary has {len(entries)} entries:\n"]
    for header, text, dt in entries:
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "????"
        sid = extract_session_id(text)
        sid_str = f"  [{sid[:8]}]" if sid else ""
        lines.append(f"  {date_str}{sid_str}  {header[3:]}")
    return "\n".join(lines)


@mcp.tool()
def diary_sessions() -> str:
    """List session IDs already in the diary. Use this to check which sessions have been processed."""
    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    sids = []
    for _, text, _ in entries:
        sid = extract_session_id(text)
        if sid:
            sids.append(sid)

    if not sids:
        return "No session IDs found in diary entries."
    return f"{len(sids)} sessions in diary:\n" + "\n".join(sids)


@mcp.tool()
def diary_page(page: int = 1, size: int = 5) -> str:
    """Read a page of full diary entries. Page is 1-based. Default 5 entries per page.
    Returns full entry text for each entry on the page, plus navigation hints."""
    preamble, entries = read_entries()
    if not entries:
        return _no_diary() if preamble is None else "Diary exists but has no entries."

    total = len(entries)
    total_pages = (total + size - 1) // size
    page = max(1, min(page, total_pages))

    start = (page - 1) * size
    end = min(start + size, total)

    parts = [f"=== Page {page}/{total_pages} (entries {start+1}–{end} of {total}) ===\n"]
    for i in range(start, end):
        _, text, _ = entries[i]
        parts.append(text)
        parts.append("\n" + "─" * 70 + "\n")

    nav = []
    if page > 1:
        nav.append(f"prev: page {page - 1}")
    if page < total_pages:
        nav.append(f"next: page {page + 1}")
    if nav:
        parts.append(f"  [{' | '.join(nav)}]")

    return "\n".join(parts)


@mcp.tool()
def diary_search(keywords: str, page: int = 1, size: int = 3) -> str:
    """Search diary entries by keyword(s). Space-separated, all must match (AND logic).
    Results are paginated: default 3 per page. Returns full text of matching entries."""
    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    kws = [k.lower() for k in keywords.split()]
    matches = [(h, t, d) for h, t, d in entries if all(k in t.lower() for k in kws)]

    if not matches:
        return f"No entries matching: {keywords}"

    total = len(matches)
    total_pages = (total + size - 1) // size
    page = max(1, min(page, total_pages))
    start = (page - 1) * size
    end = min(start + size, total)

    parts = [f"Found {total} entries matching: {keywords} "
             f"(showing {start+1}–{end}, page {page}/{total_pages})\n"]
    for _, text, _ in matches[start:end]:
        parts.append("=" * 70)
        parts.append(text)
        parts.append("")

    nav = []
    if page > 1:
        nav.append(f"prev: page {page - 1}")
    if page < total_pages:
        nav.append(f"next: page {page + 1}")
    if nav:
        parts.append(f"  [{' | '.join(nav)}]  (use diary_search with keywords=\"{keywords}\" page=N)")
    return "\n".join(parts)


@mcp.tool()
def diary_get(date_prefix: str) -> str:
    """Get diary entries by date prefix (e.g. '25 February' or '2026-02-25').
    Returns full text of matching entries."""
    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    prefix_lower = date_prefix.lower()
    matches = []
    for header, text, dt in entries:
        header_lower = header.lower()
        date_formatted = dt.strftime("%Y-%m-%d") if dt else ""
        if prefix_lower in header_lower or prefix_lower in date_formatted:
            matches.append(text)

    if not matches:
        return f"No entries matching date: {date_prefix}"
    return "\n\n".join(matches)


@mcp.tool()
def diary_insert_from_file(file_path: str) -> str:
    """Insert a diary entry from a file at the correct chronological position.
    The file must start with '## DD Month YYYY, HH:MM'. Replaces existing entries
    with the same header prefix. Returns confirmation message."""
    p = Path(file_path)
    if not p.exists():
        return f"ERROR: File not found: {file_path}"
    entry_text = p.read_text(encoding="utf-8").strip()
    return _do_insert(entry_text)


@mcp.tool()
def diary_insert_text(entry_text: str) -> str:
    """Insert a diary entry from raw text at the correct chronological position.
    The text must start with '## DD Month YYYY, HH:MM'. Returns confirmation."""
    return _do_insert(entry_text.strip())


def _do_insert(entry_text):
    """Insert entry text into the diary at the correct chronological position.
    Auto-adds **Entry written** timestamp if not already present."""
    first_line = entry_text.split("\n", 1)[0]
    if not first_line.startswith("## "):
        return f"ERROR: Entry must start with '## <date>'. Got: {first_line[:80]}"

    new_date = parse_entry_date(first_line)
    if not new_date:
        return f"ERROR: Could not parse date from: {first_line[:80]}"

    # Auto-add **Entry written** if not present
    if "**Entry written**" not in entry_text:
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
        # Insert after the **Session** line
        session_match = re.search(r"(\*\*Session\*\*:\s*`[^`]+`)", entry_text)
        if session_match:
            insert_pos = session_match.end()
            entry_text = (
                entry_text[:insert_pos]
                + f"\n**Entry written**: {now_str}"
                + entry_text[insert_pos:]
            )

    preamble, entries = read_entries()
    if preamble is None:
        preamble = "# Session Diary\n"

    # Check for duplicate
    new_header_prefix = first_line[:60].lower()
    for i, (header, text, dt) in enumerate(entries):
        if header[:60].lower() == new_header_prefix:
            entries[i] = (first_line, entry_text, new_date)
            write_diary(preamble, entries)
            return f"REPLACED existing entry: {first_line[:80]}"

    # Find insertion point
    insert_idx = len(entries)
    for i, (_, _, dt) in enumerate(entries):
        if dt and new_date < dt:
            insert_idx = i
            break

    entries.insert(insert_idx, (first_line, entry_text, new_date))
    write_diary(preamble, entries)
    return f"INSERTED at position {insert_idx + 1}/{len(entries)}: {first_line[:80]}"


@mcp.tool()
def diary_cases() -> str:
    """List all case codes mentioned in the diary with entry counts and dates."""
    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    case_pattern = re.compile(r"\b([PQA]\d{5,}[A-Z0-9-]*)\b")
    case_entries = {}

    for header, text, dt in entries:
        cases_found = set(case_pattern.findall(text))
        for case in cases_found:
            if case not in case_entries:
                case_entries[case] = []
            date_str = dt.strftime("%Y-%m-%d") if dt else "????"
            title = header[3:].split("—")[-1].strip() if "—" in header else header[3:]
            case_entries[case].append(f"{date_str}: {title[:60]}")

    if not case_entries:
        return "No case codes found in diary."

    lines = [f"Cases mentioned in diary ({len(case_entries)} cases):\n"]
    for case in sorted(case_entries.keys()):
        lines.append(f"  {case} ({len(case_entries[case])} entries)")
        for ref in case_entries[case]:
            lines.append(f"    - {ref}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def diary_case(case_code: str, page: int = 1, size: int = 3) -> str:
    """Find all diary entries mentioning a specific case code. Returns full entry text.
    Results are paginated: default 3 per page."""
    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    case_lower = case_code.lower()
    matches = [(h, t, d) for h, t, d in entries if case_lower in t.lower()]

    if not matches:
        return f"No entries mentioning case: {case_code}"

    total = len(matches)
    total_pages = (total + size - 1) // size
    page = max(1, min(page, total_pages))
    start = (page - 1) * size
    end = min(start + size, total)

    parts = [f"Found {total} entries for case {case_code} "
             f"(showing {start+1}–{end}, page {page}/{total_pages})\n"]
    for _, text, _ in matches[start:end]:
        parts.append("=" * 70)
        parts.append(text)
        parts.append("")

    nav = []
    if page > 1:
        nav.append(f"prev: page {page - 1}")
    if page < total_pages:
        nav.append(f"next: page {page + 1}")
    if nav:
        parts.append(f"  [{' | '.join(nav)}]  (use diary_case with case_code=\"{case_code}\" page=N)")
    return "\n".join(parts)


@mcp.tool()
def diary_append_supplemental(session_id: str, file_path: str = "", text: str = "") -> str:
    """Append a supplemental section to an existing diary entry identified by session ID.
    Provide either file_path (path to a .md file with the supplemental content) or text
    (raw supplemental content). The ## header and **Session** line are NOT expected —
    only the narrative body. Adds a ### Supplemental header and updates **Last updated**."""
    if not file_path and not text:
        return "ERROR: Provide either file_path or text."

    if file_path:
        p = Path(file_path)
        if not p.exists():
            return f"ERROR: File not found: {file_path}"
        suppl_text = p.read_text(encoding="utf-8").strip()
    else:
        suppl_text = text.strip()

    if not suppl_text:
        return "ERROR: Supplemental content is empty."

    preamble, entries = read_entries()
    if preamble is None:
        return _no_diary()

    # Find the entry with this session ID
    target_idx = None
    for i, (header, entry_text, dt) in enumerate(entries):
        sid = extract_session_id(entry_text)
        if sid == session_id:
            target_idx = i
            break

    if target_idx is None:
        return f"ERROR: No diary entry found for session {session_id}"

    header, entry_text, dt = entries[target_idx]
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
    now_display = datetime.now().strftime("%d %B %Y, %H:%M")

    # Build supplemental section
    supplemental = f"\n\n### Supplemental — {now_display}\n\n{suppl_text}"

    # Append to entry
    entry_text = entry_text.rstrip() + supplemental

    # Update or add **Last updated** line
    if "**Last updated**:" in entry_text:
        entry_text = re.sub(
            r"\*\*Last updated\*\*:\s*\S+",
            f"**Last updated**: {now_str}",
            entry_text
        )
    else:
        # Add after **Entry written** line
        ew_match = re.search(r"(\*\*Entry written\*\*:\s*\S+)", entry_text)
        if ew_match:
            insert_pos = ew_match.end()
            entry_text = (
                entry_text[:insert_pos]
                + f"\n**Last updated**: {now_str}"
                + entry_text[insert_pos:]
            )

    entries[target_idx] = (header, entry_text, dt)
    write_diary(preamble, entries)
    return f"SUPPLEMENTAL appended to entry for session {session_id[:8]}... ({now_display})"


@mcp.tool()
def diary_prompt() -> str:
    """Return the prompt template for generating new diary entries.
    Uses project-specific diary_prompt.md if it exists alongside diary.md,
    otherwise returns the generic default.
    Replace {SESSION_ID} with the full UUID and {SESSION_SHORT} with its first 8 chars."""
    prompt, is_custom = load_entry_prompt()
    prefix = ""
    if not is_custom:
        prefix = (
            "[Using generic default prompt. No project-specific diary_prompt.md found at "
            f"{str(DIARY_PROMPT_PATH).replace(chr(92), '/')}. "
            "Consider asking the user whether a custom prompt should be created for this project.]\n\n"
        )
    return prefix + prompt


@mcp.tool()
def diary_supplemental_prompt() -> str:
    """Return the prompt template for generating supplemental diary entries.
    Uses project-specific diary_supplemental_prompt.md if it exists, otherwise generic default.
    Replace {SESSION_ID}, {SESSION_SHORT}, and {AFTER_TIMESTAMP}."""
    from diary_mcp_shared import DIARY_SUPPLEMENTAL_PROMPT_PATH
    prompt, is_custom = load_supplemental_prompt()
    prefix = ""
    if not is_custom:
        prefix = (
            "[Using generic default supplemental prompt. No project-specific diary_supplemental_prompt.md found at "
            f"{str(DIARY_SUPPLEMENTAL_PROMPT_PATH).replace(chr(92), '/')}. "
            "Consider asking the user whether a custom prompt should be created for this project.]\n\n"
        )
    return prefix + prompt


@mcp.tool()
def diary_check_new(max_stale_days: int = 0) -> str:
    """Check whether any sessions need new diary entries or supplementals.
    Compares session logs against existing diary entries.
    Returns categories: NEW (need full entry), STALE (need supplemental),
    ONGOING (recently active, skip for now), SUPPRESSED (count), CAUGHT UP.

    max_stale_days: if > 0, sessions whose diary entry is older than this many days
    and that have no new user messages since the entry are auto-suppressed."""
    preamble, entries = read_entries()

    # Build index of existing diary entries by session ID
    entry_index = {}  # sid -> (entry_written_ts, last_updated_ts)
    existing_sids = set()
    for _, text, _ in entries:
        sid = extract_session_id(text)
        if sid:
            existing_sids.add(sid)
            ew = extract_entry_written_ts(text)
            lu = extract_last_updated_ts(text)
            entry_index[sid] = (ew, lu)

    # Get all sessions
    all_sessions = list_all_sessions()
    if not all_sessions:
        return "No session logs found. Check that the session directory exists."

    # Auto-unsuppress sessions that have received new activity
    sessions_by_id = {s["id"]: s for s in all_sessions}
    _, unsuppressed_ids = auto_unsuppress(sessions_by_id)

    # Load suppression list (after auto-unsuppress)
    sup = suppressed_set()

    threshold = timedelta(hours=STALE_THRESHOLD_HOURS)
    now = datetime.now()

    new_sessions = []
    stale_sessions = []
    ongoing_sessions = []
    suppressed_count = 0
    auto_suppressed = []
    trivial_count = 0

    for s in all_sessions:
        sid = s["id"]
        # Skip agent warmup sessions
        if sid.startswith("agent-"):
            trivial_count += 1
            continue
        # Skip tiny sessions (< MIN_SUBSTANTIVE_SIZE)
        if s["size"] < MIN_SUBSTANTIVE_SIZE:
            trivial_count += 1
            continue
        # Skip sessions with very few user messages
        if s["user_msgs"] < 3:
            trivial_count += 1
            continue

        # Skip suppressed sessions
        if sid in sup:
            suppressed_count += 1
            continue

        if sid not in existing_sids:
            new_sessions.append(s)
        else:
            # Check if session log has been modified after the entry was written
            ew_ts, lu_ts = entry_index.get(sid, (None, None))
            reference_ts = lu_ts or ew_ts  # use last_updated if available
            if reference_ts and SESSION_DIR:
                jsonl_path = SESSION_DIR / f"{sid}.jsonl"
                if jsonl_path.exists():
                    jsonl_mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)
                    if jsonl_mtime > reference_ts + timedelta(minutes=5):
                        # Session has new activity after the entry
                        age = now - jsonl_mtime
                        if age < threshold:
                            ongoing_sessions.append((s, reference_ts))
                        else:
                            # Auto-suppress if max_stale_days is set and entry is old enough
                            if max_stale_days > 0:
                                entry_age = now - reference_ts
                                if entry_age.days >= max_stale_days:
                                    auto_suppressed.append((s, reference_ts))
                                    continue
                            stale_sessions.append((s, reference_ts))

    # Persist any auto-suppressed sessions
    if auto_suppressed:
        sup_entries = read_suppressed()
        now_str = datetime.now().isoformat(timespec="seconds")
        for s, _ in auto_suppressed:
            sup_entries.append({
                "session_id": s["id"],
                "suppressed_at": now_str,
                "reason": f"auto-expired (>{max_stale_days}d)",
            })
        write_suppressed(sup_entries)
        suppressed_count += len(auto_suppressed)

    # Build output
    lines = []

    if unsuppressed_ids:
        lines.append(f"(Auto-unsuppressed {len(unsuppressed_ids)} session(s) with new activity: "
                      + ", ".join(sid[:8] + "…" for sid in unsuppressed_ids) + ")\n")

    if new_sessions:
        lines.append(f"=== NEW ({len(new_sessions)} sessions need full diary entries) ===\n")
        lines.append("RECIPE: For each session, spawn a subagent with the prompt from `diary_prompt`.\n")
        for s in new_sessions:
            size_str = f"{s['size'] // 1024}K"
            date = s['date'][:10]
            lines.append(
                f"  - {s['id']}  ({date}, {size_str}, {s['user_msgs']}u/{s['asst_msgs']}a)  {s['preview'][:70]}"
            )
        lines.append("")

    if stale_sessions:
        lines.append(f"=== STALE ({len(stale_sessions)} sessions need supplemental entries) ===\n")
        lines.append("RECIPE: For each session, spawn a subagent with the prompt from `diary_supplemental_prompt`.")
        lines.append("Use `session_outline` with `after=<entry_written_ts>` to see only new activity.\n")
        for s, ref_ts in stale_sessions:
            size_str = f"{s['size'] // 1024}K"
            ref_str = ref_ts.strftime("%Y-%m-%dT%H:%M") if ref_ts else "?"
            lines.append(
                f"  - {s['id']}  (entry: {ref_str}, now {size_str})  {s['preview'][:70]}"
            )
        lines.append("")

    if ongoing_sessions:
        lines.append(f"=== ONGOING ({len(ongoing_sessions)} sessions still active, skip for now) ===\n")
        for s, ref_ts in ongoing_sessions:
            lines.append(f"  - {s['id']}  (active within last {STALE_THRESHOLD_HOURS}h)")
        lines.append("")

    if suppressed_count:
        lines.append(f"=== SUPPRESSED ({suppressed_count} sessions hidden) ===\n")
        if auto_suppressed:
            lines.append(f"  ({len(auto_suppressed)} auto-suppressed this run, entry older than {max_stale_days}d)")
        lines.append("  Use `diary_unsuppress` to restore specific sessions.\n")

    if not new_sessions and not stale_sessions:
        lines.append(
            f"All caught up. {len(existing_sids)} sessions in diary, "
            f"{len(all_sessions)} total session logs "
            f"({trivial_count} skipped as trivial"
            + (f", {suppressed_count} suppressed" if suppressed_count else "")
            + ")."
        )
        if ongoing_sessions:
            lines.append(f"({len(ongoing_sessions)} sessions still active — check again later.)")
    else:
        lines.append(f"Summary: {len(existing_sids)} in diary, {len(new_sessions)} new, "
                      f"{len(stale_sessions)} stale, {len(ongoing_sessions)} ongoing, "
                      f"{trivial_count} trivial"
                      + (f", {suppressed_count} suppressed" if suppressed_count else "")
                      + ".")

    return "\n".join(lines)


@mcp.tool()
def diary_suppress(session_ids: str, reason: str = "user-dismissed") -> str:
    """Suppress one or more sessions so they no longer appear in diary_check_new.
    session_ids: comma-separated session IDs (full UUIDs or 8-char prefixes).
    reason: optional reason string (default: 'user-dismissed').
    Suppressed sessions auto-unsuppress if they receive new activity."""
    raw_ids = [s.strip() for s in session_ids.split(",") if s.strip()]
    if not raw_ids:
        return "ERROR: No session IDs provided."

    # Resolve prefixes to full IDs
    all_sessions = list_all_sessions()
    session_map = {s["id"]: s for s in all_sessions}

    resolved = []
    errors = []
    for raw in raw_ids:
        if raw in session_map:
            resolved.append(raw)
        else:
            # Try prefix match
            matches = [sid for sid in session_map if sid.startswith(raw)]
            if len(matches) == 1:
                resolved.append(matches[0])
            elif len(matches) > 1:
                errors.append(f"  {raw}: ambiguous, matches {len(matches)} sessions")
            else:
                errors.append(f"  {raw}: no matching session found")

    if not resolved and errors:
        return "ERROR: Could not resolve any session IDs:\n" + "\n".join(errors)

    # Read existing suppression list and add new entries
    existing = read_suppressed()
    existing_sids = {e["session_id"] for e in existing}
    now_str = datetime.now().isoformat(timespec="seconds")

    added = []
    skipped = []
    for sid in resolved:
        if sid in existing_sids:
            skipped.append(sid)
        else:
            existing.append({
                "session_id": sid,
                "suppressed_at": now_str,
                "reason": reason,
            })
            added.append(sid)

    write_suppressed(existing)

    parts = []
    if added:
        parts.append(f"Suppressed {len(added)} session(s):")
        for sid in added:
            parts.append(f"  + {sid[:8]}…")
    if skipped:
        parts.append(f"Already suppressed: {len(skipped)}")
    if errors:
        parts.append("Errors:")
        parts.extend(errors)
    return "\n".join(parts)


@mcp.tool()
def diary_unsuppress(session_ids: str) -> str:
    """Remove one or more sessions from the suppression list so they reappear in diary_check_new.
    session_ids: comma-separated session IDs (full UUIDs or 8-char prefixes)."""
    raw_ids = [s.strip() for s in session_ids.split(",") if s.strip()]
    if not raw_ids:
        return "ERROR: No session IDs provided."

    existing = read_suppressed()
    if not existing:
        return "Suppression list is empty — nothing to unsuppress."

    # Build lookup of suppressed IDs
    sup_sids = {e["session_id"] for e in existing}

    to_remove = set()
    errors = []
    for raw in raw_ids:
        if raw in sup_sids:
            to_remove.add(raw)
        else:
            matches = [sid for sid in sup_sids if sid.startswith(raw)]
            if len(matches) == 1:
                to_remove.add(matches[0])
            elif len(matches) > 1:
                errors.append(f"  {raw}: ambiguous, matches {len(matches)} suppressed sessions")
            else:
                errors.append(f"  {raw}: not found in suppression list")

    if not to_remove and errors:
        return "ERROR: Could not resolve any session IDs:\n" + "\n".join(errors)

    remaining = [e for e in existing if e["session_id"] not in to_remove]
    write_suppressed(remaining)

    parts = []
    if to_remove:
        parts.append(f"Unsuppressed {len(to_remove)} session(s):")
        for sid in sorted(to_remove):
            parts.append(f"  - {sid[:8]}…")
    if errors:
        parts.append("Errors:")
        parts.extend(errors)
    return "\n".join(parts)


# Tool registry for CLI testing
_tools = {
    "diary_list": diary_list,
    "diary_sessions": diary_sessions,
    "diary_page": diary_page,
    "diary_search": diary_search,
    "diary_get": diary_get,
    "diary_insert_from_file": diary_insert_from_file,
    "diary_insert_text": diary_insert_text,
    "diary_append_supplemental": diary_append_supplemental,
    "diary_cases": diary_cases,
    "diary_case": diary_case,
    "diary_prompt": diary_prompt,
    "diary_supplemental_prompt": diary_supplemental_prompt,
    "diary_check_new": diary_check_new,
    "diary_suppress": diary_suppress,
    "diary_unsuppress": diary_unsuppress,
}
