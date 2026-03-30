import type {
  GroupSnapshot,
  SingleSnapshot,
  VWAPMonitorEntry,
  SignalAMonitorSnapshot,
  StatusResponse,
  ReplayStatusResponse,
} from '../types/dashboard'

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

export const api = {
  status: () => fetchJSON<StatusResponse>('/api/status'),

  groups: () =>
    fetchJSON<{ groups: GroupSnapshot[] }>('/api/dashboard/groups'),

  singles: () =>
    fetchJSON<{ singles: SingleSnapshot[] }>('/api/dashboard/singles'),

  vwap: () =>
    fetchJSON<{ vwap: VWAPMonitorEntry[] }>('/api/dashboard/vwap'),

  signalA: () =>
    fetchJSON<SignalAMonitorSnapshot>('/api/dashboard/signal-a'),

  replayStatus: () =>
    fetchJSON<ReplayStatusResponse>('/api/replay/status'),

  replayJump: (time: string) =>
    fetch('/api/replay/jump', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time }),
    }).then((r) => {
      if (!r.ok) throw new Error(`Replay jump failed: ${r.status}`)
      return r.json()
    }),
}
