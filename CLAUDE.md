# Diary MCP Server

Python MCP server for maintaining a structured diary from Claude Code session logs,
plus a practice knowledge base for accumulating operational rules and work history.

## Architecture

- `diary_mcp.py` — entry point: MCP server (no args) or CLI (`diary_mcp.py <tool> [args]`)
- `diary_mcp_shared.py` — shared FastMCP instance, path detection, parsing helpers, prompt templates, suppression list I/O
- `mcp_diary_tools.py` — diary management tools (15 tools registered via `@mcp.tool()`)
- `mcp_session_tools.py` — session log parsing tools (4 tools)
- `mcp_practice_tools.py` — practice knowledge base tools (8 tools: work_log + practice_rules)
- `practice_db.py` — SQLite backend for the practice knowledge base (schema, CRUD helpers)
- `diary_tool.py` — standalone CLI wrapper (thin layer over MCP tool functions)
- `session_parser.py` — legacy standalone session parser

## Key patterns

- All tools register on a shared `mcp` instance imported from `diary_mcp_shared.py`
- Each tool module exports a `_tools` dict at the bottom for CLI testing
- Tool parameters use Python type hints; FastMCP auto-extracts the schema
- Diary entries live in `diary/diary.md`, session logs in `~/.claude/projects/<slug>/*.jsonl`
- Suppression list lives in `diary/suppressed.json`
- Practice database lives in `diary/practice.db` (SQLite, auto-created on first use)

## Practice knowledge base

Two tables in `diary/practice.db`:

- **work_log** — structured record of work activities (date, matter_code, client, action_type, outcome)
- **practice_rules** — accumulated operational rules tagged with context strings (e.g. `inventive_step,oa_response`)

Context tags are free-text, normalised to lowercase on insert. Use `practice_rules_contexts` to see available tags before doing a lookup.

## Testing

```bash
# Syntax check
python -c "import diary_mcp"

# List all tools with signatures
python diary_mcp.py --list-tools

# Run any tool
python diary_mcp.py diary_check_new
python diary_mcp.py diary_suppress <session_id>

# Practice knowledge base tests
python -m pytest test_practice.py -v
```

## Dependencies

- Python 3.10+
- `mcp` package (`pip install -r requirements.txt`)
- `sqlite3` (stdlib)
