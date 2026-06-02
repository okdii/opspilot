#!/usr/bin/env python3
"""
Reads PROGRESS.md and regenerates DASHBOARD.html.
Run: python3 generate_dashboard.py
"""

import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
PROGRESS = ROOT / "PROGRESS.md"
OUTPUT   = ROOT / "DASHBOARD.html"

# ── Parse PROGRESS.md ────────────────────────────────────────────

def parse_progress():
    text = PROGRESS.read_text(encoding="utf-8")
    phases = []
    current_phase = None

    for line in text.splitlines():
        # Phase header: ## Phase 1 — Foundation
        ph = re.match(r"^## Phase (\d+) — (.+)$", line)
        if ph:
            if current_phase:
                phases.append(current_phase)
            current_phase = {
                "id": int(ph.group(1)),
                "title": ph.group(2).strip(),
                "subtitle": "",
                "tasks": [],
            }
            continue

        # Subtitle line (italic *text* under phase header)
        if current_phase and re.match(r"^\*.*\*$", line.strip()):
            current_phase["subtitle"] = line.strip().strip("*")
            continue

        # Task line: - ✅ / 🔄 / ⬜ / 🚫
        task = re.match(r"^- (✅|🔄|⬜|🚫) (.+)$", line)
        if task and current_phase:
            icon, text = task.group(1), task.group(2).strip()
            status = {"✅": "done", "🔄": "inprogress", "⬜": "pending", "🚫": "blocked"}[icon]
            is_smoke = text.startswith("**Smoke test") or "SMOKE TEST" in text.upper()
            # Clean bold markers
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            current_phase["tasks"].append({"text": text, "status": status, "smoke": is_smoke})

    if current_phase:
        phases.append(current_phase)

    return phases

# ── Compute stats ─────────────────────────────────────────────────

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
    phases_done = sum(1 for p in phases if all(t["status"] == "done" for t in p["tasks"]))
    return {
        "total": total, "done": done, "inprog": inprog,
        "pending": total - done - inprog,
        "smoke_total": smoke_total, "smoke_done": smoke_done,
        "phases_done": phases_done,
        "pct": round(done / total * 100) if total else 0,
    }

# ── Build phase cards JS data ─────────────────────────────────────

def phases_to_js(phases):
    lines = ["const phases = ["]
    for p in phases:
        lines.append(f"  {{ id: {p['id']}, title: {json_str(p['title'])}, subtitle: {json_str(p['subtitle'])}, tasks: [")
        for t in p["tasks"]:
            smoke = "true" if t["smoke"] else "false"
            lines.append(f"    {{ text: {json_str(t['text'])}, status: {json_str(t['status'])}, smoke: {smoke} }},")
        lines.append("  ]},")
    lines.append("];")
    return "\n".join(lines)

def json_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

# ── HTML template ─────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpsPilot — Dev Progress</title>
<style>
  :root {{
    --bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2e3354;
    --accent:#6366f1;--accent2:#818cf8;--green:#22c55e;--amber:#f59e0b;
    --red:#ef4444;--blue:#3b82f6;--grey:#6b7280;--text:#e2e8f0;--muted:#94a3b8;
    --r:12px;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;padding:32px 24px}}
  .header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:32px;flex-wrap:wrap;gap:16px}}
  .header h1{{font-size:24px;font-weight:700;letter-spacing:-.5px;color:#fff}}
  .header p{{color:var(--muted);margin-top:4px;font-size:13px}}
  .badge{{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-size:12px;color:var(--muted)}}
  .badge span{{color:var(--accent2);font-weight:600}}
  .overall{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px 28px;margin-bottom:28px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center}}
  .label{{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}}
  .bar-wrap{{background:var(--surface2);border-radius:999px;height:10px;overflow:hidden;margin-bottom:8px}}
  .bar{{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:999px}}
  .sub{{font-size:12px;color:var(--muted)}}
  .pct{{font-size:42px;font-weight:800;color:#fff;letter-spacing:-2px;line-height:1;text-align:right}}
  .pct span{{font-size:20px;color:var(--muted);font-weight:400}}
  .counts{{font-size:12px;color:var(--muted);margin-top:4px;text-align:right}}
  .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px 18px}}
  .stat .val{{font-size:28px;font-weight:700;line-height:1;margin-bottom:4px}}
  .stat .sub{{font-size:12px;color:var(--muted)}}
  .g{{color:var(--green)}}.a{{color:var(--accent2)}}.b{{color:var(--blue)}}.am{{color:var(--amber)}}
  .sec-title{{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-bottom:32px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;transition:border-color .2s}}
  .card:hover{{border-color:var(--accent)}}
  .card.done{{border-color:rgba(34,197,94,.3)}}
  .card.active{{border-color:rgba(99,102,241,.4)}}
  .card-hd{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
  .card-title{{font-size:13px;font-weight:600}}
  .card-count{{font-size:12px;color:var(--muted);margin-bottom:8px}}
  .card-count b{{color:var(--text)}}
  .ph-bar-wrap{{background:var(--surface2);border-radius:999px;height:6px;overflow:hidden;margin-bottom:12px}}
  .ph-bar{{height:100%;border-radius:999px}}
  .card-sub{{font-size:11px;color:var(--muted);margin-bottom:10px}}
  ul{{list-style:none}}
  ul.hidden{{display:none}}
  li{{display:flex;align-items:flex-start;gap:8px;padding:4px 0;font-size:12px;color:var(--muted);border-bottom:1px solid rgba(255,255,255,.04)}}
  li:last-child{{border-bottom:none}}
  li.done{{color:var(--text)}}
  li.done .dot{{color:var(--green)}}
  li.inprogress{{color:var(--accent2)}}
  li.inprogress .dot{{color:var(--amber)}}
  li.smoke{{color:var(--blue);font-style:italic}}
  li.smoke.done{{color:var(--green)}}
  .dot{{width:14px;flex-shrink:0;margin-top:1px;font-size:11px}}
  .task-text{{flex:1;line-height:1.4}}
  .toggle{{background:none;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:11px;padding:3px 10px;cursor:pointer;width:100%;margin-top:8px;transition:all .15s}}
  .toggle:hover{{border-color:var(--accent);color:var(--accent2)}}
  footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:16px;padding-top:20px;border-top:1px solid var(--border)}}
  @media(max-width:600px){{.stats{{grid-template-columns:repeat(2,1fr)}}.overall{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="header">
  <div><h1>OpsPilot &mdash; Dev Progress</h1><p>11 phases &middot; {total} tasks &middot; Python + FastAPI + Vue 3 + TimescaleDB</p></div>
  <div class="badge">Generated: <span>{today}</span></div>
</div>
<div class="overall">
  <div>
    <div class="label">Overall Progress</div>
    <div class="bar-wrap"><div class="bar" style="width:{pct}%"></div></div>
    <div class="sub">{done} of {total} tasks completed</div>
  </div>
  <div>
    <div class="pct">{pct}<span>%</span></div>
    <div class="counts">{done} done &middot; {inprog} in progress &middot; {pending} pending</div>
  </div>
</div>
<div class="stats">
  <div class="stat"><div class="label">Phases Done</div><div class="val g">{phases_done}</div><div class="sub">of 11 phases</div></div>
  <div class="stat"><div class="label">Tasks Complete</div><div class="val a">{done}</div><div class="sub">of {total} total</div></div>
  <div class="stat"><div class="label">Smoke Tests Passed</div><div class="val b">{smoke_done}</div><div class="sub">of {smoke_total} gates</div></div>
  <div class="stat"><div class="label">In Progress</div><div class="val am">{inprog}</div><div class="sub">tasks active</div></div>
</div>
<div class="sec-title">Phases</div>
<div class="grid" id="grid"></div>
<footer>Source: PROGRESS.md &nbsp;&middot;&nbsp; Regenerate: <code>python3 generate_dashboard.py</code></footer>
<script>
{phases_js}

const grid = document.getElementById('grid');
phases.forEach(p => {{
  const done = p.tasks.filter(t=>t.status==='done').length;
  const inp  = p.tasks.filter(t=>t.status==='inprogress').length;
  const tot  = p.tasks.length;
  const pct  = Math.round(done/tot*100);
  const isDone   = done===tot;
  const isActive = inp>0||(done>0&&!isDone);
  const barColor = isDone?'var(--green)':isActive?'var(--accent)':'var(--grey)';
  const statusEl = isDone
    ? '<span style="color:var(--green);font-size:11px;font-weight:600;">✓ COMPLETE</span>'
    : isActive
    ? '<span style="color:var(--accent2);font-size:11px;font-weight:600;">● ACTIVE</span>'
    : '<span style="color:var(--grey);font-size:11px;">PENDING</span>';
  const tasksHtml = p.tasks.map(t=>{{
    const cls = t.status==='done'?'done':t.status==='inprogress'?'inprogress':'';
    const sc  = t.smoke?' smoke':'';
    const dot = t.status==='done'?'✓':t.status==='inprogress'?'●':'○';
    return `<li class="${{cls}}${{sc}}"><span class="dot">${{dot}}</span><span class="task-text">${{t.text}}</span></li>`;
  }}).join('');
  const card = document.createElement('div');
  card.className='card'+(isDone?' done':isActive?' active':'');
  card.innerHTML=`
    <div class="card-hd"><div class="card-title">Phase ${{p.id}} — ${{p.title}}</div>${{statusEl}}</div>
    <div class="card-count"><b>${{done}}</b> / ${{tot}} tasks &middot; ${{pct}}%</div>
    <div class="ph-bar-wrap"><div class="ph-bar" style="width:${{pct}}%;background:${{barColor}}"></div></div>
    <div class="card-sub">${{p.subtitle}}</div>
    <ul class="hidden" id="t${{p.id}}">${{tasksHtml}}</ul>
    <button class="toggle" onclick="tog(${{p.id}},this)">▼ Show tasks</button>`;
  grid.appendChild(card);
}});
function tog(id,btn){{const l=document.getElementById('t'+id);l.classList.toggle('hidden');btn.textContent=l.classList.contains('hidden')?'▼ Show tasks':'▲ Hide tasks';}}
</script>
</body>
</html>"""

# ── Generate ──────────────────────────────────────────────────────

def generate():
    phases = parse_progress()
    s = compute_stats(phases)
    js = phases_to_js(phases)

    html = HTML.format(
        today        = date.today().strftime("%Y-%m-%d"),
        total        = s["total"],
        done         = s["done"],
        inprog       = s["inprog"],
        pending      = s["pending"],
        pct          = s["pct"],
        phases_done  = s["phases_done"],
        smoke_done   = s["smoke_done"],
        smoke_total  = s["smoke_total"],
        phases_js    = js,
    )

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"✓ DASHBOARD.html generated — {s['done']}/{s['total']} tasks done ({s['pct']}%)")

if __name__ == "__main__":
    generate()
