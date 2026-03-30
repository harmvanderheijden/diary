# Diary — MCP Server for AI Session Logs

MCP server and CLI tools for maintaining a structured diary from Claude Code session logs. Records what was done, on which cases, with what outcome — and makes it searchable across sessions.

## Features

- **Diary management**: chronologically ordered markdown entries with search, pagination, and case-based filtering
- **Session log parsing**: extract summaries, outlines, and user messages from Claude Code JSONL session logs
- **New entry detection**: automatically identifies sessions that need diary entries (NEW, STALE, ONGOING, CAUGHT UP)
- **Stale session suppression**: mark finished sessions as "done" to keep check output clean; auto-unsuppresses if a session is re-opened
- **Supplemental entries**: append follow-up notes to existing entries when a session continues
- **Custom prompts**: per-project prompt templates for controlling diary entry style
- **Dual interface**: works as an MCP server or standalone CLI

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
diary_tool.py             ← Standalone CLI wrapper (thin layer over the MCP tool functions)
session_parser.py         ← Legacy standalone CLI for session parsing (works independently)
```

## MCP Tools

### Diary tools

| Tool | Args | Description |
|------|------|-------------|
| `diary_list` | — | List all entries with date, session ID, and title |
| `diary_sessions` | — | List session IDs in the diary (for deduplication) |
| `diary_page` | `page`, `size` | Paginate through full entry text (default: page 1, 5/page) |
| `diary_search` | `keywords` | Search entries by space-separated keywords (AND logic) |
| `diary_get` | `date_prefix` | Get entries by date (e.g. "25 February" or "2026-02-25") |
| `diary_insert_from_file` | `file_path` | Insert entry from file at correct chronological position |
| `diary_insert_text` | `entry_text` | Insert entry from raw text |
| `diary_append_supplemental` | `session_id`, `file_path` or `text` | Append supplemental section to existing entry |
| `diary_cases` | — | List all case codes with entry counts |
| `diary_case` | `case_code` | Find all entries mentioning a case |
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

The prompt templates served by `diary_prompt` and `diary_supplemental_prompt` can be customised per project. Place these files alongside `diary.md`:

```
diary/
  diary.md                        ← the diary itself
  diary_prompt.md                 ← custom entry prompt (optional)
  diary_supplemental_prompt.md    ← custom supplemental prompt (optional)
  suppressed.json                 ← suppression list (auto-managed)
  tmp/                            ← staging area for entries before insertion
```

If a custom prompt file exists, it is used verbatim. If not, the server returns a generic default.

Custom prompts must contain `{SESSION_ID}` and `{SESSION_SHORT}` placeholders (and `{AFTER_TIMESTAMP}` for supplementals).

## Session log location

Session logs are auto-detected from `~/.claude/projects/`. The server converts the working directory to a Claude Code project slug and looks for the matching session log directory.

## Safety note

Session logs can be very large (20+ MB). **Never** read them directly with the Read tool. Always use the session parsing tools, which handle truncation automatically.

## License

MIT
