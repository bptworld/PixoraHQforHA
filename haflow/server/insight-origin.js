// Read the command's own HA context; never infer origin from nearby state updates.
export class CommandContexts {
  constructor(nextId) { this.nextId = nextId; this.pending = new Map() }
  request(socket, fields) {
    if (this.pending.size >= 32) return Promise.reject(new Error('HA command channel is busy. No command sent.'))
    const id = this.nextId()
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('HA command result is uncertain. It was not retried.')) }, 8000)
      this.pending.set(id, { resolve, reject, timer })
      try { socket.send(JSON.stringify({ id, type: 'call_service', ...fields })) }
      catch { clearTimeout(timer); this.pending.delete(id); reject(new Error('HA command send failed. Check the device; no retry.')) }
    })
  }
  accept(message) {
    if (message.type !== 'result' || !this.pending.has(message.id)) return false
    const entry = this.pending.get(message.id)
    clearTimeout(entry.timer); this.pending.delete(message.id)
    if (message.success) entry.resolve(message.result)
    else entry.reject(new Error('HA rejected the service request. It was not retried.'))
    return true
  }
  close() {
    for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('HA disconnected. Command result is uncertain; no retry.')) }
    this.pending.clear()
  }
}

export function originReport(origin, domain, service, payload, result) {
  const raw = payload?.entity_id
  const ids = (Array.isArray(raw) ? raw : [raw]).filter(id => typeof id === 'string' && /^[a-z_]+\.[a-z0-9_]+$/.test(id)).slice(0, 128)
  const report = { source: 'HAFlow', entity_id: ids, operation: `${domain}.${service}`, reason: String(origin?.reason || 'HAFlow requested this device action.').slice(0, 600), outcome: 'requested' }
  const context = result?.context?.id
  if (typeof context === 'string' && /^[A-Za-z0-9_-]{16,80}$/.test(context)) report.action_context = context
  return report
}

export function createOriginRecorder(send, warn) {
  const queue = []
  let active = false
  const safeWarn = message => { try { warn(message) } catch { /* diagnostics are optional */ } }
  async function drain() {
    if (active) return
    active = true
    try {
      while (queue.length) {
        const { at, report } = queue.shift()
        if (Date.now() - at > 30000) continue
        try { await send(report) } catch { safeWarn('Insight origin unconfirmed; device action was not retried.') }
      }
    } finally { active = false }
  }
  return report => {
    if (queue.length >= 32) { safeWarn('Insight origin queue full; device action unchanged.'); return }
    queue.push({ at: Date.now(), report }); void drain().catch(() => {})
  }
}
