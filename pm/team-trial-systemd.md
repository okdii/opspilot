# Agent Team Trial — Phase 1 Onboarding "Complete" Blocker

> **First trial of Claude Code agent teams on OpsPilot.**
> Goal: a bounded, parallel, competing-hypotheses investigation that unblocks the
> 3 stuck Phase 1 tasks. Low risk — investigation + a recommended fix, not a big build.

## How to run it

1. **Quit and relaunch Claude Code** from `/Users/pocketdata/Code/Work/opspilot`
   (the `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` flag only loads at startup).
2. *(Optional, for split panes)* launch inside tmux first, e.g. `tmux` then `claude`,
   so each teammate gets its own pane. Otherwise it runs in-process — cycle teammates
   with **Shift+Down**.
3. Paste the prompt below.

---

## The prompt (copy from here)

```
Create an agent team to investigate the Phase 1 onboarding "complete" blocker.

CONTEXT:
- OpsPilot onboards Linux servers over SSH and auto-deploys Telegraf + Fluent Bit,
  then runs `systemctl enable --now` to start the agents (see
  backend/app/services/onboarding.py, the 10-step orchestrator).
- The success path is unverifiable because our test target, the `ssh-target`
  container (test-target/Dockerfile), runs sshd as PID 1 — NOT systemd. So
  `systemctl enable --now` fails at step 9, and steps "wait for first metric row"
  and "mark server active / push onboarding_complete" never run.
- This blocks 3 tasks in pm/PROGRESS.md (Phase 1, the two ⬜ onboarding lines and
  the onboarding smoke test).
- We DO have a Lima Ubuntu LTS VM running on this machine (from earlier this session),
  reachable over SSH on a fixed port (2222).

TASK:
Spawn 3 teammates, each owning one competing hypothesis for the cleanest fix.
Have them investigate in parallel, then message each other to challenge each
other's approach like a scientific debate, and converge on a single recommendation.

- Teammate "lima": prove out using the existing Lima Ubuntu systemd VM as the
  onboarding test target. Can onboarding SSH into it, install the agents, and
  reach `systemctl enable --now` success + first metric row? What config/wiring
  changes are needed?
- Teammate "container": make the test-target container systemd-capable
  (systemd as PID 1, e.g. an init-enabled base image / privileged + cgroup mount).
  What are the tradeoffs and CI implications?
- Teammate "tolerant": make the onboarding verify-step tolerant of non-systemd
  targets (detect init system; fall back to direct process start / nohup) so the
  "complete" path can succeed without systemd at all. Is this a hack or legitimate?

CONSTRAINTS / CRITERIA FOR THE LEAD:
- Read-only investigation first — do NOT change application code or onboarding logic
  until we agree on the approach. Reading files, inspecting containers, and running
  the VM/containers to observe behavior is fine.
- Follow CLAUDE.md (smoke-test discipline; commit+push only verified work).
- The winning recommendation must explain how it makes the onboarding SMOKE TEST
  in PROGRESS.md pass (add server → watch onboarding complete → see first metric in DB).
- Output: a short written recommendation (which hypothesis wins + why + the concrete
  next steps), posted back to me. Wait for all 3 teammates to finish before concluding.
```

---

## After the team converges

- The team should hand you a recommended fix (likely the Lima VM, since it already
  exists and is genuinely systemd-capable — but let the debate decide).
- Implement the agreed fix in a **single session** (or assign it to one teammate),
  run the onboarding smoke test, and only then flip the 3 ⬜ → ✅ in `PROGRESS.md`
  + `DASHBOARD.html`, then commit + push per CLAUDE.md Rule 4.

## Cleanup (important)

When done: tell the lead **"Clean up the team"** (not a teammate — only the lead can
clean up safely). If you used tmux and a session lingers: `tmux ls` then
`tmux kill-session -t <name>`.
```
