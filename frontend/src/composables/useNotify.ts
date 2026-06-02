import { useToast } from 'vuestic-ui'

export interface NotifyOpts {
  title?: string
  duration?: number
}

type ErrorLike = string | Error | { message?: string }

function extractMessage(input: ErrorLike): string {
  if (typeof input === 'string') return input
  if (input && typeof input === 'object' && 'message' in input && input.message) {
    return String(input.message)
  }
  return 'Something went wrong.'
}

/**
 * App-wide notifications, themed via Vuestic semantic colors.
 *   const notify = useNotify()
 *   notify.success('Saved')
 *   notify.error(err)   // accepts Error / ApiError, extracts .message
 */
export function useNotify() {
  const { init } = useToast()
  const base = { position: 'top-right' as const, closeable: true }

  return {
    success: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'success', message, title: o.title, duration: o.duration ?? 4000 }),
    info: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'info', message, title: o.title, duration: o.duration ?? 4000 }),
    warning: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'warning', message, title: o.title, duration: o.duration ?? 4000 }),
    error: (input: ErrorLike, o: NotifyOpts = {}) =>
      init({ ...base, color: 'danger', message: extractMessage(input), title: o.title, duration: o.duration ?? 6000 }),
  }
}
