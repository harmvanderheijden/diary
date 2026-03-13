"""
Diary MCP Server — exposes diary management and session parsing as MCP tools.

Provides tools for:
  - Reading, searching, and paginating the session diary
  - Inserting new diary entries
  - Parsing Claude Code session logs
  - Checking which sessions need new diary entries

Can also be used as a CLI for testing:
    python diary_mcp.py <tool_name> [args...]
    python diary_mcp.py --list-tools

As MCP server (default, no arguments):
    python diary_mcp.py
"""

import sys
import os

# Add script directory to path so we can import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diary_mcp_shared import mcp

# Import tool modules — each registers its @mcp.tool() decorated functions
import mcp_diary_tools
import mcp_session_tools


# ---------------------------------------------------------------------------
# CLI testing
# ---------------------------------------------------------------------------

def _cli_test():
    """Run a tool from the command line for testing."""
    import inspect

    tools = {}
    tools.update(mcp_diary_tools._tools)
    tools.update(mcp_session_tools._tools)

    if len(sys.argv) < 2 or sys.argv[1] == "--list-tools":
        print("Usage: python diary_mcp.py <tool_name> [args...]")
        print("\nAvailable tools:")
        for name, fn in sorted(tools.items()):
            params = list(inspect.signature(fn).parameters.keys())
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print("  %-30s %-30s %s" % (name, " ".join(params), doc))
        sys.exit(0)

    tool_name = sys.argv[1]
    if tool_name not in tools:
        print(f"Unknown tool: {tool_name}")
        print(f"Available: {', '.join(sorted(tools.keys()))}")
        sys.exit(1)

    fn = tools[tool_name]
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    args = sys.argv[2:]
    kwargs = {}
    for i, param in enumerate(params):
        if i < len(args):
            annotation = param.annotation
            if annotation == int:
                kwargs[param.name] = int(args[i])
            else:
                kwargs[param.name] = args[i]
        elif param.default is not inspect.Parameter.empty:
            pass
        else:
            print(f"Missing required argument: {param.name}")
            sys.exit(1)

    result = fn(**kwargs)
    # Force UTF-8 output to avoid Windows cp1252 errors
    sys.stdout.buffer.write(result.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        _cli_test()
    elif len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
        _cli_test()
    else:
        mcp.run()
