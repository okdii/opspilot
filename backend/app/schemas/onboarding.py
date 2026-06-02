from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class OnboardingStepOut(BaseModel):
    step: str
    step_number: int | None
    status: str
    message: str | None
    ssh_output: str | None
    duration_ms: int | None
    started_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OnboardingResponse(BaseModel):
    server_id: UUID
    started_at: datetime | None
    completed_at: datetime | None
    outcome: str  # 'success' | 'failed' | 'running' | 'pending'
    steps: list[OnboardingStepOut]
