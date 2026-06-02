# Spec 12 — AI Chat Agent

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

Phase 12 adds an AI-powered chat interface to OpsPilot that allows admins to manage servers using natural language. The AI understands requests, reads live server data from OpsPilot's existing data stores, proposes shell commands, and executes them via SSH after explicit admin approval.

**Core principle:** The LLM is the brain (understands intent, decides what command to run, interprets output). Paramiko is the hands (executes commands on the server). The admin is the gate (nothing runs without an explicit Approve click).

The LLM never touches a server directly. Flow: **You → Backend → LLM → Backend → You (approval) → Backend → Paramiko → Backend → LLM → You**.

---

## 2. Decisions

| Decision | Choice |
|---|---|
| Command scope | Full admin — arbitrary shell commands |
| Approval flow | Always confirm — every `run_ssh_command` requires explicit admin approval |
| AI provider | Configurable — Anthropic / OpenAI / Google Gemini, set in Settings |
| Server data access | Hybrid — AI reads OpsPilot DB data (metrics, alerts, logs) AND can SSH |
| Chat scope | Per-server — each session is tied to one server |
| History | Persistent + auditable — all sessions, messages, command executions saved in DB |
| Execution transport | Paramiko (already in stack) — no new SSH infrastructure |
| Access control | Admin only — same as all write operations in OpsPilot |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  BROWSER (Vue 3)                    │
│  Server Detail Page → AI Assistant tab              │
│  ├── Sessions sidebar                               │
│  ├── Message thread (streaming via SSE)             │
│  └── Command Approval Card                          │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP + SSE
┌──────────────────▼──────────────────────────────────┐
│                FastAPI Backend                      │
│  routers/chat.py                                    │
│  services/ai/                                       │
│  ├── provider.py   (Anthropic / OpenAI / Gemini)    │
│  ├── tools.py      (5 tool functions)               │
│  └── executor.py   (approval gate + Paramiko exec)  │
└──────────┬───────────────────┬──────────────────────┘
           │                   │
    ┌──────▼──────┐    ┌───────▼──────┐
    │ PostgreSQL  │    │  Monitored   │
    │ + TimescaleDB    │  Server      │
    │ + new chat  │    │  (Paramiko   │
    │   tables    │    │   SSH)       │
    └─────────────┘    └──────────────┘
```

**New files:**
- `backend/app/routers/chat.py`
- `backend/app/services/ai/__init__.py`
- `backend/app/services/ai/provider.py`
- `backend/app/services/ai/tools.py`
- `backend/app/services/ai/executor.py`
- `backend/app/migrations/versions/xxxx_add_chat_tables.py`
- `frontend/src/pages/server/ServerAIChat.vue`
- `frontend/src/stores/chat.ts`

---

## 4. Data Models

### 4.1 ChatSession
```
id          UUID PK
server_id   FK → Server (not null)
user_id     FK → User (not null)
title       TEXT (auto-generated from first user message)
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ
deleted_at  TIMESTAMPTZ (soft delete — preserves audit trail)
```

### 4.2 ChatMessage
```
id           UUID PK
session_id   FK → ChatSession
role         TEXT  'user' | 'assistant' | 'tool_result'
content      TEXT  (visible message text)
tool_calls   JSONB (raw tool call payload from LLM, nullable)
created_at   TIMESTAMPTZ
```

### 4.3 CommandExecution
```
id           UUID PK
session_id   FK → ChatSession
message_id   FK → ChatMessage
command      TEXT  (exact shell command the AI wants to run)
output       TEXT  (stdout + stderr, max 50KB, populated after execution)
status       TEXT  'pending' | 'approved' | 'rejected' | 'executed' | 'failed'
approved_by  FK → User (nullable)
approved_at  TIMESTAMPTZ (nullable)
executed_at  TIMESTAMPTZ (nullable)
created_at   TIMESTAMPTZ
```

### 4.4 Settings additions (existing key/value table)
| Key | Encrypted | Example value |
|---|---|---|
| `ai_provider` | No | `anthropic` |
| `ai_model` | No | `claude-sonnet-4-6` |
| `ai_api_key` | Yes (AES-256) | `sk-ant-...` |

---

## 5. Tool Set

The AI has access to exactly 5 tools. Tools 1–4 are instant read-only. Tool 5 always triggers the approval gate.

### Tool 1: `get_server_summary`
- **Reads:** Server table — name, IP, OS, tags, online status, last_seen
- **Returns:** Structured server profile
- **Approval required:** No

### Tool 2: `get_active_alerts`
- **Reads:** Alert table — all firing/acked/snoozed alerts for this server
- **Returns:** List of current alerts with severity and message
- **Approval required:** No

### Tool 3: `get_metrics_snapshot`
- **Input:** `metric` (`cpu` | `ram` | `disk` | `all`)
- **Reads:** TimescaleDB metrics hypertable — latest value + 1h rolling average
- **Returns:** Current metric values with context
- **Approval required:** No

### Tool 4: `get_recent_logs`
- **Input:** `source` (`nginx` | `auth` | `app` | `all`), `limit` (default 50)
- **Reads:** server_logs hypertable
- **Returns:** Last N log lines as structured JSON
- **Approval required:** No

### Tool 5: `run_ssh_command`
- **Input:** `command` (TEXT), `reason` (TEXT — why the AI wants to run this)
- **On call:**
  1. Does NOT execute immediately
  2. Creates `CommandExecution` row (status: `pending`)
  3. Pauses the AI turn
  4. Sends `approval_required` SSE event to frontend
  5. Waits for admin to approve or reject
- **On approve:** Paramiko SSH exec → captures stdout + stderr (max 50KB) → updates `CommandExecution` (status: `executed`) → result fed back to LLM to continue response
- **On reject:** LLM receives rejection, acknowledges it and may suggest a safer alternative
- **Auto-reject:** Background job rejects any `pending` execution older than 10 minutes
- **Execution timeout:** 60 seconds per command (Paramiko kills channel on exceed)

---

## 6. AI Provider Abstraction

`backend/app/services/ai/provider.py` — single interface, three implementations.

```python
class BaseAIProvider:
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        stream: bool = True
    ) -> AsyncIterator[ChatEvent]: ...

class AnthropicProvider(BaseAIProvider): ...  # claude-sonnet-4-6, claude-opus-4-8, claude-haiku-4-5
class OpenAIProvider(BaseAIProvider):    ...  # gpt-4o, gpt-4o-mini, o3-mini
class GeminiProvider(BaseAIProvider):   ...  # gemini-2.0-flash, gemini-2.0-pro

def get_provider() -> BaseAIProvider:
    # reads ai_provider, ai_model, ai_api_key from Settings at runtime
    # decrypts ai_api_key in memory — never logged or returned
```

### System Prompt (per session, server context injected)
```
You are an operations assistant for OpsPilot, managing server "{server_name}"
({ip_address}, {os}). You have access to this server's metrics, alerts, logs,
and can run shell commands with user approval.

Rules:
- Always read available data (tools 1-4) before proposing commands
- Always set a clear "reason" when calling run_ssh_command
- Prefer non-destructive diagnosis before remediation commands
- Never chain multiple destructive commands in one turn
- If a command is rejected, acknowledge it and suggest a safer alternative
```

---

## 7. API Endpoints

All endpoints require `isAdmin`. `server_id` validated against session ownership on every request.

### Session Management
```
POST   /api/servers/{server_id}/chat/sessions
         Body:    {}
         Returns: ChatSession

GET    /api/servers/{server_id}/chat/sessions
         Returns: ChatSession[] (newest first)

GET    /api/servers/{server_id}/chat/sessions/{session_id}
         Returns: ChatSession + ChatMessage[] (full history)

DELETE /api/servers/{server_id}/chat/sessions/{session_id}
         Soft delete (deleted_at set) — CommandExecution rows retained for audit
```

### Chat (main endpoint)
```
POST   /api/servers/{server_id}/chat/sessions/{session_id}/messages
         Body:    { "content": "why is CPU so high?" }
         Returns: SSE stream
           event: token              {"delta": "Let me check..."}
           event: tool_call          {"tool": "get_metrics_snapshot", "args": {...}}
           event: tool_result        {"tool": "get_metrics_snapshot", "result": {...}}
           event: approval_required  {"execution_id": "uuid", "command": "ps aux",
                                      "reason": "identify top CPU processes"}
           event: done               {"message_id": "uuid"}
```

### Command Approval
```
POST   /api/chat/executions/{execution_id}/approve
         Returns: SSE stream — execution output streams back, then AI continues

POST   /api/chat/executions/{execution_id}/reject
         Body:    { "reason": "optional note" }
         Returns: 200
```

### Settings Test
```
POST   /api/settings/ai/test
         Sends a single-turn "Hello" to configured provider
         Returns: { "ok": true } or { "ok": false, "error": "..." }
```

### Full Approval Flow Example
```
User: "why is CPU so high?"
→ LLM calls get_metrics_snapshot     → reads TimescaleDB → CPU 94%, 1h avg 87%
→ LLM calls run_ssh_command(
    command: "ps aux --sort=-%cpu | head -20",
    reason:  "identify top CPU-consuming processes"
  )
→ Backend: creates CommandExecution (pending), fires approval_required SSE, pauses
→ Admin clicks Approve
→ Backend: Paramiko executes, streams stdout back via SSE
→ LLM: "java (PID 3847) is consuming 89% CPU. Looks like a runaway JVM.
         Want me to check its startup flags or restart it?"
```

---

## 8. Frontend

### Route
`/servers/{server_id}/chat` — rendered as a new tab on the Server Detail page

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│  web-01  ·  192.168.1.10  ·  Ubuntu 22.04  ●  Online        │
│  [Dashboard] [Logs] [Services] [Database] [AI Assistant]    │
├──────────────────────┬──────────────────────────────────────┤
│  SESSIONS            │  CHAT PANEL                          │
│                      │                                      │
│  [+ New Chat]        │   why is CPU so high?          [You] │
│  ─────────────────   │  ─────────────────────────────────── │
│  ● Check disk 2h     │   [AI] CPU is at 94%.                │
│    Restart nginx     │   Let me check processes...          │
│    Install php8      │  ─────────────────────────────────── │
│                      │  ┌─ Command Approval ──────────────┐ │
│                      │  │  $ ps aux --sort=-%cpu | head   │ │
│                      │  │  Reason: identify top CPU procs │ │
│                      │  │  [ ✓ Approve ]  [ ✗ Reject ]   │ │
│                      │  └─────────────────────────────────┘ │
│                      │  ─────────────────────────────────── │
│                      │  [ Ask anything about web-01...  → ] │
└──────────────────────┴──────────────────────────────────────┘
```

### Message Types
| Type | Render |
|---|---|
| User message | Right-aligned bubble, accent colour |
| AI text (streaming) | Left-aligned, tokens appear live |
| Tool call (read) | Inline chip: `🔍 Reading metrics...` |
| Command approval card | Bordered card — monospace command + reason, Approve + Reject buttons |
| Command output | Collapsible terminal block (dark bg, monospace) |
| Error | Red inline notice |

### Pinia Store (`useChatStore`)
- `sessions[]` — sidebar list
- `activeSession` — current session + messages
- `pendingExecution` — CommandExecution awaiting approval (nullable)
- `streaming` — boolean

**Input field disabled when:** `streaming === true` OR `pendingExecution !== null`

### Unconfigured State
If `ai_provider` setting is absent, the AI Assistant tab shows:
> *"AI Assistant is not configured. Go to Settings → AI Assistant to set it up."*

---

## 9. Settings Page Extension

New **AI Assistant** section added to existing Settings page (Phase 10 pattern):

```
AI Assistant
├── Provider    [ Anthropic ▼ ]         (Anthropic / OpenAI / Google Gemini)
├── Model       [ claude-sonnet-4-6  ]
├── API Key     [ ••••••••••••••  👁 ]
└──             [ Test Connection ]  [ Save ]
```

**Test Connection** fires `POST /api/settings/ai/test` — sends a minimal "Hello" to the configured provider and surfaces the result inline.

---

## 10. Security

| Concern | Mitigation |
|---|---|
| Unauthorised access | All chat endpoints require `isAdmin` |
| Cross-server session access | `server_id` validated against session on every request |
| Runaway command output | Truncated at 50KB before DB storage and LLM injection |
| Long-running commands | 60-second Paramiko execution timeout |
| Stale pending approvals | Background job auto-rejects executions pending > 10 minutes |
| API key exposure | AES-256 encrypted at rest; never returned in API responses; never logged |
| SSH credential exposure | Existing AES-256 encryption unchanged — Paramiko uses decrypted key in memory only |

---

## 11. Error Handling

| Scenario | Behaviour |
|---|---|
| Invalid AI API key | Chat message: *"AI provider returned auth error. Check Settings → AI Assistant."* |
| Provider timeout / 503 | Retry once, then surface error in chat — session remains intact |
| SSH command non-zero exit | stderr captured and fed to LLM — AI explains the error and suggests a fix |
| SSH connection lost mid-command | Paramiko exception caught, `CommandExecution.status → 'failed'`, LLM informed |
| LLM context window exceeded | Oldest tool results trimmed from history, warning logged |

---

## 12. Audit Trail

The following is permanently queryable per server:
- All chat sessions and when they were created
- Every message exchanged (user and AI), including raw tool call payloads
- Every command the AI proposed (approved or rejected)
- Who approved each command and when
- Exact output of every executed command

---

## 13. Implementation Sub-phases

| Sub-phase | Scope |
|---|---|
| 12A | Alembic migration (3 tables + 3 settings keys), `services/ai/` layer (provider abstraction + 5 tools + executor), `routers/chat.py`, SSE streaming, auto-reject background job |
| 12B | Settings page AI Assistant section + Test Connection endpoint |
| 12C | Frontend — `ServerAIChat.vue`, `useChatStore`, command approval card, sessions sidebar, AI Assistant tab on Server Detail page |

---

## 14. Out of Scope

- Multi-server chat (per-server only)
- Non-admin user access to chat
- Voice input
- Scheduled or autonomous AI actions (no unsupervised execution)
- Custom tool plugins
