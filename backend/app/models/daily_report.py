import uuid
from datetime import date, datetime
from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyReport(Base):
    __tablename__ = "daily_report"
    __table_args__ = (UniqueConstraint("server_id", "report_date", name="uq_daily_report_server_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("server.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSONB(astext_type=Text()), nullable=False, default=list)
    data_snapshot: Mapped[dict] = mapped_column(JSONB(astext_type=Text()), nullable=False, default=dict)
    ai_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
