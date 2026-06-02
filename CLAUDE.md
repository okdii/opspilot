# OpsPilot — Development Instructions

## Development Rules (Always Follow)

### 0. Update Progress Dashboard After Every Task
When a task completes (smoke test passed), update **both** files:
- `PROGRESS.md` — change `⬜` to `✅`
- `DASHBOARD.html` — change `status: 'pending'` to `status: 'done'` for the matching task in the `phases` data array
- Update the `LAST_UPDATED` date in DASHBOARD.html
The project manager checks DASHBOARD.html in their browser to track progress.

---

### 1. Smoke Test After Every Functional Unit
After finishing each functional feature, **always run a smoke test before moving on**. This applies to every module, every endpoint, every UI component.

Smoke test checklist per unit:
- Backend: start the server, hit the endpoint(s) with curl or a REST client, verify the response shape matches the spec
- Frontend: open the page in a browser, walk through the happy path (create, view, edit, delete where applicable)
- WebSocket: verify live push arrives in the browser when expected
- Alert/scheduler: trigger the condition manually and confirm the alert fires and resolves
- Do not mark a task done until you have seen it work with your own eyes (or confirmed via test output)

Repeat this every time. No exceptions.

---

### 2. UI/UX — Use Modern Style via UI/UX Pro Max Skill
All frontend work must use the **UI/UX Pro Max skill** (`/ui-ux-pro-max`).

- Invoke the skill when designing or building any screen, component, or layout
- Style target: **modern dark dashboard** — consistent with Vuestic Admin dark theme
- Apply the skill for: component design, color decisions, spacing, chart presentation, empty states, loading states, error states, and responsive layout
- Do not ship default/unstyled Vuestic components without applying design judgment from the skill

---

### 3. Component Reuse — Always Refer to an Existing Component First (PRD §5.16.0)
Before designing or coding any screen, element, or layout, **find an existing component and reuse it before building anything new.**

- **Look first**: check `frontend/src/components/` (StatusBadge, MetricCard, LogViewer, AlertRow, Charts, …) and the Vuestic UI library before creating anything
- **Reuse, don't recreate**: if a matching component exists, use it as-is — no duplicates
- **Extend, don't fork**: if close but not exact, extend via props/slots/variants so every caller benefits — never copy-paste a component to tweak it
- **Promote on the second use**: the moment a pattern is needed in a second place, extract it into a shared component in `frontend/src/components/` and reference it everywhere
- **Single source of truth**: status colors, spacing, typography, and chart config come from the shared component + theme tokens (PRD §5.16.2) — never hardcoded per page
- When the UI/UX Pro Max skill is invoked, it must first identify the reusable component(s) involved and reference them by name

---

### 4. Commit & Push When a Task or Phase Is Complete
The moment a task or phase is **done and verified working as expected** (smoke test passed, dashboard updated per Rule 0), **commit and push it** — never leave verified work uncommitted.

- Order of operations on completion: smoke test (Rule 1) → update PROGRESS.md + DASHBOARD.html (Rule 0) → **commit + push (this rule)**
- Commit the dashboard/progress update **in the same commit** as the work it tracks
- One logical unit per commit: a finished task or a finished phase — do not batch unrelated work
- Write a clear message describing what was completed and verified (reference the phase/task)
- `git push origin main` after committing so the remote always reflects the latest verified state
- **Never commit broken or unverified work** — if the smoke test did not pass, do not commit
- Never commit secrets — `.gitignore` already excludes `.env`, `*.pem`, `*.key`; do not force-add them

---

## Project Context

- **PRD**: `/Users/pocketdata/Code/Work/opspilot/PRD.md` (v2.5, locked)
- **Specs**: `/Users/pocketdata/Code/Work/opspilot/specs/` (01–11, all approved)
- **Stack**: Python 3.11 + FastAPI (backend), Vue 3 + Vuestic Admin + Pinia (frontend), PostgreSQL + TimescaleDB
- **Deployment**: Docker Compose (`migrate` → `backend` → `frontend` + `nginx` + `postgres`)
- **Phase plan**: Follow the 11-phase milestone order from PRD §10

## Key Decisions (Do Not Re-debate)
- `canEdit = isAdmin` — resource management is Admin only
- Alert auto-resolve: `consecutive_clear_count` persisted on Alert row, resolves at 2
- Maintenance mode entering immediately suppresses all firing/acked/snoozed alerts (`state = 'suppressed'`)
- Email format: `text/plain; charset=utf-8`, no HTML
- Log alert pattern matching: `ILIKE` (case-insensitive)
- Base URL fallback: `str(request.base_url)` from FastAPI Request if not configured
- 24h chart + live WS: update rightmost hour bucket client-side, do not re-fetch
- APScheduler uses SQLAlchemy job store — jobs persist across restarts
