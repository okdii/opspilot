import re
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, field_validator


class OrgCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(v) > 80:
            raise ValueError("Name must be at most 80 characters")
        return v

    @field_validator("slug")
    @classmethod
    def slug_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) < 2:
            raise ValueError("Slug must be at least 2 characters")
        if len(v) > 50:
            raise ValueError("Slug must be at most 50 characters")
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("Slug can only contain lowercase letters, numbers, and hyphens")
        return v

    @field_validator("description")
    @classmethod
    def description_max(cls, v: str | None) -> str | None:
        if v and len(v) > 300:
            raise ValueError("Description must be at most 300 characters")
        return v


class OrgUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) < 2:
                raise ValueError("Name must be at least 2 characters")
            if len(v) > 80:
                raise ValueError("Name must be at most 80 characters")
        return v


class OrgOut(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgStatsOut(BaseModel):
    server_count: int
    domain_count: int
    member_count: int
