<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="ph-text">
      <h1 class="ph-title">{{ title }}</h1>
      <p v-if="subtitle" class="ph-sub">{{ subtitle }}</p>
    </div>
    <div class="ph-actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
.ph-title { font-size: 22px; color: #fff; letter-spacing: -0.3px; }
.ph-sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
.ph-actions { display: flex; gap: 10px; align-items: center; }
</style>
