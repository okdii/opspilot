"""Fix fail2ban_ban_events timestamps stored as local time instead of UTC.

Before v1.2.23 the collector applied .replace(tzinfo=timezone.utc) to the
server's local time, shifting all stored timestamps ahead by the server's UTC
offset. This migration subtracts that offset using the org's configured
timezone from the settings table.

Revision ID: 0027_fail2ban_fix_timestamps
Revises: 0026_fail2ban_jail_config
"""
from alembic import op

revision = "0027_fail2ban_fix_timestamps"
down_revision = "0026_fail2ban_jail_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            tz text;
            offset_secs numeric;
        BEGIN
            SELECT timezone INTO tz FROM app_settings WHERE id = 1;
            IF tz IS NULL OR tz = 'UTC' THEN
                RETURN;
            END IF;

            -- How many seconds ahead of UTC is this timezone?
            offset_secs := EXTRACT(epoch FROM (
                '2026-01-01 12:00:00'::timestamp AT TIME ZONE tz
                - '2026-01-01 12:00:00'::timestamp AT TIME ZONE 'UTC'
            ));

            IF offset_secs = 0 THEN
                RETURN;
            END IF;

            -- Subtract the offset from all events — corrects timestamps that
            -- were stored as "local time labelled UTC"
            UPDATE fail2ban_ban_events
            SET event_at = event_at - (offset_secs || ' seconds')::interval;
        END $$;
    """)


def downgrade() -> None:
    pass  # data-only fix, not reversible
