"""Tests for _access_log_security collector function."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.daily_report_collector import _access_log_security

SID = "00000000-0000-0000-0000-000000000001"
DAY_START = datetime(2026, 6, 28, tzinfo=timezone.utc)
DAY_END = datetime(2026, 6, 29, tzinfo=timezone.utc)


def _db(*row_lists):
    """Mock DB whose execute() returns successive result mocks."""
    results = []
    for rows in row_lists:
        r = MagicMock()
        r.all.return_value = rows
        results.append(r)
    db = AsyncMock()
    db.execute.side_effect = results
    return db


def test_returns_expected_top_level_keys():
    db = _db([("2xx", 10)], [("1.2.3.4", 10, 10, 0, 0)], [("/shell.php", 1, 1, 0)])
    result = asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    assert set(result.keys()) == {"status_distribution", "top_ips", "top_security_paths"}


def test_status_distribution_keyed_by_class():
    db = _db([("2xx", 1420), ("4xx", 312)], [], [])
    result = asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    dist = result["status_distribution"]
    assert dist["2xx"] == 1420
    assert dist["4xx"] == 312
    assert dist.get("3xx", 0) == 0


def test_top_ips_shape():
    db = _db([], [("45.33.32.156", 240, 0, 240, 0)], [])
    result = asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    assert len(result["top_ips"]) == 1
    ip = result["top_ips"][0]
    assert ip == {"ip": "45.33.32.156", "total": 240, "cnt_2xx": 0, "cnt_4xx": 240, "cnt_5xx": 0}


def test_top_security_paths_shape():
    db = _db([], [], [("/wp-admin/install.php", 55, 0, 55)])
    result = asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    assert len(result["top_security_paths"]) == 1
    p = result["top_security_paths"][0]
    assert p == {"path": "/wp-admin/install.php", "total": 55, "cnt_2xx": 0, "cnt_4xx": 55}


def test_empty_rows_return_empty_collections():
    db = _db([], [], [])
    result = asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    assert result["status_distribution"] == {}
    assert result["top_ips"] == []
    assert result["top_security_paths"] == []


def test_executes_exactly_three_queries():
    db = _db([], [], [])
    asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    assert db.execute.call_count == 3


def test_all_queries_pass_sid_and_date_range():
    db = _db([], [], [])
    asyncio.run(_access_log_security(db, SID, DAY_START, DAY_END))
    for call in db.execute.call_args_list:
        params = call[0][1]
        assert params["sid"] == SID
        assert params["day_start"] == DAY_START
        assert params["day_end"] == DAY_END
