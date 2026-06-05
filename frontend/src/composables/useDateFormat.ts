import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

export function useDateFormat() {
  const settings = useSettingsStore()
  const tz = computed(() => settings.general.timezone || 'UTC')

  function formatDate(iso: string | null | undefined): string {
    if (!iso) return '—'
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz.value }).format(new Date(iso))
  }

  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '—'
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: tz.value,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
      .format(new Date(iso))
      .replace(',', '')
  }

  function toTzDateKey(d: Date): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz.value }).format(d)
  }

  return { tz, formatDate, formatDateTime, toTzDateKey }
}
