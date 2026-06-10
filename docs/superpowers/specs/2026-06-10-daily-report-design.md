# Daily Report Tab — Design Spec

**Date:** 2026-06-10  
**Status:** Approved  
**Scope:** New "Daily Report ✦" tab on the Server Detail page — a per-server AI-powered daily summary

---

## 1. Overview

Every day OpsPilot collects full telemetry for each server: CPU/RAM/disk/network metrics, alert events, service uptime, cron/backup job runs, and log lines. This spec defines a **Daily Report tab** that feeds all of that data into an LLM and returns:

- A **health score** (0–100) with a plain-English verdict
- A **narrative paragraph** summarising what happened yesterday
- **Grouped findings** — each one with a title, description, and concrete "What to do" fix
- **Supporting data sections** — metrics, services, alerts, jobs, log volume

Reports are pre-generated nightly at 00:05 and cached in the database. Users can also regenerate on demand.

---

## 2. UI Layout (approved in v8 mockup)

### 2.1 Date Navigation

```
‹  Monday, 9 June 2026          [📅 Pick date]  [← Yesterday]
   Yesterday · 00:00 – 23:59 MYT
```

- Default view: **yesterday**
- Left/right arrows navigate one day; the forward arrow is disabled when viewing yesterday
- Date picker opens a calendar to jump to any date with a cached report
- "Yesterday" shortcut always resets to the default

### 2.2 Score Banner

```
[Ring gauge: 55]  |  ⚠ Poor — Act Now
                     This server needs your attention today.
                     Several real issues found...            |  3 Critical
                                                                4 Warnings
                                                                3 Healthy
                                                                ↑ 5 vs prev day
```

- Large circular ring gauge — colour matches the band (green / amber / orange / red)
- Score number centred inside the ring (28px, 800 weight)
- Band label as a coloured pill badge
- One-sentence headline + 2-line blurb explaining the verdict
- Four pills on the right: critical count, warning count, healthy count, delta vs previous day
- Banner background: subtle gradient tinted by band colour

### 2.3 AI Analysis Card

**Header row:**
- `⬡ AI Analysis` badge (indigo, with pulsing dot)
- Model name + generation timestamp + "Cached nightly"
- `↻ Regenerate` link (admin only)

**Narrative block:**
- 15px body text, 1.85 line-height
- Key numbers and problem phrases highlighted inline: green for good, amber for warnings, red for critical, indigo for AI-identified correlations

**Findings — grouped by category:**

Each group has a header:
```
GROUP NAME ————————————————————————— N findings
```

Each finding card has two zones:

**Problem zone (top):**
- Emoji icon (left) + bold title (15px, white) + severity badge (top-right)
- Muted description (13px) — one or two sentences, specific
- Coloured top border (3px) signals severity at a glance

**Action zone (bottom, distinct background):**
- `🔧 WHAT TO DO` label — coloured to match severity (red for critical, amber for warning, blue for info, green for ok)
- Bold fix text (14px white) with inline code blocks styled as dark monospace pills

Finding groups:
1. **Server Performance** — CPU, RAM, disk, network anomalies
2. **Log Anomalies & Security** — errors, security events, repeated patterns
3. **Jobs & Services** — missed cron jobs, service outages

### 2.4 Stat Row

Five quick-glance stat cards in a row:
`Avg CPU` · `Peak RAM` · `Disk /` · `Alerts Fired` · `Jobs (success/total)`

Cards with warnings or failures get a subtle amber/red tint border and background.

### 2.5 Data Sections

Four collapsible sections below the AI card, each as a bordered card:

| Section | Content |
|---------|---------|
| **Metrics** | 3-column: CPU / RAM / Disk with daily average, progress bar, peak, and trend |
| **Services** | Row per service: name · type · uptime bar · uptime % · incident count |
| **Alerts** | Row per fired alert: severity dot · message · fired/resolved times · duration |
| **Cron & Backup Jobs** | Row per job: status icon · name · run time · duration or miss reason |
| **Log Volume** | 3-column: one per log source with line counts, error/warning pills, detected anomaly flag |

---

## 3. Scoring System

Start at **100**. Deduct per finding based on severity:

| Severity | Deduction per finding |
|----------|-----------------------|
| Critical (danger) | −8 to −12 |
| Warning | −4 to −6 |
| Info | −2 to −3 |
| Healthy/OK | 0 (positive signal, no deduction) |

Score bands:

| Range | Label | Colour |
|-------|-------|--------|
| 90–100 | Excellent | Green |
| 75–89 | Good | Green |
| 60–74 | Needs Attention | Amber |
| 40–59 | Poor — Act Now | Orange |
| 0–39 | Critical | Red |

The exact deduction per finding is determined by the LLM (within the allowed range per severity). The final score is floored at 0.

---

## 4. Data Pipeline

### 4.1 Data Collected for Each Report

| Source | Query scope | What is extracted |
|--------|-------------|-------------------|
| `server_metrics_daily` | Target date | avg/peak CPU, iowait, RAM, disk %, network in/out, disk read/write |
| `server_metrics_hourly` | Target date | Per-hour CPU to identify spike windows |
| `alerts` | Fired during target date | Rule name, severity, fired_at, resolved_at |
| `services` + `service_incidents` | Incidents on target date | Service name, type, uptime %, incident windows and durations |
| `cron_jobs` + `job_runs` | Target date | Each job: expected time, actual run time, duration, success/miss |
| `backup_jobs` + `backup_runs` | Target date | Same as cron jobs |
| Log files | Target date, all configured log sources | Extract: ERROR lines, WARN lines, repeated patterns (≥3 occurrences), security events (failed auth, etc.) |

Log extraction strategy: the backend pre-processes logs and sends **extracted patterns** to the LLM — not all raw lines. This keeps the prompt within token limits regardless of log volume.

### 4.2 Log Extraction

For each log source, before calling the LLM:
1. Filter to lines with level ERROR or WARN (or matched by pattern)
2. Group identical/similar messages and count occurrences
3. Flag security patterns: `Failed password`, `Invalid user`, `authentication failure`, `Connection refused` (configurable)
4. Pass: top 20 error groups, top 10 warning groups, all security events

---

## 5. AI Provider Layer

Shared infrastructure with Spec 12 (AI Chat Agent). This spec depends on it being built first or in parallel.

### 5.1 Provider Abstraction

`backend/app/services/ai/provider.py`:
```python
class BaseAIProvider(ABC):
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...

class AnthropicProvider(BaseAIProvider): ...
class OpenAIProvider(BaseAIProvider): ...
class GeminiProvider(BaseAIProvider): ...
```

### 5.2 Settings

| Key | Type | Notes |
|-----|------|-------|
| `ai_provider` | text | `anthropic` / `openai` / `gemini` / `disabled` |
| `ai_model` | text | e.g. `claude-sonnet-4-6` |
| `ai_api_key` | text | AES-256 encrypted at rest |

Default provider: `anthropic`, default model: `claude-sonnet-4-6`.

If `ai_provider = disabled`, the Daily Report tab shows an "AI not configured" state with a link to Settings.

### 5.3 Prompt Design

**System prompt (condensed):**
> You are a server monitoring AI. Analyse the telemetry below and return ONLY valid JSON.
> Output schema: `{"narrative": string, "findings": [...], "score": int}`
> Each finding: `{"id", "group", "severity", "icon", "title", "description", "fix"}`
> Groups: `server_performance`, `log_anomalies_security`, `jobs_services`
> Severity values: `danger`, `warn`, `info`, `ok`
> Score: start 100, deduct (danger −8–12, warn −4–6, info −2–3), floor 0.
> Be specific and actionable. Reference exact values from the data. No vague advice.

**User prompt:** structured JSON payload with all collected data.

**Token budget:** max 4000 completion tokens. Input is pre-condensed to stay under 6000 tokens.

---

## 6. Database

### 6.1 New Table: `daily_reports`

```sql
CREATE TABLE daily_reports (
    id            SERIAL PRIMARY KEY,
    server_id     INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    report_date   DATE NOT NULL,
    score         INTEGER NOT NULL,
    band          TEXT NOT NULL,  -- excellent/good/needs-attention/poor/critical
    narrative     TEXT NOT NULL,
    findings      JSONB NOT NULL DEFAULT '[]',
    data_snapshot JSONB NOT NULL DEFAULT '{}',
    ai_provider   TEXT,
    ai_model      TEXT,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    prompt_tokens    INTEGER,
    completion_tokens INTEGER,
    UNIQUE (server_id, report_date)
);
```

`data_snapshot` stores the collected metrics/services/alerts/jobs/logs summary so the tab can render the data sections without re-querying.

---

## 7. API

### 7.1 GET `/api/servers/{server_id}/daily-report`

Query param: `date=YYYY-MM-DD` (default: yesterday)

Behaviour:
1. Look up `daily_reports` for this server + date
2. If found → return cached report
3. If not found + date == yesterday + AI configured → generate and cache, return result
4. If not found + AI not configured → return `{"status": "ai_not_configured"}`
5. If not found + date is not yesterday → return `{"status": "not_generated"}`

Response shape:
```json
{
  "report_date": "2026-06-09",
  "score": 55,
  "band": "poor",
  "narrative": "...",
  "findings": [...],
  "data_snapshot": { "metrics": {...}, "services": [...], "alerts": [...], "jobs": [...], "logs": [...] },
  "generated_at": "2026-06-10T00:07:15Z",
  "ai_provider": "anthropic",
  "ai_model": "claude-sonnet-4-6"
}
```

### 7.2 POST `/api/servers/{server_id}/daily-report/regenerate`

Body: `{"date": "YYYY-MM-DD"}`

Admin only. Regenerates and overwrites the cached report for the given date. Returns the new report.

---

## 8. Nightly Scheduler Job

APScheduler job: `daily_report_generate_all`
- **Schedule:** every day at `00:05` local time
- **For each active server:**
  1. Collect yesterday's data
  2. Call AI provider
  3. Parse JSON response, compute band
  4. Upsert into `daily_reports`
  5. Log token usage
- **Error handling:** if AI call fails for a server, log the error and continue with the next server (do not abort the whole batch)
- **Timeout:** 60s per server

---

## 9. Frontend Component

### 9.1 `DailyReportTab.vue`

Location: `frontend/src/views/servers/tabs/DailyReportTab.vue`

State:
- `selectedDate` — defaults to yesterday
- `report` — loaded from API
- `loading` / `error` / `status` (ai_not_configured / not_generated / loaded)

Props: `serverId: number`

Emits: nothing (self-contained)

### 9.2 Integration in `ServerDetail.vue`

Add tab entry: `{ key: 'daily-report', label: 'Daily Report ✦' }`

Tab is always visible. If AI is not configured, the tab shows an informational empty state with a Settings link rather than being hidden.

---

## 10. Empty & Error States

| State | What the tab shows |
|-------|--------------------|
| AI not configured | Centered card: "AI Analysis not set up" + link to Settings → AI Provider |
| Report not yet generated (e.g. today) | "Report will be available after 00:05 tonight" + manual Regenerate button (admin) |
| Report generating (spinner) | Skeleton loader for all sections |
| AI call failed | Error card with retry button + last error message |
| No data for date | "No telemetry found for this date" |

---

## 11. Settings UI (AI Provider section)

Part of the existing Settings page (Phase 10). Adds a new **AI Provider** section:

- Provider dropdown: Anthropic / OpenAI / Gemini / Disabled
- Model input: text field (e.g. `claude-sonnet-4-6`)
- API Key: password field (masked), AES-256 encrypted before storing
- Test connection button: calls a test endpoint, shows success/failure inline
- Save button

This section is shared with Spec 12. If Spec 12 is implemented first, this spec only integrates with what's already there.

---

## 12. Out of Scope

- Real-time / live report generation (reports are nightly + on-demand only)
- Per-finding alert rules (findings are informational, not actionable alerts)
- Comparing two dates side by side
- Report export (PDF / email)
- Per-user report preferences
