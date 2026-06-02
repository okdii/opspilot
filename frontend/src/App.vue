<script setup lang="ts">
// Root app — router-view renders matched route
</script>

<template>
  <div class="app-root">
    <router-view />
  </div>
</template>

<style>
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface-2: #22263a;
  --border: #2e3354;
  --accent: #6366f1;
  --accent-2: #818cf8;
  --green: #22c55e;
  --amber: #f59e0b;
  --red: #ef4444;
  --blue: #3b82f6;
  --grey: #6b7280;
  --text: #e2e8f0;
  --muted: #94a3b8;
}

* {
  box-sizing: border-box;
}

html, body, #app, .app-root {
  margin: 0;
  padding: 0;
  height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.app-root {
  min-height: 100vh;
}
</style>
