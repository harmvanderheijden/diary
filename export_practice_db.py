"""Export the practice knowledge base (practice.db) to human-readable form.

Usage:
    python export_practice_db.py                  # markdown to stdout, active rules only
    python export_practice_db.py -o rules.md      # write to file
    python export_practice_db.py --include-inactive
    python export_practice_db.py --by id          # group by id order instead of context
    python export_practice_db.py --work-log       # also emit the work_log table
    python export_practice_db.py --format text    # plain text instead of markdown

The default layout groups rules by context tag so related rules are read together.
Every rule appears under each of its tags (so a rule tagged `a,b` shows twice), with
a cross-reference list at the end identifying the canonical #id for deduplication.
"""

import argparse
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import practice_db


def _fmt_rule_md(r: dict, show_id: bool = True) -> list[str]:
    """Format a single rule as markdown lines."""
    lines = []
    header = f"### Rule #{r['id']}" if show_id else "###"
    if not r["active"]:
        header += " _(inactive)_"
    lines.append(header)
    lines.append("")
    lines.append(r["rule"].strip())
    if r["rationale"]:
        lines.append("")
        lines.append(f"**Why:** {r['rationale'].strip()}")
    meta = []
    if r["contexts"]:
        meta.append(f"tags: `{r['contexts']}`")
    if r["source_session"]:
        meta.append(f"source: `{r['source_session']}`")
    ts = r["updated_at"] or r["created_at"]
    if ts:
        meta.append(f"updated: {ts}")
    if meta:
        lines.append("")
        lines.append("<sub>" + " · ".join(meta) + "</sub>")
    lines.append("")
    return lines


def _fmt_rule_text(r: dict) -> list[str]:
    """Format a single rule as plain text lines."""
    lines = []
    state = "" if r["active"] else " [INACTIVE]"
    lines.append(f"[#{r['id']}]{state} tags: {r['contexts']}")
    for rl in r["rule"].strip().splitlines():
        lines.append(f"    {rl}")
    if r["rationale"]:
        lines.append(f"    Why: {r['rationale'].strip()}")
    ts = r["updated_at"] or r["created_at"]
    if ts:
        lines.append(f"    ({ts})")
    lines.append("")
    return lines


def export_rules_by_context(include_inactive: bool, fmt: str) -> str:
    rules = practice_db.list_rules(active_only=not include_inactive)
    if not rules:
        return "No practice rules in database."

    # Group rules under each of their tags
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for r in rules:
        tags = [t.strip() for t in (r["contexts"] or "").split(",") if t.strip()]
        if not tags:
            by_tag["(untagged)"].append(r)
        else:
            for t in tags:
                by_tag[t].append(r)

    tag_order = sorted(by_tag.keys(), key=lambda t: (-len(by_tag[t]), t))

    out: list[str] = []
    if fmt == "markdown":
        out.append("# Practice Rules")
        out.append("")
        out.append(
            f"_{len(rules)} rules across {len(by_tag)} context tags "
            f"({'including inactive' if include_inactive else 'active only'})._"
        )
        out.append("")
        out.append("## Contents")
        out.append("")
        for t in tag_order:
            out.append(f"- [{t}](#{_anchor(t)}) ({len(by_tag[t])})")
        out.append("")
        for t in tag_order:
            out.append(f"## {t}")
            out.append("")
            for r in by_tag[t]:
                out.extend(_fmt_rule_md(r))
    else:  # text
        out.append(f"Practice Rules — {len(rules)} rules, {len(by_tag)} tags")
        out.append("=" * 72)
        for t in tag_order:
            out.append("")
            out.append(f"== {t} ({len(by_tag[t])}) ==")
            out.append("")
            for r in by_tag[t]:
                out.extend(_fmt_rule_text(r))

    return "\n".join(out).rstrip() + "\n"


def export_rules_by_id(include_inactive: bool, fmt: str) -> str:
    rules = practice_db.list_rules(active_only=not include_inactive)
    if not rules:
        return "No practice rules in database."
    out: list[str] = []
    if fmt == "markdown":
        out.append("# Practice Rules (by id)")
        out.append("")
        out.append(
            f"_{len(rules)} rules "
            f"({'including inactive' if include_inactive else 'active only'})._"
        )
        out.append("")
        for r in rules:
            out.extend(_fmt_rule_md(r))
    else:
        out.append(f"Practice Rules — {len(rules)} rules")
        out.append("=" * 72)
        out.append("")
        for r in rules:
            out.extend(_fmt_rule_text(r))
    return "\n".join(out).rstrip() + "\n"


def export_work_log(fmt: str) -> str:
    rows = practice_db.query_work_log(limit=10000)
    if not rows:
        return "No work_log entries." + ("\n" if fmt == "text" else "\n")

    out: list[str] = []
    if fmt == "markdown":
        out.append("# Work Log")
        out.append("")
        out.append(f"_{len(rows)} entries, newest first._")
        out.append("")
        out.append("| # | Date | Matter | Client | Action | Outcome | Summary |")
        out.append("|---|------|--------|--------|--------|---------|---------|")
        for r in rows:
            cells = [
                str(r["id"]),
                r["date"] or "",
                r["matter_code"] or "",
                r["client"] or "",
                r["action_type"] or "",
                (r["outcome"] or "").replace("|", "\\|"),
                (r["summary"] or "").replace("|", "\\|").replace("\n", " "),
            ]
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    else:
        out.append(f"Work Log — {len(rows)} entries")
        out.append("=" * 72)
        for r in rows:
            mc = r["matter_code"] or "(no case)"
            out.append(
                f"#{r['id']}  {r['date']}  {mc:<25s} [{r['action_type']}] "
                f"{r['outcome'] or ''}"
            )
            if r["summary"]:
                out.append(f"    {r['summary']}")
        out.append("")
    return "\n".join(out)


def _anchor(s: str) -> str:
    return "".join(c for c in s.lower().replace(" ", "-") if c.isalnum() or c == "-")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--output", help="Write to file instead of stdout")
    p.add_argument("--include-inactive", action="store_true",
                   help="Include deactivated rules (marked as such)")
    p.add_argument("--by", choices=["context", "id"], default="context",
                   help="Grouping: by context tag (default) or by id")
    p.add_argument("--work-log", action="store_true",
                   help="Append the work_log table to the export")
    p.add_argument("--rules-only", action="store_true",
                   help="Export rules only (default; kept for clarity)")
    p.add_argument("--work-log-only", action="store_true",
                   help="Export the work_log only, no rules")
    p.add_argument("--format", choices=["markdown", "text"], default="markdown",
                   help="Output format (default: markdown)")
    args = p.parse_args()

    parts: list[str] = []
    if not args.work_log_only:
        if args.by == "context":
            parts.append(export_rules_by_context(args.include_inactive, args.format))
        else:
            parts.append(export_rules_by_id(args.include_inactive, args.format))

    if args.work_log or args.work_log_only:
        parts.append(export_work_log(args.format))

    text = ("\n" if args.format == "markdown" else "\n").join(parts)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote {len(text)} chars to {args.output}")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
