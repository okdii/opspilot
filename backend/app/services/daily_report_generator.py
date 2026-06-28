"""Generates a daily health report for a server using an AI provider.

Builds a structured JSON prompt from collected data, calls the provider,
parses the response, computes the score band, and upserts into daily_report.
"""
import json
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import DailyReport
from app.services.ai.provider import BaseAIProvider
from app.services.daily_report_collector import collect_for_date

log = logging.getLogger(__name__)

SCORE_BANDS = [
    (90, "excellent"),
    (75, "good"),
    (60, "needs-attention"),
    (40, "poor"),
    (0, "critical"),
]

SYSTEM_PROMPT = """You are a server-monitoring AI analyst. Analyse the JSON telemetry below and return ONLY valid JSON — no markdown, no prose outside the JSON object.

Output schema (strict):
{
  "narrative": "<2–4 sentence plain-English summary of what happened yesterday>",
  "findings": [
    {
      "id": "<snake_case_unique_id>",
      "group": "<server_performance|log_anomalies_security|jobs_services>",
      "severity": "<danger|warn|info|ok>",
      "icon": "<single emoji>",
      "title": "<concise one-line finding title>",
      "description": "<1–2 sentence detail with specific values>",
      "fix": "<concrete actionable fix — include exact commands in backticks where relevant>",
      "fp_likelihood": "<low|medium|high>"
    }
  ],
  "score": <integer 0–100>
}

Score rules:
- Start at 100.
- Deduct 8–12 per danger finding, 4–6 per warn finding, 2–3 per info finding, 0 for ok findings.
- Floor at 0.

Severity rules:
- danger: active security threat, data loss risk, service outage, silently failing critical path
- warn: degrading trend, missed job, high resource usage, slow queries
- info: notable but non-urgent observation with a suggested improvement
- ok: a dimension that is healthy — include at least 1–2 ok findings per report

Always include at least one finding per group that has data.
Be specific: reference exact values, timestamps, IPs, query text, file paths from the data.
Never give vague advice like "monitor it" — give the exact command or config change.

HTTP status code interpretation (applies to access_log_security data and [HTTP NNN] codes in alert messages):

Threat outcome rules:
- HTTP 2xx response on a security-pattern path (.php, /wp-admin, /xmlrpc, /.env, /shell, /admin, /config): the attack SUCCEEDED — severity MUST be danger. State explicitly that the request returned a successful response.
- HTTP 4xx or 5xx only on a security-pattern path: the attack was BLOCKED or FAILED — cap severity at warn. Note in the description that the server blocked the request.
- Alert message containing [HTTP 200] or [HTTP 201]: confirmed real incident — do not downgrade severity.
- Alert message containing only [HTTP 403], [HTTP 404], or [HTTP 429]: probe was blocked — cap at warn or info.

False positive detection rules (use top_ips and top_security_paths from access_log_security):
- IP with high total requests but cnt_2xx == 0: scanner that found nothing — set severity to info, set fp_likelihood to "high". Title should say "probe/scanner — no successful responses".
- IP with cnt_2xx > 0 on security-pattern paths: confirmed attacker — severity danger, fp_likelihood "low".
- Many different IPs each making a few requests with all 4xx responses: automated probe sweep, not a targeted attack — produce one warn finding summarising the sweep, not per-IP findings. Set fp_likelihood "medium".
- Cross-reference IPs appearing in both alerts and top_ips: if the alerted IP has cnt_2xx == 0, flag the alert as a likely false positive.

fp_likelihood field rules:
- Every finding in group log_anomalies_security MUST include fp_likelihood.
- Findings in server_performance and jobs_services MAY omit fp_likelihood (set to "low" if included).
- Values: "low" = clear confirmed threat or real issue; "medium" = ambiguous, needs review; "high" = likely false positive.

Output ONLY the JSON object. No markdown fences."""


def _score_to_band(score: int) -> str:
    for threshold, band in SCORE_BANDS:
        if score >= threshold:
            return band
    return "critical"


async def generate_and_store(
    db: AsyncSession,
    server_id: uuid.UUID,
    report_date: date,
    provider: BaseAIProvider,
    provider_name: str,
    model_name: str,
) -> DailyReport:
    """Collect data, call AI, parse response, upsert and return DailyReport row."""
    data = await collect_for_date(db, server_id, report_date)
    user_prompt = json.dumps({"report_date": str(report_date), "data": data}, default=str)

    raw_text, prompt_tokens, completion_tokens = await provider.complete(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=4000,
        timeout=90.0,
    )

    # Strip markdown fences if the model added them despite instructions
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error("AI returned non-JSON for server %s date %s: %s", server_id, report_date, exc)
        raise

    narrative = parsed.get("narrative", "")
    findings = parsed.get("findings", [])
    score = max(0, min(100, int(parsed.get("score", 50))))
    band = _score_to_band(score)

    existing = await db.scalar(
        select(DailyReport).where(
            DailyReport.server_id == server_id,
            DailyReport.report_date == report_date,
        )
    )

    if existing:
        existing.score = score
        existing.band = band
        existing.narrative = narrative
        existing.findings = findings
        existing.data_snapshot = data
        existing.ai_provider = provider_name
        existing.ai_model = model_name
        existing.prompt_tokens = prompt_tokens
        existing.completion_tokens = completion_tokens
        existing.generated_at = datetime.now(timezone.utc)
        report = existing
    else:
        report = DailyReport(
            server_id=server_id,
            report_date=report_date,
            score=score,
            band=band,
            narrative=narrative,
            findings=findings,
            data_snapshot=data,
            ai_provider=provider_name,
            ai_model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        db.add(report)

    await db.commit()
    await db.refresh(report)
    return report
