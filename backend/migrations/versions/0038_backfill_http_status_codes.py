"""Backfill HTTP status codes into old access-log alert messages.

Alerts fired before v1.2.103 lack the [HTTP NNN] suffix. For each qualifying
alert the matching server_logs rows are queried and the suffix is appended.

Revision ID: 0038_backfill_http_status_codes
Revises: 0037_exclude_pattern
Create Date: 2026-06-28
"""
import re
from datetime import timedelta

from alembic import op
import sqlalchemy as sa

revision = "0038_backfill_http_status_codes"
down_revision = "0037_exclude_pattern"
branch_labels = None
depends_on = None

_MSG_RE = re.compile(
    r"^\d+ log line\(s\) matched '(.+)' on (\S+) in the last (\d+)s"
)


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, server_id, message, sent_at FROM alert"
            " WHERE message LIKE '%log line(s) matched%'"
            "   AND message ILIKE '%access%'"
            "   AND message NOT LIKE '%[HTTP %'"
        )
    ).fetchall()

    for row in rows:
        m = _MSG_RE.match(row.message)
        if not m:
            continue
        pattern, source, window_sec = m.group(1), m.group(2), int(m.group(3))
        if "access" not in source.lower():
            continue

        t_start = row.sent_at - timedelta(seconds=window_sec)
        code_rows = conn.execute(
            sa.text(
                r"""
                SELECT DISTINCT (regexp_match(message, '" (\d{3}) '))[1] AS code
                FROM server_logs
                WHERE server_id = :sid
                  AND source LIKE :source
                  AND message ILIKE :pattern
                  AND time BETWEEN :t_start AND :t_end
                  AND (regexp_match(message, '" (\d{3}) '))[1] IS NOT NULL
                LIMIT 10
                """
            ),
            {
                "sid": str(row.server_id),
                "source": source,
                "pattern": pattern,
                "t_start": t_start,
                "t_end": row.sent_at,
            },
        ).fetchall()

        codes = sorted(r.code for r in code_rows if r.code)
        if not codes:
            continue

        conn.execute(
            sa.text("UPDATE alert SET message = message || :suffix WHERE id = :id"),
            {"suffix": f" [HTTP {', '.join(codes)}]", "id": row.id},
        )


def downgrade() -> None:
    pass
