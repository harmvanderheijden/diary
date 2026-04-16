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
    """Add a new practice rule. rule: the instruction itself.
    contexts: comma-separated tags (e.g. 'inventive_step,problem_solution_approach').
    rationale: why this rule exists. source_session: session UUID where learned."""
    row_id = practice_db.insert_rule(
        rule=rule, rationale=rationale, contexts=contexts,
        source_session=source_session,
    )
    normalised = practice_db._normalise_contexts(contexts)
    return f"Added rule #{row_id} [{normalised}]: {rule[:80]}..."


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
# Tool registry for CLI testing
# ---------------------------------------------------------------------------

_tools = {
    "work_log_insert": work_log_insert,
    "work_log_query": work_log_query,
    "work_log_stats": work_log_stats,
    "practice_rules_contexts": practice_rules_contexts,
    "practice_rules_lookup": practice_rules_lookup,
    "practice_rules_add": practice_rules_add,
    "practice_rules_update": practice_rules_update,
    "practice_rules_list": practice_rules_list,
}
