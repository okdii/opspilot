"""Tests for Task 1: exclude_pattern in _general_count."""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.services.log_evaluator import _general_count


def _rule(*, match_field=None, exclude_pattern=None):
    r = MagicMock()
    r.match_field = match_field
    r.server_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    r.source = "%access%"
    r.pattern = "%POST%.php% 200 %"
    r.exclude_pattern = exclude_pattern
    r.window_sec = 300
    return r


def _db(count=5):
    result = MagicMock()
    result.scalar_one.return_value = count
    db = AsyncMock()
    db.execute.return_value = result
    return db


def test_plain_branch_passes_excl_param_when_set():
    """Plain-message branch must include excl=<pattern> in query params."""
    rule = _rule(exclude_pattern="%jsvisit_counter%")
    db = _db()
    asyncio.run(_general_count(db, rule))
    params = db.execute.call_args[0][1]
    assert params["excl"] == "%jsvisit_counter%"


def test_plain_branch_passes_excl_none_when_unset():
    """Plain-message branch must pass excl=None when exclude_pattern is None."""
    rule = _rule(exclude_pattern=None)
    db = _db()
    asyncio.run(_general_count(db, rule))
    params = db.execute.call_args[0][1]
    assert params["excl"] is None


def test_field_branch_passes_excl_param_when_set():
    """Field-scoped branch must include excl=<pattern> in query params."""
    rule = _rule(match_field="url", exclude_pattern="%/administrator/%")
    db = _db()
    asyncio.run(_general_count(db, rule))
    params = db.execute.call_args[0][1]
    assert params["excl"] == "%/administrator/%"


def test_field_branch_passes_excl_none_when_unset():
    """Field-scoped branch must pass excl=None when exclude_pattern is None."""
    rule = _rule(match_field="url", exclude_pattern=None)
    db = _db()
    asyncio.run(_general_count(db, rule))
    params = db.execute.call_args[0][1]
    assert params["excl"] is None


def test_general_count_returns_db_value():
    """Return value must come from scalar_one(), cast to int."""
    rule = _rule()
    db = _db(count=7)
    result = asyncio.run(_general_count(db, rule))
    assert result == 7
