"""extend app_settings for Phase 10 settings

Revision ID: 0003_settings_columns
Revises: 0002
Create Date: 2026-06-02
"""
import os
import base64
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

revision: str = "0003_settings_columns"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _encrypt(plaintext: str, key: bytes) -> str:
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def upgrade() -> None:
    op.alter_column("app_settings", "smtp_user", new_column_name="smtp_username")
    op.alter_column("app_settings", "smtp_from", new_column_name="smtp_from_address")
    op.add_column("app_settings", sa.Column("instance_name", sa.String(255), nullable=False, server_default="OpsPilot"))
    op.add_column("app_settings", sa.Column("smtp_encryption", sa.String(10), nullable=False, server_default="tls"))
    op.add_column("app_settings", sa.Column("smtp_recipients", sa.Text(), nullable=True))
    op.add_column("app_settings", sa.Column("alerts_retention_days", sa.Integer(), nullable=False, server_default="90"))
    op.add_column("app_settings", sa.Column("writer_password_encrypted", sa.Text(), nullable=True))

    writer_pw = os.environ.get("OPSPILOT_WRITER_PASSWORD")
    enc_key_b64 = os.environ.get("OPSPILOT_ENCRYPTION_KEY")
    if writer_pw and enc_key_b64:
        key = base64.b64decode(enc_key_b64)
        op.execute(
            sa.text("UPDATE app_settings SET writer_password_encrypted = :v WHERE id = 1").bindparams(
                v=_encrypt(writer_pw, key)
            )
        )


def downgrade() -> None:
    op.drop_column("app_settings", "writer_password_encrypted")
    op.drop_column("app_settings", "alerts_retention_days")
    op.drop_column("app_settings", "smtp_recipients")
    op.drop_column("app_settings", "smtp_encryption")
    op.drop_column("app_settings", "instance_name")
    op.alter_column("app_settings", "smtp_from_address", new_column_name="smtp_from")
    op.alter_column("app_settings", "smtp_username", new_column_name="smtp_user")
