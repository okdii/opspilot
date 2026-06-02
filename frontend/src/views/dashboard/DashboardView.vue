<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'

const auth = useAuthStore()
const orgStore = useOrgStore()
</script>

<template>
  <div class="page">
    <header class="hdr">
      <h1>Dashboard</h1>
      <p>Welcome back, {{ auth.user?.username }}</p>
    </header>

    <!-- Admin with no orgs: setup flow -->
    <div v-if="orgStore.orgs.length === 0 && auth.isAdmin" class="center-wrap">
      <div class="setup-card">
        <div class="setup-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>
            <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>
            <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>
            <path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>
          </svg>
        </div>
        <h2>Welcome to OpsPilot</h2>
        <p class="desc">Create your first organization to start monitoring your infrastructure.</p>

        <div class="steps">
          <div class="step step-active">
            <span class="step-n">1</span>
            <div class="step-text">
              <strong>Create an organization</strong>
              <small>Group servers and team members under a shared workspace</small>
            </div>
          </div>
          <div class="step step-dim">
            <span class="step-n dim">2</span>
            <div class="step-text dim">
              <strong>Add servers</strong>
              <small>Connect infrastructure via SSH to begin monitoring</small>
            </div>
          </div>
          <div class="step step-dim">
            <span class="step-n dim">3</span>
            <div class="step-text dim">
              <strong>Configure alerts</strong>
              <small>Get notified when something needs your attention</small>
            </div>
          </div>
        </div>

        <router-link to="/organizations" class="cta">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Create Organization
        </router-link>
      </div>
    </div>

    <!-- Non-admin with no orgs -->
    <div v-else-if="orgStore.orgs.length === 0" class="center-wrap">
      <div class="setup-card">
        <div class="setup-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
        </div>
        <h2>No organization yet</h2>
        <p class="desc">Ask your administrator to set up an organization and invite you to it.</p>
      </div>
    </div>

    <!-- Has orgs — Phase 2 placeholder -->
    <div v-else>
      <div class="stat-row">
        <div class="stat-tile">
          <div class="stat-icon-wrap purple">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>
              <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>
              <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>
            </svg>
          </div>
          <div>
            <div class="stat-val">{{ orgStore.orgs.length }}</div>
            <div class="stat-lbl">Organizations</div>
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-icon-wrap blue">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/>
              <line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>
            </svg>
          </div>
          <div>
            <div class="stat-val">—</div>
            <div class="stat-lbl">Servers</div>
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-icon-wrap amber">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
          </div>
          <div>
            <div class="stat-val">—</div>
            <div class="stat-lbl">Active Alerts</div>
          </div>
        </div>
      </div>

      <div class="coming-card">
        <div class="coming-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div class="coming-body">
          <h3>Real-time dashboard — Phase 2</h3>
          <p>Live metrics, CPU &amp; memory charts, and alert feeds will appear here. For now, manage your servers and organizations below.</p>
          <div class="coming-actions">
            <router-link to="/servers" class="btn-primary">View Servers</router-link>
            <router-link v-if="auth.isAdmin" to="/organizations" class="btn-ghost">Organizations</router-link>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.hdr h1 { font-size: 22px; color: #fff; letter-spacing: -0.3px; }
.hdr p { color: var(--muted); font-size: 13px; margin-top: 4px; margin-bottom: 28px; }

/* Empty / setup states */
.center-wrap { display: flex; justify-content: center; padding: 48px 20px; }
.setup-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 36px 40px; max-width: 440px; width: 100%; text-align: center; }
.setup-icon { width: 56px; height: 56px; background: rgba(99,102,241,0.12); border: 1px solid rgba(99,102,241,0.25); border-radius: 14px; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; color: var(--accent-2); }
.setup-card h2 { font-size: 17px; color: #fff; margin-bottom: 8px; letter-spacing: -0.2px; }
.setup-card .desc { color: var(--muted); font-size: 13px; line-height: 1.6; margin-bottom: 24px; }

/* Steps */
.steps { display: flex; flex-direction: column; margin-bottom: 24px; text-align: left; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.step { display: flex; align-items: flex-start; gap: 12px; padding: 13px 16px; border-bottom: 1px solid var(--border); }
.step:last-child { border-bottom: none; }
.step-active { background: rgba(99,102,241,0.07); }
.step-n { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
.step-n.dim { background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); }
.step-text strong { display: block; font-size: 13px; color: #fff; font-weight: 500; margin-bottom: 2px; }
.step-text.dim strong { color: var(--muted); }
.step-text small { font-size: 11px; color: var(--muted); line-height: 1.4; display: block; }

/* CTA */
.cta { display: inline-flex; align-items: center; gap: 7px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; padding: 10px 22px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 13px; transition: opacity 0.15s; }
.cta:hover { opacity: 0.88; }

/* Stat row */
.stat-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; display: flex; align-items: center; gap: 14px; }
.stat-icon-wrap { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-icon-wrap.purple { background: rgba(99,102,241,0.12); color: var(--accent-2); }
.stat-icon-wrap.blue { background: rgba(59,130,246,0.12); color: var(--blue); }
.stat-icon-wrap.amber { background: rgba(245,158,11,0.12); color: var(--amber); }
.stat-val { font-size: 22px; font-weight: 700; color: #fff; letter-spacing: -0.5px; line-height: 1; }
.stat-lbl { font-size: 11px; color: var(--muted); margin-top: 3px; text-transform: uppercase; letter-spacing: 0.05em; }

/* Coming card */
.coming-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; display: flex; align-items: flex-start; gap: 16px; }
.coming-icon { width: 40px; height: 40px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--muted); }
.coming-body h3 { font-size: 14px; color: var(--text); font-weight: 600; margin-bottom: 6px; }
.coming-body p { font-size: 12px; color: var(--muted); line-height: 1.65; }
.coming-actions { margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }
.btn-primary { padding: 8px 16px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 7px; font-size: 12px; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; cursor: pointer; }
.btn-ghost { padding: 8px 16px; background: transparent; border: 1px solid var(--border); color: var(--text); border-radius: 7px; font-size: 12px; text-decoration: none; display: inline-flex; align-items: center; }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent-2); }
</style>
