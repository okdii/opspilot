<script setup lang="ts">
// icon is an inline SVG string (consistent with AppLayout nav icons). Avoid emojis.
defineProps<{ icon?: string; title: string; message?: string }>()
</script>

<template>
  <div class="empty-state">
    <div v-if="icon" class="es-icon" v-html="icon"></div>
    <h2 class="es-title">{{ title }}</h2>
    <p v-if="message" class="es-msg">{{ message }}</p>
    <div class="es-action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty-state { text-align: center; padding: 80px 20px; }
.es-icon { margin-bottom: 12px; color: var(--muted); display: flex; justify-content: center; }
.es-title { font-size: 18px; color: #fff; margin-bottom: 6px; }
.es-msg { color: var(--muted); margin-bottom: 20px; }
</style>
