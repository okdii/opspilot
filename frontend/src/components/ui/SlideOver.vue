<script setup lang="ts">
import { watch, onUnmounted } from 'vue'

const props = defineProps<{
  modelValue: boolean
  title?: string
  subtitle?: string
  width?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

function close() { emit('update:modelValue', false) }

// Lock body scroll while open.
watch(
  () => props.modelValue,
  (open) => { document.body.style.overflow = open ? 'hidden' : '' },
)
onUnmounted(() => { document.body.style.overflow = '' })
</script>

<template>
  <Teleport to="body">
    <Transition name="so-fade">
      <div v-if="modelValue" class="so-scrim" @click.self="close">
        <Transition name="so-slide" appear>
          <aside class="so-drawer" role="dialog" :aria-label="title || 'Panel'" :style="{ width: width || '600px' }">
            <header class="so-hdr">
              <div>
                <h2 v-if="title">{{ title }}</h2>
                <p v-if="subtitle" class="so-sub">{{ subtitle }}</p>
                <slot name="header" />
              </div>
              <button class="so-close" aria-label="Close" @click="close">✕</button>
            </header>
            <div class="so-body"><slot /></div>
            <footer v-if="$slots.footer" class="so-footer"><slot name="footer" /></footer>
          </aside>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.so-scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1100; display: flex; justify-content: flex-end; }
.so-fade-enter-active, .so-fade-leave-active { transition: opacity .25s ease; }
.so-fade-enter-from, .so-fade-leave-to { opacity: 0; }
.so-slide-enter-active, .so-slide-leave-active { transition: transform .25s ease-out; }
.so-slide-enter-from, .so-slide-leave-to { transform: translateX(100%); }
.so-drawer { max-width: 100vw; height: 100%; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -20px 0 50px rgba(0,0,0,0.4); }
.so-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: flex-start; flex-shrink: 0; }
.so-hdr h2 { font-size: 16px; color: #fff; }
.so-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.so-close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 4px; line-height: 1; }
.so-close:hover { color: var(--text); }
.so-body { flex: 1; overflow-y: auto; padding: 20px 22px; }
.so-footer { flex-shrink: 0; border-top: 1px solid var(--border); padding: 14px 22px; display: flex; gap: 10px; flex-wrap: wrap; }
@media (max-width: 640px) { .so-drawer { width: 100vw !important; } }
</style>
