/**
 * Client-side cron expression → short human label (spec 09 §4.2).
 * Handles the common cases; falls back to the raw expression for anything complex.
 * Returns { label, valid }. Invalid expressions are flagged so the row can warn.
 */
export interface CronLabel {
  label: string
  valid: boolean
}

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

function isNum(s: string): boolean {
  return /^\d+$/.test(s)
}

function fmtTime(hour: number, min: number): string {
  const ampm = hour < 12 ? 'am' : 'pm'
  let h = hour % 12
  if (h === 0) h = 12
  const mm = String(min).padStart(2, '0')
  return min === 0 ? `${h}:00${ampm}` : `${h}:${mm}${ampm}`
}

/** Basic structural validation: 5 space-separated fields with allowed chars. */
function structurallyValid(expr: string): boolean {
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return false
  return parts.every((p) => /^[\d*,/-]+$/.test(p))
}

export function cronToLabel(expr: string): CronLabel {
  const raw = expr.trim()
  if (!structurallyValid(raw)) return { label: raw, valid: false }

  const [min, hour, dom, mon, dow] = raw.split(/\s+/)

  // Every N minutes — */N * * * *
  const minStep = min.match(/^\*\/(\d+)$/)
  if (minStep && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    const n = Number(minStep[1])
    return { label: n === 1 ? 'Every minute' : `Every ${n} minutes`, valid: true }
  }

  // Every N hours — 0 */N * * *
  const hourStep = hour.match(/^\*\/(\d+)$/)
  if (min === '0' && hourStep && dom === '*' && mon === '*' && dow === '*') {
    const n = Number(hourStep[1])
    return { label: n === 1 ? 'Every hour' : `Every ${n} hours`, valid: true }
  }

  // Every minute — * * * * *
  if (min === '*' && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    return { label: 'Every minute', valid: true }
  }

  // Every hour at :MM — MM * * * *
  if (isNum(min) && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    return { label: `Every hour at :${String(Number(min)).padStart(2, '0')}`, valid: true }
  }

  // Specific time of day
  if (isNum(min) && isNum(hour) && mon === '*') {
    const time = fmtTime(Number(hour), Number(min))

    // Weekdays — dow = 1-5
    if (dom === '*' && dow === '1-5') return { label: `Weekdays at ${time}`, valid: true }
    // Single weekday — dow = single number
    if (dom === '*' && isNum(dow)) {
      const d = Number(dow) % 7
      const dayName = DOW[d] ?? `day ${dow}`
      const t = Number(hour) === 0 && Number(min) === 0 ? 'midnight' : time
      return { label: `Every ${dayName} at ${t}`, valid: true }
    }
    // Every day at TIME — dom=* dow=*
    if (dom === '*' && dow === '*') return { label: `Every day at ${time}`, valid: true }
    // Day of month
    if (isNum(dom) && dow === '*') return { label: `Day ${dom} of each month at ${time}`, valid: true }
  }

  // Unrecognised but structurally fine → show raw, still valid.
  return { label: raw, valid: true }
}
