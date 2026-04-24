# How the Memory Works

This project is one slice of a layered memory system that Claude Code uses to carry knowledge across sessions. The layers have very different lifetimes, sizes, and access patterns. Understanding which tier a piece of information belongs in is the difference between a rule that fires reliably and a note that gets lost.

## The tiers at a glance

| Tier | Lives in | Lifetime | Loaded automatically? | Best for |
|------|----------|----------|----------------------|----------|
| 1. Conversation context | the current session | this session only | yes (it *is* the session) | working state, partial reasoning, scratch |
| 2. Session logs | `~/.claude/projects/<slug>/*.jsonl` | forever (append-only) | no — must be parsed | raw audit trail, "what exactly happened when" |
| 3. Auto memory | `~/.claude/projects/<slug>/memory/*.md` | forever | `MEMORY.md` index only | user profile, feedback, project context, references |
| 4. Diary | `diary/diary.md` | forever | no — read on demand | narrative record of a work session: task, outcome, lessons |
| 5. Work log | `diary/practice.db` → `work_log` | forever | no — queried on demand | structured activity records (matter, client, action, outcome) |
| 6. Practice rules | `diary/practice.db` → `practice_rules` | forever | no — looked up by context | durable operational rules with rationale |
| 7. CLAUDE.md | `~/.claude/CLAUDE.md` and project `CLAUDE.md` | forever | yes (always in prompt) | invariant instructions that must always apply |

The tiers are roughly ordered from most ephemeral / cheapest to access, to most permanent / most load-bearing. Information should live in the *highest-numbered* tier that makes sense for it — lower tiers exist to feed the higher ones.

## Tier 1 — conversation context

The current session's messages. Everything else exists because this tier gets compacted and eventually replaced. Nothing written here persists beyond the session unless Claude deliberately promotes it somewhere below.

**When to use:** for any working state that is only interesting until the task is done.

**When not to use:** any fact, rule, or decision you would want a future Claude — or the current Claude tomorrow — to know. Promote it to the appropriate tier below before the session ends.

## Tier 2 — session logs (JSONL)

Every Claude Code session is written as an append-only `.jsonl` file in `~/.claude/projects/<project-slug>/`. These are the authoritative, lossless transcript. They are large (10–50 MB is normal) and growing.

Session logs are *not* a retrieval mechanism — you cannot grep them efficiently, and the Read tool should not be pointed at them. The session parsing tools in `mcp_session_tools.py` exist to extract shape and substance (outline, summary, user messages) without pulling the whole file into context.

**When to use:** forensic reconstruction. "What did I actually tell Claude at 14:30?" "Which tool calls did the prior session make?" They are the source of truth when the diary or memory disagrees with what really happened.

**When not to use:** everyday lookup. If a fact matters, it belongs in a higher tier.

## Tier 3 — auto memory (`~/.claude/projects/<slug>/memory/`)

Claude's private per-project memory store, managed by Claude itself, not by the user. `MEMORY.md` is a one-line-per-entry index always loaded into the conversation; each individual memory lives in its own file with frontmatter (`name`, `description`, `type`) and is read only when the index entry signals it is relevant.

Four memory types, each with a distinct purpose:

- **user** — who the user is, their role, preferences, expertise. Lets Claude calibrate explanations and defaults.
- **feedback** — "do X, don't do Y" guidance from the user, including *why*. Both corrections ("stop doing that") and quiet confirmations ("yes, that was the right call") belong here.
- **project** — state and motivation that are not derivable from the code: deadlines, incidents, who is doing what and why.
- **reference** — pointers to external systems (Linear project, Grafana dashboard, Slack channel).

**When to use:** anything persistent and personal to *this user on this project* that isn't an operational rule of the practice and isn't better expressed in code or CLAUDE.md.

**When not to use:** operational rules with broad applicability (those go in the practice DB), or invariants that must apply on every single turn (those go in CLAUDE.md).

## Tier 4 — the diary (`diary/diary.md`)

A single markdown file of chronologically ordered entries, one per meaningful work session. Each entry records the case, the task, what happened, difficulties, outcome, and strategic notes. Supplemental sections are appended when a session continues.

The diary is a narrative, not a lookup table. It answers "what did I work on Tuesday?" and "what did I decide about the Samsung chart last month?" It is intentionally human-readable and diffable.

The tooling around the diary (`diary_check_new`, `diary_suppress`, `diary_search`, `diary_case`, `diary_page`) exists to make the narrative searchable and to keep the index of open sessions clean.

**When to use:** at the end of a substantive session, to record what happened while it is fresh. Diary entries are also the raw material from which practice rules tend to be distilled.

**When not to use:** for rapid operational lookup during a task. Rules that you want surfaced at the start of work belong in the practice rules DB, not buried in a narrative.

## Tier 5 — work log (`practice.db` → `work_log`)

A SQLite table of structured activity records: one row per distinct unit of work, with columns for `date`, `matter_code`, `client`, `action_type`, `outcome`, and a short `summary`. Unlike the diary (which is freeform narrative), the work log is meant to be queried and aggregated: "how many OA responses this quarter for client X?", "what have I been doing for matter Y?"

The schema is in `practice_db.py`. MCP tools `work_log_insert`, `work_log_query`, and `work_log_stats` provide the access layer.

**When to use:** any time a work activity reaches a recordable milestone (response filed, letter sent, IDF drafted, trainee review completed). Insertion can happen from the diary-writing workflow or directly.

**When not to use:** for free-form narrative — that's the diary. For rules about *how* to do the work — that's the practice rules table.

## Tier 6 — practice rules (`practice.db` → `practice_rules`)

The operational knowledge base: durable "when X, do Y because Z" rules accumulated over time and tagged by context. Each rule has a `rule` body, a `rationale` (often referencing the incident that prompted it), a set of comma-separated `contexts`, and an `active` flag so retired rules can be kept for history.

Rules are retrieved by calling `practice_rules_lookup(contexts=...)` at the start of a task: the model identifies the relevant activity and cross-cutting tags (e.g. `inventive_step,oa_response`) and the tool returns every active rule that matches any of those tags.

The practice rules table is the most load-bearing tier for day-to-day work. It is where insights from past sessions crystallise into rules that actually shape future behaviour. The diary is the raw material; practice rules are the refined product.

**Lifecycle of a rule:**

1. A mistake or insight surfaces in a session (often captured first in the diary as a strategic note).
2. The user confirms the insight is worth codifying.
3. `practice_rules_add` is called. Duplicate detection runs; if a related rule exists, that rule is surfaced and refined via `practice_rules_update`.
4. In future sessions, `practice_rules_lookup` returns the rule for matching contexts, and the rule guides behaviour.
5. If the rule turns out to be wrong or stale, it is retired (`active = 0`), not deleted — the history is kept.

**When to use:** any rule you want applied reliably at the *start* of a task (as opposed to guidance that only matters for one user or one project — those go in feedback memory).

**When not to use:** ephemeral notes about the current task; anything that applies globally on every turn (CLAUDE.md); user-specific feedback that belongs in auto memory.

## Tier 7 — CLAUDE.md

The most permanent and the most expensive tier, in the sense that its contents are always in the prompt. Two scopes: the user's global `~/.claude/CLAUDE.md` (applies to every project) and the project's `CLAUDE.md` (applies only here).

CLAUDE.md content must meet a high bar: it should be short, invariant, and broadly applicable. If a rule is only relevant for a specific activity, it belongs in the practice rules DB with a context tag, not in CLAUDE.md.

**When to use:** identity, user profile, architecture summary, top-level conventions, the "how to test this project" section.

**When not to use:** long operational checklists, activity-specific advice, anything that could plausibly be looked up when needed rather than loaded on every turn.

## How the tiers feed each other

```
session context (tier 1)
        │
        ├──► session log (tier 2)  ─── raw audit trail, append-only
        │
        ├──► auto memory (tier 3)  ─── user/feedback/project/reference
        │        (written by Claude when learning about the user)
        │
        ├──► diary entry (tier 4)  ─── narrative record at end of session
        │        │
        │        └──► work_log row (tier 5)  ─── structured summary
        │        │
        │        └──► practice rule (tier 6)  ─── distilled operational rule
        │
        └──► CLAUDE.md (tier 7)    ─── rarely, and only for invariants
```

The critical flow during a *new* session runs in the other direction:

1. CLAUDE.md and MEMORY.md load automatically — the invariant frame.
2. If the diary MCP is connected, `diary_check_new` surfaces any unwritten sessions and `practice_check_setup` verifies the system is wired.
3. At the start of a task, Claude calls `practice_rules_lookup` with the relevant contexts to surface applicable rules.
4. During the task, Claude may consult specific memory files, `diary_search`, or `session_outline` for context.
5. At the end of the task, Claude writes a diary entry, optionally inserts a `work_log` row, and promotes any new insights to `practice_rules_add` (or refines existing rules via `practice_rules_update`).

## Placement heuristics

Ask these questions in order when deciding where a piece of information belongs:

1. **Is it an invariant that must apply to every single turn?** → CLAUDE.md (tier 7). Use sparingly.
2. **Is it a rule that should fire at the start of a specific kind of task?** → practice rules (tier 6), tagged by context.
3. **Is it a structured activity record I'll want to query or count later?** → work log (tier 5).
4. **Is it a narrative of what happened in this session?** → diary (tier 4).
5. **Is it user-, feedback-, project-, or reference-level context that isn't an operational rule?** → auto memory (tier 3).
6. **Is it only relevant for forensic reconstruction?** → nothing to do; the session log already captured it (tier 2).
7. **Is it only useful until this task is done?** → leave it in conversation context (tier 1).

## Staleness and correction

Every tier except CLAUDE.md and session logs can decay. Memory files can list functions that no longer exist; diary entries can be wrong about an outcome; practice rules can be superseded by a better rule. The two principles:

- **Trust current state over recalled state.** Before acting on a memory or rule that names a specific file, function, or flag, verify it still exists. Grep or Read first.
- **Don't delete — retire or update.** Practice rules have an `active` flag; memory files can be rewritten rather than appended to; diary entries get `Supplemental` sections rather than edits. History matters.

Session logs are the one tier that must not be edited. They are the final audit.

## Tooling map

| Tier | Read | Write |
|------|------|-------|
| 2 — session logs | `session_list`, `session_summary`, `session_outline`, `session_user_messages` | (Claude Code writes automatically) |
| 3 — auto memory | (MEMORY.md index loads automatically; individual files via Read) | Write tool, directly in `~/.claude/projects/<slug>/memory/` |
| 4 — diary | `diary_list`, `diary_page`, `diary_search`, `diary_get`, `diary_case`, `diary_cases`, `diary_sessions`, `diary_check_new` | `diary_insert_from_file`, `diary_insert_text`, `diary_append_supplemental`, `diary_suppress`, `diary_unsuppress` |
| 5 — work_log | `work_log_query`, `work_log_stats` | `work_log_insert` |
| 6 — practice_rules | `practice_rules_contexts`, `practice_rules_lookup`, `practice_rules_list` | `practice_rules_add`, `practice_rules_add_force`, `practice_rules_update` |
| all | `practice_check_setup` — one-shot health check across diary, practice DB, session dir, prompt files, MEMORY.md | |

For bulk export of the practice DB to markdown or text (e.g. for review, diffing, or archival), run `python export_practice_db.py` — see the README for flags.
