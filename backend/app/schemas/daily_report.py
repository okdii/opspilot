from datetime import date, datetime
from pydantic import BaseModel


class DailyReportFinding(BaseModel):
    id: str
    group: str
    severity: str          # danger | warn | info | ok
    icon: str
    title: str
    description: str
    fix: str


class DailyReportResponse(BaseModel):
    status: str = "ok"     # ok | ai_not_configured | not_generated
    report_date: date | None = None
    score: int | None = None
    band: str | None = None
    narrative: str | None = None
    findings: list[DailyReportFinding] = []
    data_snapshot: dict = {}
    ai_provider: str | None = None
    ai_model: str | None = None
    generated_at: datetime | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class RegenerateRequest(BaseModel):
    date: date
