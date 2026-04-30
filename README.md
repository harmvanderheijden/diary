# Diary — MCP Server for AI Session Logs and Practice Knowledge Base

MCP server and CLI tools for maintaining a structured diary from Claude Code session logs, plus a practice knowledge base for operational rules and structured work history. Records what was done, on which cases, with what outcome — and makes it searchable across sessions.

## Features

- **Diary management**: chronologically ordered markdown entries with search, pagination, and case-based filtering
- **Session log parsing**: extract summaries, outlines, and user messages from Claude Code JSONL session logs
- **New entry detection**: automatically identifies sessions that need diary entries (NEW, STALE, ONGOING, CAUGHT UP)
- **Stale session suppression**: mark finished sessions as "done" to keep check output clean; auto-unsuppresses if a session is re-opened
- **Supplemental entries**: append follow-up notes to existing entries when a session continues
- **Custom prompts**: per-project prompt templates for controlling diary entry style
- **Practice rules database**: accumulate operational rules tagged by context, with duplicate detection and refinement
- **Work log**: structured record of activities (date, matter, client, action type, outcome) with filtering and aggregation
- **Setup check**: one-shot report on diary, practice DB, session dir, prompt files, and MEMORY.md wiring
- **Rules export**: dump the practice DB to human-readable markdown or plain text
- **Dual interface**: works as an MCP server or standalone CLI

A companion document, [HOW_THE_MEMORY_WORKS.md](HOW_THE_MEMORY_WORKS.md), explains how the diary, practice DB, auto-memory, CLAUDE.md, and raw session logs relate to one another.

## Requirements

- Python 3.10+
- `mcp` package (the FastMCP SDK)

```bash
pip install -r requirements.txt
```

## Quick start

### As MCP server

Add to your Claude Code MCP configuration (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "diary": {
      "command": "python",
      "args": ["/path/to/tools/diary_mcp.py"]
    }
  }
}
```

Restart Claude Code. The diary tools will appear as `mcp__diary__*`.

### As CLI

```bash
# List all tools
python tools/diary_mcp.py --list-tools

# Run a tool directly
python tools/diary_mcp.py diary_list
python tools/diary_mcp.py diary_check_new
python tools/diary_mcp.py session_outline <session_id>

# Standalone diary CLI (diary commands only)
python tools/diary_tool.py list
python tools/diary_tool.py check
python tools/diary_tool.py page 3
```

## Architecture

```
diary_mcp.py              ← MCP server entry point (also CLI: diary_mcp.py <tool> [args])
diary_mcp_shared.py       ← Shared FastMCP instance, paths, parsing helpers, prompt templates
mcp_diary_tools.py        ← Diary management MCP tools (list, page, search, insert, supplement, etc.)
mcp_session_tools.py      ← Session log parsing MCP tools (list, summary, outline, user_messages)
mcp_practice_tools.py     ← Practice-knowledge MCP tools (work_log_*, practice_rules_*, practice_check_setup)
practice_db.py            ← SQLite backend for the practice knowledge base (schema + CRUD helpers)
diary_tool.py             ← Standalone CLI wrapper (thin layer over the MCP tool functions)
session_parser.py         ← Legacy standalone CLI for session parsing (works independently)
seed_practice_db.py       ← One-time seed of initial practice rules
seed_work_log.py          ← One-time seed of initial work_log entries
export_practice_db.py     ← Dump practice.db to human-readable markdown or text
test_practice.py          ← Pytest suite for the practice DB
```

Data files live under `diary/` in the working project:

```
diary/
  diary.md                        ← the diary itself
  practice.db                     ← SQLite: work_log + practice_rules
  diary_prompt.md                 ← custom entry prompt (optional)
  diary_supplemental_prompt.md    ← custom supplemental prompt (optional)
  suppressed.json                 ← suppression list (auto-managed)
  tmp/                            ← staging area for entries before insertion
```

## MCP Tools

### Diary tools

| Tool | Args | Description |
|------|------|-------------|
| `diary_list` | — | List all entries with date, session ID, and title |
| `diary_sessions` | — | List session IDs in the diary (for deduplication) |
| `diary_page` | `page`, `size` | Paginate through full entry text (default: page 1, 5/page) |
| `diary_search` | `keywords`, `page`, `size` | Search entries by space-separated keywords (AND logic). Paginated (default 3/page). |
| `diary_get` | `date_prefix` | Get entries by date (e.g. "25 February" or "2026-02-25") |
| `diary_insert_from_file` | `file_path` | Insert entry from file at correct chronological position |
| `diary_insert_text` | `entry_text` | Insert entry from raw text |
| `diary_append_supplemental` | `session_id`, `file_path` or `text` | Append supplemental section to existing entry |
| `diary_cases` | — | List all case codes with entry counts |
| `diary_case` | `case_code`, `page`, `size` | Find all entries mentioning a case. Paginated (default 3/page). |
| `diary_prompt` | — | Show the prompt template for generating new entries |
| `diary_supplemental_prompt` | — | Show the prompt template for generating supplemental entries |
| `diary_check_new` | `max_stale_days` | Check: NEW, STALE, ONGOING, SUPPRESSED, CAUGHT UP. Optional auto-suppress threshold. |
| `diary_suppress` | `session_ids`, `reason` | Suppress sessions from diary_check_new (comma-separated IDs or 8-char prefixes) |
| `diary_unsuppress` | `session_ids` | Remove sessions from the suppression list |

### Session tools

| Tool | Args | Description |
|------|------|-------------|
| `session_list` | — | List all sessions with dates, sizes, message counts |
| `session_summary` | `session_id` | Compact summary: tools, matter codes, files, messages |
| `session_outline` | `session_id`, `after` | Full conversation outline; `after` filters to records after a timestamp |
| `session_user_messages` | `session_id` | Just the user messages from a session |

### Practice-knowledge tools

All data lives in `diary/practice.db` (SQLite). The DB and its tables are created automatically on first use.

**Work log** — structured record of activities:

| Tool | Args | Description |
|------|------|-------------|
| `work_log_insert` | `date`, `action_type`, `matter_code`, `client`, `outcome`, `summary`, `session_id` | Record a work activity. `date` is ISO (YYYY-MM-DD). `action_type` examples: `oa_response`, `translation_check`, `claim_draft`, `client_letter`, `idf_drafting`, `trainee_review`, `call_prep`, `filing_prep`. |
| `work_log_query` | `client`, `matter_code`, `action_type`, `since`, `until`, `limit` | Query the log with optional filters. Returns matching rows ordered newest-first. |
| `work_log_stats` | `since`, `group_by` | Aggregate counts. `group_by` is one or more of `client`, `action_type`, `matter_code` (comma-separated). |

**Practice rules** — accumulated operational rules tagged by context:

| Tool | Args | Description |
|------|------|-------------|
| `practice_rules_contexts` | — | List all context tags in use with rule counts. Call this before `practice_rules_lookup` to see what tags exist. |
| `practice_rules_lookup` | `contexts` | Find active rules matching ANY of the comma-separated context tags (e.g. `inventive_step,oa_response`). Returns full rule text and rationale. |
| `practice_rules_add` | `rule`, `contexts`, `rationale`, `source_session` | Add a new rule. Automatically flags near-duplicates (>40% keyword overlap with an existing rule sharing a tag) so you can refine the existing rule instead. |
| `practice_rules_add_force` | `rule`, `contexts`, `rationale`, `source_session` | Force-add a rule, bypassing duplicate detection. Use only after confirming the candidate is distinct from the flagged rule. |
| `practice_rules_update` | `rule_id`, `rule`, `rationale`, `contexts`, `active` | Edit an existing rule. Set `active=0` to retire a rule, `active=1` to reactivate. |
| `practice_rules_list` | `active_only` | Dump all rules. Set `active_only=0` to include retired rules. |

### Setup check

| Tool | Args | Description |
|------|------|-------------|
| `practice_check_setup` | — | One-shot status report: presence and counts for `diary.md`, `practice.db` (rules, work_log, tags), session log directory, the two prompt files, `suppressed.json`, and `MEMORY.md` (plus checks that MEMORY.md references the practice DB and the lookup/correction rules). |

## Context tags

Context tags are free-text labels attached to each practice rule and normalised to lowercase on insert. They are the primary retrieval axis: when about to start a task, call `practice_rules_lookup` with the relevant tags to surface any applicable rules.

Typical tag patterns in use:

- **Activity**: `oa_response`, `client_letter`, `reporting_letter`, `idf_drafting`, `claim_draft`, `claim_amendment`, `patentability_assessment`, `prior_art_analysis`, `case_analysis`, `docx_editing`, `track_changes`, `filing_prep`
- **Jurisdiction / procedure**: `ep`, `pct`, `problem_solution_approach`, `oral_proceedings`, `amended_description`
- **Cross-cutting**: `basis_check`, `inventive_step`, `clarity`, `samsung`, `email`

Rules typically carry two or three tags (activity + cross-cutting). Add tags liberally — broader tagging means rules surface more often. Use `practice_rules_contexts` to see what tags already exist before inventing new ones.

## Duplicate detection

`practice_rules_add` runs a cheap heuristic before inserting:

1. Strip stopwords and short tokens from the proposed rule to get distinctive keywords.
2. Find existing active rules that share at least one context tag.
3. Score them by how many keywords appear in their rule text.
4. If the top match has ≥40% keyword overlap, return it instead of inserting.

When a duplicate is flagged, the correct response is almost always `practice_rules_update` on the existing rule (to refine or expand it) rather than `practice_rules_add_force`. Force-add only when the new rule is genuinely distinct and simply happens to share vocabulary.

## Exporting the practice database

`export_practice_db.py` dumps `diary/practice.db` to human-readable form for review, diffing, or archival.

```bash
# Markdown to stdout, rules grouped by context tag (default)
python export_practice_db.py

# Write to file
python export_practice_db.py -o rules.md

# Include retired (inactive) rules
python export_practice_db.py --include-inactive

# Group by id instead of context (each rule appears once)
python export_practice_db.py --by id

# Also dump the work_log table
python export_practice_db.py --work-log

# Plain-text output instead of markdown
python export_practice_db.py --format text

# Work log only
python export_practice_db.py --work-log-only
```

The default grouping by context means a rule tagged `a,b` appears under both `a` and `b`; the `#id` header is the canonical reference. Use `--by id` for a flat, deduplicated dump.

## Diary entry format

```markdown
## DD Month YYYY, HH:MM–HH:MM — <case(s)>: <short title>

**Session**: `<session-uuid>`
**Entry written**: 2026-03-12T16:46
**Last updated**: 2026-03-12T18:30    ← only present if supplementals added

**Case**: <matter_code> (description)

**Task**: What was being worked on

**What happened**: Detailed narrative...

**Difficulties**: Problems encountered...

**Outcome**: Deliverables and results...

**Strategic notes for future reference**: Insights not in the deliverables...

### Supplemental — 12 March 2026, 18:30   ← appended when session continues

**Task**: Continuation work...

**What happened**: ...
```

## Workflow for writing new diary entries

1. Run `diary_check_new` to see which sessions need entries
2. It reports 5 categories:
   - **NEW** — sessions with no diary entry → use `diary_prompt` template
   - **STALE** — sessions with an entry but significant new activity → use `diary_supplemental_prompt` template
   - **ONGOING** — sessions active within the last 2 hours → skip for now
   - **SUPPRESSED** — sessions explicitly marked as done (count only)
   - **CAUGHT UP** — everything accounted for
3. For NEW sessions: use the template from `diary_prompt` (replacing `{SESSION_ID}` and `{SESSION_SHORT}`)
4. For STALE sessions: use the template from `diary_supplemental_prompt` (replacing `{SESSION_ID}`, `{SESSION_SHORT}`, and `{AFTER_TIMESTAMP}`)
5. To dismiss stale sessions you don't intend to process: `diary_suppress` with their session IDs
6. To auto-suppress old stale sessions: `diary_check_new` with `max_stale_days=14`
7. Re-run `diary_check_new` to confirm

## Project-specific prompts

The prompt templates served by `diary_prompt` and `diary_supplemental_prompt` can be customised per project. Place the prompt files alongside `diary.md` (see the directory layout in the Architecture section above).

If a custom prompt file exists, it is used verbatim. If not, the server returns a generic default.

Custom prompts must contain `{SESSION_ID}` and `{SESSION_SHORT}` placeholders (and `{AFTER_TIMESTAMP}` for supplementals).

## Testing

```bash
# Syntax check
python -c "import diary_mcp"

# List all tools with signatures
python diary_mcp.py --list-tools

# Run any tool directly
python diary_mcp.py diary_check_new
python diary_mcp.py practice_check_setup
python diary_mcp.py practice_rules_contexts

# Practice database tests
python -m pytest test_practice.py -v
```

## Session log location

Session logs are auto-detected from `~/.claude/projects/`. The server converts the working directory to a Claude Code project slug and looks for the matching session log directory.

## Safety note

Session logs can be very large (20+ MB). **Never** read them directly with the Read tool. Always use the session parsing tools, which handle truncation automatically.

## License

MIT
