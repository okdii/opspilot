"""server_metrics compression policy (compress chunks > 2 days)

Revision ID: 0005_server_metrics_compression
Revises: 0004_maintenance_ends_nullable
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_server_metrics_compression"
down_revision = "0004_maintenance_ends_nullable"
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE server_metrics SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'server_id, metric_name',
            timescaledb.compress_orderby   = 'time DESC'
        )
    """))
    conn.execute(sa.text("SELECT add_compression_policy('server_metrics', INTERVAL '2 days')"))

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SELECT remove_compression_policy('server_metrics', if_exists => true)"))
    conn.execute(sa.text("ALTER TABLE server_metrics SET (timescaledb.compress = false)"))
