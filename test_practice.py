"""Tests for the practice knowledge base (practice_db + mcp_practice_tools)."""

import os
import sys
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

# Ensure the diary_tool package is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect the practice DB to a temp directory for every test."""
    db_path = tmp_path / "diary" / "practice.db"
    monkeypatch.setattr("practice_db.DB_PATH", db_path)
    yield db_path


# ---------------------------------------------------------------------------
# practice_db unit tests
# ---------------------------------------------------------------------------

class TestPracticeDB:
    """Low-level database operations."""

    def test_get_db_creates_tables(self, isolated_db):
        import practice_db
        conn = practice_db.get_db()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "work_log" in tables
        assert "practice_rules" in tables

    def test_get_db_creates_parent_dir(self, isolated_db):
        import practice_db
        # The dir shouldn't exist yet (tmp_path/diary/)
        assert not isolated_db.parent.exists()
        practice_db.get_db().close()
        assert isolated_db.parent.exists()

    def test_get_db_idempotent(self, isolated_db):
        """Calling get_db twice doesn't fail or duplicate tables."""
        import practice_db
        practice_db.get_db().close()
        practice_db.get_db().close()


class TestNormaliseContexts:

    def test_basic(self):
        from practice_db import _normalise_contexts
        assert _normalise_contexts("  Foo , bar, BAZ ") == "bar,baz,foo"

    def test_deduplication(self):
        from practice_db import _normalise_contexts
        assert _normalise_contexts("a,b,a,A") == "a,b"

    def test_empty(self):
        from practice_db import _normalise_contexts
        assert _normalise_contexts("  , , ") == ""

    def test_single(self):
        from practice_db import _normalise_contexts
        assert _normalise_contexts("inventive_step") == "inventive_step"


# ---------------------------------------------------------------------------
# work_log tests
# ---------------------------------------------------------------------------

class TestWorkLog:

    def test_insert_and_query(self):
        import practice_db
        row_id = practice_db.insert_work_log(
            date="2026-04-16", matter_code="P6082137PCT-EP",
            client="VitalFluid", action_type="oa_response",
            outcome="completed", summary="Response to second OA",
        )
        assert row_id >= 1

        rows = practice_db.query_work_log(client="VitalFluid")
        assert len(rows) == 1
        assert rows[0]["matter_code"] == "P6082137PCT-EP"
        assert rows[0]["action_type"] == "oa_response"

    def test_query_filters(self):
        import practice_db
        practice_db.insert_work_log(
            date="2026-04-10", client="Samsung", action_type="translation_check",
        )
        practice_db.insert_work_log(
            date="2026-04-15", client="Samsung", action_type="oa_response",
        )
        practice_db.insert_work_log(
            date="2026-04-15", client="VitalFluid", action_type="oa_response",
        )

        # Filter by client
        assert len(practice_db.query_work_log(client="Samsung")) == 2

        # Filter by action_type
        assert len(practice_db.query_work_log(action_type="oa_response")) == 2

        # Filter by since
        assert len(practice_db.query_work_log(since="2026-04-12")) == 2

        # Combined
        assert len(practice_db.query_work_log(client="Samsung", action_type="oa_response")) == 1

    def test_query_case_insensitive_client(self):
        import practice_db
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="x")
        assert len(practice_db.query_work_log(client="samsung")) == 1
        assert len(practice_db.query_work_log(client="SAMSUNG")) == 1

    def test_query_matter_code_partial_match(self):
        import practice_db
        practice_db.insert_work_log(
            date="2026-04-16", matter_code="P6082137PCT-EP", action_type="x",
        )
        practice_db.insert_work_log(
            date="2026-04-16", matter_code="P6082137PCT-US", action_type="y",
        )
        # Partial match on family root
        assert len(practice_db.query_work_log(matter_code="P6082137")) == 2

    def test_query_empty(self):
        import practice_db
        assert practice_db.query_work_log(client="nonexistent") == []

    def test_stats_by_client(self):
        import practice_db
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="x")
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="y")
        practice_db.insert_work_log(date="2026-04-16", client="VitalFluid", action_type="x")

        stats = practice_db.stats_work_log(group_by="client")
        assert len(stats) == 2
        # Samsung should be first (2 entries)
        assert stats[0]["client"] == "Samsung"
        assert stats[0]["count"] == 2

    def test_stats_with_since(self):
        import practice_db
        practice_db.insert_work_log(date="2026-03-01", client="Old", action_type="x")
        practice_db.insert_work_log(date="2026-04-16", client="New", action_type="x")

        stats = practice_db.stats_work_log(since="2026-04-01", group_by="client")
        assert len(stats) == 1
        assert stats[0]["client"] == "New"

    def test_stats_multi_group(self):
        import practice_db
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="oa_response")
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="oa_response")
        practice_db.insert_work_log(date="2026-04-16", client="Samsung", action_type="translation_check")

        stats = practice_db.stats_work_log(group_by="client,action_type")
        assert len(stats) == 2
        assert stats[0]["count"] == 2  # oa_response


# ---------------------------------------------------------------------------
# practice_rules tests
# ---------------------------------------------------------------------------

class TestPracticeRules:

    def test_insert_and_lookup(self):
        import practice_db
        rid = practice_db.insert_rule(
            rule="Do not use headings in PSA arguments.",
            rationale="Reads like a checklist.",
            contexts="inventive_step, problem_solution_approach",
        )
        assert rid >= 1

        # Lookup by one matching tag
        rules = practice_db.lookup_rules("inventive_step")
        assert len(rules) == 1
        assert "headings" in rules[0]["rule"]

        # Lookup by the other tag
        rules = practice_db.lookup_rules("problem_solution_approach")
        assert len(rules) == 1

    def test_lookup_matches_any_tag(self):
        import practice_db
        practice_db.insert_rule(rule="Rule A", contexts="inventive_step")
        practice_db.insert_rule(rule="Rule B", contexts="claim_amendment")

        # Both should match when querying with both tags
        rules = practice_db.lookup_rules("inventive_step,claim_amendment")
        assert len(rules) == 2

    def test_lookup_no_match(self):
        import practice_db
        practice_db.insert_rule(rule="Rule A", contexts="inventive_step")
        assert practice_db.lookup_rules("translation_check") == []

    def test_lookup_empty_contexts(self):
        import practice_db
        assert practice_db.lookup_rules("") == []
        assert practice_db.lookup_rules("  , , ") == []

    def test_contexts_normalised_on_insert(self):
        import practice_db
        rid = practice_db.insert_rule(
            rule="Test", contexts="  ZZZ , aaa, MMM, aaa ",
        )
        rules = practice_db.list_rules()
        stored = [r for r in rules if r["id"] == rid][0]
        assert stored["contexts"] == "aaa,mmm,zzz"

    def test_update_rule_text(self):
        import practice_db
        rid = practice_db.insert_rule(rule="Original", contexts="test")
        ok = practice_db.update_rule(rid, rule="Updated")
        assert ok
        rules = practice_db.list_rules()
        assert rules[0]["rule"] == "Updated"
        assert rules[0]["updated_at"] is not None

    def test_update_contexts(self):
        import practice_db
        rid = practice_db.insert_rule(rule="Test", contexts="old_tag")
        practice_db.update_rule(rid, contexts="new_tag, another_tag")
        rules = practice_db.list_rules()
        assert rules[0]["contexts"] == "another_tag,new_tag"

    def test_deactivate_and_reactivate(self):
        import practice_db
        rid = practice_db.insert_rule(rule="Test", contexts="test")

        # Deactivate
        practice_db.update_rule(rid, active=0)
        assert practice_db.list_rules(active_only=True) == []
        assert len(practice_db.list_rules(active_only=False)) == 1

        # Lookup should not find inactive rules
        assert practice_db.lookup_rules("test") == []

        # Reactivate
        practice_db.update_rule(rid, active=1)
        assert len(practice_db.lookup_rules("test")) == 1

    def test_update_nonexistent_returns_false(self):
        import practice_db
        assert practice_db.update_rule(9999, rule="nope") is False

    def test_update_no_changes_returns_false(self):
        import practice_db
        rid = practice_db.insert_rule(rule="Test", contexts="test")
        assert practice_db.update_rule(rid) is False

    def test_list_rules_active_vs_all(self):
        import practice_db
        practice_db.insert_rule(rule="Active rule", contexts="a")
        rid2 = practice_db.insert_rule(rule="Inactive rule", contexts="b")
        practice_db.update_rule(rid2, active=0)

        assert len(practice_db.list_rules(active_only=True)) == 1
        assert len(practice_db.list_rules(active_only=False)) == 2

    def test_list_contexts(self):
        import practice_db
        practice_db.insert_rule(rule="R1", contexts="inventive_step,oa_response")
        practice_db.insert_rule(rule="R2", contexts="oa_response,claim_amendment")
        practice_db.insert_rule(rule="R3", contexts="oa_response")

        ctx = practice_db.list_contexts()
        # oa_response appears in all 3, should be first
        assert ctx[0] == ("oa_response", 3)
        # The other two appear once each
        tags = {t for t, c in ctx}
        assert "inventive_step" in tags
        assert "claim_amendment" in tags

    def test_list_contexts_excludes_inactive(self):
        import practice_db
        rid = practice_db.insert_rule(rule="R1", contexts="only_tag")
        practice_db.update_rule(rid, active=0)
        assert practice_db.list_contexts() == []

    def test_list_contexts_empty(self):
        import practice_db
        assert practice_db.list_contexts() == []


# ---------------------------------------------------------------------------
# MCP tool integration tests (string output)
# ---------------------------------------------------------------------------

class TestMCPTools:
    """Test the MCP tool wrappers return well-formed string output."""

    def test_work_log_insert_returns_confirmation(self):
        import mcp_practice_tools as tools
        result = tools.work_log_insert(
            date="2026-04-16", action_type="oa_response",
            matter_code="P6082137PCT-EP", client="VitalFluid",
            summary="Test entry",
        )
        assert "Logged:" in result
        assert "P6082137PCT-EP" in result

    def test_work_log_query_empty(self):
        import mcp_practice_tools as tools
        result = tools.work_log_query(client="nonexistent")
        assert "No matching" in result

    def test_work_log_query_with_results(self):
        import mcp_practice_tools as tools
        tools.work_log_insert(date="2026-04-16", action_type="x", client="Test")
        result = tools.work_log_query(client="Test")
        assert "Found" in result

    def test_work_log_stats_empty(self):
        import mcp_practice_tools as tools
        result = tools.work_log_stats()
        assert "No work log data" in result

    def test_work_log_stats_with_data(self):
        import mcp_practice_tools as tools
        tools.work_log_insert(date="2026-04-16", action_type="x", client="Samsung")
        result = tools.work_log_stats()
        assert "Samsung" in result

    def test_practice_rules_add_and_lookup(self):
        import mcp_practice_tools as tools
        result = tools.practice_rules_add(
            rule="No headings in PSA",
            contexts="inventive_step",
            rationale="Reads like checklist",
        )
        assert "Added rule" in result

        result = tools.practice_rules_lookup("inventive_step")
        assert "No headings" in result
        assert "checklist" in result

    def test_practice_rules_lookup_fallback(self):
        """When no match, shows available tags."""
        import mcp_practice_tools as tools
        tools.practice_rules_add(rule="X", contexts="real_tag")
        result = tools.practice_rules_lookup("nonexistent")
        assert "No rules matching" in result
        assert "real_tag" in result

    def test_practice_rules_lookup_no_rules_at_all(self):
        import mcp_practice_tools as tools
        result = tools.practice_rules_lookup("anything")
        assert "no rules exist" in result

    def test_practice_rules_contexts_menu(self):
        import mcp_practice_tools as tools
        tools.practice_rules_add(rule="R1", contexts="inventive_step,oa_response")
        tools.practice_rules_add(rule="R2", contexts="oa_response")
        result = tools.practice_rules_contexts()
        assert "oa_response" in result
        assert "(2 rules)" in result
        assert "inventive_step" in result
        assert "(1 rule)" in result

    def test_practice_rules_contexts_empty(self):
        import mcp_practice_tools as tools
        result = tools.practice_rules_contexts()
        assert "No practice rules" in result

    def test_practice_rules_update_success(self):
        import mcp_practice_tools as tools
        tools.practice_rules_add(rule="Old text", contexts="test")
        result = tools.practice_rules_update(rule_id=1, rule="New text")
        assert "Updated" in result

    def test_practice_rules_update_not_found(self):
        import mcp_practice_tools as tools
        result = tools.practice_rules_update(rule_id=9999, rule="nope")
        assert "ERROR" in result

    def test_practice_rules_list_empty(self):
        import mcp_practice_tools as tools
        result = tools.practice_rules_list()
        assert "No practice rules" in result

    def test_practice_rules_list_with_data(self):
        import mcp_practice_tools as tools
        tools.practice_rules_add(rule="A rule", contexts="ctx")
        result = tools.practice_rules_list()
        assert "1 active" in result
        assert "A rule" in result
