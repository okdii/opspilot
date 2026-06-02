import { api } from '@/services/api'

type MessageHandler = (data: any) => void

export class WSClient {
  private ws: WebSocket | null = null
  private reconnectDelay = 2000
  private maxDelay = 30000
  private shouldReconnect = true
  private handlers: Set<MessageHandler> = new Set()
  private subscriptions: Array<Record<string, unknown>> = []
  private reconnectTimer: number | null = null

  on(handler: MessageHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
    // Track subscriptions for resubscribe on reconnect
    if (typeof msg.action === 'string' && msg.action.startsWith('subscribe')) {
      this.subscriptions.push(msg)
    }
  }

  async connect(): Promise<void> {
    this.shouldReconnect = true
    await this.openConnection()
  }

  disconnect(): void {
    this.shouldReconnect = false
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  private async openConnection(): Promise<void> {
    try {
      const { data } = await api.get<{ ticket: string }>('/api/ws-ticket')
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.ws = new WebSocket(`${proto}://${window.location.host}/ws?ticket=${data.ticket}`)

      this.ws.addEventListener('open', () => {
        this.reconnectDelay = 2000
        // Resubscribe
        for (const sub of this.subscriptions) {
          this.ws?.send(JSON.stringify(sub))
        }
      })

      this.ws.addEventListener('message', (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          this.handlers.forEach((h) => h(msg))
        } catch {
          /* ignore */
        }
      })

      this.ws.addEventListener('close', () => {
        if (this.shouldReconnect) this.scheduleReconnect()
      })

      this.ws.addEventListener('error', () => {
        this.ws?.close()
      })
    } catch (err) {
      // 401 handled by interceptor; otherwise retry
      if (this.shouldReconnect) this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay)
      void this.openConnection()
    }, this.reconnectDelay)
  }
}

export const wsClient = new WSClient()
