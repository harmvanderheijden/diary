"""Practice knowledge base tools for the MCP server.

Provides tools for:
  - Logging structured work activity (work_log)
  - Managing accumulated practice rules with context-based lookup
"""

from diary_mcp_shared import mcp
import practice_db


# ---------------------------------------------------------------------------
# Work log tools
# ---------------------------------------------------------------------------

@mcp.tool()
def work_log_insert(date: str, action_type: str, matter_code: str = "",
                    client: str = "", outcome: str = "", summary: str = "",
                    session_id: str = "") -> str:
    """Record a work activity. date is ISO format (YYYY-MM-DD).
    action_type examples: oa_response, translation_check, claim_draft,
    client_letter, idf_drafting, trainee_review, call_prep, filing_prep."""
    row_id = practice_db.insert_work_log(
        session_id=session_id, date=date, matter_code=matter_code,
        client=client, action_type=action_type, outcome=outcome,
        summary=summary,
    )
    return f"Logged: #{row_id} {date} {matter_code or '(no case)'} [{action_type}] {summary[:60]}"


@mcp.tool()
def work_log_query(client: str = "", matter_code: str = "",
                   action_type: str = "", since: str = "", until: str = "",
                   limit: int = 50) -> str:
    """Query work log with optional filters. All filters are optional.
    since/until are ISO dates (YYYY-MM-DD). Returns matching entries."""
    rows = practice_db.query_work_log(
        client=client, matter_code=matter_code, action_type=action_type,
        since=since, until=until, limit=limit,
    )
    if not rows:
        return "No matching work log entries."

    lines = [f"Found {len(rows)} entries:\n"]
    for r in rows:
        mc = r["matter_code"] or "(no case)"
        lines.append(
            f"  #{r['id']}  {r['date']}  {mc:<25s} [{r['action_type']}] "
            f"{r['outcome'] or ''}"
        )
        if r["summary"]:
            lines.append(f"         {r['summary'][:80]}")
    return "\n".join(lines)


@mcp.tool()
def work_log_stats(since: str = "", group_by: str = "client") -> str:
    """Aggregate work log statistics. group_by can be 'client', 'action_type',
    'matter_code', or comma-separated combinations like 'client,action_type'.
    since is optional ISO date (YYYY-MM-DD)."""
    rows = practice_db.stats_work_log(since=since, group_by=group_by)
    if not rows:
        return "No work log data" + (f" since {since}" if since else "") + "."

    cols = [c.strip() for c in group_by.split(",") if c.strip()]
    lines = [f"Work log stats" + (f" since {since}" if since else "") + ":\n"]
    for r in rows:
        label = " / ".join(str(r.get(c, "?")) for c in cols)
        lines.append(f"  {label:<40s} {r['count']:>4d}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Practice rules tools
# ---------------------------------------------------------------------------

@mcp.tool()
def practice_rules_contexts() -> str:
    """List all context tags in use with their rule counts.
    Call this before practice_rules_lookup to see what tags are available."""
    items = practice_db.list_contexts()
    if not items:
        return "No practice rules exist yet."

    lines = [f"Available context tags ({len(items)} tags, from {sum(c for _, c in items)} active rules):\n"]
    for tag, count in items:
        lines.append(f"  {tag:<35s} ({count} rule{'s' if count != 1 else ''})")
    return "\n".join(lines)


@mcp.tool()
def practice_rules_lookup(contexts: str) -> str:
    """Find active practice rules matching any of the given context tags.
    contexts: comma-separated tags, e.g. 'inventive_step,oa_response'.
    If no results, call practice_rules_contexts() to see available tags."""
    rules = practice_db.lookup_rules(contexts)
    if not rules:
        # Helpful fallback: show available contexts
        available = practice_db.list_contexts()
        if available:
            tag_list = ", ".join(t for t, _ in available[:15])
            return (f"No rules matching: {contexts}\n"
                    f"Available tags: {tag_list}\n"
                    f"Use practice_rules_contexts() for the full list.")
        return f"No rules matching: {contexts} (no rules exist yet)."

    lines = [f"Found {len(rules)} rule(s) for: {contexts}\n"]
    for r in rules:
        lines.append(f"--- Rule #{r['id']} [{r['contexts']}] ---")
        lines.append(r["rule"])
        if r["rationale"]:
            lines.append(f"  Why: {r['rationale']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def practice_rules_add(rule: str, contexts: str, rationale: str = "",
                       source_session: str = "") -> str:
    """Add a new practice rule. Automatically checks for near-duplicates first.
    rule: the instruction itself.
    contexts: comma-separated tags (e.g. 'inventive_step,problem_solution_approach').
    rationale: why this rule exists. source_session: session UUID where learned.
    If a similar rule exists, returns it instead of inserting — use
    practice_rules_update to refine the existing rule if needed."""
    # Extract distinctive keywords for duplicate check
    stop = {"the", "and", "for", "that", "this", "with", "from", "when", "not",
            "are", "was", "were", "been", "have", "has", "had", "will", "can",
            "should", "must", "use", "using", "also", "does", "don", "into"}
    keywords = [w.strip(".,;:!?'\"()") for w in rule.split()
                if w.strip(".,;:!?'\"()").lower() not in stop and len(w) >= 4]

    similar = practice_db.find_similar_rules(contexts, keywords)
    if similar:
        # Check if any candidate is a strong match (>40% keyword overlap)
        best = similar[0]
        best_lower = best["rule"].lower()
        kw_lower = [k.lower() for k in keywords if len(k) >= 4]
        hits = sum(1 for kw in kw_lower if kw in best_lower) if kw_lower else 0
        overlap = hits / len(kw_lower) if kw_lower else 0

        if overlap >= 0.4:
            return (
                f"DUPLICATE detected — existing rule #{best['id']} [{best['contexts']}] "
                f"has {hits}/{len(kw_lower)} keyword overlap ({overlap:.0%}):\n\n"
                f"EXISTING: {best['rule'][:200]}\n\n"
                f"PROPOSED: {rule[:200]}\n\n"
                f"Use practice_rules_update(rule_id={best['id']}, ...) to refine the "
                f"existing rule, or call practice_rules_add_force to insert anyway."
            )

    row_id = practice_db.insert_rule(
        rule=rule, rationale=rationale, contexts=contexts,
        source_session=source_session,
    )
    normalised = practice_db._normalise_contexts(contexts)
    return f"Added rule #{row_id} [{normalised}]: {rule[:80]}..."


@mcp.tool()
def practice_rules_add_force(rule: str, contexts: str, rationale: str = "",
                             source_session: str = "") -> str:
    """Force-add a practice rule, bypassing duplicate detection.
    Use only after practice_rules_add flagged a duplicate that you've confirmed is distinct."""
    row_id = practice_db.insert_rule(
        rule=rule, rationale=rationale, contexts=contexts,
        source_session=source_session,
    )
    normalised = practice_db._normalise_contexts(contexts)
    return f"Force-added rule #{row_id} [{normalised}]: {rule[:80]}..."


@mcp.tool()
def practice_rules_update(rule_id: int, rule: str = "", rationale: str = "",
                          contexts: str = "", active: int = -1) -> str:
    """Update an existing practice rule. Only provide fields you want to change.
    Set active=0 to deactivate a rule, active=1 to reactivate."""
    ok = practice_db.update_rule(
        rule_id, rule=rule, rationale=rationale, contexts=contexts, active=active,
    )
    if not ok:
        return f"ERROR: Rule #{rule_id} not found or no changes provided."
    parts = [f"Updated rule #{rule_id}:"]
    if rule:
        parts.append(f"  rule: {rule[:80]}...")
    if rationale:
        parts.append(f"  rationale: {rationale[:80]}...")
    if contexts:
        parts.append(f"  contexts: {practice_db._normalise_contexts(contexts)}")
    if active >= 0:
        parts.append(f"  active: {bool(active)}")
    return "\n".join(parts)


@mcp.tool()
def practice_rules_list(active_only: int = 1) -> str:
    """List all practice rules. Set active_only=0 to include deactivated rules."""
    rules = practice_db.list_rules(active_only=bool(active_only))
    if not rules:
        return "No practice rules" + (" (active)" if active_only else "") + "."

    status = "active " if active_only else ""
    lines = [f"{len(rules)} {status}practice rules:\n"]
    for r in rules:
        state = "" if r["active"] else " [INACTIVE]"
        lines.append(f"--- #{r['id']} [{r['contexts']}]{state} ---")
        lines.append(r["rule"][:200])
        if r["rationale"]:
            lines.append(f"  Why: {r['rationale'][:120]}")
        updated = r["updated_at"] or r["created_at"]
        lines.append(f"  ({updated})")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Setup check
# ---------------------------------------------------------------------------

@mcp.tool()
def practice_check_setup() -> str:
    """Check the diary + practice knowledge base setup for this project.
    Reports status of all components and flags anything missing or misconfigured."""
    info = practice_db.check_setup()
    lines = ["Diary & Practice System Status\n"]

    # Diary
    d = info["diary_md"]
    if d["status"] == "ok":
        lines.append(f"  diary/diary.md              OK ({d['entries']} entries)")
    else:
        lines.append(f"  diary/diary.md              MISSING -- will be created on first diary entry")

    # Practice DB
    p = info["practice_db"]
    if p["status"] == "ok":
        lines.append(
            f"  diary/practice.db           OK ({p['rules_active']} active rules, "
            f"{p['rules_inactive']} inactive, {p['work_log_count']} work_log entries)"
        )
        if p["work_log_count"]:
            lines.append(
                f"    work_log range:           {p['work_log_range'][0]} to {p['work_log_range'][1]}"
            )
        lines.append(f"    context tags:             {p['context_tags']} tags")
    else:
        lines.append(f"  diary/practice.db           MISSING -- will be created on first tool call")
        lines.append(f"    Run seed_practice_db.py to populate initial rules")

    # Session dir
    s = info["session_dir"]
    if s["status"] == "ok":
        lines.append(f"  session logs                OK ({s['sessions']} files)")
    else:
        lines.append(f"  session logs                MISSING -- no session directory found")

    # Optional files
    lines.append(f"  diary_prompt.md             {info['diary_prompt']}")
    lines.append(
        f"  diary_supplemental_prompt   {info['diary_supplemental_prompt']}"
    )
    lines.append(f"  suppressed.json             {info['suppressed_json']}")

    # MEMORY.md integration
    lines.append("")
    m = info["memory_md"]
    if m["status"] == "ok":
        lines.append(f"  MEMORY.md                   OK")
        checks = [
            ("practice DB referenced", m["has_practice_db_ref"]),
            ("lookup key rule", m["has_lookup_rule"]),
            ("correction key rule", m["has_correction_rule"]),
        ]
        for label, ok in checks:
            status = "OK" if ok else "MISSING -- add to Key Rules section"
            lines.append(f"    {label:<28s} {status}")
    else:
        lines.append(f"  MEMORY.md                   MISSING at {m['path']}")
        lines.append(f"    Create it and add practice DB references + key rules")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registry for CLI testing
# ---------------------------------------------------------------------------

_tools = {
    "work_log_insert": work_log_insert,
    "work_log_query": work_log_query,
    "work_log_stats": work_log_stats,
    "practice_rules_contexts": practice_rules_contexts,
    "practice_rules_lookup": practice_rules_lookup,
    "practice_rules_add": practice_rules_add,
    "practice_rules_add_force": practice_rules_add_force,
    "practice_rules_update": practice_rules_update,
    "practice_rules_list": practice_rules_list,
    "practice_check_setup": practice_check_setup,
}
