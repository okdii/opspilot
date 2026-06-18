<script setup lang="ts">
import { ref } from 'vue'
import ThreatIntelligence from './security/ThreatIntelligence.vue'
import AttackerIntelligence from './security/AttackerIntelligence.vue'
import Fail2banPanel from './fail2ban/Fail2banPanel.vue'

defineProps<{ serverId: string }>()

type SubTab = 'threat' | 'attackers' | 'fail2ban'
const subTab = ref<SubTab>('threat')
</script>

<template>
  <div class="security-tab">
    <div class="sub-tabbar">
      <div class="sub-tabs">
        <button class="sub-tab" :class="{ active: subTab === 'threat' }" @click="subTab = 'threat'">
          Threat Intelligence
        </button>
        <button class="sub-tab" :class="{ active: subTab === 'attackers' }" @click="subTab = 'attackers'">
          Attackers
        </button>
        <button class="sub-tab" :class="{ active: subTab === 'fail2ban' }" @click="subTab = 'fail2ban'">
          Fail2ban
        </button>
      </div>
    </div>

    <ThreatIntelligence v-if="subTab === 'threat'" :server-id="serverId" />
    <AttackerIntelligence v-else-if="subTab === 'attackers'" :server-id="serverId" />
    <Fail2banPanel v-else :server-id="serverId" />
  </div>
</template>

<style scoped>
.security-tab { padding: 4px 0 32px; }

.sub-tabbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 10px;
}
.sub-tabs { display: flex; gap: 2px; }
.sub-tab {
  background: none; border: none; color: var(--muted);
  font-size: 13px; padding: 6px 12px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -11px;
}
.sub-tab:hover { color: var(--text); }
.sub-tab.active { color: var(--accent-2); border-bottom-color: var(--accent-2); }
</style>
