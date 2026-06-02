#!/usr/bin/env python3
"""
Live dashboard server.
Run: python3 dashboard_server.py
Open: http://localhost:4999
Auto-reloads when PROGRESS.md changes.
"""

import json
import re
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT     = Path(__file__).parent
PROGRESS = ROOT / "PROGRESS.md"
PORT     = 4999

# ── Parse PROGRESS.md ────────────────────────────────────────────────────────

def parse_progress():
    text = PROGRESS.read_text(encoding="utf-8")
    phases, current = [], None
    for line in text.splitlines():
        ph = re.match(r"^## Phase (\d+) — (.+)$", line)
        if ph:
            if current:
                phases.append(current)
            current = {"id": int(ph.group(1)), "title": ph.group(2).strip(),
                       "subtitle": "", "tasks": []}
            continue
        if current and re.match(r"^\*.*\*$", line.strip()):
            current["subtitle"] = line.strip().strip("*")
            continue
        task = re.match(r"^- (✅|🔄|⬜|🚫) (.+)$", line)
        if task and current:
            icon, text = task.group(1), task.group(2).strip()
            status = {"✅": "done", "🔄": "inprogress", "⬜": "pending", "🚫": "blocked"}[icon]
            is_smoke = text.startswith("**Smoke test") or "SMOKE TEST" in text.upper()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            current["tasks"].append({"text": text, "status": status, "smoke": is_smoke})
    if current:
        phases.append(current)
    return phases

def compute_stats(phases):
    total = done = inprog = smoke_total = smoke_done = 0
    for p in phases:
        for t in p["tasks"]:
            total += 1
            if t["smoke"]:
                smoke_total += 1
            if t["status"] == "done":
                done += 1
                if t["smoke"]:
                    smoke_done += 1
            elif t["status"] == "inprogress":
                inprog += 1
    phases_done = sum(1 for p in phases if p["tasks"] and all(t["status"] == "done" for t in p["tasks"]))
    return {
        "total": total, "done": done, "inprog": inprog,
        "pending": total - done - inprog,
        "smoke_total": smoke_total, "smoke_done": smoke_done,
        "phases_done": phases_done,
        "pct": round(done / total * 100) if total else 0,
    }

def build_payload():
    phases = parse_progress()
    s = compute_stats(phases)
    return {"stats": s, "phases": phases, "today": date.today().strftime("%Y-%m-%d")}

# ── SSE client registry ───────────────────────────────────────────────────────

_clients      = []
_clients_lock = threading.Lock()

def register_client(wfile):
    with _clients_lock:
        _clients.append(wfile)

def unregister_client(wfile):
    with _clients_lock:
        if wfile in _clients:
            _clients.remove(wfile)

def notify_all():
    msg = b"data: refresh\n\n"
    dead = []
    with _clients_lock:
        for wfile in list(_clients):
            try:
                wfile.write(msg)
                wfile.flush()
            except Exception:
                dead.append(wfile)
        for wfile in dead:
            _clients.remove(wfile)

# ── File watcher ──────────────────────────────────────────────────────────────

def watch_file():
    last = 0.0
    while True:
        try:
            mtime = PROGRESS.stat().st_mtime
            if mtime != last:
                if last != 0.0:
                    notify_all()
                last = mtime
        except FileNotFoundError:
            pass
        time.sleep(0.8)

# ── HTML page ─────────────────────────────────────────────────────────────────

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpsPilot — Live Progress</title>
<style>
  :root{--bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2e3354;
    --accent:#6366f1;--accent2:#818cf8;--green:#22c55e;--amber:#f59e0b;
    --red:#ef4444;--blue:#3b82f6;--grey:#6b7280;--text:#e2e8f0;--muted:#94a3b8;--r:12px}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;padding:32px 24px}
  .header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:32px;flex-wrap:wrap;gap:16px}
  .header h1{font-size:24px;font-weight:700;letter-spacing:-.5px;color:#fff}
  .header p{color:var(--muted);margin-top:4px;font-size:13px}
  .badges{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .badge{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-size:12px;color:var(--muted)}
  .badge span{color:var(--accent2);font-weight:600}
  .live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:6px;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .overall{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px 28px;margin-bottom:28px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center}
  .label{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
  .bar-wrap{background:var(--surface2);border-radius:999px;height:10px;overflow:hidden;margin-bottom:8px}
  .bar{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:999px;transition:width .6s ease}
  .sub{font-size:12px;color:var(--muted)}
  .pct{font-size:42px;font-weight:800;color:#fff;letter-spacing:-2px;line-height:1;text-align:right}
  .pct span{font-size:20px;color:var(--muted);font-weight:400}
  .counts{font-size:12px;color:var(--muted);margin-top:4px;text-align:right}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}
  .stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px 18px}
  .stat .val{font-size:28px;font-weight:700;line-height:1;margin-bottom:4px}
  .stat .sub{font-size:12px;color:var(--muted)}
  .g{color:var(--green)}.a{color:var(--accent2)}.b{color:var(--blue)}.am{color:var(--amber)}
  .sec-title{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-bottom:32px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;transition:border-color .2s}
  .card:hover{border-color:var(--accent)}
  .card.done{border-color:rgba(34,197,94,.3)}
  .card.active{border-color:rgba(99,102,241,.4)}
  .card-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
  .card-title{font-size:13px;font-weight:600}
  .card-count{font-size:12px;color:var(--muted);margin-bottom:8px}
  .card-count b{color:var(--text)}
  .ph-bar-wrap{background:var(--surface2);border-radius:999px;height:6px;overflow:hidden;margin-bottom:12px}
  .ph-bar{height:100%;border-radius:999px;transition:width .6s ease}
  .card-sub{font-size:11px;color:var(--muted);margin-bottom:10px}
  ul{list-style:none}
  ul.hidden{display:none}
  li{display:flex;align-items:flex-start;gap:8px;padding:4px 0;font-size:12px;color:var(--muted);border-bottom:1px solid rgba(255,255,255,.04)}
  li:last-child{border-bottom:none}
  li.done{color:var(--text)}
  li.done .dot{color:var(--green)}
  li.inprogress{color:var(--accent2)}
  li.inprogress .dot{color:var(--amber)}
  li.smoke{color:var(--blue);font-style:italic}
  li.smoke.done{color:var(--green)}
  .dot{width:14px;flex-shrink:0;margin-top:1px;font-size:11px}
  .task-text{flex:1;line-height:1.4}
  .toggle{background:none;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:11px;padding:3px 10px;cursor:pointer;width:100%;margin-top:8px;transition:all .15s}
  .toggle:hover{border-color:var(--accent);color:var(--accent2)}
  .flash{animation:flash .5s ease}
  @keyframes flash{0%{background:rgba(99,102,241,.15)}100%{background:transparent}}
  footer{text-align:center;color:var(--muted);font-size:12px;margin-top:16px;padding-top:20px;border-top:1px solid var(--border)}
  @media(max-width:600px){.stats{grid-template-columns:repeat(2,1fr)}.overall{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>OpsPilot &mdash; Dev Progress</h1>
    <p id="sub-line">Loading…</p>
  </div>
  <div class="badges">
    <div class="badge"><span class="live-dot"></span>Live</div>
    <div class="badge">Updated: <span id="updated-at">—</span></div>
  </div>
</div>

<div class="overall">
  <div>
    <div class="label">Overall Progress</div>
    <div class="bar-wrap"><div class="bar" id="overall-bar" style="width:0%"></div></div>
    <div class="sub" id="overall-sub">—</div>
  </div>
  <div>
    <div class="pct" id="overall-pct">—<span>%</span></div>
    <div class="counts" id="overall-counts">—</div>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="label">Phases Done</div><div class="val g" id="s-phases">—</div><div class="sub">of 11 phases</div></div>
  <div class="stat"><div class="label">Tasks Complete</div><div class="val a" id="s-done">—</div><div class="sub" id="s-done-sub">of — total</div></div>
  <div class="stat"><div class="label">Smoke Tests</div><div class="val b" id="s-smoke">—</div><div class="sub" id="s-smoke-sub">of — gates</div></div>
  <div class="stat"><div class="label">In Progress</div><div class="val am" id="s-inprog">—</div><div class="sub">tasks active</div></div>
</div>

<div class="sec-title">Phases</div>
<div class="grid" id="grid"></div>

<footer>Source: PROGRESS.md &nbsp;&middot;&nbsp; <span class="live-dot" style="animation:pulse 2s infinite"></span> auto-updates on save</footer>

<script>
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

// Track which cards have their task list open
const openCards = new Set();

function tog(id, btn) {
  const l = document.getElementById('t' + id);
  l.classList.toggle('hidden');
  const open = !l.classList.contains('hidden');
  open ? openCards.add(id) : openCards.delete(id);
  btn.textContent = open ? '▲ Hide tasks' : '▼ Show tasks';
}

function render(data) {
  const s = data.stats;

  // Header
  document.getElementById('sub-line').textContent =
    `11 phases · ${s.total} tasks · Python + FastAPI + Vue 3 + TimescaleDB`;
  document.getElementById('updated-at').textContent = data.today;

  // Overall bar
  document.getElementById('overall-bar').style.width = s.pct + '%';
  document.getElementById('overall-sub').textContent = `${s.done} of ${s.total} tasks completed`;
  document.getElementById('overall-pct').innerHTML = s.pct + '<span>%</span>';
  document.getElementById('overall-counts').textContent =
    `${s.done} done · ${s.inprog} in progress · ${s.pending} pending`;

  // Stat cards
  document.getElementById('s-phases').textContent  = s.phases_done;
  document.getElementById('s-done').textContent    = s.done;
  document.getElementById('s-done-sub').textContent = `of ${s.total} total`;
  document.getElementById('s-smoke').textContent   = s.smoke_done;
  document.getElementById('s-smoke-sub').textContent = `of ${s.smoke_total} gates`;
  document.getElementById('s-inprog').textContent  = s.inprog;

  // Phase cards
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  data.phases.forEach(p => {
    const done = p.tasks.filter(t => t.status === 'done').length;
    const inp  = p.tasks.filter(t => t.status === 'inprogress').length;
    const tot  = p.tasks.length;
    const pct  = tot ? Math.round(done / tot * 100) : 0;
    const isDone   = tot > 0 && done === tot;
    const isActive = inp > 0 || (done > 0 && !isDone);
    const barColor = isDone ? 'var(--green)' : isActive ? 'var(--accent)' : 'var(--grey)';
    const statusEl = isDone
      ? '<span style="color:var(--green);font-size:11px;font-weight:600;">✓ COMPLETE</span>'
      : isActive
      ? '<span style="color:var(--accent2);font-size:11px;font-weight:600;">● ACTIVE</span>'
      : '<span style="color:var(--grey);font-size:11px;">PENDING</span>';

    const tasksHtml = p.tasks.map(t => {
      const cls = t.status === 'done' ? 'done' : t.status === 'inprogress' ? 'inprogress' : '';
      const sc  = t.smoke ? ' smoke' : '';
      const dot = t.status === 'done' ? '✓' : t.status === 'inprogress' ? '●' : '○';
      return `<li class="${cls}${sc}"><span class="dot">${dot}</span><span class="task-text">${esc(t.text)}</span></li>`;
    }).join('');

    const isOpen   = openCards.has(p.id);
    const listCls  = isOpen ? '' : ' hidden';
    const btnLabel = isOpen ? '▲ Hide tasks' : '▼ Show tasks';

    const card = document.createElement('div');
    card.className = 'card' + (isDone ? ' done' : isActive ? ' active' : '') + ' flash';
    card.innerHTML = `
      <div class="card-hd"><div class="card-title">Phase ${p.id} — ${esc(p.title)}</div>${statusEl}</div>
      <div class="card-count"><b>${done}</b> / ${tot} tasks · ${pct}%</div>
      <div class="ph-bar-wrap"><div class="ph-bar" style="width:${pct}%;background:${barColor}"></div></div>
      <div class="card-sub">${esc(p.subtitle)}</div>
      <ul class="${listCls}" id="t${p.id}">${tasksHtml}</ul>
      <button class="toggle" onclick="tog(${p.id},this)">${btnLabel}</button>`;
    grid.appendChild(card);
  });
}

async function refresh() {
  try {
    const res = await fetch('/data.json');
    if (!res.ok) return;
    render(await res.json());
  } catch (e) { /* server restarting */ }
}

// Initial load
refresh();

// SSE for live updates
(function connect() {
  const es = new EventSource('/events');
  es.onmessage = () => refresh();
  es.onerror   = () => { es.close(); setTimeout(connect, 2000); };
})();
</script>
</body>
</html>"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress per-request logs

    def do_GET(self):
        if self.path == "/":
            self._respond(200, "text/html; charset=utf-8", PAGE.encode())
        elif self.path == "/data.json":
            try:
                payload = json.dumps(build_payload(), ensure_ascii=False).encode()
                self._respond(200, "application/json", payload)
            except Exception as e:
                self._respond(500, "text/plain", str(e).encode())
        elif self.path == "/events":
            self._sse()
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        register_client(self.wfile)
        try:
            while True:
                time.sleep(30)  # keepalive heartbeat
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            unregister_client(self.wfile)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=watch_file, daemon=True)
    t.start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"✓ Dashboard live at http://localhost:{PORT}")
    print(f"  Watching: {PROGRESS}")
    print("  Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
