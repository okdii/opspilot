# OpsPilot — Progress

## Fail2ban / Security Monitoring

✅ fail2ban monitoring — Security tab with jail stats, banned IPs, geo, 24h chart
✅ Security incident detection (Part 1) — behavior-based kill-chain detection (recon→exploit→webshell→persistence→log-tampering), 10 alert types, per-IP probe-scan grouping, log-silence heartbeat, Fluent Bit web_access/auditd/mariadb_general feeds, onboarding hardening, Security Events timeline UI
✅ Security auto-response (Part 2) — semi-auto remediation (Tier 1 auto: block_ip/quarantine_file/kill_pid; Tier 2 approval: revert_authorized_keys/disable_db_user), allow-listed verb channel, confidence+circuit-breaker gates, TTL auto-unblock, full audit ledger with one-click undo, per-server opt-in + global kill switch
