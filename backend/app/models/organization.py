import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    members: Mapped[list["UserOrganization"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    servers: Mapped[list["Server"]] = relationship(back_populates="organization")
    domains: Mapped[list["Domain"]] = relationship(back_populates="organization")
    invites: Mapped[list["Invite"]] = relationship(back_populates="organization")
