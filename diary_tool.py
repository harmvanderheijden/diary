"""
Diary Tool — Session Diary (CLI interface)
=====================================================

Standalone CLI for managing the session diary. The same functionality is also
available via the Diary MCP server (diary_mcp.py).

Usage:
    python diary_tool.py list                           # List all entries (date + title line + session ID)
    python diary_tool.py sessions                       # List just the session IDs already in the diary
    python diary_tool.py page [N] [size]                # Show page N (1-based, default 1) of entries, `size` per page (default 5)
    python diary_tool.py search <keyword> [keyword2..]  # Search entries by keyword(s)
    python diary_tool.py get <date_prefix>              # Get a specific entry by date prefix
    python diary_tool.py insert <entry_file>            # Insert entry from file at correct chronological position
    python diary_tool.py insert_text <text>             # Insert entry from stdin/argument (use with heredoc)
    python diary_tool.py cases                          # List all case numbers mentioned in the diary
    python diary_tool.py case <case_code>               # Find all entries mentioning a case
    python diary_tool.py prompt                         # Show the sample prompt for generating new diary entries
    python diary_tool.py check                          # Check if new sessions need diary entries

The diary file is at: C:/Users/hhi/source/codetest/diary/diary.md

Entry format convention:
    ## DD Month YYYY, HH:MM–HH:MM — <case>: <short title>

    **Session**: <session_uuid>

    **Case**: <matter_code> (description)
    ...rest of entry...

The date in the ## header is used for chronological ordering.
The **Session** line links back to the original session log for full detail.
"""

import sys
import os

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add script directory to path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from diary_mcp_shared import (
    read_entries, write_diary, parse_entry_date, extract_session_id,
    DIARY_PATH,
)

# Import the MCP tool functions for reuse (they return strings instead of printing)
from mcp_diary_tools import (
    diary_list, diary_sessions, diary_page, diary_search, diary_get,
    diary_insert_from_file, diary_insert_text, diary_append_supplemental,
    diary_cases, diary_case,
    diary_prompt, diary_supplemental_prompt, diary_check_new,
)


def _print_result(result):
    """Print a tool result string."""
    print(result)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        _print_result(diary_list())
    elif cmd == "sessions":
        _print_result(diary_sessions())
    elif cmd == "page":
        page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        page_size = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        _print_result(diary_page(page_num, page_size))
    elif cmd == "prompt":
        _print_result(diary_prompt())
    elif cmd == "check":
        _print_result(diary_check_new())
    elif cmd == "search" and len(sys.argv) > 2:
        _print_result(diary_search(" ".join(sys.argv[2:])))
    elif cmd == "get" and len(sys.argv) > 2:
        _print_result(diary_get(" ".join(sys.argv[2:])))
    elif cmd == "insert" and len(sys.argv) > 2:
        _print_result(diary_insert_from_file(sys.argv[2]))
    elif cmd == "insert_text" and len(sys.argv) > 2:
        _print_result(diary_insert_text(sys.argv[2]))
    elif cmd == "cases":
        _print_result(diary_cases())
    elif cmd == "case" and len(sys.argv) > 2:
        _print_result(diary_case(sys.argv[2]))
    elif cmd == "supplement" and len(sys.argv) > 3:
        _print_result(diary_append_supplemental(sys.argv[2], file_path=sys.argv[3]))
    elif cmd == "supplemental_prompt":
        _print_result(diary_supplemental_prompt())
    else:
        print(__doc__)
        sys.exit(1)
