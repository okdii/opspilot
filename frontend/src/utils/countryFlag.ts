export function flagEmoji(code: string | null): string {
  if (!code || code === 'XX') return '🏳'
  return code.toUpperCase().replace(/./gu, ch =>
    String.fromCodePoint(0x1F1E6 + ch.charCodeAt(0) - 65)
  )
}
